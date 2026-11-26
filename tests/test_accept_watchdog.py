from __future__ import annotations

import time

from eval.accept_watchdog import AcceptWatchdog


def test_consecutive_fail_abort():
    wd = AcceptWatchdog(suite_start=time.monotonic())
    wd._limits["consecutive_fail_max"] = 3  # noqa: SLF001
    wd.record_row(False)
    wd.record_row(False)
    abort, _ = wd.should_abort(total_rows=2, failed_rows=2)
    assert not abort
    wd.record_row(False)
    abort, reason = wd.should_abort(total_rows=3, failed_rows=3)
    assert abort and reason == "consecutive_failures"


def test_fail_rate_abort():
    wd = AcceptWatchdog(suite_start=time.monotonic())
    wd._limits["min_rows_before_rate"] = 4  # noqa: SLF001
    wd._limits["fail_rate_max"] = 0.25  # noqa: SLF001
    abort, _ = wd.should_abort(total_rows=4, failed_rows=1)
    assert not abort
    abort, reason = wd.should_abort(total_rows=8, failed_rows=3)
    assert abort and reason == "fail_rate"