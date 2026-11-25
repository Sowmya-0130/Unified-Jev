"""Smoke trace: two questions through get_final_answer (no Streamlit). Logs agents + JEV gates."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import API_unified
importlib.reload(API_unified)
import aurix_core
importlib.reload(aurix_core)

_JEV_FLAGS = [
    ("S1", API_unified.JEV_S1_SAFETY_ENABLED),
    ("S4", API_unified.JEV_ROUTING_ENABLED),
    ("S7", API_unified.JEV_S7_SQL_RESULT_ENABLED),
    ("S9", API_unified.JEV_S9_EVAL_ENABLED),
    ("S13", API_unified.JEV_S13_CRITIC_ENABLED),
]
print("JEV core flags:", {k: v for k, v in _JEV_FLAGS})
print("Azure endpoint:", API_unified.AZURE_OPENAI_API_BASE)
_key = API_unified.JEV_API_KEY or ""
print("JEV_API_KEY:", (_key[:7] + "****") if len(_key) > 7 else "(empty)")

_orig_transition = aurix_core.state_transition
_agents_run: list[str] = []


def _logging_transition(last_speaker, groupchat):
    nxt = _orig_transition(last_speaker, groupchat)
    if nxt is not None:
        _agents_run.append(getattr(nxt, "name", str(nxt)))
    return nxt


aurix_core.state_transition = _logging_transition


def _jev_from_history(chat_history) -> list[str]:
    markers = []
    for item in chat_history.chat_history:
        content = item.get("content") or ""
        name = item.get("name", "")
        if "jev_s" in content.lower() or "openjev" in content.lower() or "routed by openjev" in content.lower():
            markers.append(name)
        if name in ("Sql_Execution_Critic", "Evaluation_Agent", "critic_agent", "routing_agent"):
            if "jev" in content.lower():
                markers.append(f"{name}(synthetic)")
    return markers


def run_case(label: str, question: str) -> None:
    global _agents_run
    _agents_run = []
    print("\n" + "=" * 60)
    print("CASE:", label)
    print("Q:", question[:120])
    try:
        out = aurix_core.get_final_answer(question)
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "403" in msg:
            print("ERROR CLASS: 401/403 credentials — stop; fix Azure settings in .env.")
        elif "getaddrinfo" in msg.lower() or "cannot resolve" in msg.lower():
            print("ERROR CLASS: DNS — alias/resolution issue")
        else:
            print("ERROR CLASS: other")
        print("TRACEBACK/MSG:", type(exc).__name__, msg[:500])
        return

    llm = (out.get("llm_answer") or "")[:200]
    if "401" in llm or "403" in llm or "invalid subscription key" in llm.lower():
        print("ERROR CLASS: 401/403 in response — credentials; pipeline did not complete.")
        print("llm_answer snippet:", llm)
        return

    print("analysis_type:", out.get("analysis_type"))
    print("agents_transition_sequence:", _agents_run)
    skipped = []
    if "Sql_Execution_Critic" not in _agents_run and API_unified.JEV_S7_SQL_RESULT_ENABLED:
        skipped.append("Sql_Execution_Critic (possible S7 skip)")
    if "Evaluation_Agent" not in _agents_run and out.get("analysis_type", "").startswith("SQL"):
        skipped.append("Evaluation_Agent (possible S9 skip)")
    if "critic_agent" not in _agents_run and "Semantic" in str(out.get("analysis_type", "")):
        skipped.append("critic_agent (possible S13 skip)")
    if "routing_agent" not in _agents_run:
        skipped.append("routing_agent (possible S4 skip)")
    print("likely_skipped_llm_agents:", skipped or "(none detected)")
    trace = out.get("jev_trace") or {}
    lat = trace.get("latency") or {}
    print("latency_summary:", json.dumps(lat, indent=2, default=str)[:3000])
    print("jev_trace:", json.dumps(trace, indent=2, default=str)[:4000])
    print("final_answer keys:", list((out.get("final_answer") or {}).keys()))


if __name__ == "__main__":
    run_case(
        "SQL",
        "What is the total amount spent on Chemical Resistant Boots and Kevlar Gloves in the last two months?",
    )
    run_case(
        "Semantic",
        "What is the return policy for damaged products according to company emails?",
    )