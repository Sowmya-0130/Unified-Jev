"""Deterministic SQL result → Insight JSON (no LLM) for simple shapes."""
from __future__ import annotations

import json
import re
from typing import Any


def _parse_rows(payload: str) -> list[dict[str, Any]] | None:
    text = (payload or "").strip()
    if not text or "sql_pipeline_error" in text[:200]:
        return None
    if text.startswith("An error occurred") or text.startswith("Query blocked"):
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, list):
        return data
    return None


def _scalar_from_row(row: dict[str, Any]) -> float | int | None:
    if len(row) != 1:
        return None
    val = next(iter(row.values()))
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return val
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def build_insight_from_sql_result(
    result_payload: str,
    executed_sql: str,
) -> dict[str, Any] | None:
    rows = _parse_rows(result_payload)
    if rows is None:
        return None
    ex = (executed_sql or "").strip()
    if not ex:
        return None

    if not rows:
        return {
            "query_answer": "No matching data.",
            "inference": "The query returned zero rows.",
            "executed_sql": ex,
            "python_code": None,
        }

    if len(rows) == 1:
        row = rows[0]
        null_or_zero = all(
            v is None or (isinstance(v, (int, float)) and float(v) == 0.0)
            for v in row.values()
        )
        has_count_zero = any(
            k.lower().find("count") >= 0 and v in (0, 0.0, "0")
            for k, v in row.items()
        )
        scalar = _scalar_from_row(row)
        if scalar is None and (null_or_zero or has_count_zero):
            return {
                "query_answer": "No matching data.",
                "inference": "No rows or NULL aggregates for the given filters.",
                "executed_sql": ex,
                "python_code": None,
            }
        if scalar is None and len(row) == 1 and next(iter(row.values())) is None:
            return {
                "query_answer": "No matching data.",
                "inference": "Aggregate returned NULL (no matching rows).",
                "executed_sql": ex,
                "python_code": None,
            }
        if scalar is not None:
            from sql_pipeline import validate_insight_schema

            if float(scalar) == 0.0 and _aggregate_empty(ex):
                return {
                    "query_answer": "No matching data.",
                    "inference": "Aggregate is zero (no matching rows for the filters).",
                    "executed_sql": ex,
                    "python_code": None,
                }
            out = {
                "query_answer": _format_number(scalar),
                "inference": "Single-value result from executed SQL.",
                "executed_sql": ex,
                "python_code": None,
            }
            if validate_insight_schema(out):
                return None
            return out

    if len(rows) <= 8 and _is_simple_list(rows):
        lines = []
        for i, row in enumerate(rows, 1):
            parts = [f"{k}: {v}" for k, v in row.items()]
            lines.append(f"{i}. " + ", ".join(parts))
        return {
            "query_answer": "\n".join(lines),
            "inference": f"Listed {len(rows)} row(s) from SQL.",
            "executed_sql": ex,
            "python_code": None,
        }
    return None


def _format_number(val: float | int) -> str:
    if isinstance(val, float) and val == int(val):
        return str(int(val))
    if isinstance(val, float):
        return re.sub(r"\.?0+$", "", f"{val:.6f}".rstrip("0").rstrip("."))
    return str(val)


_AGG_EMPTY_RE = re.compile(r"\b(SUM|COUNT|AVG|MIN|MAX)\s*\(", re.IGNORECASE)


def _aggregate_empty(executed_sql: str) -> bool:
    return bool(_AGG_EMPTY_RE.search(executed_sql or ""))


def _is_simple_list(rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        if len(row) > 4:
            return False
        for v in row.values():
            if isinstance(v, str) and len(v) > 120:
                return False
    return True