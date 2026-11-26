"""Refuse eval/verify if other AURIX python processes are still running."""
from __future__ import annotations

import json
import os
import sys
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_MATCH = (
    "Unified-SingleDB",
    "sql_acceptance",
    "safety_acceptance",
    "both_acceptance",
    "bench_correctness",
    "run-a1-verify",
    "isolated_ask",
    "accept_worker",
    "streamlit",
    "pytest",
    "latency_ab_orchestrator",
)


def _self_pid() -> int:
    return os.getpid()


def _list_python_processes() -> list[dict]:
    if sys.platform != "win32":
        return []
    ps = (
        "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        raw = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps],
            text=True,
            timeout=30,
        ).strip()
    except (subprocess.SubprocessError, OSError):
        return []
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    return [r for r in data if isinstance(r, dict)]


def assert_solo_aurix_runtime(*, role: str = "eval") -> None:
    """Exit 2 if another AURIX-related python process is alive."""
    me = _self_pid()
    hits: list[str] = []
    for row in _list_python_processes():
        pid = int(row.get("ProcessId") or 0)
        if pid == me or pid <= 0:
            continue
        cmd = (row.get("CommandLine") or "").lower()
        root = str(_ROOT).lower()
        if root not in cmd and not any(m in cmd for m in _MATCH):
            continue
        if "accept_worker.py" in cmd:
            continue
        if "pytest" in cmd and "tests" in cmd and role.startswith("pytest"):
            continue
        hits.append(f"pid={pid} cmd={(row.get('CommandLine') or '')[:160]}")
    if hits:
        msg = (
            f"Another AURIX process is running ({role}); stop it first:\n"
            + "\n".join(hits[:8])
        )
        print(msg, file=sys.stderr)
        raise SystemExit(2)