from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock, patch

import pytest


def test_async_flag_off_runs_sync():
    import API_unified
    from postchecks_async import PostcheckContext, dispatch_postchecks

    with patch.object(API_unified, "ASYNC_POSTCHECKS_ENABLED", False):
        with patch("postchecks_async._execute_postchecks") as ex:
            with patch("postchecks_async.run_postchecks_async") as async_mock:
                dispatch_postchecks(PostcheckContext(question="q", route="sql", insight_text="i"))
    ex.assert_called_once()
    assert ex.call_args.kwargs.get("async_mode") is False
    async_mock.assert_not_called()


def test_async_flag_on_returns_immediately():
    import API_unified
    from postchecks_async import PostcheckContext, dispatch_postchecks

    with patch.object(API_unified, "ASYNC_POSTCHECKS_ENABLED", True):
        with patch("postchecks_async.run_postchecks_async") as async_mock:
            t0 = time.perf_counter()
            dispatch_postchecks(
                PostcheckContext(question="q", route="semantic", answer_text="a", chunks=[])
            )
            assert time.perf_counter() - t0 < 0.2
            async_mock.assert_called_once()


def test_async_exception_isolated():
    import API_unified
    from postchecks_async import PostcheckContext, _execute_postchecks

    with patch.object(API_unified, "JEV_S9_EVAL_ENABLED", True):
        with patch.object(API_unified, "JEV_SHADOW_MODE", False):
            with patch("jev_client.jev_eval_quality", side_effect=RuntimeError("boom")):
                _execute_postchecks(
                    PostcheckContext(question="q", route="sql", insight_text="x", trace_id="tid"),
                    async_mode=True,
                )
    assert True


def test_async_timeout(monkeypatch, caplog):
    import API_unified
    from postchecks_async import PostcheckContext, run_postchecks_async

    monkeypatch.setattr(API_unified, "ASYNC_POSTCHECKS_TIMEOUT_S", 0.05)
    with caplog.at_level(logging.WARNING, logger="postchecks.async"):

        def slow(*_a, **_k):
            time.sleep(1.0)

        with patch("postchecks_async._execute_postchecks", side_effect=slow):
            run_postchecks_async(PostcheckContext(question="q", route="sql", insight_text="i", trace_id="t"))
            time.sleep(0.25)
    assert any("ASYNC_POSTCHECKS_TIMEOUT" in r.message for r in caplog.records)


def test_thread_spawn_failure_falls_back_to_sync():
    import API_unified
    from postchecks_async import PostcheckContext, run_postchecks_async

    with patch.object(API_unified, "ASYNC_POSTCHECKS_ENABLED", True):
        with patch("postchecks_async.threading.Thread") as t_cls:
            t_cls.return_value.start.side_effect = OSError("spawn fail")
            with patch("postchecks_async.run_postchecks_sync") as sync_mock:
                run_postchecks_async(PostcheckContext(question="q", route="sql", insight_text="i"))
                sync_mock.assert_called_once()