"""A3: S9/S13 post-checks on or off the critical path (feature-flagged)."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger("postchecks.async")


@dataclass
class PostcheckContext:
    question: str
    route: str  # "sql" | "semantic"
    trace_id: str | None = None
    insight_text: str | None = None
    answer_text: str | None = None
    chunks: Any = None


def _trace_id_fallback(trace_id: str | None) -> str | None:
    if trace_id:
        return trace_id
    try:
        from jev_trace import snapshot

        return (snapshot().get("request_id") or "").strip() or None
    except Exception:  # noqa: BLE001
        return None


def _sync_s9(question: str, insight_text: str, *, trace_id: str | None) -> None:
    from API_unified import JEV_CONFIDENCE_THRESHOLD, JEV_S9_EVAL_ENABLED, JEV_SHADOW_MODE

    if not (JEV_S9_EVAL_ENABLED and not JEV_SHADOW_MODE):
        return
    from jev_client import jev_eval_quality
    from jev_trace import jev_timed, log_gate_decision, record_step

    t0 = __import__("time").perf_counter()
    _eq = jev_timed("S9", lambda: jev_eval_quality(question, insight_text))
    ms = (__import__("time").perf_counter() - t0) * 1000
    record_step("postcheck", "S9", ms, status="ok", request_id=trace_id)
    _skip = (
        _eq.get("source") == "openjev"
        and _eq.get("skip_llm_eval")
        and float(_eq.get("composite") or 0) >= float(JEV_CONFIDENCE_THRESHOLD)
    )
    log_gate_decision(
        "S9",
        input_summary={"question_len": len(question), "async": False, "request_id": trace_id},
        decision="pass" if _skip else "defer",
        action="skip_llm" if _skip else "run_llm",
        decision_source="jev" if _eq.get("source") == "openjev" else "code",
    )


def _sync_s13(question: str, answer: str, chunks: Any, *, trace_id: str | None) -> None:
    from API_unified import JEV_CONFIDENCE_THRESHOLD, JEV_S13_CRITIC_ENABLED

    if not JEV_S13_CRITIC_ENABLED:
        return
    from jev_client import jev_critic_check
    from jev_trace import jev_timed, log_gate_decision, record_step

    t0 = __import__("time").perf_counter()
    _cr = jev_timed("S13", lambda: jev_critic_check(question, answer, chunks))
    ms = (__import__("time").perf_counter() - t0) * 1000
    record_step("postcheck", "S13", ms, status="ok", request_id=trace_id)
    _pass = bool(_cr.get("is_grounded")) and float(_cr.get("confidence") or 0) >= JEV_CONFIDENCE_THRESHOLD
    log_gate_decision(
        "S13",
        decision="pass" if _pass else "defer",
        action="skip_llm" if _pass else "run_llm",
        decision_source="jev" if _cr.get("source") == "openjev" else "code",
        input_summary={"async": False, "request_id": trace_id},
    )


def _async_s9(question: str, insight_text: str, *, trace_id: str | None) -> None:
    try:
        from API_unified import JEV_CONFIDENCE_THRESHOLD, JEV_S9_EVAL_ENABLED, JEV_SHADOW_MODE

        if not (JEV_S9_EVAL_ENABLED and not JEV_SHADOW_MODE):
            return
        from jev_client import jev_eval_quality
        from jev_trace import jev_timed, log_gate_decision, record_step

        t0 = __import__("time").perf_counter()
        _eq = jev_timed("S9", lambda: jev_eval_quality(question, insight_text))
        ms = (__import__("time").perf_counter() - t0) * 1000
        record_step("postcheck", "S9", ms, status="ok", request_id=trace_id)
        _skip = (
            _eq.get("source") == "openjev"
            and _eq.get("skip_llm_eval")
            and float(_eq.get("composite") or 0) >= float(JEV_CONFIDENCE_THRESHOLD)
        )
        log_gate_decision(
            "S9",
            input_summary={"question_len": len(question), "async": True, "request_id": trace_id},
            decision="pass" if _skip else "defer",
            action="skip_llm" if _skip else "run_llm",
            decision_source="jev" if _eq.get("source") == "openjev" else "code",
        )
    except BaseException as exc:  # noqa: BLE001
        _log.warning("async S9 failed trace_id=%s: %s", trace_id, exc)
        try:
            from jev_trace import record_step

            record_step("postcheck", "S9", 0.0, status="error", request_id=trace_id)
        except Exception:  # noqa: BLE001
            pass


def _async_s13(question: str, answer: str, chunks: Any, *, trace_id: str | None) -> None:
    try:
        from API_unified import JEV_CONFIDENCE_THRESHOLD, JEV_S13_CRITIC_ENABLED

        if not JEV_S13_CRITIC_ENABLED:
            return
        from jev_client import jev_critic_check
        from jev_trace import jev_timed, log_gate_decision, record_step

        t0 = __import__("time").perf_counter()
        _cr = jev_timed("S13", lambda: jev_critic_check(question, answer, chunks))
        ms = (__import__("time").perf_counter() - t0) * 1000
        record_step("postcheck", "S13", ms, status="ok", request_id=trace_id)
        _pass = bool(_cr.get("is_grounded")) and float(_cr.get("confidence") or 0) >= JEV_CONFIDENCE_THRESHOLD
        log_gate_decision(
            "S13",
            decision="pass" if _pass else "defer",
            action="skip_llm" if _pass else "run_llm",
            decision_source="jev" if _cr.get("source") == "openjev" else "code",
            input_summary={"async": True, "request_id": trace_id},
        )
    except BaseException as exc:  # noqa: BLE001
        _log.warning("async S13 failed trace_id=%s: %s", trace_id, exc)
        try:
            from jev_trace import record_step

            record_step("postcheck", "S13", 0.0, status="error", request_id=trace_id)
        except Exception:  # noqa: BLE001
            pass


def _execute_postchecks(ctx: PostcheckContext, *, async_mode: bool) -> None:
    rid = _trace_id_fallback(ctx.trace_id)
    if ctx.route == "sql" and ctx.insight_text:
        if async_mode:
            _async_s9(ctx.question, ctx.insight_text, trace_id=rid)
        else:
            _sync_s9(ctx.question, ctx.insight_text, trace_id=rid)
    elif ctx.route == "semantic" and ctx.answer_text is not None:
        if async_mode:
            _async_s13(ctx.question, ctx.answer_text, ctx.chunks, trace_id=rid)
        else:
            _sync_s13(ctx.question, ctx.answer_text, ctx.chunks, trace_id=rid)


def run_postchecks_sync(context: PostcheckContext) -> None:
    """Blocking S9/S13 — identical to pre-A3 orchestrator inline path."""
    try:
        from jev_trace import record_step

        record_step("postchecks", "sync", 0.0, status="ok", request_id=context.trace_id)
    except Exception:  # noqa: BLE001
        pass
    _execute_postchecks(context, async_mode=False)


def _watchdog_join(worker: threading.Thread, timeout_s: float, trace_id: str | None) -> None:
    worker.join(timeout=timeout_s)
    if worker.is_alive():
        _log.warning(
            "postcheck thread exceeded ASYNC_POSTCHECKS_TIMEOUT_S=%s trace_id=%s",
            timeout_s,
            trace_id,
        )


def run_postchecks_async(context: PostcheckContext) -> None:
    """Non-blocking daemon post-checks; failures logged only."""
    from API_unified import ASYNC_POSTCHECKS_TIMEOUT_S

    rid = _trace_id_fallback(context.trace_id)

    def worker() -> None:
        try:
            _execute_postchecks(context, async_mode=True)
        except BaseException as exc:  # noqa: BLE001
            _log.warning("postcheck worker failed trace_id=%s: %s", rid, exc)

    try:
        from jev_trace import record_step

        record_step("postchecks", "async", 0.0, status="ok", request_id=rid)
    except Exception:  # noqa: BLE001
        pass

    try:
        thread = threading.Thread(
            target=worker,
            name=f"aurix-postcheck-{context.route}",
            daemon=True,
        )
        thread.start()
    except Exception as exc:  # noqa: BLE001
        _log.warning("async postcheck spawn failed, falling back to sync trace_id=%s: %s", rid, exc)
        run_postchecks_sync(context)
        return

    threading.Thread(
        target=_watchdog_join,
        args=(thread, float(ASYNC_POSTCHECKS_TIMEOUT_S), rid),
        name="aurix-postcheck-watchdog",
        daemon=True,
    ).start()


def dispatch_postchecks(context: PostcheckContext) -> None:
    from API_unified import ASYNC_POSTCHECKS_ENABLED

    if ASYNC_POSTCHECKS_ENABLED:
        run_postchecks_async(context)
    else:
        run_postchecks_sync(context)


def schedule_s9_postcheck(question: str, insight_text: str) -> None:
    dispatch_postchecks(
        PostcheckContext(question=question, route="sql", insight_text=insight_text)
    )


def schedule_s13_postcheck(question: str, answer: str, chunks: Any) -> None:
    dispatch_postchecks(
        PostcheckContext(
            question=question,
            route="semantic",
            answer_text=answer,
            chunks=chunks,
        )
    )