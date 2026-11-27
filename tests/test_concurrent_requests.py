"""Concurrent get_final_answer without global chat lock."""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def test_five_concurrent_requests_no_cross_talk(monkeypatch):
    import aurix_core as core

    seen: dict[str, str] = {}
    lock = threading.Lock()

    def _fake(question: str) -> dict:
        q = str(question)
        with lock:
            seen[q] = threading.current_thread().name
        return {
            "final_answer": {"query_answer": f"A:{q[-12:]}", "llm_answer": "ok"},
            "jev_trace": {"latency": {"total_ms": 1}, "request_id": q[-8:]},
        }

    monkeypatch.setattr(core, "_get_final_answer_impl", _fake)
    questions = [f'{{"question":"item-{i}"}}' for i in range(5)]
    with ThreadPoolExecutor(max_workers=5) as pool:
        futs = [pool.submit(core.get_final_answer, q) for q in questions]
        results = [f.result(timeout=10) for f in futs]
    assert len(results) == 5
    assert len(seen) == 5
    assert all("request_busy" not in (r.get("Reasoning") or "") for r in results)


def test_parallel_slow_requests_no_request_busy(monkeypatch):
    import API_unified
    import aurix_core as core
    from routing_s4 import S4Preflight

    monkeypatch.setattr(API_unified, "ORCHESTRATOR", "pipeline")
    monkeypatch.setattr(API_unified, "REQUEST_TIMEOUT_S", 1)
    monkeypatch.setattr(core, "REQUEST_TIMEOUT_S", 1, raising=False)
    monkeypatch.setattr(API_unified, "JEV_S1_SAFETY_ENABLED", False)
    monkeypatch.setattr(core, "JEV_S1_SAFETY_ENABLED", False, raising=False)
    monkeypatch.setattr(API_unified, "AZURE_OPENAI_PROBE_BEFORE_CHAT", False)
    monkeypatch.setattr("sql_catalog.get_catalog_readonly", lambda: SimpleNamespace(display_names={}))
    monkeypatch.setattr(
        "routing_s4.preflight_s4",
        lambda *_a, **_k: S4Preflight(handled=False, route="SQL-based", next_agent="Sql_Generator"),
    )
    _allow = SimpleNamespace(
        action="allow",
        reasons=[],
        regex_flags=[],
        p_toxic=0.0,
        p_pii=0.0,
        p_injection=0.0,
        max_p_unsafe=0.0,
        jev=None,
    )
    monkeypatch.setattr("safety_gate.evaluate_safety", lambda *a, **k: _allow)
    monkeypatch.setattr("safety_gate.log_s1_gate", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "orchestrator.run_pipeline",
        lambda *a, **k: time.sleep(30),
    )
    monkeypatch.setattr("catalog_runtime.bootstrap_catalog", lambda **k: None)

    _ctx = MagicMock(__enter__=lambda s: s, __exit__=lambda *a: False)
    with patch("jev_trace.setup_step", return_value=_ctx):
        with patch(
            "azure_llm_runtime.refresh_azure_openai_runtime",
            return_value=("http://x", None),
        ):
            with patch("jev_trace.begin_chat_phase"):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    t0 = time.perf_counter()
                    f1 = pool.submit(core.get_final_answer, '{"question":"a"}')
                    f2 = pool.submit(core.get_final_answer, '{"question":"b"}')
                    r1 = f1.result(timeout=15)
                    r2 = f2.result(timeout=15)
    assert time.perf_counter() - t0 < 12.0
    assert "request_busy" not in (r1.get("Reasoning") or "")
    assert "request_busy" not in (r2.get("Reasoning") or "")