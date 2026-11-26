"""Acceptance harness watchdog (env thresholds from API_unified)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable


def _env_limits() -> dict[str, float | int]:
    from API_unified import (
        ACCEPT_CONSECUTIVE_FAIL_MAX,
        ACCEPT_FAIL_RATE_MAX,
        ACCEPT_MIN_ROWS_BEFORE_RATE,
        ACCEPT_QUESTION_TIMEOUT_S,
        ACCEPT_SUITE_TIMEOUT_S,
    )

    return {
        "question_timeout_s": ACCEPT_QUESTION_TIMEOUT_S,
        "suite_timeout_s": ACCEPT_SUITE_TIMEOUT_S,
        "consecutive_fail_max": ACCEPT_CONSECUTIVE_FAIL_MAX,
        "fail_rate_max": ACCEPT_FAIL_RATE_MAX,
        "min_rows_before_rate": ACCEPT_MIN_ROWS_BEFORE_RATE,
    }


def run_subprocess_question(question: str, timeout_s: float) -> tuple[Any, str | None]:
    """Fresh process per question; OS kill on timeout so harness always continues."""
    import json
    import subprocess
    import sys

    script = Path(__file__).resolve().parent / "isolated_ask.py"
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(question),
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout_s)),
            cwd=Path(__file__).resolve().parents[1],
        )
    except subprocess.TimeoutExpired:
        return None, f"question_timeout_after_{timeout_s}s"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-500:]
        return None, f"subprocess_exit_{proc.returncode}:{tail}"
    try:
        return json.loads(proc.stdout or "{}"), None
    except json.JSONDecodeError as e:
        return None, f"subprocess_json_error:{e}"


def run_acceptance_question(question: str, timeout_s: float) -> tuple[Any, str | None]:
    from API_unified import ACCEPT_ISOLATE_SUBPROCESS, ACCEPT_USE_WARM_WORKER

    if ACCEPT_USE_WARM_WORKER:
        from eval.warm_worker import get_warm_worker

        return get_warm_worker().ask(question, timeout_s)
    if ACCEPT_ISOLATE_SUBPROCESS:
        return run_subprocess_question(question, timeout_s)
    import aurix_core as core

    return run_with_timeout(lambda: core.get_final_answer(question), timeout_s)


def run_with_timeout(fn: Callable[[], Any], timeout_s: float) -> tuple[Any, str | None]:
    """Run fn in a thread; return (result, error_message).

    On timeout, do not block the caller on pool shutdown (orphan worker may still run).
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    pool = ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(fn)
    try:
        return fut.result(timeout=max(1.0, float(timeout_s))), None
    except FuturesTimeout:
        fut.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
        return None, f"question_timeout_after_{timeout_s}s"
    finally:
        if not pool._shutdown:  # noqa: SLF001
            pool.shutdown(wait=False, cancel_futures=True)


class AcceptWatchdog:
    def __init__(self, *, suite_start: float | None = None) -> None:
        self._t0 = suite_start if suite_start is not None else time.monotonic()
        self._consecutive_fail = 0
        self._limits = _env_limits()

    def suite_expired(self) -> bool:
        return (time.monotonic() - self._t0) >= float(self._limits["suite_timeout_s"])

    def record_row(self, passed: bool) -> None:
        if passed:
            self._consecutive_fail = 0
        else:
            self._consecutive_fail += 1

    def should_abort(self, *, total_rows: int, failed_rows: int) -> tuple[bool, str | None]:
        if self.suite_expired():
            return True, "suite_timeout"
        if self._consecutive_fail >= int(self._limits["consecutive_fail_max"]):
            return True, "consecutive_failures"
        min_rows = int(self._limits["min_rows_before_rate"])
        if total_rows >= min_rows and total_rows > 0:
            rate = failed_rows / total_rows
            if rate > float(self._limits["fail_rate_max"]):
                return True, "fail_rate"
        return False, None

    def write_abort(
        self,
        out_path: Path,
        *,
        reason: str,
        rows: list[dict],
        extra: dict | None = None,
    ) -> Path:
        payload = {
            "abort_reason": reason,
            "rows": rows,
            "elapsed_s": round(time.monotonic() - self._t0, 2),
            "limits": self._limits,
            "extra": extra or {},
        }
        abort_path = out_path.parent / f"{out_path.stem}-abort.json"
        abort_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return abort_path