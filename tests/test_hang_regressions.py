"""Regression: accept watchdog + HTTP 429 transport (no global chat lock)."""
from __future__ import annotations

import time

import httpx
import pytest

from eval.accept_watchdog import run_with_timeout


def test_run_with_timeout_returns_after_budget_without_joining_worker():
    def _hang() -> str:
        time.sleep(2.0)
        return "never"

    t0 = time.perf_counter()
    out, err = run_with_timeout(_hang, 0.25)
    elapsed = time.perf_counter() - t0
    assert out is None
    assert err and "question_timeout" in err
    assert elapsed < 2.0


@pytest.mark.both_integration
def test_both_parallel_uses_get_final_answer(monkeypatch):
    monkeypatch.delenv("AURIX_BOTH_STUB", raising=False)
    import aurix_core as core
    from both_answer import both_independent_answer

    calls: list[str] = []

    def _fake(question: str) -> dict:
        calls.append(question[:12])
        return {
            "final_answer": {"query_answer": f"sql:{question[:8]}", "llm_answer": "doc"},
            "jev_trace": {"latency": {"total_ms": 1}},
        }

    monkeypatch.setattr(core, "get_final_answer", _fake)
    monkeypatch.setattr(core, "_get_final_answer_impl", _fake)
    resp = both_independent_answer(
        "Compare Product A sales to the handbook section on returns",
        parallel=True,
    )
    assert resp["final_answer"]["query_answer"]
    assert len(calls) >= 2


def test_jev_post_honours_429_at_http_transport(monkeypatch):
    import API_unified
    import jev_client

    monkeypatch.setattr(API_unified, "JEV_RETRY_MAX", 3)
    monkeypatch.setattr(API_unified, "JEV_RETRY_BASE_MS", 1)
    monkeypatch.setattr(jev_client, "_get_jev_config", lambda: ("test-key", "https://jev.test", "m"))

    class _Transport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)

    def _client() -> httpx.Client:
        return httpx.Client(transport=_Transport())

    monkeypatch.setattr(jev_client, "_http_client", _client)
    out = jev_client._jev_post("s1", {"is_toxic": "Is this toxic?"})
    assert out is None
    assert jev_client._last_jev_failure == "http:429"