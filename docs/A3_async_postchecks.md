# A3 — Async post-checks

- `ASYNC_POSTCHECKS_ENABLED` (default **false**): when true, S9/S13 run in daemon threads after the user-facing answer path.
- `ASYNC_POSTCHECKS_TIMEOUT_S` (default **30**): watchdog logs a warning if a background post-check thread is still running after this many seconds.
- Errors in background threads are logged to `postchecks.async` only; they never change the user response.