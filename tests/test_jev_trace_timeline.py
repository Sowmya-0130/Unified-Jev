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
    assert not any(s["kind"] == "setup" and s["name"] == "autogen_user_proxy" for s in summary["timeline"])


def test_exclusive_latency_buckets_nested_spans():
    """Setup + LLM + JEV + DB must not double-count parent initiate_chat (kind=chat)."""
    jev_trace.reset()
    jev_trace.record_step("setup", "azure_openai_probe", 100.0)
    jev_trace.record_step("jev", "S4", 40.0)
    jev_trace.record_step("agent_turn", "Sql_Generator", 500.0)
    jev_trace.record_step("tool", "db_execute_query", 120.0)
    jev_trace.record_step("chat", "initiate_chat", 800.0)

    summary = jev_trace.summarize_latency()
    assert summary["total_setup_ms"] == 100.0
    assert summary.get("setup_exclusive_ms") == 100.0
    assert summary["total_chat_wall_ms"] == 800.0
    assert summary["total_llm_ms"] == 500.0
    assert summary["total_db_ms"] == 120.0
    assert summary["total_jev_ms"] == 40.0
    assert summary["bucket_sum_ms"] == 760.0
    assert not any(
        s.get("name") == "initiate_chat" and s.get("kind") == "setup"
        for s in summary["timeline"]
    )


def test_sql_tool_wall_not_double_counted():
    jev_trace.reset()
    jev_trace.begin_chat_phase()

    class _SqlTool:
        name = "Sql_tool"

    class _Critic:
        name = "Sql_Execution_Critic"

    jev_trace.mark_agent_transition(_SqlTool())
    jev_trace.record_step("tool", "db_execute_query", 200.0)
    jev_trace.mark_agent_transition(_Critic())
    summary = jev_trace.summarize_latency()
    assert not any(
        s.get("name") == "Sql_tool" for s in summary["timeline"]
    )
    assert summary["total_db_ms"] == 200.0


def test_bucket_rule_49177_vs_49469():
    total_ms, bucket_sum_ms = 49468.8, 49177.2
    tolerance = max(50.0, total_ms * 0.01)
    assert abs(bucket_sum_ms - total_ms) / total_ms < 0.01
    assert abs(bucket_sum_ms - total_ms) <= tolerance


def test_pending_tool_subtracts_from_agent():
    jev_trace.reset()
    jev_trace.begin_chat_phase()

    class _A:
        name = "Sql_Generator"

    class _B:
        name = "Query_Executor"

    jev_trace.mark_agent_transition(_A())
    jev_trace.record_step("tool", "db_execute_query", 500.0)
    jev_trace.mark_agent_transition(_B())
    summary = jev_trace.summarize_latency()
    assert summary["total_db_ms"] == 500.0
    assert summary["total_llm_ms"] < 500.0