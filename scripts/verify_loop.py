"""Run quick health checks in a loop-friendly script (no secrets printed)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
PY = _ROOT / ".venv" / "Scripts" / "python.exe"
if not PY.is_file():
    PY = Path(sys.executable)


def run(label: str, script: str) -> bool:
    print("\n---", label, "---")
    r = subprocess.run([str(PY), str(_ROOT / script)], cwd=str(_ROOT))
    ok = r.returncode == 0
    print(label, "OK" if ok else "FAIL")
    return ok


def main() -> int:
    ok = True
    for label, script in [
        ("import aurix_core", "-c"),
        ("test_sql", "test_sql.py"),
        ("test_azure_openai", "test_azure_openai.py"),
        ("check_jev syntax", "check_jev.py"),
    ]:
        if script == "-c":
            print("\n--- import aurix_core ---")
            r = subprocess.run([str(PY), "-c", "import aurix_core; print('import OK')"], cwd=str(_ROOT))
            if r.returncode != 0:
                ok = False
            continue
        ok = run(label, script) and ok
    print("\n=== SUMMARY ===", "ALL OK" if ok else "SOME CHECKS FAILED")
    if not ok:
        print(
            "If test_azure_openai failed with 401: get working Azure keys from repo owner "
            "(GitHub never shipped .env). SQL/JEV/code fixes cannot replace invalid credentials."
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())