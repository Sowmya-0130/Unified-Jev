"""Both-independent answers: SQL + document paths (sequential; merged response)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from dual_route import split_both_question


def _sql_part(question: str, *, parent_request_id: str) -> dict:
    import aurix_core as core

    from question_sql_normalize import normalize_question_for_sql

    sql_q, _ = split_both_question(question)
    sql_q = normalize_question_for_sql(sql_q)
    return core._get_final_answer_impl(
        sql_q,
        both_nested=True,
        both_leg="sql",
        safety_parent_request_id=parent_request_id,
    )


def _semantic_part(question: str, *, parent_request_id: str) -> dict:
    import aurix_core as core

    _, doc_q = split_both_question(question)
    sem_q = doc_q if doc_q != question else question
    return core._get_final_answer_impl(
        sem_q,
        both_nested=True,
        both_leg="semantic",
        safety_parent_request_id=parent_request_id,
    )


def _extract_sql_metric(sql_resp: dict) -> str:
    sql_fa = sql_resp.get("final_answer") or {}
    return (sql_fa.get("query_answer") or sql_resp.get("query_answer") or "").strip()


def _extract_document_answer(sem_resp: dict) -> str:
    """Prefer llm_answer; fall back when semantic leg mis-routed through SQL template."""
    import re

    sem_fa = sem_resp.get("final_answer") or {}
    for key in ("llm_answer", "Inference", "Reasoning"):
        text = (sem_fa.get(key) or sem_resp.get(key) or "").strip()
        if not text:
            continue
        if key == "Reasoning" and text.lower().startswith("both-independent"):
            continue
        if len(text) >= 8:
            return text
    qa = (sem_fa.get("query_answer") or sem_resp.get("query_answer") or "").strip()
    if qa and not re.fullmatch(r"[\d.,\s]+", qa):
        return qa
    return (sem_fa.get("llm_answer") or sem_resp.get("llm_answer") or "").strip()


def _note_conflicting_doc_windows(text: str) -> str:
    """Flag when corpus has multiple reporting windows (no threshold change)."""
    t = (text or "").strip()
    if not t:
        return t
    low = t.lower()
    if ("7 days" in low or "7 day" in low) and ("48 hour" in low):
        note = (
            "\n\n---\n"
            "*Policy note: Source docs mention more than one reporting window "
            "(e.g. 7 days vs 48 hours). Use the term that matches your contract "
            "or product line.*"
        )
        if note not in t:
            t = t + note
    return t


def merge_both_responses(question: str, sql_resp: dict, sem_resp: dict) -> dict:
    q_ans = _extract_sql_metric(sql_resp)
    l_ans = _note_conflicting_doc_windows(_extract_document_answer(sem_resp))
    from API_unified import MERGE_NODE_ENABLED
    from merge_node import DbOutput, DocsOutput, synthesize

    trace_id = None
    try:
        from jev_trace import snapshot

        trace_id = str(snapshot().get("request_id") or "")
    except Exception:  # noqa: BLE001
        pass

    if MERGE_NODE_ENABLED:
        mr = synthesize(
            question,
            DbOutput(text=q_ans, sql=sql_resp.get("query"), metadata={}),
            DocsOutput(text=l_ans, passages=[]),
            trace_id=trace_id,
        )
        q_ans = mr.query_answer or q_ans
        l_ans = mr.final_text if mr.merge_strategy == "llm_synthesis" else l_ans
        if mr.merge_strategy == "llm_synthesis":
            sections = [
                {
                    "kind": "merged",
                    "title": "Answer",
                    "body": mr.final_text,
                }
            ]
            reasoning = f"Both-independent: merge_node ({mr.merge_strategy})"
        else:
            sections = []
            if q_ans:
                sections.append({"kind": "sql", "title": "Database answer", "body": q_ans})
            if l_ans:
                sections.append({"kind": "doc", "title": "Documentation & policy", "body": l_ans})
            reasoning = f"Both-independent: merge_node ({mr.merge_strategy})"
        merged_extra = {
            "merge_strategy": mr.merge_strategy,
            "merge_grounded": mr.grounded,
            "merge_confidence": mr.confidence,
        }
    else:
        sections = []
        if q_ans:
            sections.append({"kind": "sql", "title": "Database answer", "body": q_ans})
        if l_ans:
            sections.append({"kind": "doc", "title": "Documentation & policy", "body": l_ans})
        reasoning = "Both-independent: SQL aggregate + document retrieval"
        merged_extra = {}

    llm_out = l_ans
    if merged_extra.get("merge_strategy") == "llm_synthesis":
        llm_out = sections[0]["body"] if sections and sections[0].get("kind") == "merged" else l_ans

    merged = {
        "initial_question": question,
        "analysis_type": "Both-independent",
        "query_answer": q_ans,
        "llm_answer": llm_out,
        "final_answer": {"query_answer": q_ans, "llm_answer": llm_out},
        "both_sections": sections,
        "Reasoning": reasoning,
        "both_sql_trace": sql_resp.get("jev_trace"),
        "both_semantic_trace": sem_resp.get("jev_trace"),
        **merged_extra,
    }
    for key in ("query", "database_name", "executed_sqls"):
        if sql_resp.get(key) is not None:
            merged[key] = sql_resp.get(key)
    lat_sql = (sql_resp.get("jev_trace") or {}).get("latency") or {}
    lat_sem = (sem_resp.get("jev_trace") or {}).get("latency") or {}
    merged["jev_trace"] = {
        "latency": {
            "total_ms": (lat_sql.get("total_ms") or 0) + (lat_sem.get("total_ms") or 0),
            "both_parallel": False,
            "sql_total_ms": lat_sql.get("total_ms"),
            "semantic_total_ms": lat_sem.get("total_ms"),
        },
        "analysis_type": "Both-independent",
    }
    return merged


def both_independent_answer(
    question: str,
    *,
    parallel: bool = True,
    parent_request_id: str | None = None,
) -> dict:
    """Run SQL and semantic pipelines; default parallel with isolated get_final_answer calls."""
    import os

    if parent_request_id is None:
        from jev_trace import snapshot

        parent_request_id = str(snapshot().get("request_id") or "")

    try:
        from jev_trace import trace_stdout

        trace_stdout(
            f"Both-independent: sql+semantic legs (parallel={parallel})"
        )
    except Exception:  # noqa: BLE001
        pass

    if os.environ.get("AURIX_BOTH_STUB") == "1":
        return merge_both_responses(
            question,
            {
                "final_answer": {"query_answer": "stub-sql", "llm_answer": "stub"},
                "jev_trace": {"latency": {"total_ms": 1}},
            },
            {
                "final_answer": {"query_answer": "", "llm_answer": "stub-doc"},
                "jev_trace": {"latency": {"total_ms": 1}},
            },
        )
    if not parallel:
        sql_resp = _sql_part(question, parent_request_id=parent_request_id)
        sem_resp = _semantic_part(question, parent_request_id=parent_request_id)
        return merge_both_responses(question, sql_resp, sem_resp)

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_sql = pool.submit(_sql_part, question, parent_request_id=parent_request_id)
        fut_sem = pool.submit(_semantic_part, question, parent_request_id=parent_request_id)
        sql_resp = fut_sql.result()
        sem_resp = fut_sem.result()
    out = merge_both_responses(question, sql_resp, sem_resp)
    out["jev_trace"]["latency"]["both_parallel"] = True
    return out