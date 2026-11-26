"""Single warm acceptance worker subprocess (restart on question timeout)."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_WORKER = Path(__file__).resolve().parent / "accept_worker.py"

_worker: "WarmAcceptWorker | None" = None
_worker_lock = threading.Lock()


class WarmAcceptWorker:
    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None
        self._start()

    def _start(self) -> None:
        self._proc = subprocess.Popen(
            [sys.executable, str(_WORKER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            cwd=str(_ROOT),
        )
        self._ping()

    def _ping(self) -> None:
        assert self._proc and self._proc.stdin and self._proc.stdout
        self._proc.stdin.write(json.dumps({"cmd": "ping"}) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line.strip():
            raise RuntimeError("accept_worker ping failed")
        data = json.loads(line)
        if not data.get("ok"):
            raise RuntimeError("accept_worker not ok")

    def restart(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.kill()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        self._start()

    def ask(self, question: str, timeout_s: float) -> tuple[Any, str | None]:
        if not self._proc or self._proc.poll() is not None:
            self._start()
        assert self._proc and self._proc.stdin and self._proc.stdout
        t0 = time.monotonic()
        self._proc.stdin.write(json.dumps({"question": question}) + "\n")
        self._proc.stdin.flush()
        try:
            line = self._readline_within(timeout_s)
        except TimeoutError:
            self.restart()
            return None, f"question_timeout_after_{timeout_s}s"
        if not line.strip():
            self.restart()
            return None, "worker_empty_stdout"
        try:
            pkt = json.loads(line)
        except json.JSONDecodeError as exc:
            self.restart()
            return None, f"worker_json_error:{exc}"
        if not pkt.get("ok"):
            return None, str(pkt.get("error") or "worker_error")
        resp = pkt.get("response")
        if isinstance(resp, dict):
            lat = (resp.get("jev_trace") or {}).get("latency") or {}
            if lat.get("total_ms") is None and pkt.get("latency_ms") is not None:
                lat = {**lat, "total_ms": pkt.get("latency_ms")}
                jt = resp.setdefault("jev_trace", {})
                jt["latency"] = lat
        _ = t0
        return resp, None

    def _readline_within(self, timeout_s: float) -> str:
        assert self._proc and self._proc.stdout
        end = time.monotonic() + max(0.5, float(timeout_s))

        def _reader() -> str:
            return self._proc.stdout.readline()  # type: ignore[union-attr]

        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_reader)
            try:
                return fut.result(timeout=max(0.1, end - time.monotonic()))
            except FuturesTimeout as exc:
                fut.cancel()
                pool.shutdown(wait=False, cancel_futures=True)
                raise TimeoutError(str(exc)) from exc
            finally:
                if not pool._shutdown:  # noqa: SLF001
                    pool.shutdown(wait=False, cancel_futures=True)


def get_warm_worker() -> WarmAcceptWorker:
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = WarmAcceptWorker()
        return _worker