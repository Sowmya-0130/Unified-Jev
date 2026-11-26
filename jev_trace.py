"""Per-request JEV / pipeline trace (no secrets, no PII bodies)."""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field


@dataclass
class _TraceState:
    request_id: str = ""
    events: list = field(default_factory=list)
    timeline: list = field(default_factory=list)
    t0: float = 0.0
    segment_start: float = 0.0
    last_turn_agent: str | None = None
    chat_phase_started: bool = False
    sql_attempts: int = 0
    termination: dict | None = None
    gate_decisions: list = field(default_factory=list)
    last_jev_ms: dict = field(default_factory=dict)
    seg_open_t_ms: float = 0.0
    chat_start_t_ms: float = 0.0
    llm_api_calls: list = field(default_factory=list)
    pending_tool_jev_ms: float = 0.0
    executed_sqls: list = field(default_factory=list)
    request_question: str = ""
    match_row_count: int | None = None
    insight_path: str | None = None
    template_insight: dict | None = None


_tls = threading.local()


def _st() -> _TraceState:
    st = getattr(_tls, "st", None)
    if st is None:
        st = _TraceState()
        _tls.st = st
    return st



import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

_log = logging.getLogger("aurix.jev_trace")

T = TypeVar("T")

# Agents whose wall time between transitions is treated as LLM time
_LLM_AGENT_NAMES = frozenset(
    {
        "routing_agent",
        "Sql_Execution_Critic",
        "Evaluation_Agent",
        "evaluation_agent",
        "critic_agent",
        "Responsible_AI_Agent",
        "Sql_Generator",
        "Insight_Generator",
        "llm_answer_maker",
        "Eryl_agent",
        "Query_Executor",
        "query_transformer",
    }
)


def record_executed_sql(sql: str) -> None:
    if sql and str(sql).strip():
        _st().executed_sqls.append(str(sql).strip())


def set_request_question(question: str) -> None:
    _st().request_question = str(question or "")


def get_request_question() -> str:
    return _st().request_question


def reset() -> str:
    import uuid

    st = _TraceState()
    st.request_id = uuid.uuid4().hex[:12]
    st.t0 = time.perf_counter()
    st.segment_start = st.t0
    _tls.st = st
    return st.request_id



def record_match_row_count(count: int) -> None:
    _st().match_row_count = int(count)


def get_match_row_count() -> int | None:
    return _st().match_row_count


def record_insight_path(path: str) -> None:
    _st().insight_path = str(path or "").strip() or None


def get_insight_path() -> str | None:
    return _st().insight_path


def record_template_insight(payload: dict[str, Any]) -> None:
    _st().template_insight = dict(payload)


def get_template_insight() -> dict[str, Any] | None:
    return dict(_st().template_insight) if _st().template_insight else None


def reset_sql_attempts() -> None:
    _st().sql_attempts = 0


def bump_sql_attempt() -> None:
    _st().sql_attempts += 1


def take_sql_attempts() -> int:
    return _st().sql_attempts


def get_executed_sqls() -> list[str]:
    return list(_st().executed_sqls)


def record_step(
    kind: str,
    name: str,
    duration_ms: float,
    *,
    status: str = "ok",
    retry_count: int = 0,
    **fields: Any,
) -> None:
    row = {
        "kind": kind,
        "name": name,
        "duration_ms": round(duration_ms, 1),
        "status": status,
        "retry_count": retry_count,
        "t_ms": round((time.perf_counter() - _st().t0) * 1000, 1),
    }
    row.update({k: v for k, v in fields.items() if v is not None})
    _st().timeline.append(row)
    if kind in ("tool", "jev"):
        _st().pending_tool_jev_ms += float(row["duration_ms"])


def begin_chat_phase() -> None:
    """Start agent-segment timing at initiate_chat (excludes pre-chat setup)."""
    _st().chat_phase_started = True
    _st().segment_start = time.perf_counter()
    _st().seg_open_t_ms = round((time.perf_counter() - _st().t0) * 1000, 1)
    _st().chat_start_t_ms = _st().seg_open_t_ms


@contextmanager
def setup_step(name: str) -> Iterator[None]:
    """Pre-chat setup only (probe, safety, refresh). Not for initiate_chat."""
    t0 = time.perf_counter()
    status = "ok"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        ms = (time.perf_counter() - t0) * 1000
        ms = max(0.0, ms - _st().pending_tool_jev_ms)
        _st().pending_tool_jev_ms = 0.0
        record_step("setup", name, ms, status=status)


@contextmanager
def chat_wall_step(name: str) -> Iterator[None]:
    """Parent wall-clock for initiate_chat; excluded from exclusive latency buckets."""
    t0 = time.perf_counter()
    status = "ok"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        record_step("chat", name, (time.perf_counter() - t0) * 1000, status=status)


def record_termination(reason: str, **fields: Any) -> None:
    row = {"reason": reason, **{k: v for k, v in fields.items() if v is not None}}
    _st().termination = row
    event("termination", **row)


def _overlap_tool_jev_ms(up_to_t_ms: float) -> float:
    return round(
        sum(
            s["duration_ms"]
            for s in _st().timeline
            if s["kind"] in ("tool", "jev")
            and _st().seg_open_t_ms < float(s.get("t_ms", 0)) <= up_to_t_ms
        ),
        1,
    )


def record_llm_api_call(
    agent: str,
    *,
    response_id: str | None,
    usage: dict[str, int] | None,
    cached: bool = False,
) -> None:
    row = {
        "agent": agent,
        "response_id": response_id,
        "cached": cached,
        "prompt_tokens": (usage or {}).get("prompt_tokens", 0),
        "completion_tokens": (usage or {}).get("completion_tokens", 0),
        "reasoning_tokens": (usage or {}).get("reasoning_tokens", 0),
        "t_ms": round((time.perf_counter() - _st().t0) * 1000, 1),
    }
    _st().llm_api_calls.append(row)


def mark_agent_transition(last_speaker: Any) -> None:
    """Record wall time for the agent that just finished speaking."""
    if not _st().chat_phase_started:
        return
    now = time.perf_counter()
    name = getattr(last_speaker, "name", None) or str(last_speaker)
    if _st().segment_start > 0:
        dur = (now - _st().segment_start) * 1000
        dur = max(0.0, dur - _st().pending_tool_jev_ms)
        _st().pending_tool_jev_ms = 0.0
        if name == "Sql_tool":
            # Wall time is already recorded on db_execute_query (I-20).
            pass
        elif name == "user_proxy":
            pass
        elif name in _LLM_AGENT_NAMES:
            record_step("agent_turn", name, dur, status="ok")
        else:
            record_step("setup", name, dur, status="ok")
    _st().last_turn_agent = name
    _st().segment_start = now
    _st().seg_open_t_ms = round((now - _st().t0) * 1000, 1)


def finalize_agent_timeline() -> None:
    """Close the last open agent segment after initiate_chat returns."""
    if not _st().chat_phase_started or _st().last_turn_agent is None or _st().segment_start <= 0:
        return
    now = time.perf_counter()
    name = _st().last_turn_agent
    dur = (now - _st().segment_start) * 1000
    dur = max(0.0, dur - _st().pending_tool_jev_ms)
    _st().pending_tool_jev_ms = 0.0
    if name == "Sql_tool":
        pass
    elif name in _LLM_AGENT_NAMES:
        record_step("agent_turn", name, dur, status="ok")
    elif name == "user_proxy":
        record_step("setup", "autogen_user_proxy", dur, status="ok")
    else:
        record_step("setup", name, dur, status="ok")
    _st().last_turn_agent = None
    _st().segment_start = now


def jev_timed(gate: str, fn: Callable[[], T]) -> T:
    t0 = time.perf_counter()
    status = "ok"
    out: Any = None
    try:
        out = fn()
        if isinstance(out, dict):
            status = str(out.get("source", "ok"))
        return out
    except Exception:
        status = "error"
        raise
    finally:
        ms = (time.perf_counter() - t0) * 1000
        _st().last_jev_ms[gate] = ms
        record_step("jev", gate, ms, status=status)


def last_jev_gate_ms(gate: str) -> float | None:
    return _st().last_jev_ms.get(gate)


def log_gate_decision(
    gate: str,
    *,
    input_summary: dict[str, Any] | None = None,
    decision: str | None = None,
    confidence: float | None = None,
    threshold: float | None = None,
    action: str,
    fallback_reason: str | None = None,
    llm_skipped_ms: float | None = None,
    shadow_jev_would: str | None = None,
    **extra: Any,
) -> None:
    """Structured JEV gate outcome (sizes only in input_summary — no PII)."""
    row: dict[str, Any] = {
        "gate": gate,
        "input_summary": input_summary or {},
        "decision": decision,
        "confidence": confidence,
        "threshold": threshold,
        "action": action,
        "fallback_reason": fallback_reason,
        "jev_ms": last_jev_gate_ms(gate),
        "llm_skipped_ms": llm_skipped_ms,
        "shadow_jev_would": shadow_jev_would,
        "t_ms": round((time.perf_counter() - _st().t0) * 1000, 1),
    }
    row.update({k: v for k, v in extra.items() if v is not None})
    _st().gate_decisions.append(row)
    flat = {
        k: v
        for k, v in row.items()
        if k not in ("input_summary", "gate") and v is not None
    }
    event(gate, **flat)


def gate_decisions() -> list[dict[str, Any]]:
    return list(_st().gate_decisions)


def get_events() -> list[dict[str, Any]]:
    return list(_st().events)


def event(gate: str, **fields: Any) -> None:
    fields = {k: v for k, v in fields.items() if v is not None}
    row = {
        "gate": gate,
        "t_ms": round((time.perf_counter() - _st().t0) * 1000, 1),
        **fields,
    }
    _st().events.append(row)
    _log.info(json.dumps({"request_id": _st().request_id, **row}, default=str))


def summarize_latency() -> dict[str, Any]:
    agent_steps = [s for s in _st().timeline if s["kind"] == "agent_turn"]
    setup_steps = [s for s in _st().timeline if s["kind"] == "setup"]
    db_steps = [s for s in _st().timeline if s["kind"] == "tool"]
    jev_steps = [s for s in _st().timeline if s["kind"] == "jev"]
    chat_steps = [s for s in _st().timeline if s["kind"] == "chat"]
    total_setup_ms = round(sum(s["duration_ms"] for s in setup_steps), 1)
    total_chat_wall_ms = round(sum(s["duration_ms"] for s in chat_steps), 1)
    def _pre_chat(s: dict) -> bool:
        return _st().chat_start_t_ms > 0 and float(s.get("t_ms", 0)) < _st().chat_start_t_ms

    def _in_chat(s: dict) -> bool:
        return _st().chat_start_t_ms == 0 or float(s.get("t_ms", 0)) >= _st().chat_start_t_ms

    setup_exclusive_ms = round(
        sum(
            s["duration_ms"]
            for s in setup_steps
            if (_pre_chat(s) if _st().chat_start_t_ms > 0 else True)
        ),
        1,
    )
    pre_chat_jev_ms = round(sum(s["duration_ms"] for s in jev_steps if _pre_chat(s)), 1)

    total_llm_ms = round(
        sum(
            s["duration_ms"]
            for s in agent_steps
            if s["name"] in _LLM_AGENT_NAMES and _in_chat(s)
        ),
        1,
    )
    total_db_ms = round(sum(s["duration_ms"] for s in db_steps if _in_chat(s)), 1)
    total_jev_ms_all = round(sum(s["duration_ms"] for s in jev_steps), 1)
    total_jev_ms = round(sum(s["duration_ms"] for s in jev_steps if _in_chat(s)), 1)
    total_ms = round((time.perf_counter() - _st().t0) * 1000, 1)
    # JEV pre-chat is already in setup_exclusive_ms; in-chat JEV only here (avoids ~6% overcount).
    bucket_sum_ms = round(
        setup_exclusive_ms + total_llm_ms + total_db_ms + total_jev_ms,
        1,
    )
    other_ms = round(max(0.0, total_ms - bucket_sum_ms), 1)
    tolerance = max(50.0, total_ms * 0.01) if total_ms > 0 else 1.0
    inner_ms = round(total_llm_ms + total_db_ms + total_jev_ms, 1)
    buckets_exclusive = abs(bucket_sum_ms - total_ms) <= tolerance

    ranked = sorted(_st().timeline, key=lambda s: s["duration_ms"], reverse=True)
    top5 = [
        {
            "kind": s["kind"],
            "name": s["name"],
            "duration_ms": s["duration_ms"],
            "status": s.get("status"),
            "retry_count": s.get("retry_count", 0),
        }
        for s in ranked[:5]
    ]

    jev_skipped_llm = sum(
        1 for e in _st().events if e.get("skip_llm")
    )

    llm_turn_count = sum(
        1 for s in agent_steps if s["name"] in _LLM_AGENT_NAMES
    )

    per_agent_tokens: dict[str, dict[str, int]] = {}
    for call in _st().llm_api_calls:
        ag = call.get("agent") or "?"
        bucket = per_agent_tokens.setdefault(
            ag,
            {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0, "calls": 0},
        )
        bucket["calls"] += 1
        for key in ("prompt_tokens", "completion_tokens", "reasoning_tokens"):
            bucket[key] += int(call.get(key) or 0)
    token_totals = {
        "prompt_tokens": sum(int(c.get("prompt_tokens") or 0) for c in _st().llm_api_calls),
        "completion_tokens": sum(int(c.get("completion_tokens") or 0) for c in _st().llm_api_calls),
        "reasoning_tokens": sum(int(c.get("reasoning_tokens") or 0) for c in _st().llm_api_calls),
        "llm_api_calls": len(_st().llm_api_calls),
    }

    return {
        "request_id": _st().request_id,
        "total_ms": total_ms,
        "total_llm_ms": total_llm_ms,
        "total_db_ms": total_db_ms,
        "total_jev_ms": total_jev_ms_all,
        "total_jev_ms_in_chat": total_jev_ms,
        "llm_turn_count": llm_turn_count,
        "jev_skipped_llm_agents": jev_skipped_llm,
        "db_tool_calls": len(db_steps),
        "jev_calls": len(jev_steps),
        "total_setup_ms": total_setup_ms,
        "setup_exclusive_ms": setup_exclusive_ms,
        "pre_chat_jev_ms": pre_chat_jev_ms,
        "total_chat_wall_ms": total_chat_wall_ms,
        "bucket_sum_ms": bucket_sum_ms,
        "other_ms": other_ms,
        "buckets_exclusive_within_1pct": buckets_exclusive,
        "termination": dict(_st().termination) if _st().termination else None,
        "top5_slowest": top5,
        "timeline": list(_st().timeline),
        "gate_decisions": list(_st().gate_decisions),
        "executed_sqls": list(_st().executed_sqls),
        "match_row_count": _st().match_row_count,
        "insight_path": _st().insight_path,
        "template_insight": dict(_st().template_insight) if _st().template_insight else None,
        "sql_attempts": max(_st().sql_attempts, len(_st().executed_sqls)),
        "llm_tokens": token_totals,
        "llm_tokens_by_agent": per_agent_tokens,
        "llm_response_ids": [
            c.get("response_id") for c in _st().llm_api_calls if c.get("response_id")
        ],
    }


def print_latency_summary(summary: dict[str, Any] | None = None) -> None:
    from API_unified import TRACE_PRINT_SUMMARY

    if not TRACE_PRINT_SUMMARY:
        return
    summary = summary or summarize_latency()
    lines = [
        "",
        "=== AURIX latency summary (request %s) ===" % summary.get("request_id", "?"),
        "total_ms=%s  setup_ms=%s  llm_ms=%s  db_ms=%s  jev_ms=%s  other_ms=%s  buckets_ok=%s"
        % (
            summary["total_ms"],
            summary.get("total_setup_ms", 0),
            summary["total_llm_ms"],
            summary["total_db_ms"],
            summary["total_jev_ms"],
            summary.get("other_ms", 0),
            summary.get("buckets_exclusive_within_1pct"),
        ),
        "llm_turns=%s  jev_skipped_llm=%s  db_calls=%s  jev_calls=%s"
        % (
            summary["llm_turn_count"],
            summary["jev_skipped_llm_agents"],
            summary["db_tool_calls"],
            summary["jev_calls"],
        ),
    ]
    tok = summary.get("llm_tokens") or {}
    if tok.get("llm_api_calls"):
        lines.append(
            "tokens: prompt=%s completion=%s reasoning=%s api_calls=%s"
            % (
                tok.get("prompt_tokens", 0),
                tok.get("completion_tokens", 0),
                tok.get("reasoning_tokens", 0),
                tok.get("llm_api_calls", 0),
            )
        )
        for ag, bucket in sorted((summary.get("llm_tokens_by_agent") or {}).items()):
            lines.append(
                "  agent=%s calls=%s prompt=%s completion=%s"
                % (
                    ag,
                    bucket.get("calls", 0),
                    bucket.get("prompt_tokens", 0),
                    bucket.get("completion_tokens", 0),
                )
            )
    lines.append("top5_slowest:")
    for i, row in enumerate(summary.get("top5_slowest") or [], 1):
        lines.append(
            "  %d. [%s] %s — %.1fms status=%s retries=%s"
            % (
                i,
                row.get("kind"),
                row.get("name"),
                row.get("duration_ms", 0),
                row.get("status"),
                row.get("retry_count", 0),
            )
        )
    if summary.get("termination"):
        lines.append("termination: %s" % summary["termination"].get("reason", "?"))
    gates = summary.get("gate_decisions") or []
    if gates:
        lines.append("=== JEV gate decisions ===")
        hdr = "%-4s %-10s %6s %6s %8s %-12s %s"
        lines.append(hdr % ("gate", "action", "conf", "thr", "jev_ms", "fallback", "decision"))
        for g in gates:
            lines.append(
                hdr
                % (
                    g.get("gate", "?"),
                    g.get("action", "?"),
                    _fmt_opt_float(g.get("confidence")),
                    _fmt_opt_float(g.get("threshold")),
                    _fmt_opt_float(g.get("jev_ms")),
                    g.get("fallback_reason") or "-",
                    str(g.get("decision") or g.get("shadow_jev_would") or "")[:40],
                )
            )
    text = "\n".join(lines)
    print(text)
    _log.info(text)


def _fmt_opt_float(v: Any) -> str:
    if v is None:
        return "-"
    try:
        return "%.3f" % float(v)
    except (TypeError, ValueError):
        return str(v)


def persist_request_trace(summary: dict[str, Any] | None = None) -> Path | None:
    """Write per-request latency JSON when TRACE_PERSIST=true (TRACE_PERSIST_DIR from .env)."""
    from API_unified import TRACE_PERSIST, TRACE_PERSIST_DIR

    if not TRACE_PERSIST:
        return None
    summary = summary or summarize_latency()
    rid = str(summary.get("request_id") or _st().request_id or "").strip()
    if not rid:
        return None
    try:
        out_dir = Path(TRACE_PERSIST_DIR).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{rid}.json"
        path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        return path
    except OSError as exc:
        _log.warning("persist_request_trace failed: %s", exc)
        return None


def snapshot() -> dict[str, Any]:
    return {
        "request_id": _st().request_id,
        "events": list(_st().events),
        "latency": summarize_latency(),
    }


def summarize_chat_agents(chat_history) -> dict[str, Any]:
    names: list[str] = []
    try:
        for item in chat_history.chat_history:
            n = item.get("name")
            if n:
                names.append(n)
    except Exception:  # noqa: BLE001
        pass
    llm_like = set(_LLM_AGENT_NAMES)
    run = [n for n in names if n in llm_like]
    skipped_markers = {
        "routing_agent": "S4",
        "Sql_Execution_Critic": "S7",
        "evaluation_agent": "S9",
        "critic_agent": "S13",
    }
    synthetic = []
    for item in getattr(chat_history, "chat_history", []) or []:
        body = str(item.get("content", ""))
        for agent, gate in skipped_markers.items():
            if item.get("name") == agent and "jev" in body.lower():
                synthetic.append(gate)
    return {
        "agent_messages": names,
        "llm_agent_turns": run,
        "llm_turn_count": len(run),
        "jev_synthetic_skip_gates": synthetic,
    }


def summarize_pipeline_transcript(transcript: list[dict]) -> dict[str, Any]:
    names = [str(item.get("name")) for item in transcript if item.get("name")]
    llm_like = set(_LLM_AGENT_NAMES)
    run = [n for n in names if n in llm_like]
    return {
        "agent_messages": names,
        "chat_agent_sequence": names,
        "llm_agent_turns": run,
        "llm_turn_count": len(run),
        "orchestrator": "pipeline",
    }