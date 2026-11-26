"""SQL / request timeout behavior and per-request trace persistence."""
from __future__ import annotations

import json
import time
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import jev_trace


def test_sql_query_timeout_returns_within_budget(monkeypatch):
    import metadata
    from concurrent.futures import TimeoutError as FuturesTimeout

    class _Fut:
        def result(self, timeout=None):
            assert timeout == 1.0
            raise FuturesTimeout()

        def cancel(self) -> bool:
            return True

    class _Pool:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def submit(self, _fn, *_a, **_k):
            return _Fut()

        def shutdown(self, wait=True, cancel_futures=False):
            self._shutdown = True

    import API_unified

    monkeypatch.setattr(API_unified, "SQL_QUERY_TIMEOUT_S", 1)
    monkeypatch.setattr("concurrent.futures.ThreadPoolExecutor", lambda **_: _Pool())
    t0 = time.perf_counter()
    with pytest.raises(TimeoutError, match="SQL_QUERY_TIMEOUT_S"):
        metadata.fetch_dataframe_readonly("SELECT 1")
    assert time.perf_counter() - t0 < 0.5


def test_db_execute_query_surfaces_sql_timeout(monkeypatch):
    from types import SimpleNamespace

    import aurix_core as core
    import metadata

    def _boom(*_a, **_k):
        raise TimeoutError("SQL query exceeded SQL_QUERY_TIMEOUT_S (1s)")

    _ok = SimpleNamespace(ok=True, normalized_sql="SELECT 1", error_payload=lambda: "")
    monkeypatch.setattr("sql_catalog.get_catalog_readonly", lambda: SimpleNamespace(display_names={}))
    monkeypatch.setattr("sql_pipeline.validate_sql", lambda *_a, **_k: _ok)
    monkeypatch.setattr(metadata, "fetch_dataframe_readonly", _boom)
    out = core.db_execute_query(query="SELECT 1", db_name="SQL")
    assert "SQL_QUERY_TIMEOUT_S" in out


def test_request_timeout_user_message(monkeypatch):
    import threading
    import time
    from types import SimpleNamespace

    import API_unified
    import aurix_core as core
    from routing_s4 import S4Preflight

    monkeypatch.setattr(API_unified, "ORCHESTRATOR", "pipeline")
    monkeypatch.setattr(API_unified, "REQUEST_TIMEOUT_S", 1)
    monkeypatch.setattr(core, "REQUEST_TIMEOUT_S", 1, raising=False)
    monkeypatch.setattr(API_unified, "JEV_S1_SAFETY_ENABLED", False)
    monkeypatch.setattr(core, "JEV_S1_SAFETY_ENABLED", False, raising=False)
    monkeypatch.setattr(core, "JEV_S2_CLARITY_ENABLED", False, raising=False)
    monkeypatch.setattr(API_unified, "AZURE_OPENAI_PROBE_BEFORE_CHAT", False)
    monkeypatch.setattr(core, "AZURE_OPENAI_PROBE_BEFORE_CHAT", False, raising=False)
    monkeypatch.setattr(core, "_AZURE_CHAT_PROBE_DONE", True, raising=False)
    monkeypatch.setattr(core, "_AZURE_CHAT_PROBE_ERROR", None, raising=False)
    monkeypatch.setattr("sql_catalog.get_catalog_readonly", lambda: SimpleNamespace(display_names={}))
    monkeypatch.setattr("catalog_runtime.bootstrap_catalog", lambda **_: None)
    monkeypatch.setattr(
        "routing_s4.preflight_s4",
        lambda *_a, **_k: S4Preflight(handled=False, route="SQL-based", next_agent="Sql_Generator"),
    )
    monkeypatch.setattr(
        "safety_gate.evaluate_safety",
        lambda *a, **k: SimpleNamespace(
            action="allow",
            reasons=[],
            regex_flags=[],
            p_toxic=0.0,
            p_pii=0.0,
            p_injection=0.0,
            max_p_unsafe=0.0,
            jev=None,
        ),
    )
    monkeypatch.setattr("safety_gate.log_s1_gate", lambda *_a, **_k: None)
    monkeypatch.setattr("orchestrator.run_pipeline", lambda *_a, **_k: time.sleep(30))
    monkeypatch.setattr("data_profile.refresh_data_profile", lambda: None)
    monkeypatch.setattr(core, "JEV_S3_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(core, "JEV_S5_MODEL_ROUTER_ENABLED", False, raising=False)
    monkeypatch.setattr("jev_trace.persist_request_trace", lambda *_a, **_k: None)
    monkeypatch.setattr("jev_trace.print_latency_summary", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "azure_llm_runtime.refresh_azure_openai_runtime",
        lambda *a, **k: ("http://x", None),
    )

    _ctx = MagicMock(__enter__=lambda s: s, __exit__=lambda *a: False)
    with patch("jev_trace.setup_step", return_value=_ctx):
        with patch("jev_trace.begin_chat_phase"):
            t0 = time.perf_counter()
            resp = core.get_final_answer('{"question":"hi"}')
    assert time.perf_counter() - t0 <= float(API_unified.REQUEST_TIMEOUT_S) + 3.0
    assert "REQUEST_TIMEOUT_S" in (resp.get("llm_answer") or "")
    assert resp.get("Reasoning") == "request_timeout"


def test_persist_request_trace_writes_file(tmp_path, monkeypatch):
    import API_unified

    monkeypatch.setattr(API_unified, "TRACE_PERSIST", True)
    monkeypatch.setattr(API_unified, "TRACE_PERSIST_DIR", str(tmp_path))
    jev_trace.reset()
    jev_trace.record_step("setup", "probe", 10.0)
    summary = jev_trace.summarize_latency()
    path = jev_trace.persist_request_trace(summary)
    assert path and path.is_file()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["request_id"] == summary["request_id"]
    path.unlink(missing_ok=True)