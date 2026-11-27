"""Time-window hints for SQL repair (catalog date columns, no hardcoded tables)."""
from __future__ import annotations

import json
import re

from question_time import (
    TimeWindow,
    date_columns_from_catalog,
    hint_line,
    parse_time_window,
)
from schema_linker import score_tables, tables_mentioned_in_question
from sql_catalog import SqlCatalog, TableRef, get_catalog_readonly


def _year_from_window(tw: TimeWindow) -> int | None:
    m = re.search(r"(20\d{2})", tw.raw_phrase or "")
    return int(m.group(1)) if m else None


def _table_refs_for_question(question: str, catalog: SqlCatalog) -> list[TableRef]:
    refs: list[TableRef] = []
    seen: set[tuple[str, str]] = set()
    for ref in tables_mentioned_in_question(question, catalog) + [
        r for _, r in score_tables(question, catalog)[:3]
    ]:
        k = ref.key()
        if k not in seen:
            seen.add(k)
            refs.append(ref)
    return refs


def time_predicate_repair_hint(question: str) -> str:
    """
    Extra repair text when validation failed for missing time filter.
    Uses live catalog column names only.
    """
    tw = parse_time_window(question)
    if not tw:
        return ""
    catalog = get_catalog_readonly()
    refs = _table_refs_for_question(question, catalog)
    keys = [r.key() for r in refs]
    dcols = date_columns_from_catalog(question, catalog, keys)
    base = hint_line(tw, dcols)
    bracketed = refs[0].bracketed() if refs else "[schema].[table]"
    if tw.kind == "calendar_year":
        year = _year_from_window(tw)
        col = dcols[0] if dcols else None
        if year and col:
            return (
                f"{base}\n"
                f"Example pattern (adapt table alias): "
                f"WHERE YEAR({bracketed}.{col}) = {year} "
                f"OR ({bracketed}.{col} >= '{year}-01-01' AND {bracketed}.{col} < '{year + 1}-01-01'). "
                "Preserve product/name filters from the question."
            )
    if tw.kind == "last_months" and tw.months and dcols:
        col = dcols[0]
        return (
            f"{base}\n"
            f"Example: WHERE {bracketed}.{col} >= DATEADD(month, -{tw.months}, CAST(GETDATE() AS date))."
        )
    return base


_RE_BRACKET_TABLE = re.compile(
    r"\[(?P<sch>[^\]]+)\]\.\[(?P<tbl>[^\]]+)\]",
    re.IGNORECASE,
)


def _predicate_for_window(tw: TimeWindow, date_col: str) -> str | None:
    if tw.kind == "calendar_year":
        year = _year_from_window(tw)
        if year:
            return f"YEAR({date_col}) = {year}"
    if tw.kind == "last_months" and tw.months:
        return (
            f"{date_col} >= DATEADD(month, -{tw.months}, CAST(GETDATE() AS date))"
        )
    if tw.kind == "this_quarter":
        return f"{date_col} >= DATEADD(quarter, DATEDIFF(quarter, 0, GETDATE()), 0)"
    return None


def _inject_where_and(sql: str, predicate: str) -> str:
    raw = (sql or "").strip().rstrip(";")
    low = raw.lower()
    m_where = re.search(r"\bwhere\b", low)
    stop = re.compile(r"\b(group\s+by|order\s+by|having|union)\b", re.IGNORECASE)

    if m_where:
        tail = raw[m_where.end() :]
        m_stop = stop.search(tail)
        insert_at = m_where.end() + (m_stop.start() if m_stop else len(tail))
        return raw[:insert_at].rstrip() + f" AND ({predicate})" + raw[insert_at:]

    m_from = re.search(r"\bfrom\b", low)
    if not m_from:
        return f"{raw} WHERE {predicate}"
    rest = raw[m_from.end() :]
    m_stop = stop.search(rest)
    if m_stop:
        idx = m_from.end() + m_stop.start()
        return raw[:idx].rstrip() + f" WHERE {predicate} " + raw[idx:]
    return f"{raw} WHERE {predicate}"


def _validated_table_keys(sql: str, catalog: SqlCatalog) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for m in _RE_BRACKET_TABLE.finditer(sql or ""):
        sch, tbl = catalog.resolve_table_key(m.group("sch"), m.group("tbl"))
        if not catalog.has_table(sch, tbl):
            continue
        k = (sch.lower(), tbl.lower())
        if k in seen:
            continue
        seen.add(k)
        keys.append((sch, tbl))
    return keys


def try_patch_missing_time_predicate(
    sql: str, question: str, catalog: SqlCatalog
) -> str | None:
    """Deterministic AND/WHERE for catalog date column when validator needs a time window."""
    if not (sql or "").strip():
        return None
    tw = parse_time_window(question)
    if not tw:
        return None
    keys = _validated_table_keys(sql, catalog)
    if not keys:
        return None
    dcols = date_columns_from_catalog(question, catalog, keys)
    if not dcols:
        return None
    from question_time import sql_has_date_predicate

    if sql_has_date_predicate(sql, dcols):
        return None
    pred = _predicate_for_window(tw, dcols[0])
    if not pred:
        return None
    return _inject_where_and(sql, pred)


def patch_sql_json(sg_out: str, question: str, catalog: SqlCatalog) -> str | None:
    from sql_execute_step import parse_sql_generator_query

    sql = parse_sql_generator_query(sg_out)
    if not sql:
        return None
    patched = try_patch_missing_time_predicate(sql, question, catalog)
    if not patched or patched.strip() == sql.strip():
        return None
    return json.dumps({"sql_query": patched})


def enrich_validation_repair_reason(reason: str, sql_tool_body: str, question: str) -> str:
    """Append catalog-backed time hints when Sql_tool reported missing_time_predicate."""
    out = (reason or "").strip()
    body = str(sql_tool_body or "")
    needs_time = "missing_time_predicate" in out.lower() or "missing_time_predicate" in body.lower()
    if not needs_time:
        try:
            data = json.loads(body)
            if isinstance(data, dict) and data.get("class") == "missing_time_predicate":
                needs_time = True
        except json.JSONDecodeError:
            pass
    if not needs_time:
        return out
    hint = time_predicate_repair_hint(question)
    if not hint:
        return out
    if hint in out:
        return out
    return f"{out}\n\n{hint}"