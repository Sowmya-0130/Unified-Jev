"""Unit tests for per-request latency timeline (I-16)."""
from __future__ import annotations

import jev_trace


def test_summarize_latency_totals_and_top5():
    jev_trace.reset()
    jev_trace.record_step("agent_turn", "Sql_Generator", 1200.0)
    jev_trace.record_step("tool", "db_execute_query", 400.0, retry_count=2)
    jev_trace.record_step("jev", "S4", 50.0, status="openjev")
    jev_trace.record_step("agent_turn", "routing_agent", 800.0)
    jev_trace.event("S4", skip_llm="routing_agent")

    summary = jev_trace.summarize_latency()
    assert summary["total_llm_ms"] == 2000.0
    assert summary["total_db_ms"] == 400.0
    assert summary["total_jev_ms"] == 50.0
    assert summary["jev_skipped_llm_agents"] == 1
    assert summary["llm_turn_count"] == 2
    assert len(summary["top5_slowest"]) == 4
    assert summary["top5_slowest"][0]["name"] == "Sql_Generator"


def test_agent_transition_records_wall_time():
    import time

    jev_trace.reset()
    jev_trace.begin_chat_phase()

    class _A:
        name = "user_proxy"

    class _B:
        name = "Sql_Generator"

    jev_trace.mark_agent_transition(_A())
    time.sleep(0.01)
    jev_trace.mark_agent_transition(_B())
    jev_trace.finalize_agent_timeline()
    summary = jev_trace.summarize_latency()
    assert summary["llm_turn_count"] >= 1
    assert any(s["kind"] == "setup" and s["name"] == "autogen_user_proxy" for s in summary["timeline"])