"""S4 JEV-only routing (no routing_agent LLM when ROUTING_LLM_FALLBACK=false)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

RouteChoice = Literal["SQL-based", "Semantic-based", "Both", "Both-independent", "Both-dependent"]


@dataclass
class S4Preflight:
    handled: bool
    finish_response: dict | None = None
    route: str | None = None
    next_agent: str | None = None
    jev: dict[str, Any] | None = None
    low_confidence_both: bool = False


def jev_s4_decision(question: str, schema_summary: str) -> dict[str, Any]:
    from jev_client import jev_routing_decision
    from jev_trace import jev_timed

    from dual_route import merge_openjev_route

    raw = jev_timed("S4", lambda: jev_routing_decision(question, schema_summary))
    return merge_openjev_route(question, raw)


def preflight_s4(question: str, *, schema_summary: str) -> S4Preflight:
    from API_unified import JEV_CONFIDENCE_THRESHOLD, JEV_ROUTING_ENABLED, ROUTING_LLM_FALLBACK
    from dual_route import infer_dual_route, next_agent_for_route

    if infer_dual_route(question) == "Both-independent":
        from both_answer import both_independent_answer

        return S4Preflight(
            handled=True,
            finish_response=both_independent_answer(question, parallel=True),
        )

    if not JEV_ROUTING_ENABLED or ROUTING_LLM_FALLBACK:
        return S4Preflight(handled=False)

    jev = jev_s4_decision(question, schema_summary)
    from jev_trace import log_gate_decision

    conf = float(jev.get("confidence") or 0.0)
    choice = (jev.get("choice") or "").strip() or "SQL-based"
    if (jev.get("source") or "").strip() == "fallback":
        return S4Preflight(handled=False, jev=jev)
    low_conf = conf < JEV_CONFIDENCE_THRESHOLD
    if low_conf:
        from both_answer import both_independent_answer

        log_gate_decision(
            "S4",
            input_summary={"question_len": len(question), "schema_chars": len(schema_summary)},
            decision="Both",
            confidence=conf,
            threshold=JEV_CONFIDENCE_THRESHOLD,
            action="skip_llm",
            fallback_reason="low_confidence_both_parallel",
        )
        return S4Preflight(
            handled=True,
            finish_response=both_independent_answer(question, parallel=True),
            low_confidence_both=True,
            jev=jev,
        )

    log_gate_decision(
        "S4",
        input_summary={"question_len": len(question), "schema_chars": len(schema_summary)},
        decision=choice,
        confidence=conf,
        threshold=JEV_CONFIDENCE_THRESHOLD,
        action="skip_llm",
    )
    if choice.startswith("Both"):
        from both_answer import both_independent_answer

        return S4Preflight(
            handled=True,
            finish_response=both_independent_answer(question, parallel=True),
            jev=jev,
        )

    next_ag = next_agent_for_route(choice)
    if next_ag == "Both_handler":
        next_ag = "Eryl_agent"
    return S4Preflight(
        handled=False,
        route=choice,
        next_agent=next_ag,
        jev=jev,
    )


def append_synthetic_routing(groupchat: Any, question: str, pre: S4Preflight) -> None:
    import json

    from dual_route import coerce_sql_only_route

    route = pre.route or "SQL-based"
    coerced = coerce_sql_only_route(question, route)
    if coerced:
        route = coerced
        pre.next_agent = "Sql_Generator"
    groupchat.messages.append({
        "name": "jev_s4_routing",
        "role": "assistant",
        "content": json.dumps({
            "initial_question": question,
            "analysis_type": route,
            "next_agent": pre.next_agent or "Sql_Generator",
            "next_step": f"JEV S4 (conf {float((pre.jev or {}).get('confidence') or 0):.2f})",
            "Reasoning": "JEV S4 routing (no routing_agent LLM)",
        }),
    })