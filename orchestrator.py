"""Code pipeline orchestrator (A1): explicit state machine, one LLM turn per writer agent."""
from __future__ import annotations

import json
from typing import Any, Callable

from agent_runner import agent_llm_turn
from pipeline_response import build_response
from request_context import RequestContext, _MessagesProxy


def _proxy(ctx: RequestContext) -> _MessagesProxy:
    return _MessagesProxy(ctx)


def _attach_transcript(resp: dict, ctx: RequestContext) -> dict:
    out = dict(resp)
    out["_pipeline_transcript"] = list(ctx.transcript)
    return out


def _s4_label(route: str | None) -> str:
    r = (route or "SQL-based").strip()
    if r.lower().startswith("semantic"):
        return "Semantic-based"
    return "SQL-based"


def run_sql_path(ctx: RequestContext, *, finish: Callable[..., dict]) -> dict:
    import aurix_core as core
    from API_unified import JEV_S7_SQL_RESULT_ENABLED, JEV_S9_EVAL_ENABLED, JEV_SHADOW_MODE, SQL_MAX_REPAIR_ROUNDS
    from gate_inputs import latest_sql_tool_result, s7_input
    from jev_client import s7_resolve
    from jev_trace import event as _jev_event, jev_timed, log_gate_decision, record_termination
    from request_state import bump_validation_repair, take_validation_repairs
    from routing_s4 import append_synthetic_routing, S4Preflight
    from sql_execute_step import (
        append_sql_tool_message,
        parse_sql_generator_query,
        run_validated_sql,
        validation_error_body,
    )

    gc = _proxy(ctx)
    from API_unified import SCHEMA_LINK_TOP_K
    from request_state import prestaged_schema_block
    from schema_linker import linked_schema_block
    from sql_catalog import get_catalog_readonly

    schema = prestaged_schema_block() or linked_schema_block(
        ctx.question, k=SCHEMA_LINK_TOP_K, catalog=get_catalog_readonly()
    )
    from sql_generator_prompt import SQL_GENERATOR_BASE

    pre = S4Preflight(handled=False, route=ctx.analysis_type or "SQL-based", next_agent="Sql_Generator", jev={})
    append_synthetic_routing(gc, ctx.question, pre)

    user_msg = json.dumps({"initial_question": ctx.question, "analysis_type": "SQL-based"})
    sg_prompt = f"{SQL_GENERATOR_BASE}\n{schema}\n\n{user_msg}"
    sg_out = agent_llm_turn(core.Sql_Generator, sg_prompt, sender=core.user_proxy)
    ctx.append("Sql_Generator", sg_out)

    for _ in range(SQL_MAX_REPAIR_ROUNDS + 1):
        _q = parse_sql_generator_query(sg_out)
        _to_run, _ = run_validated_sql(_q, question=ctx.question)
        if _to_run:
            body = core.db_execute_query(query=_to_run, db_name="SQL")
        else:
            from sql_repair_recovery import try_time_window_zero_from_generator_sql

            _mrc = try_time_window_zero_from_generator_sql(gc)
            if _mrc == 0 and core._emit_template_insight(gc, "[]"):
                record_termination("sql_validation_recovery_empty", attempts=0)
                base = build_response({}, ctx.transcript, analysis_type="SQL-based")
                return finish(_attach_transcript(base, ctx), termination_reason="pipeline_sql_template")
            body = validation_error_body(_q, question=ctx.question)

        append_sql_tool_message(gc, body)
        _jev_event("agent", name="Sql_tool")
        from jev_trace import mark_agent_transition

        mark_agent_transition(core.Sql_tool)

        _sql_out, _idx = latest_sql_tool_result(ctx.transcript)
        if "sql_pipeline_error" in str(_sql_out):
            bump_validation_repair()
            if take_validation_repairs() >= SQL_MAX_REPAIR_ROUNDS:
                from sql_repair_recovery import try_time_window_zero_from_generator_sql

                _mrc = try_time_window_zero_from_generator_sql(gc)
                if _mrc == 0 and core._emit_template_insight(gc, "[]"):
                    record_termination("sql_validation_recovery_empty", attempts=take_validation_repairs())
                    base = build_response({}, ctx.transcript, analysis_type="SQL-based")
                    return finish(_attach_transcript(base, ctx), termination_reason="pipeline_sql_template")
                record_termination("sql_max_repair_rounds", attempts=take_validation_repairs())
                break
            repair_prompt = (
                f"SQL validation failed. Prior output:\n{sg_out}\nError:\n{_sql_out}\n"
                "Return corrected JSON with one sql_query."
            )
            sg_out = agent_llm_turn(core.Sql_Generator, repair_prompt, sender=core.user_proxy)
            ctx.append("Sql_Generator", sg_out)
            continue

        def _run_s7():
            return s7_resolve(_sql_out or "", jev_enabled=JEV_S7_SQL_RESULT_ENABLED)

        _rcheck = jev_timed("S7", _run_s7) if JEV_S7_SQL_RESULT_ENABLED else _run_s7()
        _s7_in = s7_input(_sql_out or "", message_index=_idx)
        _valid = bool(_rcheck.get("is_valid"))
        _no_data = bool(_rcheck.get("no_matching_data"))
        log_gate_decision(
            "S7",
            input_summary=_s7_in,
            decision="pass" if _valid else ("no_data" if _no_data else "fail"),
            confidence=_rcheck.get("confidence"),
            action="skip_llm",
            decision_source=_rcheck.get("decision_source") or _rcheck.get("source") or "code",
        )
        if _no_data:
            if core._emit_template_insight(gc, "[]"):
                base = build_response({}, ctx.transcript, analysis_type="SQL-based")
                return finish(_attach_transcript(base, ctx), termination_reason="pipeline_sql_no_rows")
            break
        if _valid:
            if core._emit_template_insight(gc, _sql_out or ""):
                base = build_response({}, ctx.transcript, analysis_type="SQL-based")
                return finish(_attach_transcript(base, ctx), termination_reason="pipeline_sql_template")
            core._bind_insight_for_sql(gc)
            ins_prompt = json.dumps({"sql_result_preview": str(_sql_out or "")[:4000]})
            ins_out = agent_llm_turn(core.Insight_Generator, ins_prompt, sender=core.user_proxy)
            ctx.append("Insight_Generator", ins_out)
            if JEV_S9_EVAL_ENABLED and not JEV_SHADOW_MODE:
                try:
                    from jev_client import jev_eval_quality
                    from jev_trace import jev_timed as _jt

                    _eq = _jt("S9", lambda: jev_eval_quality(ctx.question, ins_out))
                    _skip = (
                        _eq.get("source") == "openjev"
                        and _eq.get("skip_llm_eval")
                        and float(_eq.get("composite") or 0) >= float(
                            __import__("API_unified", fromlist=["JEV_CONFIDENCE_THRESHOLD"]).JEV_CONFIDENCE_THRESHOLD
                        )
                    )
                    log_gate_decision(
                        "S9",
                        input_summary={"question_len": len(ctx.question)},
                        decision="pass" if _skip else "defer",
                        action="skip_llm" if _skip else "run_llm",
                        decision_source="jev" if _eq.get("source") == "openjev" else "code",
                    )
                except Exception:  # noqa: BLE001
                    pass
            base = build_response({}, ctx.transcript, analysis_type="SQL-based")
            return finish(_attach_transcript(base, ctx), termination_reason="pipeline_sql_completed")
        bump_validation_repair()
        if take_validation_repairs() >= SQL_MAX_REPAIR_ROUNDS:
            record_termination("sql_max_repair_rounds", attempts=take_validation_repairs())
            break
        sg_out = agent_llm_turn(
            core.Sql_Generator,
            f"SQL result check failed: {_rcheck}. Return fixed sql_query JSON.",
            sender=core.user_proxy,
        )
        ctx.append("Sql_Generator", sg_out)

    if core._emit_template_insight(gc, "[]"):
        base = build_response({}, ctx.transcript, analysis_type="SQL-based")
        return finish(_attach_transcript(base, ctx), termination_reason="pipeline_sql_honest_template")
    base = build_response({}, ctx.transcript, analysis_type="SQL-based")
    return finish(_attach_transcript(base, ctx), termination_reason="pipeline_sql_exit")


def run_semantic_path(ctx: RequestContext, *, finish: Callable[..., dict]) -> dict:
    import asyncio

    import aurix_core as core
    from jev_trace import mark_agent_transition, record_termination
    from routing_s4 import append_synthetic_routing, S4Preflight

    gc = _proxy(ctx)
    pre = S4Preflight(handled=False, route="Semantic-based", next_agent="Eryl_agent", jev={})
    append_synthetic_routing(gc, ctx.question, pre)

    chunks = asyncio.run(core.extract_context(question=ctx.question))
    ctx.append("retriever", json.dumps(chunks, default=str))
    mark_agent_transition(core.retriever)

    if chunks.get("not_found"):
        msg = "I could not find enough information in the documents to answer that question."
        ctx.append("llm_answer_maker", msg)
        base = build_response({"llm_answer": msg}, ctx.transcript, analysis_type="Semantic-based")
        return finish(_attach_transcript(base, ctx), termination_reason="pipeline_semantic_not_found")

    prompt = json.dumps({"question": ctx.question, "context": chunks}, default=str)
    ans = agent_llm_turn(core.llm_answer_maker, prompt, sender=core.user_proxy)
    ctx.append("llm_answer_maker", ans)

    from API_unified import JEV_CONFIDENCE_THRESHOLD, JEV_S13_CRITIC_ENABLED

    if JEV_S13_CRITIC_ENABLED:
        try:
            from gate_inputs import parse_vector_context
            from jev_client import jev_critic_check
            from jev_trace import jev_timed, log_gate_decision

            _chunks = parse_vector_context(json.dumps(chunks))
            _cr = jev_timed("S13", lambda: jev_critic_check(ctx.question, ans, _chunks))
            _pass = bool(_cr.get("is_grounded")) and float(_cr.get("confidence") or 0) >= JEV_CONFIDENCE_THRESHOLD
            log_gate_decision(
                "S13",
                decision="pass" if _pass else "defer",
                action="skip_llm" if _pass else "run_llm",
                decision_source="jev" if _cr.get("source") == "openjev" else "code",
            )
        except Exception:  # noqa: BLE001
            record_termination("pipeline_s13_defer")

    base = build_response({"llm_answer": ans}, ctx.transcript, analysis_type="Semantic-based")
    return finish(_attach_transcript(base, ctx), termination_reason="pipeline_semantic_completed")


def run_pipeline(
    question: str,
    *,
    request_id: str,
    route: str | None,
    next_agent: str | None,
    finish: Callable[..., dict],
    base_response: dict | None = None,
) -> dict:
    """Dispatch SQL / semantic pipeline after pre-chat S1+S4."""
    ctx = RequestContext(request_id=request_id, question=question)
    ctx.analysis_type = _s4_label(route)

    import aurix_core as core
    from request_state import jev_route_next_agent

    dest = next_agent or jev_route_next_agent()
    if dest == "Eryl_agent" or ctx.analysis_type == "Semantic-based":
        return run_semantic_path(ctx, finish=finish)
    return run_sql_path(ctx, finish=finish)