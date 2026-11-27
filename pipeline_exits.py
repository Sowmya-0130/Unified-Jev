"""A5: centralized pipeline exit reasons → user-visible copy (no trace jargon)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

MessageFn = Callable[[str, dict[str, Any]], str]


@dataclass(frozen=True)
class ExitSpec:
    reason: str
    user_message: str | MessageFn
    reasoning_internal: str
    shows_in_ui: bool
    answer_field: str  # "query_answer" | "llm_answer"
    http_ok: bool = True


def _clarity_message(question: str, ctx: dict[str, Any]) -> str:
    hints: list[str] = []
    ql = (question or "").lower()
    if len((question or "").split()) < 6:
        hints.append("a bit more detail about what you want to measure or look up")
    if not re.search(r"\b20\d{2}\b", ql) and not re.search(r"\blast\s+\d+\s+month", ql):
        hints.append("a time range (for example a year or “last N months”)")
    if not re.search(r"\b(total|count|average|how many|what is)\b", ql):
        hints.append("whether you need a total, a count, or descriptive information")
    hint = ", ".join(hints) if hints else "more specific product, metric, or time range"
    return (
        "Your question needs a little more detail before I can answer reliably. "
        f"Please add {hint}, then try again."
    )


def _timeout_message(_question: str, ctx: dict[str, Any]) -> str:
    return (
        "This request took too long to complete. "
        "Try a shorter or more specific question and run it again."
    )


def _timeout_operator(_question: str, ctx: dict[str, Any]) -> str:
    sec = ctx.get("timeout_s")
    if sec is not None:
        return f"REQUEST_TIMEOUT_S={sec}s — check DB retry loop, LLM latency, or JEV queue."
    return "REQUEST_TIMEOUT exceeded — check DB retry loop, LLM latency, or JEV queue."


def _sql_fail_message(question: str, ctx: dict[str, Any]) -> str:
    from sql_tool_outcome import user_message_for_failed_pipeline

    return user_message_for_failed_pipeline(
        question=question,
        last_sql_out=str(ctx.get("last_sql_out") or ""),
    )


EXIT_REGISTRY: dict[str, ExitSpec] = {
    "pipeline_sql_exit": ExitSpec(
        "pipeline_sql_exit",
        _sql_fail_message,
        "pipeline_sql_exit",
        True,
        "query_answer",
    ),
    "safety_gate_sql_blocked": ExitSpec(
        "safety_gate_sql_blocked",
        _sql_fail_message,
        "safety_gate_sql_blocked",
        True,
        "query_answer",
    ),
    "pipeline_sql_no_rows": ExitSpec(
        "pipeline_sql_no_rows",
        "The query ran successfully but found no matching rows for this question.",
        "pipeline_sql_no_rows",
        True,
        "query_answer",
    ),
    "pipeline_sql_honest_template": ExitSpec(
        "pipeline_sql_honest_template",
        "No database answer could be produced for this question after validation.",
        "pipeline_sql_honest_template",
        True,
        "query_answer",
    ),
    "pipeline_semantic_not_found": ExitSpec(
        "pipeline_semantic_not_found",
        "I could not find enough information in the documents to answer that question.",
        "pipeline_semantic_not_found",
        True,
        "llm_answer",
    ),
    "request_timeout": ExitSpec(
        "request_timeout",
        _timeout_message,
        "request_timeout",
        True,
        "llm_answer",
    ),
    "jev_s2_clarity_block": ExitSpec(
        "jev_s2_clarity_block",
        _clarity_message,
        "jev_s2_clarity_block",
        True,
        "llm_answer",
    ),
    "safety_blocked": ExitSpec(
        "safety_blocked",
        "This question could not be answered because the safety check did not allow it. Try rephrasing.",
        "safety_blocked",
        True,
        "llm_answer",
    ),
    "safety_jev_unavailable": ExitSpec(
        "safety_jev_unavailable",
        "Safety checks are temporarily unavailable. Please retry in a moment or rephrase your question.",
        "safety_jev_unavailable",
        True,
        "llm_answer",
    ),
    "azure_openai_probe_failed": ExitSpec(
        "azure_openai_probe_failed",
        "",
        "azure_openai_probe_failed",
        False,
        "llm_answer",
    ),
    "initiate_chat_exception": ExitSpec(
        "initiate_chat_exception",
        "",
        "initiate_chat_exception",
        False,
        "llm_answer",
    ),
    "sql_validation_recovery_empty": ExitSpec(
        "sql_validation_recovery_empty",
        "",
        "sql_validation_recovery_empty",
        False,
        "query_answer",
    ),
    "pipeline_sql_template": ExitSpec(
        "pipeline_sql_template",
        "",
        "pipeline_sql_template",
        False,
        "query_answer",
    ),
    "pipeline_sql_completed": ExitSpec(
        "pipeline_sql_completed",
        "",
        "pipeline_sql_completed",
        False,
        "query_answer",
    ),
    "pipeline_semantic_completed": ExitSpec(
        "pipeline_semantic_completed",
        "",
        "pipeline_semantic_completed",
        False,
        "llm_answer",
    ),
    "both_independent": ExitSpec(
        "both_independent",
        "",
        "both_independent",
        False,
        "query_answer",
    ),
    "sql_max_repair_rounds": ExitSpec(
        "sql_max_repair_rounds",
        _sql_fail_message,
        "sql_max_repair_rounds",
        True,
        "query_answer",
    ),
}


def all_exit_reasons() -> frozenset[str]:
    return frozenset(EXIT_REGISTRY.keys())


def shows_in_ui(reason: str) -> bool:
    spec = EXIT_REGISTRY.get(reason)
    return bool(spec and spec.shows_in_ui)


def is_user_facing_exit(final_output: dict) -> bool:
    r = str(final_output.get("Reasoning") or "").strip()
    if shows_in_ui(r):
        return True
    return r in {
        "pipeline_sql_exit",
        "safety_gate_sql_blocked",
        "request_timeout",
        "jev_s2_clarity_block",
        "pipeline_semantic_not_found",
        "pipeline_sql_honest_template",
        "pipeline_sql_no_rows",
    }


def operator_detail(reason: str, *, question: str = "", context: dict[str, Any] | None = None) -> str:
    ctx = dict(context or {})
    if reason == "request_timeout":
        return _timeout_operator(question, ctx)
    if reason == "azure_openai_probe_failed":
        return f"Azure OpenAI probe failed | question={(question or '')[:120]!r}"
    if reason == "initiate_chat_exception":
        err = str(ctx.get("error") or "")
        return f"initiate_chat_exception | {err[:200]}"
    if reason in ("pipeline_sql_exit", "safety_gate_sql_blocked", "sql_max_repair_rounds"):
        from sql_tool_outcome import pipeline_failure_detail

        return pipeline_failure_detail(
            question=question,
            last_sql_out=str(ctx.get("last_sql_out") or ""),
        )
    return f"{reason} | question={(question or '')[:240]!r}"


def resolve_exit(
    reason: str,
    *,
    question: str = "",
    context: dict[str, Any] | None = None,
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build response fields for Streamlit / API (merge into orchestrator response)."""
    ctx = dict(context or {})
    spec = EXIT_REGISTRY.get(reason)
    out = dict(base or {})
    if spec is None:
        out.setdefault("Reasoning", reason or "pipeline_exit")
        return out

    msg = spec.user_message(question, ctx) if callable(spec.user_message) else spec.user_message
    out["Reasoning"] = spec.reasoning_internal

    if msg and spec.shows_in_ui:
        if spec.answer_field == "query_answer":
            out["query_answer"] = msg
            out.setdefault("llm_answer", "")
        else:
            out["llm_answer"] = msg
            out.setdefault("query_answer", "")

    fa = dict(out.get("final_answer") or {})
    fa.setdefault("query_answer", out.get("query_answer", ""))
    fa.setdefault("llm_answer", out.get("llm_answer", ""))
    out["final_answer"] = fa
    return out


def apply_exit_fields(
    reason: str,
    *,
    question: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Subset for build_response() first argument."""
    return resolve_exit(reason, question=question, context=context)


def trace_exit(reason: str, *, question: str = "", context: dict[str, Any] | None = None) -> None:
    try:
        from jev_trace import trace_stdout

        trace_stdout(f"exit:{reason} | {operator_detail(reason, question=question, context=context)}")
    except Exception:  # noqa: BLE001
        pass