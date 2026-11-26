"""Classify SQL vs semantic vs Both using catalog linkage + doc-intent (no hardcoded tables)."""
from __future__ import annotations

import re

_DOC_INTENT = re.compile(
    r"\b(documentation|document|policy|policies|return|returns|warranty|terms|procedure)\b",
    re.IGNORECASE,
)
_SQL_INTENT = re.compile(
    r"\b(total|sum|how many|count|average|avg|top\s+\d+|list the|amount|composite_score)\b",
    re.IGNORECASE,
)
_BOTH_SPLIT = re.compile(
    r"\s+and\s+(?:what|how)\s+(?:does|do|is|are)\b",
    re.IGNORECASE,
)


def split_both_question(question: str) -> tuple[str, str]:
    """Return (data-oriented part, document-oriented part)."""
    q = (question or "").strip()
    m = _BOTH_SPLIT.search(q)
    if not m:
        return q, q
    left = q[: m.start()].strip().rstrip(",?") + "?"
    right = q[m.start() + 5 :].strip()
    if not right.endswith("?"):
        right = right.rstrip(".") + "?"
    return left, right


def catalog_supports_sql(question: str) -> bool:
    from schema_linker import tables_mentioned_in_question, score_tables
    from sql_catalog import CatalogUnavailableError, get_catalog

    try:
        cat = get_catalog()
    except (CatalogUnavailableError, Exception):  # noqa: BLE001
        return bool(_SQL_INTENT.search(question or ""))
    if tables_mentioned_in_question(question, cat):
        return True
    scored = score_tables(question, cat)
    return bool(scored and scored[0][0] >= 30.0)


def infer_dual_route(question: str) -> str | None:
    q = (question or "").strip()
    if not q:
        return None
    doc = bool(_DOC_INTENT.search(q))
    sqlish = bool(_SQL_INTENT.search(q)) or catalog_supports_sql(q)
    if doc and sqlish:
        return "Both-independent"
    return None


def merge_openjev_route(question: str, jev: dict) -> dict:
    """Override OpenJev when question clearly needs Both."""
    out = dict(jev)
    dual = infer_dual_route(question)
    if not dual:
        return out
    choice = (jev.get("choice") or "").strip()
    if choice.startswith("Both"):
        return out
    if choice == "Semantic-based" and catalog_supports_sql(question):
        out["choice"] = dual
        out["confidence"] = max(float(jev.get("confidence") or 0.0), 0.88)
        out["decision_source"] = "heuristic_both"
    elif choice == "SQL-based" and _DOC_INTENT.search(question):
        out["choice"] = dual
        out["confidence"] = max(float(jev.get("confidence") or 0.0), 0.88)
        out["decision_source"] = "heuristic_both"
    return out


def next_agent_for_route(route: str) -> str:
    if route == "SQL-based" or route == "Both-dependent":
        return "Sql_Generator"
    if route == "Semantic-based":
        return "Eryl_agent"
    if route.startswith("Both"):
        return "Both_handler"
    return "Eryl_agent"


def coerce_sql_only_route(question: str, analysis_type: str) -> str | None:
    """LLM sometimes labels pure analytics as Both-*; correct when catalog has no doc leg."""
    at = (analysis_type or "").strip()
    if not at.startswith("Both"):
        return None
    if _DOC_INTENT.search(question or ""):
        return None
    if infer_dual_route(question) == "Both-independent":
        return None
    if catalog_supports_sql(question):
        return "SQL-based"
    return None