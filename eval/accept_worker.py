"""Long-lived accept worker: one JSON line in, one JSON line out (stdout)."""
from __future__ import annotations

import io
import json
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    from catalog_runtime import bootstrap_catalog

    try:
        bootstrap_catalog()
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("accept_worker").warning("catalog bootstrap: %s", exc)

    import aurix_core as core

    for raw in sys.stdin:
        line = (raw or "").strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps({"ok": False, "error": f"bad_json:{exc}"}))
            sys.stdout.write("\n")
            sys.stdout.flush()
            continue
        if req.get("cmd") == "ping":
            sys.stdout.write(json.dumps({"ok": True, "pong": True}) + "\n")
            sys.stdout.flush()
            continue
        question = req.get("question", "")
        _cap = io.StringIO()
        _real = sys.stdout
        sys.stdout = _cap
        try:
            response = core.get_final_answer(question)
        except Exception as exc:  # noqa: BLE001
            sys.stdout = _real
            sys.stdout.write(json.dumps({"ok": False, "error": str(exc)}, default=str) + "\n")
            sys.stdout.flush()
            continue
        sys.stdout = _real
        latency = (response.get("jev_trace") or {}).get("latency") or {}
        sys.stdout.write(
            json.dumps(
                {"ok": True, "response": response, "latency_ms": latency.get("total_ms")},
                default=str,
            )
            + "\n"
        )
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())