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
            question = _request_question()
            out = {
                "query_answer": format_prose_scalar(question, scalar),
                "inference": "Single-value result from executed SQL.",
                "executed_sql": ex,
                "python_code": None,
            }
            if validate_insight_schema(out):
                return None
            return out

    if len(rows) == 1 and len(rows[0]) > 1:
        question = _request_question()
        prose = format_prose_from_row(question, rows[0])
        from sql_pipeline import validate_insight_schema

        out = {
            "query_answer": prose,
            "inference": "Single row with metrics from executed SQL.",
            "executed_sql": ex,
            "python_code": None,
        }
        if validate_insight_schema(out):
            return None
        return out

    if len(rows) <= 8 and _is_simple_list(rows):
        question = _request_question()
        if len(rows) == 1:
            prose = format_prose_from_row(question, rows[0])
        else:
            intro = f"**{(question or 'Results').rstrip('?')}**\n\n"
            bullets = []
            for row in rows:
                prose = format_prose_from_row("", row).replace("**", "")
                bullets.append(f"- {prose.strip()}")
            prose = intro + "\n".join(bullets)
        return {
            "query_answer": prose,
            "inference": f"Summarized {len(rows)} row(s) from SQL.",
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


def _format_number_locale(val: float | int) -> str:
    s = _format_number(val)
    if "." in s:
        whole, frac = s.split(".", 1)
    else:
        whole, frac = s, ""
    neg = whole.startswith("-")
    if neg:
        whole = whole[1:]
    with_commas = f"{int(whole):,}" if whole.isdigit() else whole
    out = f"{'-' if neg else ''}{with_commas}"
    return f"{out}.{frac}" if frac else out


def _human_metric_label(col_name: str) -> str:
    name = (col_name or "").replace("_", " ").strip()
    low = name.lower()
    if "total" in low and "amount" in low:
        return "total order amount"
    if low in ("total", "sum", "metric"):
        return "total"
    return name.lower() if name else "result"


def _request_question() -> str:
    try:
        from jev_trace import get_request_question

        return (get_request_question() or "").strip()
    except ImportError:
        return ""


def format_prose_from_row(question: str, row: dict[str, Any]) -> str:
    """Chat-style answer from one result row (no raw key: value dump)."""
    q = (question or "").strip().rstrip("?").strip()
    amount_val: Any = None
    amount_key = ""
    count_val: Any = None
    for k, v in row.items():
        kl = k.lower()
        if v is None:
            continue
        if "count" in kl and count_val is None and isinstance(v, (int, float)):
            count_val = v
            continue
        if amount_val is None and isinstance(v, (int, float)):
            if any(t in kl for t in ("total", "amount", "sum", "avg", "metric", "revenue")):
                amount_val, amount_key = v, k
            elif not any("count" in x.lower() for x in row) or len(row) == 1:
                amount_val, amount_key = v, k
    if amount_val is None:
        for k, v in row.items():
            if "count" not in k.lower() and isinstance(v, (int, float)):
                amount_val, amount_key = v, k
                break

    lines: list[str] = []
    if q:
        lines.append(f"**{q}**")
        lines.append("")
    if amount_val is not None:
        label = _human_metric_label(amount_key)
        lines.append(
            f"The {label} is **{_format_number_locale(float(amount_val))}**."
        )
    if count_val is not None:
        n = int(count_val)
        noun = "order" if n == 1 else "orders"
        lines.append(f"This is based on **{n:,}** matching {noun} in the database.")
    if not lines or (q and len(lines) <= 2 and amount_val is None):
        parts = [f"{_human_metric_label(k)}: {_format_number_locale(v)}" for k, v in row.items() if v is not None]
        if q:
            return f"**{q}**\n\n" + " ".join(parts) + "."
        return " ".join(parts) + "."
    return "\n".join(lines)


def format_prose_scalar(question: str, scalar: float | int) -> str:
    q = (question or "").strip().rstrip("?").strip()
    val = _format_number_locale(scalar)
    if q:
        return f"**{q}**\n\nThe answer is **{val}**."
    return f"The answer is **{val}**."


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