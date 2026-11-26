from __future__ import annotations

from unittest.mock import patch

from dual_route import (
    coerce_sql_only_route,
    infer_dual_route,
    merge_openjev_route,
    split_both_question,
)


def test_split_both_question():
    q = (
        "What were the total order amounts for Kevlar Gloves in 2025, "
        "and what does the documentation say about returns for those products?"
    )
    sql_q, doc_q = split_both_question(q)
    assert "total" in sql_q.lower()
    assert "documentation" in doc_q.lower() or "return" in doc_q.lower()


def test_infer_dual_on_doc_and_sql():
    q = (
        "What is the total Total_Amount for Chemical Resistant Boots in dupoint email data Orders, "
        "and what does the return policy documentation say about defective items?"
    )
    with patch("dual_route.catalog_supports_sql", return_value=True):
        assert infer_dual_route(q) == "Both-independent"


def test_merge_openjev_semantic_to_both():
    q = "Total amount in Orders and return policy in documentation?"
    jev = {"choice": "Semantic-based", "confidence": 0.91, "source": "openjev"}
    with patch("dual_route.catalog_supports_sql", return_value=True):
        out = merge_openjev_route(q, jev)
    assert out["choice"] == "Both-independent"
    assert out["confidence"] >= 0.88


def test_coerce_sql_only_route_rejects_misrouted_both():
    q = (
        "What is the total Total_Amount for Chemical Resistant Boots and Kevlar Gloves "
        "orders in dupoint email data Orders in the last 2 months?"
    )
    with patch("dual_route.catalog_supports_sql", return_value=True):
        assert coerce_sql_only_route(q, "Both-dependent") == "SQL-based"
        assert coerce_sql_only_route(q, "SQL-based") is None