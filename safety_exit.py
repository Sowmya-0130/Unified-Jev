"""Merge safety_gate blocked_response with pipeline exit copy."""
from __future__ import annotations

from typing import Any

from pipeline_exits import resolve_exit, trace_exit
from safety_gate import SafetyVerdict, blocked_response


def response_for_safety_block(verdict: SafetyVerdict, question: str, term: str) -> dict[str, Any]:
    base = blocked_response(verdict, question)
    trace_exit(term, question=question)
    out = resolve_exit(term, question=question, base=base)
    custom = (verdict.blocked_message or "").strip()
    if custom:
        out["llm_answer"] = custom
        fa = dict(out.get("final_answer") or {})
        fa["llm_answer"] = custom
        out["final_answer"] = fa
    out["Reasoning"] = term
    if base.get("rai_evaluation"):
        out["rai_evaluation"] = base["rai_evaluation"]
    return out