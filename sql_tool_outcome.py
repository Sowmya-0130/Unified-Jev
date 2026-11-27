"""Classify Sql_tool payloads for S7 vs validation repair (deterministic)."""
from __future__ import annotations

import json
from typing import Any


def _try_parse_json(raw: str) -> Any | None:
    text = str(raw or "").strip()
    if not text.startswith("{") and not text.startswith("["):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def is_validation_error_body(body: str) -> bool:
    raw = str(body or "")
    if "sql_pipeline_error" in raw:
        return True
    data = _try_parse_json(raw)
    return isinstance(data, dict) and bool(data.get("sql_pipeline_error"))


def is_safety_blocked_body(body: str) -> bool:
    data = _try_parse_json(str(body or ""))
    if isinstance(data, dict) and str(data.get("status") or "") == "safety_gate":
        return True
    return "safety_gate" in str(body or "") and "pre-chat safety" in str(body or "").lower()


def validation_repair_reason(body: str) -> str:
    data = _try_parse_json(str(body or ""))
    if isinstance(data, dict) and data.get("sql_pipeline_error"):
        cls = data.get("class") or "validation"
        msg = data.get("message") or "SQL did not pass validation"
        return f"SQL validation failed ({cls}): {msg}"
    if is_safety_blocked_body(body):
        return "SQL execution was blocked by safety gate before database run."
    return "SQL validation failed."


def s7_indicates_validation(rcheck: dict) -> bool:
    if not isinstance(rcheck, dict):
        return False
    if rcheck.get("pipeline_validation"):
        return True
    return str(rcheck.get("error_type") or "") in ("validation", "safety_gate")


def pipeline_failure_detail(*, question: str, last_sql_out: str) -> str:
    """Operator detail for terminal / logs (not shown in Streamlit)."""
    raw = str(last_sql_out or "").strip()
    q = (question or "").strip()
    if is_validation_error_body(raw):
        return f"{validation_repair_reason(raw)} | question={q[:240]!r}"
    if is_safety_blocked_body(raw):
        return f"safety_gate_sql_blocked | question={q[:240]!r} | body={raw[:400]}"
    return f"pipeline_sql_exit | question={q[:240]!r} | last_sql_out={raw[:800]}"


def log_pipeline_failure(
    *,
    question: str,
    last_sql_out: str,
    termination: str = "pipeline_sql_exit",
) -> None:
    try:
        from jev_trace import trace_stdout

        detail = pipeline_failure_detail(question=question, last_sql_out=last_sql_out)
        trace_stdout(f"{termination}: {detail}")
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning(
            "%s: %s", termination, pipeline_failure_detail(question=question, last_sql_out=last_sql_out)
        )


def user_message_for_failed_pipeline(*, question: str, last_sql_out: str) -> str:
    """Short user-facing text when pipeline exits without Insight (no catalog/trace jargon)."""
    raw = str(last_sql_out or "").strip()
    if is_safety_blocked_body(raw):
        return (
            "This question could not be answered because the safety check did not allow it. "
            "Try rephrasing your question."
        )
    if is_validation_error_body(raw):
        return (
            "No database result is available for this question yet. "
            "Try adding a specific fund name, table, or time range."
        )
    lower = raw.lower()
    if "invalid object" in lower or "does not exist" in lower:
        return (
            "The query referenced data that is not available under that name. "
            "Try being more specific about which fund or dataset you mean."
        )
    if "sql catalog not warm" in lower:
        return "The data catalog is still loading. Wait a moment, refresh, and try again."
    if raw == "[]" or raw.startswith("[]"):
        return "The query ran successfully but found no matching rows for this question."
    if "an error occurred" in lower[:220] or lower.startswith("error"):
        return (
            "The database could not run the generated query for this question. "
            "Try rephrasing or narrowing the question."
        )
    return (
        "No database answer is available for this question right now. "
        "Try rephrasing or adding more detail."
    )