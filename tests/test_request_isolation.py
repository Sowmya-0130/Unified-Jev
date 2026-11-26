from __future__ import annotations

import threading

import pytest

from request_state import reset_sql_loop_guard, sql_loop_guard


def test_sql_loop_guard_resets_per_request_id():
    reset_sql_loop_guard("req-a")
    sql_loop_guard()["valid"] = True
    sql_loop_guard()["insight_done"] = True
    reset_sql_loop_guard("req-b")
    assert sql_loop_guard()["request_id"] == "req-b"
    assert sql_loop_guard()["valid"] is False
    assert sql_loop_guard()["insight_done"] is False


def test_sql_loop_guard_thread_isolation():
    errors: list[str] = []

    def worker(tag: str) -> None:
        try:
            reset_sql_loop_guard(tag)
            sql_loop_guard()["valid"] = True
            sql_loop_guard()["result_fp"] = tag
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

    threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # Main thread guard untouched by workers
    reset_sql_loop_guard("main")
    assert sql_loop_guard()["result_fp"] is None


def test_get_final_answer_impl_clears_groupchat_at_entry():
    import inspect

    import aurix_core as core

    src = inspect.getsource(core._get_final_answer_impl)
    assert "groupchat.messages.clear()" in src


@pytest.mark.live
def test_same_question_three_times_in_one_process():
    import os

    import aurix_core as core

    os.environ["LLM_RESPONSE_CACHE"] = "false"
    core.clear_answer_cache()
    q = (
        "What is the total Total_Amount for Chemical Resistant Boots and Kevlar Gloves "
        "orders in dupoint email data Orders in the last 2 months?"
    )
    paths = []
    for _ in range(3):
        core.clear_answer_cache()
        r = core.get_final_answer(q)
        lat = (r.get("jev_trace") or {}).get("latency") or {}
        paths.append(lat.get("insight_path"))
        assert (r.get("final_answer") or {}).get("query_answer") == "No matching data."
        assert lat.get("match_row_count") == 0
    assert paths == ["template", "template", "template"]