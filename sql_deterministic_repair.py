"""Deterministic SQL repairs before LLM repair (scalar collapse, time predicates)."""
from __future__ import annotations

import json
import re

from question_time import parse_time_window
from sql_catalog import SqlCatalog
from sql_pipeline import SqlValidationResult, validate_sql, _question_expects_scalar_aggregate
from sql_time_repair import try_patch_missing_time_predicate


def _table_keys_from_sql(sql: str, catalog: SqlCatalog) -> list[tuple[str, str]]:
    from sql_time_repair import _RE_BRACKET_TABLE

    keys: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for m in _RE_BRACKET_TABLE.finditer(sql or ""):
        sch, tbl = catalog.resolve_table_key(m.group("sch"), m.group("tbl"))
        if not catalog.has_table(sch, tbl):
            continue
        k = (sch.lower(), tbl.lower())
        if k not in seen:
            seen.add(k)
            keys.append((sch, tbl))
    for m in re.finditer(
        r"\bfrom\s+([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\b",
        sql or "",
        re.IGNORECASE,
    ):
        sch, tbl = catalog.resolve_table_key(m.group(1), m.group(2))
        if not catalog.has_table(sch, tbl):
            continue
        k = (sch.lower(), tbl.lower())
        if k not in seen:
            seen.add(k)
            keys.append((sch, tbl))
    return keys


def try_collapse_groupby_scalar(sql: str, question: str) -> str | None:
    """Scalar total questions: drop GROUP BY and keep one aggregate in SELECT."""
    if not _question_expects_scalar_aggregate(question):
        return None
    raw = (sql or "").strip()
    if not re.search(r"\bgroup\s+by\b", raw, re.IGNORECASE):
        return None
    if not re.search(r"\b(sum|count|avg|min|max)\s*\(", raw, re.IGNORECASE):
        return None
    collapsed = re.sub(
        r"\bgroup\s+by\b.*?(?=\border\s+by\b|\bhaving\b|;|$)",
        "",
        raw,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )
    m = re.search(r"\bselect\b(.*?)\bfrom\b", collapsed, re.IGNORECASE | re.DOTALL)
    if not m:
        return collapsed.strip()
    agg = re.search(
        r"((?:sum|count|avg|min|max)\s*\(\s*[^)]+\s*\)(?:\s+as\s+[A-Za-z_][\w]*)?)",
        m.group(1),
        re.IGNORECASE,
    )
    if not agg:
        return collapsed.strip()
    from_m = re.search(r"\bfrom\b", collapsed[m.end() - 4 :], re.IGNORECASE)
    if not from_m:
        return collapsed.strip()
    tail = collapsed[m.end() - 4 + from_m.start() :]
    return f"SELECT {agg.group(1)} {tail}".strip()


def apply_deterministic_sql_repairs(
    sql: str,
    question: str,
    catalog: SqlCatalog,
    *,
    vr: SqlValidationResult | None = None,
) -> str | None:
    """Return improved SQL or None if no change."""
    vr = vr or validate_sql(sql, catalog, question=question)
    current = (sql or "").strip()
    if not current:
        return None
    candidate = current

    if vr.error_class == "unrequested_fanout" or re.search(r"\bgroup\s+by\b", current, re.I):
        collapsed = try_collapse_groupby_scalar(current, question)
        if collapsed and collapsed != current:
            candidate = collapsed

    if parse_time_window(question or ""):
        tw_pat = try_patch_missing_time_predicate(candidate, question, catalog)
        if tw_pat:
            candidate = tw_pat

    return candidate if candidate != current else None


def repair_sql_until_valid(
    sql: str | None,
    question: str | None,
    catalog: SqlCatalog,
) -> tuple[str | None, str | None]:
    """Like run_validated_sql inner loop — returns (executable, normalized)."""
    current = (sql or "").strip()
    if not current:
        return None, None
    for _ in range(4):
        vr = validate_sql(current, catalog, question=question)
        if vr.ok:
            out = vr.normalized_sql or current
            return out, out
        nxt = apply_deterministic_sql_repairs(current, question or "", catalog, vr=vr)
        if not nxt or nxt == current:
            if parse_time_window(question or ""):
                nxt = try_patch_missing_time_predicate(current, question or "", catalog)
            if not nxt or nxt == current:
                break
        current = nxt
    return None, None


def patch_generator_sql_deterministic(
    sg_out: str,
    question: str,
    sql_tool_body: str,
    catalog: SqlCatalog,
) -> str | None:
    from jev_trace import trace_stdout
    from sql_execute_step import parse_sql_generator_query

    sql = parse_sql_generator_query(sg_out)
    if not sql:
        trace_stdout("SQL deterministic repair: skip (no sql_query in generator output)")
        return None
    vr = validate_sql(sql, catalog, question=question)
    repaired = apply_deterministic_sql_repairs(sql, question, catalog, vr=vr)
    if not repaired:
        keys = _table_keys_from_sql(sql, catalog)
        trace_stdout(
            f"SQL deterministic repair: skip class={vr.error_class!s} "
            f"tables={len(keys)} time_q={bool(parse_time_window(question))}"
        )
        return None
    vr2 = validate_sql(repaired, catalog, question=question)
    if not vr2.ok:
        trace_stdout(f"SQL deterministic repair: patched still invalid ({vr2.error_class})")
        return None
    trace_stdout(f"SQL deterministic repair: ok ({vr.error_class} → valid)")
    return json.dumps({"sql_query": repaired})


def recover_last_generator_sql(transcript: list, question: str, catalog: SqlCatalog) -> str | None:
    """After empty generator reply, reuse last non-empty SQL with deterministic repairs."""
    from sql_execute_step import parse_sql_generator_query

    for msg in reversed(transcript or []):
        if msg.get("name") != "Sql_Generator":
            continue
        sql = parse_sql_generator_query(msg.get("content"))
        if not sql:
            continue
        fixed, _ = repair_sql_until_valid(sql, question, catalog)
        if fixed:
            return json.dumps({"sql_query": fixed})
    return None