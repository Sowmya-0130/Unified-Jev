"""In-process empty_boots isolation (live DB)."""
from __future__ import annotations

import os

import pytest

EMPTY_Q = (
    "What is the total Total_Amount for Chemical Resistant Boots and Kevlar Gloves "
    "orders in dupoint email data Orders in the last 2 months?"
)
OTHER_Q = "How many rows are in dupoint email data Orders?"


def _assert_empty_boots(resp: dict) -> None:
    from empty_answer_eval import empty_answer_acceptable

    jt = resp.get("jev_trace") or {}
    lat = jt.get("latency") or jt
    exec_sql = lat.get("executed_sqls") or []
    assert exec_sql, "expected executed SQL or COUNT recovery"
    fa = resp.get("final_answer") or {}
    ans = fa.get("query_answer") or resp.get("query_answer") or ""
    assert empty_answer_acceptable(ans, EMPTY_Q)
    if lat.get("match_row_count") == 0:
        assert lat.get("insight_path") == "template"


@pytest.mark.live
def test_empty_boots_five_times_in_process():
    os.environ["LLM_RESPONSE_CACHE"] = "false"
    import aurix_core as core

    for _ in range(5):
        core.clear_answer_cache()
        _assert_empty_boots(core.get_final_answer(EMPTY_Q))


@pytest.mark.live
def test_alternate_empty_boots_pattern():
    os.environ["LLM_RESPONSE_CACHE"] = "false"
    import aurix_core as core

    for q in (OTHER_Q, EMPTY_Q, OTHER_Q, EMPTY_Q):
        core.clear_answer_cache()
        if q == EMPTY_Q:
            _assert_empty_boots(core.get_final_answer(q))
        else:
            r = core.get_final_answer(q)
            lat = (r.get("jev_trace") or {}).get("latency") or {}
            assert lat.get("executed_sqls")