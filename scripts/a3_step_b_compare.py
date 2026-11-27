"""Step B: compare sync vs async post-checks on live pipeline (2 questions)."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

QUESTIONS = {
    "sql": "What were the total Dupont order amounts for Kevlar Gloves in 2025?",
    "semantic": "What does the documentation say about returns for Kevlar Gloves?",
}


def _one_run(mode: str, question: str) -> dict:
    os.environ["ASYNC_POSTCHECKS_ENABLED"] = "true" if mode == "async" else "false"
    os.environ.setdefault("ORCHESTRATOR", "pipeline")
    import importlib

    import API_unified
    import aurix_core as core

    importlib.reload(API_unified)
    importlib.reload(core)
    from catalog_runtime import bootstrap_catalog

    try:
        bootstrap_catalog()
    except Exception:  # noqa: BLE001
        pass

    t0 = time.perf_counter()
    out = core.get_final_answer(question)
    wall_ms = (time.perf_counter() - t0) * 1000
    lat = (out.get("jev_trace") or {}).get("latency") or {}
    qa = (out.get("query_answer") or (out.get("final_answer") or {}).get("query_answer") or "")
    llm = (out.get("llm_answer") or (out.get("final_answer") or {}).get("llm_answer") or "")
    term = out.get("termination_reason") or (out.get("jev_trace") or {}).get("termination")
    return {
        "mode": mode,
        "question_key": question[:40],
        "wall_ms": round(wall_ms, 1),
        "total_ms": lat.get("total_ms"),
        "jev_ms": lat.get("jev_ms"),
        "llm_ms": lat.get("llm_ms"),
        "db_ms": lat.get("db_ms"),
        "termination": term,
        "has_answer": bool(str(qa or llm).strip()),
        "answer_len": len(str(qa or llm)),
    }


def main() -> int:
    rows: list[dict] = []
    for qkind, qtext in QUESTIONS.items():
        for mode in ("sync", "async"):
            print(f"[a3-step-b] {qkind} {mode} …", flush=True)
            try:
                rows.append({"kind": qkind, **_one_run(mode, qtext)})
            except Exception as exc:  # noqa: BLE001
                rows.append({"kind": qkind, "mode": mode, "error": str(exc)[:200]})
    out_path = _ROOT / ".loop" / "logs" / "a3-step-b.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())