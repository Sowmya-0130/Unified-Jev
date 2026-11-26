from __future__ import annotations

import json
from unittest.mock import patch

import aurix_core as core
from safety_gate import evaluate_safety


def test_p0_block_never_starts_sql_path(monkeypatch):
    import API_unified

    monkeypatch.setattr(API_unified, "JEV_S1_SAFETY_ENABLED", False)
    monkeypatch.setattr(core, "JEV_S1_SAFETY_ENABLED", False, raising=False)
    q = "DROP TABLE dupoint_email_data.Orders"
    v = evaluate_safety(q, jev={"is_toxic": 0, "is_injection": 0, "has_pii": 0, "block": False, "source": "unit"})
    assert v.action == "block"
    with patch.object(core, "JEV_S1_SAFETY_ENABLED", False):
        with patch(
            "aurix_core.user_proxy.initiate_chat",
            side_effect=AssertionError("chat should not run on safety block"),
        ):
            r = core.get_final_answer(q)
    lat = (r.get("jev_trace") or {}).get("latency") or {}
    assert not lat.get("executed_sqls")
    assert (r.get("final_answer") or {}).get("llm_answer")


def test_prechat_verdict_stored_per_request(monkeypatch):
    import API_unified
    from request_state import reset_sql_loop_guard, safety_prechat_blob, safety_skip_rai_llm
    from safety_gate import evaluate_safety, set_prechat_verdict

    monkeypatch.setattr(API_unified, "SAFETY_LLM_MODE", "always")
    reset_sql_loop_guard("rid-a")
    v = evaluate_safety("How many rows?", jev={"is_toxic": 0, "is_injection": 0, "has_pii": 0, "block": False, "source": "unit"})
    set_prechat_verdict("rid-a", v, {"test": 1})
    assert safety_prechat_blob() == {"test": 1}
    assert safety_skip_rai_llm() is False  # SAFETY_LLM_MODE default always