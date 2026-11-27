from __future__ import annotations

import API_unified
from merge_node import DbOutput, DocsOutput, synthesize
from unittest.mock import patch


def test_db_only_returns_db_strategy():
    mr = synthesize("q", DbOutput(text="6405"), DocsOutput(), trace_id="t")
    assert mr.merge_strategy == "db_only"
    assert mr.final_text == "6405"


def test_docs_only_returns_docs_strategy():
    mr = synthesize("q", DbOutput(), DocsOutput(text="7-day returns"), trace_id="t")
    assert mr.merge_strategy == "docs_only"


def test_both_llm_synthesis_grounded(monkeypatch):
    monkeypatch.setattr(API_unified, "MERGE_NODE_ENABLED", True)
    json_out = '{"final_text": "Combined answer", "sources": ["data", "docs"]}'
    with patch("merge_node._llm_synthesis", return_value=("Combined answer", ["data", "docs"])):
        with patch("merge_node._grounding_check", return_value=(True, 0.9)):
            mr = synthesize("q", DbOutput(text="100"), DocsOutput(text="policy"), trace_id="t")
    assert mr.merge_strategy == "llm_synthesis"
    assert mr.grounded is True


def test_both_llm_synthesis_ungrounded_falls_back_to_concat(monkeypatch):
    monkeypatch.setattr(API_unified, "MERGE_NODE_ENABLED", True)
    with patch("merge_node._llm_synthesis", return_value=("Bad hallucination", ["data"])):
        with patch("merge_node._grounding_check", return_value=(False, 0.2)):
            mr = synthesize("q", DbOutput(text="100"), DocsOutput(text="policy"), trace_id="t")
    assert mr.merge_strategy == "concat_fallback"
    assert "[Data]" in mr.final_text


def test_both_empty_returns_template(monkeypatch):
    monkeypatch.setattr(API_unified, "MERGE_NODE_ENABLED", True)
    mr = synthesize("q", DbOutput(), DocsOutput(), trace_id="t")
    assert "No data found" in mr.final_text


def test_merge_exception_falls_back_to_concat(monkeypatch):
    monkeypatch.setattr(API_unified, "MERGE_NODE_ENABLED", True)
    with patch("merge_node._llm_synthesis", side_effect=RuntimeError("llm")):
        mr = synthesize("q", DbOutput(text="9"), DocsOutput(text="doc"), trace_id="t")
    assert mr.merge_strategy == "concat_fallback"


def test_merge_timeout_falls_back_to_concat(monkeypatch):
    monkeypatch.setattr(API_unified, "MERGE_NODE_ENABLED", True)
    monkeypatch.setattr(API_unified, "MERGE_NODE_TIMEOUT_S", 0.01)

    def slow(*_a, **_k):
        import time

        time.sleep(0.5)
        return ("late", ["data"])

    with patch("merge_node._llm_synthesis", side_effect=slow):
        mr = synthesize("q", DbOutput(text="1"), DocsOutput(text="d"), trace_id="t")
    assert mr.merge_strategy == "concat_fallback"


def test_merge_node_disabled_uses_old_behavior(monkeypatch):
    monkeypatch.setattr(API_unified, "MERGE_NODE_ENABLED", False)
    mr = synthesize("q", DbOutput(text="100"), DocsOutput(text="docs"), trace_id="t")
    assert mr.query_answer == "100"
    assert mr.llm_answer == "docs"