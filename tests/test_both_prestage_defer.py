"""S4 preflight must not run both_independent_answer (avoids JEV storm in prestage)."""
from __future__ import annotations

from unittest.mock import patch

import both_answer
from routing_s4 import preflight_s4


def test_preflight_defers_both_independent_without_finish_response():
    q = (
        "What is the total Total_Amount for Kevlar Gloves in dupoint email data Orders, "
        "and what does the documentation say about returns for those products?"
    )
    both_calls: list[str] = []

    def _boom(question: str, **kwargs):  # noqa: ANN001
        both_calls.append(question)
        raise AssertionError("both_independent_answer must not run inside preflight_s4")

    with patch.object(both_answer, "both_independent_answer", side_effect=_boom):
        with patch("dual_route.catalog_supports_sql", return_value=True):
            pf = preflight_s4(q, schema_summary="schema")
    assert pf.handled is True
    assert pf.finish_response is None
    assert pf.route == "Both-independent"
    assert pf.next_agent == "Both_handler"
    assert both_calls == []


def test_prestage_s4_arm_does_not_invoke_both(monkeypatch):
    import prestage

    q = (
        "Total for Kevlar Gloves in Orders, "
        "and what does the documentation say about returns?"
    )
    monkeypatch.setattr(
        "both_answer.both_independent_answer",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no sync both")),
    )
    _s4, ms, st = prestage._run_s4(q, "meta")
    assert st == "ok"
    assert _s4 is not None
    assert _s4.finish_response is None
    assert _s4.route == "Both-independent"
    assert ms >= 0