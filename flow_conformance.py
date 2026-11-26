"""Trace conformance vs TARGET FLOW (diagram in docs/ARCHITECTURE_JEV.md)."""
from __future__ import annotations

from typing import Any

FORBIDDEN_SPEAKERS = frozenset({
    "Responsible_AI_Agent",
    "routing_agent",
    "Query_Executor",
})

FORBIDDEN_UNLESS_ROLLBACK = frozenset({
    "Sql_Execution_Critic",
    "query_transformer",
})

SQL_ALLOWED = frozenset({
    "user_proxy",
    "azure_safety_check",
    "Sql_Generator",
    "Sql_tool",
    "Insight_Generator",
    "evaluation_agent",
    "Responsible_AI_Agent",  # only when SAFETY_LLM_MODE != off
    "routing_agent",  # only when ROUTING_LLM_FALLBACK
})

GATE_DECISION_MAKER = {
    "S1": ("regex", "jev"),
    "S4": ("jev",),
    "S7": ("code", "jev", "heuristic"),
    "S9": ("jev", "heuristic", "code"),
    "S13": ("jev",),
}


def _speakers(trace: dict) -> list[str]:
    lat = trace.get("latency") or {}
    tl = trace.get("timeline") or lat.get("timeline") or []
    names: list[str] = []
    for step in tl:
        if step.get("kind") == "agent_turn" and step.get("name"):
            names.append(str(step["name"]))
    if not names:
        seq = trace.get("chat_agent_sequence") or lat.get("chat_agent_sequence") or []
        for step in seq:
            if isinstance(step, str):
                names.append(step)
            elif isinstance(step, dict) and step.get("name"):
                names.append(str(step["name"]))
    return names


def check_trace(
    trace: dict,
    *,
    safety_llm_mode: str = "off",
    routing_llm_fallback: bool = False,
    sql_s7_llm_fallback: bool = False,
    semantic_query_transformer: bool = False,
) -> list[str]:
    violations: list[str] = []
    rid = str(trace.get("request_id") or trace.get("latency", {}).get("request_id") or "?")
    term = (trace.get("termination") or {}).get("reason") or trace.get("latency", {}).get("termination")
    if isinstance(term, dict):
        term = term.get("reason")
    speakers = _speakers(trace)

    if term in ("safety_blocked", "safety_grey_blocked") or str(term).startswith("safety"):
        if speakers and any(s not in ("user_proxy",) for s in speakers if s != "azure_safety_check"):
            pass  # pre-chat block may have empty speakers
        return violations

    forbidden = set(FORBIDDEN_SPEAKERS)
    if safety_llm_mode == "off":
        forbidden.add("Responsible_AI_Agent")
    if not routing_llm_fallback:
        forbidden.add("routing_agent")
    if not sql_s7_llm_fallback:
        forbidden |= {"Sql_Execution_Critic"}
    if not semantic_query_transformer:
        forbidden.add("query_transformer")

    for sp in speakers:
        if sp in forbidden:
            violations.append(f"{rid}: forbidden speaker {sp}")

    for g in (trace.get("gate_decisions") or trace.get("latency", {}).get("gate_decisions") or []):
        gate = str(g.get("gate") or "")
        action = str(g.get("action") or "")
        src = str(g.get("decision_source") or "")
        if gate == "S1" and safety_llm_mode == "off" and action == "run_llm":
            violations.append(f"{rid}: S1 run_llm not allowed in off mode")
        if gate == "S4" and not routing_llm_fallback and action == "run_llm":
            violations.append(f"{rid}: S4 run_llm not allowed")
    return violations


def assert_trace_conforms(trace: dict, **kwargs: Any) -> None:
    v = check_trace(trace, **kwargs)
    if v:
        raise AssertionError("; ".join(v))