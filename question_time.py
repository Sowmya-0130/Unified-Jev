"""Parse relative time windows from natural-language questions (no hardcoded table names)."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TimeWindow:
    kind: str
    months: int | None = None
    raw_phrase: str = ""


def parse_time_window(question: str) -> TimeWindow | None:
    text = question or ""
    m = re.search(r"\blast\s+(\d+)\s+months?\b", text, re.IGNORECASE)
    if m:
        return TimeWindow(kind="last_months", months=int(m.group(1)), raw_phrase=m.group(0))
    if re.search(r"\bthis\s+quarter\b", text, re.IGNORECASE):
        return TimeWindow(kind="this_quarter", raw_phrase="this quarter")
    m = re.search(r"\bin\s+20\d{2}\b", text, re.IGNORECASE)
    if m:
        return TimeWindow(kind="calendar_year", raw_phrase=m.group(0))
    m = re.search(r"\b(?:for|during)\s+.{0,80}?\b(20\d{2})\b", text, re.IGNORECASE)
    if m:
        return TimeWindow(kind="calendar_year", raw_phrase=f"in {m.group(1)}")
    return None


def hint_line(window: TimeWindow, date_columns: list[str]) -> str:
    cols = ", ".join(date_columns[:6]) if date_columns else "(use a date/datetime column from linked tables)"
    if window.kind == "last_months" and window.months:
        return (
            f"**Time filter (required):** question asks for `{window.raw_phrase}` — "
            f"SQL WHERE must filter using {cols} (e.g. DATEADD(month, -{window.months}, GETDATE()))."
        )
    if window.kind == "calendar_year":
        m = re.search(r"(20\d{2})", window.raw_phrase or "")
        year = m.group(1) if m else "YYYY"
        return (
            f"**Time filter (required):** question asks for `{window.raw_phrase}` — "
            f"SQL WHERE must filter using {cols} (e.g. YEAR(<col>) = {year} "
            f"or <col> between '{year}-01-01' and '{year}-12-31')."
        )
    return f"**Time filter (required):** `{window.raw_phrase}` — SQL WHERE must use {cols}."


def date_columns_from_catalog(question: str, catalog, table_keys: list[tuple[str, str]]) -> list[str]:
    """Date-like column names present on linked tables (from catalog, not hardcoded per table)."""
    hits: list[str] = []
    for sch, tbl in table_keys:
        for col in catalog.columns(sch, tbl):
            cl = col.lower()
            if "date" in cl or cl.endswith("_at") or cl.endswith("_on"):
                hits.append(col)
    return sorted(set(hits))


def sql_has_date_predicate(sql: str, date_columns: list[str]) -> bool:
    low = (sql or "").lower()
    if re.search(r"\byear\s*\(", low):
        return True
    if any(fn in low for fn in ("dateadd", "datediff", "getdate", "current_timestamp")):
        return True
    if re.search(r"\bbetween\b", low) and re.search(r"date", low):
        return True
    for col in date_columns:
        if col.lower() in low:
            return True
    return False