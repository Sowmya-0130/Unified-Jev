"""Recover time-window empty answers when Sql_Generator fails validation before DB execute."""
from __future__ import annotations

import json
import re
from typing import Any

from metadata import fetch_dataframe_readonly
from question_time import parse_time_window
from sql_catalog import get_catalog
from sql_execute_step import parse_sql_generator_query
from sql_match_count import build_filter_count_sql, question_needs_match_count
from sql_pipeline import validate_sql


def _groupchat_messages(groupchat: Any) -> list[dict]:
    return list(getattr(groupchat, "messages", None) or [])


def _question_from_groupchat(groupchat: Any) -> str:
    from jev_trace import get_request_question

    q = (get_request_question() or "").strip()
    if q:
        return q
    for msg in reversed(_groupchat_messages(groupchat)):
        raw = str(msg.get("content") or "")
        m = re.search(r'"question":\s*(.+?)(?:\n|$)', raw, re.IGNORECASE)
        if m:
            return m.group(1).strip().strip('"').strip()
    return ""


def try_time_window_zero_from_generator_sql(groupchat: Any) -> int | None:
    """
    Run COUNT(*) derived from the last Sql_Generator attempt (same FROM/WHERE).
    Returns match row count, or None if not applicable.
    """
    from jev_trace import get_request_question

    question = _question_from_groupchat(groupchat)
    if not question_needs_match_count(question):
        return None
    for msg in reversed(_groupchat_messages(groupchat)):
        if msg.get("name") != "Sql_Generator":
            continue
        sql = parse_sql_generator_query(msg.get("content"))
        if not sql:
            continue
        catalog = get_catalog()
        from sql_time_repair import try_patch_missing_time_predicate

        patched = try_patch_missing_time_predicate(sql, question, catalog)
        if patched:
            sql = patched
        count_sql = build_filter_count_sql(sql)
        if not count_sql:
            continue
        vr = validate_sql(count_sql, catalog, question=question)
        if not vr.ok:
            continue
        executed = vr.normalized_sql or count_sql
        try:
            df = fetch_dataframe_readonly(executed)
            n = int(df.iloc[0, 0]) if not df.empty else 0
        except Exception:  # noqa: BLE001
            return None
        from jev_trace import bump_sql_attempt, record_executed_sql, record_match_row_count, reset_sql_attempts

        record_executed_sql(executed)
        reset_sql_attempts()
        bump_sql_attempt()
        record_match_row_count(n)
        return n
    return None


def generator_sql_on_time_window_question(question: str) -> bool:
    return parse_time_window(question) is not None