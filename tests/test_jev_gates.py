"""Mocked state_transition tests for JEV gates S4/S7/S9/S13 (no live LLM/JEV)."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import aurix_core as core


class _GC:
    def __init__(self, messages: list[dict]):
        self.messages = messages


def _user_question_msg(q: str = "How many rows?") -> dict:
    return {"name": "user", "role": "user", "content": json.dumps({"question": q})}


def _rai_pass() -> dict:
    return {
        "name": "Responsible_AI_Agent",
        "role": "assistant",
        "content": json.dumps({"rai_check_passed": True, "next_agent": "routing_agent"}),
    }


@pytest.mark.parametrize(
    "confidence,choice,expect",
    [
        (0.95, "SQL Analysis", core.Sql_Generator),
        (0.50, "SQL Analysis", core.routing_agent),
    ],
)
def test_s4_routing_confidence(confidence, choice, expect):
    gc = _GC([_user_question_msg(), _rai_pass()])
    mock_jev = {"confidence": confidence, "choice": choice, "source": "openjev"}
    with (
        patch.object(core, "JEV_ROUTING_ENABLED", True),
        patch.object(core, "JEV_CONFIDENCE_THRESHOLD", 0.8),
        patch("jev_client.jev_routing_decision", return_value=mock_jev),
    ):
        nxt = core.state_transition(core.Responsible_AI_Agent, gc)
    assert nxt is expect
    if expect is core.Sql_Generator:
        assert any(m.get("name") == "routing_agent" for m in gc.messages)


def test_s4_routing_jev_error_falls_back():
    gc = _GC([_user_question_msg(), _rai_pass()])
    with (
        patch.object(core, "JEV_ROUTING_ENABLED", True),
        patch("jev_client.jev_routing_decision", side_effect=TimeoutError("jev")),
    ):
        nxt = core.state_transition(core.Responsible_AI_Agent, gc)
    assert nxt is core.routing_agent


def test_s4_routing_flag_off():
    gc = _GC([_user_question_msg(), _rai_pass()])
    with patch.object(core, "JEV_ROUTING_ENABLED", False):
        nxt = core.state_transition(core.Responsible_AI_Agent, gc)
    assert nxt is core.routing_agent


@pytest.mark.parametrize(
    "is_valid,confidence,expect",
    [
        (True, 0.9, core.Insight_Generator),
        (True, 0.5, core.Sql_Execution_Critic),
        (False, 0.9, core.Sql_Generator),
    ],
)
def test_s7_sql_result(is_valid, confidence, expect):
    sql_out = '[{"x": 1}]'
    gc = _GC([_user_question_msg(), {"name": "Sql_tool", "content": sql_out}])
    mock = {
        "source": "openjev",
        "is_valid": is_valid,
        "confidence": confidence,
        "error_type": "empty",
    }
    with (
        patch.object(core, "JEV_S7_SQL_RESULT_ENABLED", True),
        patch.object(core, "JEV_CONFIDENCE_THRESHOLD", 0.8),
        patch("jev_client.jev_sql_result_check", return_value=mock),
    ):
        nxt = core.state_transition(core.Sql_tool, gc)
    assert nxt is expect


def test_s7_jev_error_falls_back():
    gc = _GC([_user_question_msg(), {"name": "Sql_tool", "content": "[]"}])
    with (
        patch.object(core, "JEV_S7_SQL_RESULT_ENABLED", True),
        patch("jev_client.jev_sql_result_check", side_effect=RuntimeError("jev")),
    ):
        nxt = core.state_transition(core.Sql_tool, gc)
    assert nxt is core.Sql_Execution_Critic


@pytest.mark.parametrize(
    "composite,expect",
    [
        (0.85, core.user_proxy),
        (0.70, core.Evaluation_Agent),
    ],
)
def test_s9_eval_quality(composite, expect):
    insight = {"query_answer": "42", "Inference": "ok"}
    gc = _GC(
        [
            _user_question_msg(),
            {"name": "Insight_Generator", "content": json.dumps(insight)},
        ]
    )
    mock = {
        "source": "openjev",
        "skip_llm_eval": composite >= 0.8,
        "composite": composite,
        "helpfulness": composite,
        "groundedness": composite,
        "completeness": composite,
    }
    with (
        patch.object(core, "JEV_S9_EVAL_ENABLED", True),
        patch.object(core, "JEV_CONFIDENCE_THRESHOLD", 0.8),
        patch("jev_client.jev_eval_quality", return_value=mock),
    ):
        nxt = core.state_transition(core.Insight_Generator, gc)
    assert nxt is expect


@pytest.mark.parametrize(
    "faithful,expect",
    [
        (0.9, core.user_proxy),
        (0.5, core.critic_agent),
    ],
)
def test_s13_critic(faithful, expect):
    gc = _GC([_user_question_msg(), {"name": "llm_answer_maker", "content": "policy text"}])
    mock = {
        "source": "openjev",
        "ok": faithful >= 0.8,
        "is_faithful": faithful,
        "no_hallucination": faithful,
        "concern": "",
    }
    with (
        patch.object(core, "JEV_S13_CRITIC_ENABLED", True),
        patch.object(core, "JEV_CONFIDENCE_THRESHOLD", 0.8),
        patch("jev_client.jev_critic_check", return_value=mock),
    ):
        nxt = core.state_transition(core.llm_answer_maker, gc)
    assert nxt is expect


def test_s13_jev_error_falls_back():
    gc = _GC([_user_question_msg(), {"name": "llm_answer_maker", "content": "x"}])
    with (
        patch.object(core, "JEV_S13_CRITIC_ENABLED", True),
        patch("jev_client.jev_critic_check", side_effect=RuntimeError("jev")),
    ):
        nxt = core.state_transition(core.llm_answer_maker, gc)
    assert nxt is core.critic_agent