"""A2 parallel pre-stage (mocked, non-live)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from prestage import PrestageResult, run_prestage


def test_db_execute_blocked_before_safety_verdict(monkeypatch):
    from request_state import ensure_guard_request_id, safety_allows_sql_execute, safety_prechat_store

    ensure_guard_request_id("rid-1")
    assert safety_allows_sql_execute() is False

    safety_prechat_store("rid-1", "allow", {})
    assert safety_allows_sql_execute() is True

    ensure_guard_request_id("rid-2")
    safety_prechat_store("rid-2", "block", {})
    assert safety_allows_sql_execute() is False


def test_run_prestage_serial_records_arms():
    s4 = type("S4", (), {"handled": False, "finish_response": None, "route": "SQL-based", "next_agent": "Sql_Generator"})()

    with (
        patch("API_unified.PRESTAGE_PARALLEL_ENABLED", False),
        patch("prestage._run_s1", return_value=(None, 1.0, "skipped")),
        patch("prestage._run_s4", return_value=(s4, 2.0, "ok")),
        patch("prestage._run_schema_link", return_value=("schema block", 3.0, "ok")),
        patch("prestage._scan_answer_cache", return_value=(None, 4.0, "ok")),
        patch("prestage._refresh_profile", return_value=(True, 0.5, "ok")),
    ):
        res = run_prestage("q?", schema_summary="meta", answer_cache={})

    assert res.schema_block == "schema block"
    assert res.s4 is s4
    assert res.arm_ms["s4"] == 2.0
    assert res.cache_scan_complete is True


def test_prestage_trace_steps():
    res = PrestageResult(arm_ms={"s1": 10.0, "wall": 50.0}, arm_status={"s1": "ok"}, wall_ms=50.0)
    from jev_trace import reset as trace_reset, snapshot

    trace_reset()
    from prestage import record_prestage_trace

    record_prestage_trace(res)
    timeline = snapshot().get("latency", {}).get("timeline", [])
    kinds = [r.get("name") for r in timeline if r.get("kind") == "prestage"]
    assert "s1" in kinds
    assert "wall" in kinds


def test_db_execute_query_rejects_without_allow(monkeypatch):
    import aurix_core as core

    from request_state import ensure_guard_request_id

    ensure_guard_request_id("no-safety")
    out = core.db_execute_query(query="SELECT 1", db_name="SQL")
    assert "safety_gate" in out or "blocked" in out.lower()