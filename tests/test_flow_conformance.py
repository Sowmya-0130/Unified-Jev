"""Unit tests for TARGET FLOW speaker / forbidden-agent rules."""
from __future__ import annotations

import pytest

from flow_conformance import assert_trace_conforms, check_trace


def _trace(speakers: list[str], **extra) -> dict:
    return {
        "request_id": "t1",
        "latency": {
            "timeline": [{"kind": "agent_turn", "name": s} for s in speakers],
            "gate_decisions": extra.get("gate_decisions", []),
            "termination": {"reason": extra.get("termination", "completed")},
        },
    }


def test_sql_path_no_forbidden_off_mode():
    tr = _trace(
        [
            "user_proxy",
            "Sql_Generator",
            "Sql_tool",
            "Insight_Generator",
            "user_proxy",
        ]
    )
    assert check_trace(tr, safety_llm_mode="off") == []


def test_forbidden_routing_agent():
    tr = _trace(["user_proxy", "routing_agent", "Sql_Generator"])
    v = check_trace(tr, routing_llm_fallback=False)
    assert any("routing_agent" in x for x in v)


def test_forbidden_sql_execution_critic_default():
    tr = _trace(["user_proxy", "Sql_Generator", "Sql_tool", "Sql_Execution_Critic"])
    v = check_trace(tr, sql_s7_llm_fallback=False)
    assert any("Sql_Execution_Critic" in x for x in v)


def test_assert_raises_on_violation():
    tr = _trace(["Responsible_AI_Agent"])
    with pytest.raises(AssertionError):
        assert_trace_conforms(tr, safety_llm_mode="off")