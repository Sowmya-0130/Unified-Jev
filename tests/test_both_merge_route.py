"""Both merge + doc-leg routing (structured + unstructured)."""
from __future__ import annotations

from unittest.mock import patch

import API_unified
import pytest

from both_answer import _extract_document_answer, merge_both_responses


@pytest.fixture(autouse=True)
def _legacy_merge_sections(monkeypatch):
    """Keep merge tests on concat path unless testing merge_node directly."""
    monkeypatch.setattr(API_unified, "MERGE_NODE_ENABLED", False)
from dual_route import is_document_only_question
from routing_s4 import preflight_both_leg


def test_document_only_leg_not_sql_when_catalog_scores():
    q = "what does the documentation say about returns for those products?"
    assert is_document_only_question(q) is True
    with patch("dual_route.catalog_supports_sql", return_value=True):
        leg = preflight_both_leg(q)
    assert leg.route == "Semantic-based"
    assert leg.next_agent == "Eryl_agent"


def test_forced_semantic_leg_kwarg():
    pf = preflight_both_leg("anything", leg="semantic")
    assert pf.route == "Semantic-based"
    assert pf.next_agent == "Eryl_agent"


def test_merge_pulls_inference_when_llm_answer_empty():
    merged = merge_both_responses(
        "full q",
        {"final_answer": {"query_answer": "6405"}, "query_answer": "6405"},
        {
            "final_answer": {"query_answer": "", "llm_answer": ""},
            "Inference": "Returns allowed within 30 days of purchase.",
        },
    )
    assert merged["query_answer"] == "6405"
    assert "30" in merged["llm_answer"]
    assert _extract_document_answer(
        {"Inference": "Returns allowed within 30 days of purchase."}
    ).startswith("Returns")


def test_merge_both_sections_and_policy_note():
    doc = "Report damage within 7 days. Inspection within 48 hours of receipt."
    merged = merge_both_responses(
        "q",
        {"query_answer": "6405"},
        {"llm_answer": doc},
    )
    assert len(merged["both_sections"]) == 2
    assert merged["both_sections"][0]["kind"] == "sql"
    assert merged["both_sections"][1]["kind"] == "doc"
    assert "7 days" in merged["llm_answer"]
    assert "Policy note" in merged["llm_answer"]


def test_merge_does_not_use_semantic_numeric_as_doc():
    merged = merge_both_responses(
        "q",
        {"query_answer": "100"},
        {"query_answer": "999", "llm_answer": ""},
    )
    assert merged["query_answer"] == "100"
    assert merged["llm_answer"] == ""