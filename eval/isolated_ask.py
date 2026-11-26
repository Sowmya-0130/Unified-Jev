"""One acceptance question in a fresh process (killed on timeout)."""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("ORCHESTRATOR", "pipeline")


def main() -> int:
    import aurix_core as core

    raw = sys.stdin.read()
    question = json.loads(raw) if raw.strip() else ""
    _stdout = sys.stdout
    _buf = io.StringIO()
    sys.stdout = _buf
    try:
        out = core.get_final_answer(question)
    finally:
        sys.stdout = _stdout
    _stdout.write(json.dumps(out, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())