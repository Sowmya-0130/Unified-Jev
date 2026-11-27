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


def _schema_repair_prompt(
    schema: str,
    question: str,
    sg_out: str,
    sql_out: str,
    reason: str,
) -> str:
    from sql_generator_prompt import SQL_GENERATOR_BASE
    from sql_time_repair import enrich_validation_repair_reason

    reason = enrich_validation_repair_reason(reason, sql_out, question)
    user_msg = json.dumps({"initial_question": question, "analysis_type": "SQL-based"})
    from sql_catalog import get_catalog_readonly
    from sql_few_shot_bank import augment_sql_generator_prompt

    head, _few_ids = augment_sql_generator_prompt(
        SQL_GENERATOR_BASE, schema, user_msg, question, catalog=get_catalog_readonly()
    )
    base = (
        f"{head}\n\n"
        f"{reason}\nPrior Sql_Generator output:\n{sg_out}\n"
        f"Sql_tool result:\n{sql_out}\n"
    )
    if "empty" in reason.lower() or "no sql_query" in reason.lower():
        base += (
            "Your last reply was empty or missing sql_query. "
            'Respond with ONLY JSON: {"sql_query": "SELECT ..."} using tables/columns from the schema.\n'
        )
    return base + "Return corrected JSON with one sql_query using ONLY tables/columns from the schema above."


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
    from sql_tool_outcome import (
        is_safety_blocked_body,
        is_validation_error_body,
        s7_indicates_validation,
        user_message_for_failed_pipeline,
        validation_repair_reason,
    )

    gc = _proxy(ctx)
    from API_unified import SCHEMA_LINK_TOP_K
    from question_sql_normalize import normalize_question_for_sql
    from request_state import prestaged_schema_block
    from schema_linker import linked_schema_block
    from sql_catalog import get_catalog_readonly

    sql_question = normalize_question_for_sql(ctx.question)
    ctx.extra["sql_question_normalized"] = sql_question
    schema = prestaged_schema_block() or linked_schema_block(
        sql_question, k=SCHEMA_LINK_TOP_K, catalog=get_catalog_readonly()
    )
    from sql_generator_prompt import SQL_GENERATOR_BASE

    pre = S4Preflight(handled=False, route=ctx.analysis_type or "SQL-based", next_agent="Sql_Generator", jev={})
    append_synthetic_routing(gc, ctx.question, pre)

    from jev_trace import trace_stdout

    trace_stdout("SQL path: schema linked, calling Sql_Generator…")
    user_msg = json.dumps({"initial_question": sql_question, "analysis_type": "SQL-based"})
    from sql_few_shot_bank import augment_sql_generator_prompt

    cat = get_catalog_readonly()
    sg_prompt, few_ids = augment_sql_generator_prompt(
        SQL_GENERATOR_BASE, schema, user_msg, sql_question, catalog=cat
    )
    if few_ids:
        trace_stdout(f"SQL few-shot ids: {','.join(few_ids)}")
    sg_out = agent_llm_turn(core.Sql_Generator, sg_prompt, sender=core.user_proxy)
    trace_stdout("SQL path: Sql_Generator returned, validating / executing…")
    ctx.append("Sql_Generator", sg_out)

    for _round in range(SQL_MAX_REPAIR_ROUNDS + 1):
        _q = parse_sql_generator_query(sg_out)
        if not _q:
            from sql_catalog import get_catalog
            from sql_deterministic_repair import recover_last_generator_sql

            recovered = recover_last_generator_sql(ctx.transcript, sql_question, get_catalog())
            if recovered:
                sg_out = recovered
                trace_stdout("SQL path: recovered last generator SQL with deterministic repair")
                _q = parse_sql_generator_query(sg_out)
        _to_run, _ = run_validated_sql(_q, question=sql_question)
        if _to_run:
            body = core.db_execute_query(query=_to_run, db_name="SQL")
        else:
            from sql_repair_recovery import try_time_window_zero_from_generator_sql

            _mrc = try_time_window_zero_from_generator_sql(gc)
            if _mrc == 0 and core._emit_template_insight(gc, "[]"):
                record_termination("sql_validation_recovery_empty", attempts=0)
                base = build_response({}, ctx.transcript, analysis_type="SQL-based")
                return finish(_attach_transcript(base, ctx), termination_reason="pipeline_sql_template")
            body = validation_error_body(_q, question=sql_question)

        append_sql_tool_message(gc, body)
        trace_stdout(
            f"SQL path: round {_round} Sql_tool "
            f"({'executed' if _to_run else 'validation-only'})"
        )
        _jev_event("agent", name="Sql_tool")
        from jev_trace import mark_agent_transition

        mark_agent_transition(core.Sql_tool)

        _sql_out, _idx = latest_sql_tool_result(ctx.transcript)

        def _validation_repair(reason: str) -> dict | str:
            """'continue' | 'break' | finished response dict."""
            nonlocal sg_out
            bump_validation_repair()
            if take_validation_repairs() >= SQL_MAX_REPAIR_ROUNDS:
                from sql_repair_recovery import try_time_window_zero_from_generator_sql

                _mrc = try_time_window_zero_from_generator_sql(gc)
                if _mrc == 0 and core._emit_template_insight(gc, "[]"):
                    record_termination("sql_validation_recovery_empty", attempts=take_validation_repairs())
                    base = build_response({}, ctx.transcript, analysis_type="SQL-based")
                    return finish(_attach_transcript(base, ctx), termination_reason="pipeline_sql_template")
                record_termination("sql_max_repair_rounds", attempts=take_validation_repairs())
                from pipeline_exits import trace_exit

                _lout, _ = latest_sql_tool_result(ctx.transcript)
                trace_exit(
                    "sql_max_repair_rounds",
                    question=ctx.question,
                    context={"last_sql_out": _lout},
                )
                return "break"
            sg_out = agent_llm_turn(
                core.Sql_Generator,
                _schema_repair_prompt(schema, sql_question, sg_out, _sql_out, reason),
                sender=core.user_proxy,
            )
            ctx.append("Sql_Generator", sg_out)
            return "continue"

        def _apply_validation_repair(reason: str) -> dict | None:
            out = _validation_repair(reason)
            if isinstance(out, dict):
                return out
            if out == "continue":
                return None
            return {}  # break sentinel

        if is_safety_blocked_body(_sql_out):
            from sql_tool_outcome import log_pipeline_failure, user_message_for_failed_pipeline

            log_pipeline_failure(
                question=ctx.question,
                last_sql_out=_sql_out,
                termination="safety_gate_sql_blocked",
            )
            from pipeline_exits import apply_exit_fields, trace_exit

            trace_exit(
                "safety_gate_sql_blocked",
                question=ctx.question,
                context={"last_sql_out": _sql_out},
            )
            base = build_response(
                apply_exit_fields(
                    "safety_gate_sql_blocked",
                    question=ctx.question,
                    context={"last_sql_out": _sql_out},
                ),
                ctx.transcript,
                analysis_type="SQL-based",
            )
            return finish(_attach_transcript(base, ctx), termination_reason="safety_gate_sql_blocked")
        if is_validation_error_body(_sql_out):
            reason = validation_repair_reason(_sql_out)
            from sql_catalog import get_catalog
            from sql_deterministic_repair import patch_generator_sql_deterministic

            patched = patch_generator_sql_deterministic(
                sg_out, sql_question, _sql_out, get_catalog()
            )
            if patched:
                sg_out = patched
                trace_stdout("SQL path: deterministic repair applied, re-validating…")
                continue
            _early = _apply_validation_repair(reason)
            if isinstance(_early, dict) and _early:
                return _early
            if _early is None:
                continue
            break

        def _run_s7():
            return s7_resolve(_sql_out or "", jev_enabled=JEV_S7_SQL_RESULT_ENABLED)

        _rcheck = jev_timed("S7", _run_s7) if JEV_S7_SQL_RESULT_ENABLED else _run_s7()
        _s7_in = s7_input(_sql_out or "", message_index=_idx)
        if s7_indicates_validation(_rcheck):
            reason = validation_repair_reason(_sql_out)
            from sql_catalog import get_catalog
            from sql_deterministic_repair import patch_generator_sql_deterministic

            patched = patch_generator_sql_deterministic(
                sg_out, sql_question, _sql_out, get_catalog()
            )
            if patched:
                sg_out = patched
                trace_stdout("SQL path: deterministic repair applied (S7), re-validating…")
                continue
            _early = _apply_validation_repair(reason)
            if isinstance(_early, dict) and _early:
                return _early
            if _early is None:
                continue
            break

        _valid = _rcheck.get("is_valid") is True
        _no_data = bool(_rcheck.get("no_matching_data"))
        log_gate_decision(
            "S7",
            input_summary=_s7_in,
            decision="pass" if _valid else ("no_data" if _no_data else "fail"),
            confidence=_rcheck.get("confidence"),
            action="skip_llm",
            decision_source=_rcheck.get("decision_source") or _rcheck.get("source") or "code",
        )
        if _rcheck.get("is_valid") is None:
            if core._emit_template_insight(gc, _sql_out or ""):
                base = build_response({}, ctx.transcript, analysis_type="SQL-based")
                return finish(_attach_transcript(base, ctx), termination_reason="pipeline_sql_template")
            _early = _apply_validation_repair(
                "SQL result shape was inconclusive for S7; return SQL that yields a simple JSON row list."
            )
            if isinstance(_early, dict) and _early:
                return _early
            if _early is None:
                continue
            break
        if _no_data:
            if core._emit_template_insight(gc, "[]"):
                from pipeline_exits import trace_exit

                trace_exit("pipeline_sql_no_rows", question=ctx.question)
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
                from postchecks_async import PostcheckContext, dispatch_postchecks

                dispatch_postchecks(
                    PostcheckContext(
                        question=ctx.question,
                        route="sql",
                        trace_id=ctx.request_id,
                        insight_text=ins_out,
                    )
                )
            base = build_response({}, ctx.transcript, analysis_type="SQL-based")
            return finish(_attach_transcript(base, ctx), termination_reason="pipeline_sql_completed")
        _fail_reason = (
            f"SQL result check failed (error_type={_rcheck.get('error_type')!s}, "
            f"check={_rcheck!r})."
        )
        _early = _apply_validation_repair(_fail_reason)
        if isinstance(_early, dict) and _early:
            return _early
        if _early is None:
            continue
        break

    if core._emit_template_insight(gc, "[]"):
        from pipeline_exits import trace_exit

        trace_exit("pipeline_sql_honest_template", question=ctx.question)
        base = build_response({}, ctx.transcript, analysis_type="SQL-based")
        return finish(_attach_transcript(base, ctx), termination_reason="pipeline_sql_honest_template")
    _last_sql, _ = latest_sql_tool_result(ctx.transcript)
    from sql_tool_outcome import log_pipeline_failure, user_message_for_failed_pipeline

    log_pipeline_failure(
        question=ctx.question,
        last_sql_out=_last_sql,
        termination="pipeline_sql_exit",
    )
    from pipeline_exits import apply_exit_fields, trace_exit

    trace_exit(
        "pipeline_sql_exit",
        question=ctx.question,
        context={"last_sql_out": _last_sql},
    )
    base = build_response(
        apply_exit_fields(
            "pipeline_sql_exit",
            question=ctx.question,
            context={"last_sql_out": _last_sql},
        ),
        ctx.transcript,
        analysis_type="SQL-based",
    )
    return finish(_attach_transcript(base, ctx), termination_reason="pipeline_sql_exit")


def run_semantic_path(ctx: RequestContext, *, finish: Callable[..., dict]) -> dict:
    import asyncio

    import aurix_core as core
    from jev_trace import mark_agent_transition, record_termination
    from routing_s4 import append_synthetic_routing, S4Preflight

    gc = _proxy(ctx)
    pre = S4Preflight(handled=False, route="Semantic-based", next_agent="retriever", jev={})
    append_synthetic_routing(gc, ctx.question, pre)

    chunks = asyncio.run(core.extract_context(question=ctx.question))
    ctx.append("retriever", json.dumps(chunks, default=str))
    mark_agent_transition(core.retriever)

    if chunks.get("not_found"):
        from pipeline_exits import apply_exit_fields

        fields = apply_exit_fields("pipeline_semantic_not_found", question=ctx.question)
        msg = fields.get("llm_answer") or ""
        ctx.append("llm_answer_maker", msg)
        base = build_response(fields, ctx.transcript, analysis_type="Semantic-based")
        return finish(_attach_transcript(base, ctx), termination_reason="pipeline_semantic_not_found")

    prompt = json.dumps({"question": ctx.question, "context": chunks}, default=str)
    ans = agent_llm_turn(core.llm_answer_maker, prompt, sender=core.user_proxy)
    ctx.append("llm_answer_maker", ans)

    from API_unified import JEV_S13_CRITIC_ENABLED

    if JEV_S13_CRITIC_ENABLED:
        from gate_inputs import parse_vector_context
        from postchecks_async import PostcheckContext, dispatch_postchecks

        _chunks = parse_vector_context(json.dumps(chunks))
        dispatch_postchecks(
            PostcheckContext(
                question=ctx.question,
                route="semantic",
                trace_id=ctx.request_id,
                answer_text=ans,
                chunks=_chunks,
            )
        )

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
    trace_t0: float | None = None,
) -> dict:
    """Dispatch SQL / semantic pipeline after pre-chat S1+S4."""
    from jev_trace import begin_chat_phase, use_request_trace

    use_request_trace(request_id, t0=trace_t0)
    from request_state import sync_safety_for_request

    sync_safety_for_request(request_id)
    begin_chat_phase()
    ctx = RequestContext(request_id=request_id, question=question)
    ctx.analysis_type = _s4_label(route)

    import aurix_core as core
    from request_state import jev_route_next_agent

    dest = next_agent or jev_route_next_agent()
    if dest == "Eryl_agent" or ctx.analysis_type == "Semantic-based":
        return run_semantic_path(ctx, finish=finish)
    return run_sql_path(ctx, finish=finish)