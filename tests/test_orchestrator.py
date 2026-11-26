"""Orchestrator wiring (no live LLM)."""
from __future__ import annotations

import os

os.environ.setdefault("ORCHESTRATOR", "groupchat")

from request_context import RequestContext, _MessagesProxy


def test_request_context_transcript():
    ctx = RequestContext(request_id="r1", question="q")
    ctx.append("Sql_Generator", "{}")
    assert len(ctx.transcript) == 1
    proxy = _MessagesProxy(ctx)
    assert proxy.messages is ctx.transcript


def test_pipeline_response_builder():
    from pipeline_response import build_response

    tr = [
        {"name": "Insight_Generator", "content": '{"query_answer": "42"}'},
    ]
    out = build_response({}, tr, analysis_type="SQL-based")
    assert out["final_answer"]["query_answer"] == "42"


def test_summarize_pipeline_transcript():
    from jev_trace import summarize_pipeline_transcript

    s = summarize_pipeline_transcript(
        [{"name": "Sql_Generator"}, {"name": "Sql_tool"}, {"name": "Insight_Generator"}]
    )
    assert s["llm_turn_count"] == 2
    assert s["orchestrator"] == "pipeline"