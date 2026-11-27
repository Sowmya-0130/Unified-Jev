"""Nested Both legs pass both_nested + parent safety (no duplicate JEV prestage)."""
from __future__ import annotations

from both_answer import both_independent_answer


def test_both_legs_use_parent_request_id(monkeypatch):
    monkeypatch.delenv("AURIX_BOTH_STUB", raising=False)
    monkeypatch.setattr("API_unified.MERGE_NODE_ENABLED", False, raising=False)
    legs: list[tuple[str, str]] = []

    def _sql(question: str, *, parent_request_id: str) -> dict:
        legs.append(("sql", parent_request_id))
        return {
            "final_answer": {"query_answer": "1", "llm_answer": ""},
            "jev_trace": {"latency": {"total_ms": 1}},
        }

    def _sem(question: str, *, parent_request_id: str) -> dict:
        legs.append(("sem", parent_request_id))
        return {
            "final_answer": {"query_answer": "", "llm_answer": "policy"},
            "jev_trace": {"latency": {"total_ms": 1}},
        }

    monkeypatch.setattr("both_answer._sql_part", _sql)
    monkeypatch.setattr("both_answer._semantic_part", _sem)
    q = (
        "What is the total for Kevlar Gloves in Orders, "
        "and what does the documentation say about returns?"
    )
    out = both_independent_answer(q, parallel=False, parent_request_id="parent-rid")
    assert len(legs) == 2
    assert all(pid == "parent-rid" for _, pid in legs)
    assert out["query_answer"] == "1"
    assert "policy" in (out.get("llm_answer") or "")