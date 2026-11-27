"""Deterministic SQL execute step (replaces Query_Executor LLM)."""
from __future__ import annotations

import json
import re

from gate_inputs import parse_autogen_tool_body
from sql_catalog import get_catalog
from sql_pipeline import validate_sql


def parse_sql_generator_query(message: str) -> str | None:
    text = str(message or "").strip()
    text = text.replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r'"sql_query"\s*:\s*"([^"]+)"', text)
        if m:
            return m.group(1).replace("\\n", "\n")
        return None
    q = data.get("sql_query")
    if q is None or str(q).strip().lower() in ("none", "null", ""):
        return None
    return str(q).strip()


def tool_wrap(body: str) -> str:
    return f"***** Response from calling tool (call_code) *****\n{body}\n***** End of response *****"


def run_validated_sql(sql: str | None, *, question: str | None = None) -> tuple[str | None, str | None]:
    """Returns (normalized_sql_to_execute, executed_sql_or_none); caller runs db_execute_query."""
    if not sql:
        return None, None
    if not question:
        try:
            from jev_trace import get_request_question

            question = get_request_question() or None
        except ImportError:
            pass
    from sql_deterministic_repair import repair_sql_until_valid

    catalog = get_catalog()
    to_run, normalized = repair_sql_until_valid(sql, question, catalog)
    if not to_run:
        return None, None
    return to_run, normalized or to_run


def validation_error_body(sql: str | None, *, question: str | None = None) -> str:
    if not sql:
        return '{"sql_pipeline_error": true, "class": "empty", "message": "No sql_query"}'
    if question is None:
        try:
            from jev_trace import get_request_question

            question = get_request_question() or None
        except ImportError:
            question = None
    vr = validate_sql(sql, get_catalog(), question=question)
    if not vr.ok:
        return vr.error_payload()
    # Never return "" — UNION/GROUP BY can pass validate_sql without question.
    return json.dumps(
        {
            "sql_pipeline_error": True,
            "class": vr.error_class or "validation",
            "message": "SQL did not pass validation for this question",
        }
    )


def append_sql_tool_message(groupchat, body: str) -> int:
    groupchat.messages.append(
        {"name": "Sql_tool", "role": "assistant", "content": tool_wrap(body)}
    )
    return len(groupchat.messages) - 1