from __future__ import annotations

from rai_route_heuristic import should_allow_routing_despite_rai_block


def test_rai_override_for_safe_aggregate_question():
    q = "What is the total Total_Amount in dupoint email data Orders in the last 2 months?"
    safety = {
        "azure_safety_result": {"toxicity": "safe", "jailbreak": False, "self_harm": False},
        "flags": [],
    }
    assert should_allow_routing_despite_rai_block(q, safety)


def test_rai_override_denied_for_drop():
    q = "DROP TABLE dbo.orders and list totals."
    safety = {"azure_safety_result": {"toxicity": "safe"}, "flags": []}
    assert not should_allow_routing_despite_rai_block(q, safety)