"""Per-request JEV / pipeline trace (no secrets, no PII bodies)."""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Callable, TypeVar

_log = logging.getLogger("aurix.jev_trace")

_events: list[dict[str, Any]] = []
_timeline: list[dict[str, Any]] = []
_request_id: str = ""
_t0: float = 0.0
_segment_start: float = 0.0
_last_turn_agent: str | None = None
_sql_attempts: int = 0

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


def reset() -> str:
    global _request_id, _events, _timeline, _t0, _segment_start, _last_turn_agent, _sql_attempts
    _request_id = uuid.uuid4().hex[:12]
    _events = []
    _timeline = []
    _t0 = time.perf_counter()
    _segment_start = _t0
    _last_turn_agent = None
    _sql_attempts = 0
    return _request_id


def reset_sql_attempts() -> None:
    global _sql_attempts
    _sql_attempts = 0


def bump_sql_attempt() -> None:
    global _sql_attempts
    _sql_attempts += 1


def take_sql_attempts() -> int:
    return _sql_attempts


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
        "t_ms": round((time.perf_counter() - _t0) * 1000, 1),
    }
    row.update({k: v for k, v in fields.items() if v is not None})
    _timeline.append(row)


def mark_agent_transition(last_speaker: Any) -> None:
    """Record wall time for the agent turn that just finished."""
    global _segment_start, _last_turn_agent
    now = time.perf_counter()
    name = getattr(last_speaker, "name", None) or str(last_speaker)
    if _last_turn_agent is not None and _segment_start > 0:
        record_step(
            "agent_turn",
            _last_turn_agent,
            (now - _segment_start) * 1000,
            status="ok",
        )
    _last_turn_agent = name
    _segment_start = now


def finalize_agent_timeline() -> None:
    """Close the last open agent segment after initiate_chat returns."""
    global _segment_start, _last_turn_agent
    if _last_turn_agent is None or _segment_start <= 0:
        return
    now = time.perf_counter()
    record_step(
        "agent_turn",
        _last_turn_agent,
        (now - _segment_start) * 1000,
        status="ok",
    )
    _last_turn_agent = None
    _segment_start = now


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
        record_step("jev", gate, ms, status=status)


def event(gate: str, **fields: Any) -> None:
    fields = {k: v for k, v in fields.items() if v is not None}
    row = {
        "gate": gate,
        "t_ms": round((time.perf_counter() - _t0) * 1000, 1),
        **fields,
    }
    _events.append(row)
    _log.info(json.dumps({"request_id": _request_id, **row}, default=str))


def summarize_latency() -> dict[str, Any]:
    agent_steps = [s for s in _timeline if s["kind"] == "agent_turn"]
    db_steps = [s for s in _timeline if s["kind"] == "tool"]
    jev_steps = [s for s in _timeline if s["kind"] == "jev"]

    total_llm_ms = round(
        sum(s["duration_ms"] for s in agent_steps if s["name"] in _LLM_AGENT_NAMES),
        1,
    )
    total_db_ms = round(sum(s["duration_ms"] for s in db_steps), 1)
    total_jev_ms = round(sum(s["duration_ms"] for s in jev_steps), 1)
    total_ms = round((time.perf_counter() - _t0) * 1000, 1)

    ranked = sorted(_timeline, key=lambda s: s["duration_ms"], reverse=True)
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
        1 for e in _events if e.get("skip_llm")
    )

    llm_turn_count = sum(
        1 for s in agent_steps if s["name"] in _LLM_AGENT_NAMES
    )

    return {
        "request_id": _request_id,
        "total_ms": total_ms,
        "total_llm_ms": total_llm_ms,
        "total_db_ms": total_db_ms,
        "total_jev_ms": total_jev_ms,
        "llm_turn_count": llm_turn_count,
        "jev_skipped_llm_agents": jev_skipped_llm,
        "db_tool_calls": len(db_steps),
        "jev_calls": len(jev_steps),
        "top5_slowest": top5,
        "timeline": list(_timeline),
    }


def print_latency_summary(summary: dict[str, Any] | None = None) -> None:
    summary = summary or summarize_latency()
    lines = [
        "",
        "=== AURIX latency summary (request %s) ===" % summary.get("request_id", "?"),
        "total_ms=%s  llm_ms=%s  db_ms=%s  jev_ms=%s"
        % (
            summary["total_ms"],
            summary["total_llm_ms"],
            summary["total_db_ms"],
            summary["total_jev_ms"],
        ),
        "llm_turns=%s  jev_skipped_llm=%s  db_calls=%s  jev_calls=%s"
        % (
            summary["llm_turn_count"],
            summary["jev_skipped_llm_agents"],
            summary["db_tool_calls"],
            summary["jev_calls"],
        ),
        "top5_slowest:",
    ]
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
    text = "\n".join(lines)
    print(text)
    _log.info(text)


def snapshot() -> dict[str, Any]:
    return {
        "request_id": _request_id,
        "events": list(_events),
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