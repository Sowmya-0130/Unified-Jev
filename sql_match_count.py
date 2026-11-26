"""Derive filtered row COUNT(*) from executed aggregate SQL."""
from __future__ import annotations

import json
import re
from typing import Any

from question_time import parse_time_window


def question_needs_match_count(question: str | None) -> bool:
    return parse_time_window(question or "") is not None


def build_filter_count_sql(sql: str) -> str | None:
    """COUNT(*) with the same FROM/WHERE as the primary SELECT (no UNION)."""
    raw = (sql or "").strip().rstrip(";")
    if not raw:
        return None
    if re.search(r"\bUNION\b", raw, re.IGNORECASE) or re.search(r"\bWITH\b", raw, re.IGNORECASE):
        m = re.search(
            r"FROM\s+(\[[^\]]+\]\.\[[^\]]+\])\s+WHERE\s+(.+?)\r?\n\s*\)",
            raw,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            table = m.group(1)
            where = m.group(2).strip().rstrip(")")
            where = re.sub(r"\s+GROUP\s+BY.*", "", where, flags=re.IGNORECASE)
            return f"SELECT COUNT(*) AS match_row_count FROM {table} WHERE {where}"
        for part in re.split(r"\bUNION\s+ALL\b", raw, flags=re.IGNORECASE):
            inner = part.strip()
            if re.search(r"\bGROUP\s+BY\b", inner, re.IGNORECASE):
                continue
            cs = build_filter_count_sql(inner)
            if cs:
                return cs
        return None
    low = raw.lower()
    from_idx = re.search(r"\bfrom\b", low, re.IGNORECASE)
    if not from_idx:
        return None
    tail = raw[from_idx.start() :]
    for stop in (re.compile(r"\bORDER\s+BY\b", re.I), re.compile(r"\bGROUP\s+BY\b", re.I)):
        m = stop.search(tail)
        if m:
            tail = tail[: m.start()]
    tail = tail.strip()
    if not tail.lower().startswith("from"):
        return None
    return f"SELECT COUNT(*) AS match_row_count {tail}"


def count_from_result_payload(sql_out: str, executed_sql: str) -> int | None:
    """Use COUNT/_count column in the result JSON when present."""
    raw = (sql_out or "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list) or not data:
        return None
    if len(data) != 1 or not isinstance(data[0], dict):
        return None
    row: dict[str, Any] = data[0]
    for key, val in row.items():
        if "count" in str(key).lower() and val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                pass
    return None


def resolve_match_row_count(
    sql_out: str,
    executed_sql: str,
    question: str | None,
    *,
    db_count: int | None = None,
) -> int | None:
    if not question_needs_match_count(question):
        return None
    if db_count is not None:
        return db_count
    inline = count_from_result_payload(sql_out, executed_sql)
    if inline is not None:
        return inline
    return None