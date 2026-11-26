"""Deterministic SQL validation, execution policy, and answer grounding (Q0–Q4 core)."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from sql_catalog import SqlCatalog, TableRef, get_catalog
from sql_safety import assert_readonly_sql

# Permanent SQL Server errors — no retries (Q3).
PERMANENT_SQL_MARKERS: tuple[str, ...] = (
    "40515",
    "(207)",
    "207)",
    "(208)",
    "208)",
    "(102)",
    "102)",
    "(229)",
    "229)",
)

TRANSIENT_SQL_MARKERS: tuple[str, ...] = (
    "1205",
    "deadlock",
    "connection reset",
    "timeout",
    "08s01",
    "40197",
    "40613",
)


@dataclass
class SqlValidationResult:
    ok: bool
    normalized_sql: str | None = None
    error_class: str | None = None
    message: str = ""
    candidates: list[str] = field(default_factory=list)
    identifier: str | None = None

    def error_payload(self) -> str:
        return json.dumps(
            {
                "sql_pipeline_error": True,
                "class": self.error_class,
                "message": self.message,
                "candidates": self.candidates,
                "identifier": self.identifier,
            }
        )


_RE_BRACKET_PAIR = re.compile(
    r"\[(?P<sch>[^\]]+)\]\.\[(?P<tbl>[^\]]+)\]",
    re.IGNORECASE,
)
_RE_DBO_BRACKET_TABLE = re.compile(
    r"\bdbo\.\[(?P<tbl>[^\]]+)\]",
    re.IGNORECASE,
)
_RE_THREE_PART = re.compile(
    r"\bdbo\.([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\b",
    re.IGNORECASE,
)
_RE_TWO_PART = re.compile(
    r"\b([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\b",
    re.IGNORECASE,
)
_RE_DBO_TWO_PART = re.compile(
    r"\bdbo\.([A-Za-z_][\w]*)\b",
    re.IGNORECASE,
)
_RE_SELECT_STAR = re.compile(r"\bSELECT\s+TOP\s+\d+\s+\*", re.IGNORECASE)
_RE_BRACKET_PAIR_GLOBAL = re.compile(r"\[([^\]]+)\]\.\[([^\]]+)\]", re.IGNORECASE)
_COL_RE = re.compile(
    r"\b([A-Za-z_][\w]*)\b(?=\s*(?:,|FROM|WHERE|GROUP|ORDER|HAVING|$))",
    re.IGNORECASE,
)

_SQL_KEYWORDS = frozenset(
    k.lower()
    for k in (
        "select",
        "from",
        "where",
        "group",
        "by",
        "order",
        "having",
        "top",
        "as",
        "and",
        "or",
        "on",
        "join",
        "inner",
        "left",
        "right",
        "with",
        "count",
        "sum",
        "avg",
        "min",
        "max",
        "distinct",
        "case",
        "when",
        "then",
        "else",
        "end",
        "null",
        "not",
        "in",
        "like",
        "between",
        "dbo",
        "asc",
        "desc",
    )
)

_execution_three_part_counter = 0


def apply_canonical_identifiers(sql: str, catalog: SqlCatalog) -> str:
    def _repl(m: re.Match[str]) -> str:
        key = (m.group(1).lower(), m.group(2).lower())
        if catalog.has_table(key[0], key[1]):
            return catalog.bracketed(key[0], key[1])
        return m.group(0)

    return _RE_BRACKET_PAIR_GLOBAL.sub(_repl, sql)


def sql_fingerprint(sql: str) -> str:
    q = re.sub(r"\s+", " ", (sql or "").strip().lower())
    return hashlib.sha256(q.encode()).hexdigest()[:16]


def classify_sql_exception(exc: BaseException | str) -> str:
    text = str(exc).lower()
    for m in PERMANENT_SQL_MARKERS:
        if m.lower() in text:
            return "permanent"
    for m in TRANSIENT_SQL_MARKERS:
        if m.lower() in text:
            return "transient"
    return "unknown"


def max_retries_for_exception(exc: BaseException | str) -> int:
    return 0 if classify_sql_exception(exc) == "permanent" else 1


def assert_execution_query_matches(*, validated_sql: str, attempted_sql: str) -> None:
    if sql_fingerprint(validated_sql) != sql_fingerprint(attempted_sql):
        raise ValueError(
            "Executor must run validated SQL unchanged "
            f"(validated={validated_sql!r}, attempted={attempted_sql!r})"
        )


def _extract_table_refs(
    sql: str, catalog: SqlCatalog | None = None
) -> list[tuple[str, str, str]]:
    """Return list of (kind, schema, table) where kind is bracketed|dbo_bracket|three_part|two_part."""
    refs: list[tuple[str, str, str]] = []
    for m in _RE_BRACKET_PAIR.finditer(sql):
        sch, tbl = m.group("sch"), m.group("tbl")
        if sch.lower() != "dbo" and tbl.lower() == "dbo":
            refs.append(("invalid_nested", sch, tbl))
        elif catalog:
            rsch, rtbl = catalog.resolve_table_key(sch, tbl)
            refs.append(("bracketed", rsch, rtbl))
        else:
            refs.append(("bracketed", sch, tbl))
    for m in _RE_DBO_BRACKET_TABLE.finditer(sql):
        refs.append(("dbo_bracket", "dbo", m.group("tbl")))
    for m in _RE_DBO_TWO_PART.finditer(sql):
        if not any(r[1] == "dbo" and r[2] == m.group(1) for r in refs if r[0] == "dbo_bracket"):
            refs.append(("two_part", "dbo", m.group(1)))
    if not any(k in ("bracketed", "dbo_bracket") for k, _, _ in refs):
        for m in _RE_THREE_PART.finditer(sql):
            refs.append(("three_part", "dbo", f"{m.group(1)}.{m.group(2)}"))
        for m in _RE_TWO_PART.finditer(sql):
            if m.group(0).lower().startswith("dbo."):
                continue
            if len(m.group(1)) <= 1:
                continue
            sch, tbl = m.group(1), m.group(2)
            if catalog and not (
                catalog.has_table(sch, tbl)
                or catalog.has_table("dbo", f"{sch}.{tbl}")
                or catalog.has_table("dbo", tbl)
            ):
                continue
            refs.append(("two_part", sch, tbl))
    return refs


def _question_expects_scalar_aggregate(question: str) -> bool:
    q = (question or "").lower()
    return any(
        phrase in q
        for phrase in (
            "what is the total",
            "combined total",
            "how many rows",
            "how many ",
            "what is the average",
            "average ",
            "sum of",
            "sum total",
            "total total_amount",
            "total amount",
        )
    )


def _select_column_names(sql: str) -> set[str]:
    m = re.search(r"\bselect\b(.*?)\bfrom\b", sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return set()
    segment = m.group(1)
    cols: set[str] = set()
    for piece in segment.split(","):
        piece = piece.strip()
        piece = re.sub(r"^(distinct|top\s+\d+)\s+", "", piece, flags=re.IGNORECASE)
        if piece == "*":
            continue
        piece = re.sub(r"\bas\s+\w+", "", piece, flags=re.IGNORECASE).strip()
        if "(" in piece:
            continue
        piece = re.sub(r"\(.*\)", "", piece).strip()
        for token in piece.split():
            t = token.strip()
            if t and t.lower() not in _SQL_KEYWORDS and not t.isdigit():
                cols.add(t.split(".")[-1])
    return {c for c in cols if c and c.lower() not in _SQL_KEYWORDS}


def validate_sql(
    sql: str,
    catalog: SqlCatalog | None = None,
    *,
    question: str | None = None,
) -> SqlValidationResult:
    catalog = catalog or get_catalog()
    raw = (sql or "").strip()
    try:
        from sqlglot_validate import validate_with_sqlglot

        sg = validate_with_sqlglot(raw, catalog)
        if sg is not None and not sg.ok:
            if sg.error_class in ("invalid_identifier", "parse", "empty", "unrequested_fanout"):
                return sg
            # unknown_table from sqlglot may be alias noise — fall through to heuristics
    except Exception:  # noqa: BLE001
        pass
    if not raw:
        return SqlValidationResult(False, error_class="empty", message="Empty SQL")

    if question and _question_expects_scalar_aggregate(question):
        if re.search(r"\bUNION\b", raw, re.IGNORECASE):
            return SqlValidationResult(
                False,
                error_class="unrequested_union",
                message="UNION not allowed for single-value aggregate questions",
            )
        if re.search(r"\bGROUP\s+BY\b", raw, re.IGNORECASE) and not re.search(
            r"\btop\s+\d+\b", question, re.IGNORECASE
        ):
            return SqlValidationResult(
                False,
                error_class="unrequested_fanout",
                message="GROUP BY not allowed for single total questions (use one aggregate)",
            )

    try:
        assert_readonly_sql(raw)
    except ValueError as e:
        return SqlValidationResult(False, error_class="readonly", message=str(e))

    if _RE_SELECT_STAR.search(raw) and "group by" not in raw.lower():
        return SqlValidationResult(
            False,
            error_class="unrequested_fanout",
            message="SELECT TOP * row fan-out blocked (use aggregates/GROUP BY)",
        )

    if re.search(r"\[[^\]]+\]\.\s*dbo\.", raw, re.IGNORECASE):
        need = _select_column_names(raw)
        return SqlValidationResult(
            False,
            error_class="invalid_identifier",
            message="Invalid bracketed chain with dbo segment",
            candidates=catalog.candidate_tables_with_columns(need) or catalog.all_bracketed_names(),
        )

    refs = _extract_table_refs(raw, catalog)
    for kind, sch, tbl in refs:
        if kind == "invalid_nested":
            cands = catalog.candidate_tables_with_columns(_select_column_names(raw))
            return SqlValidationResult(
                False,
                error_class="invalid_identifier",
                message=f"Invalid nested reference [{sch}].[{tbl}]",
                candidates=cands,
                identifier=f"[{sch}].[{tbl}]",
            )
        if kind == "three_part":
            parts = tbl.split(".")
            need = _select_column_names(raw)
            if re.search(r"count\s*\(\s*\*", raw, re.IGNORECASE):
                need = set()
            resolved_bracketed: str | None = None
            if len(parts) == 2 and catalog.has_table(parts[0], parts[1]):
                resolved_bracketed = f"[{parts[0]}].[{parts[1]}]"
            elif catalog.has_table("dbo", ".".join(parts)):
                resolved_bracketed = f"[dbo].[{'.'.join(parts)}]"
            canonicals = (
                catalog.candidate_tables_with_columns(need)
                if need
                else catalog.all_bracketed_names()
            )
            if resolved_bracketed:
                pattern = re.compile(r"\bdbo\." + re.escape(tbl) + r"\b", re.IGNORECASE)
                normalized = pattern.sub(resolved_bracketed, raw).rstrip(";")
                return SqlValidationResult(True, normalized_sql=normalized)
            if len(canonicals) > 1:
                return SqlValidationResult(
                    False,
                    error_class="ambiguous_table",
                    message="Three-part name is ambiguous",
                    candidates=canonicals,
                    identifier=f"dbo.{tbl}",
                )
            return SqlValidationResult(
                False,
                error_class="invalid_identifier",
                message=f"Cannot resolve dbo.{tbl}",
                candidates=canonicals,
                identifier=f"dbo.{tbl}",
            )

    validated_refs: list[tuple[str, str]] = []
    for kind, sch, tbl in refs:
        if kind in ("bracketed", "dbo_bracket", "two_part"):
            if kind == "dbo_bracket":
                sch, tbl = "dbo", tbl
            sch, tbl = catalog.resolve_table_key(sch, tbl)
            if catalog.is_shadow_table(sch, tbl):
                sch, tbl = catalog.shadow_targets.get((sch, tbl), (sch, tbl))
            if not catalog.has_table(sch, tbl):
                return SqlValidationResult(
                    False,
                    error_class="unknown_table",
                    message=f"Unknown table [{sch}].[{tbl}]",
                    candidates=catalog.all_bracketed_names(),
                    identifier=f"[{sch}].[{tbl}]",
                )
            validated_refs.append((sch, tbl))

    from sql_column_validate import validate_query_columns

    col_vr = validate_query_columns(raw, catalog)
    if col_vr is not None and not col_vr.ok:
        return col_vr

    if question:
        from question_time import (
            date_columns_from_catalog,
            parse_time_window,
            sql_has_date_predicate,
        )

        tw = parse_time_window(question)
        if tw and validated_refs:
            dcols = date_columns_from_catalog(question, catalog, validated_refs)
            if dcols and not sql_has_date_predicate(raw, dcols):
                return SqlValidationResult(
                    False,
                    error_class="missing_time_predicate",
                    message=(
                        f"Question time window '{tw.raw_phrase}' requires a WHERE on "
                        f"{', '.join(dcols[:4])}"
                    ),
                )

    normalized = raw.rstrip(";")
    for kind, sch, tbl in refs:
        if kind == "two_part":
            bracketed = catalog.bracketed(sch, tbl)
            normalized = re.sub(
                r"\b" + re.escape(f"{sch}.{tbl}") + r"\b",
                bracketed,
                normalized,
                flags=re.IGNORECASE,
            )
    normalized = apply_canonical_identifiers(normalized, catalog)
    return SqlValidationResult(True, normalized_sql=normalized)


def record_three_part_execution_attempt(sql: str) -> None:
    global _execution_three_part_counter
    if _RE_THREE_PART.search(sql):
        _execution_three_part_counter += 1
        import logging

        logging.getLogger("aurix.sql_pipeline").error(
            "PRODUCTION GUARD: 3-part SQL reached execution (count=%s) sql=%s",
            _execution_three_part_counter,
            sql[:200],
        )


INSIGHT_REQUIRED_KEYS = frozenset({"query_answer", "inference", "executed_sql"})
INSIGHT_LEGACY_ALIASES = {
    "query_query": "executed_sql",
    "query_scores": "inference",
    "scores": "inference",
}


def validate_insight_schema(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for old, new in INSIGHT_LEGACY_ALIASES.items():
        if old in payload:
            errors.append(f"renamed:{old}->{new}")
    missing = [k for k in INSIGHT_REQUIRED_KEYS if k not in payload or payload[k] in (None, "")]
    errors.extend(f"missing:{k}" for k in missing)
    return errors


def extract_numbers(text: str) -> set[float]:
    found: set[float] = set()
    for m in re.finditer(r"-?\d+(?:\.\d+)?", text or ""):
        try:
            found.add(float(m.group(0)))
        except ValueError:
            pass
    return found


def assert_answer_grounded(
    *,
    query_answer: str,
    executed_sql: str,
    claimed_sql: str,
    result_rows: list[dict[str, Any]],
) -> None:
    if sql_fingerprint(executed_sql) != sql_fingerprint(claimed_sql):
        raise ValueError("executed_sql does not match the SQL that was actually run")
    nums = extract_numbers(query_answer)
    if not nums:
        return
    row_nums: set[float] = set()
    for row in result_rows:
        for v in row.values():
            if v is None:
                continue
            try:
                row_nums.add(float(v))
            except (TypeError, ValueError):
                for m in re.finditer(r"-?\d+(?:\.\d+)?", str(v)):
                    row_nums.add(float(m.group(0)))
    if not row_nums:
        raise ValueError("no numeric values in result rows for grounding check")
    derived = set()
    if len(row_nums) > 1 and "sum" in executed_sql.lower():
        derived.add(sum(row_nums))
    allowed = row_nums | derived
    for n in nums:
        if not any(abs(n - a) < 0.01 or (a != 0 and abs(n / a - 1.0) < 0.001) for a in allowed):
            raise ValueError(f"answer number {n} not grounded in executed result")