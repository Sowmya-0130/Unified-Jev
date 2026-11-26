"""JEV fail-safe: timeout / HTTP / malformed / low confidence -> original LLM path."""
from __future__ import annotations

import json
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import httpx
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


@pytest.mark.groupchat_legacy
@pytest.mark.parametrize(
    "failure",
    ["timeout", "http_500", "malformed", "low_conf"],
)
def test_s4_failsafe_paths(failure):
    gc = _GC([_user_question_msg(), _rai_pass()])
    if failure == "low_conf":
        mock_jev = {"confidence": 0.2, "choice": "SQL Analysis", "source": "openjev"}
        patches = [patch("jev_client.jev_routing_decision", return_value=mock_jev)]
    else:
        mock_jev = {"confidence": 0.0, "choice": None, "source": "fallback"}
        patches = [
            patch("jev_client.jev_routing_decision", return_value=mock_jev),
            patch("jev_client.jev_last_failure", return_value=failure.replace("http_500", "error")),
        ]
    with ExitStack() as stack:
        stack.enter_context(patch.object(core, "JEV_ROUTING_ENABLED", True))
        stack.enter_context(patch.object(core, "JEV_CONFIDENCE_THRESHOLD", 0.8))
        stack.enter_context(patch.object(core, "JEV_SHADOW_MODE", False))
        for p in patches:
            stack.enter_context(p)
        nxt = core.state_transition(core.Responsible_AI_Agent, gc)
    if failure == "low_conf":
        assert nxt is core.user_proxy
    else:
        assert nxt is core.routing_agent


def test_s1_jev_error_still_returns_safety():
    with patch("jev_client.jev_safety_check", side_effect=RuntimeError("jev down")):
        result = core.azure_safety_check("hello")
    assert "risk_score" in result
    assert result["toxicity_detected"] is False


def test_jev_post_timeout_sets_failure():
    import jev_client

    client = MagicMock()
    client.post.side_effect = httpx.TimeoutException("slow")
    with (
        patch.object(jev_client, "_http_client", return_value=client),
        patch.object(jev_client, "_get_jev_config", return_value=("key", "http://x", "m")),
    ):
        assert jev_client._jev_post("state", {"q": {}}) is None
    assert jev_client.jev_last_failure() == "timeout"


@pytest.mark.groupchat_legacy
@pytest.mark.parametrize(
    "gate_attr,fn_patch,speaker,extra_msgs,mock_low",
    [
        (
            "JEV_S7_SQL_RESULT_ENABLED",
            "s7_resolve",
            "Sql_tool",
            [{"name": "Sql_tool", "content": "not-rows-payload"}],
            True,
        ),
        ("JEV_S9_EVAL_ENABLED", "jev_eval_quality", "Insight_Generator", [{"name": "Insight_Generator", "content": "{}"}], True),
        ("JEV_S13_CRITIC_ENABLED", "jev_critic_check", "llm_answer_maker", [{"name": "llm_answer_maker", "content": "x"}], True),
    ],
)
def test_s7_s9_s13_low_conf_falls_back(gate_attr, fn_patch, speaker, extra_msgs, mock_low):
    gc = _GC([_user_question_msg(), *extra_msgs])
    low = {
        "source": "openjev",
        "confidence": 0.2,
        "is_valid": True,
        "decision_source": "jev",
        "ok": False,
        "skip_llm_eval": False,
        "composite": 0.2,
        "is_faithful": 0.2,
        "no_hallucination": 0.2,
    }
    spk = getattr(core, speaker)
    expect = {
        "Sql_tool": core.Sql_Execution_Critic,
        "Insight_Generator": core.Evaluation_Agent,
        "llm_answer_maker": core.critic_agent,
    }[speaker]
    if speaker == "Sql_tool":
        low = {
            "is_valid": None,
            "source": "llm",
            "decision_source": "llm",
            "confidence": 0.2,
        }
    with (
        patch.object(core, gate_attr, True),
        patch.object(core, "JEV_CONFIDENCE_THRESHOLD", 0.8),
        patch.object(core, "JEV_SHADOW_MODE", False),
        patch(f"jev_client.{fn_patch}", return_value=low),
    ):
        nxt = core.state_transition(spk, gc)
    assert nxt is expect


def test_jev_post_malformed_sets_failure():
    import jev_client

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"answers": "not-a-dict"}
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.post.return_value = resp
    with (
        patch.object(jev_client, "_http_client", return_value=client),
        patch.object(jev_client, "_get_jev_config", return_value=("key", "http://x", "m")),
    ):
        assert jev_client._jev_post("state", {"q": {}}) is None
    assert jev_client.jev_last_failure() == "malformed"