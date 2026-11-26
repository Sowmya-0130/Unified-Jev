"""Both-independent answers: SQL + document paths (sequential; merged response)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from dual_route import split_both_question


def _sql_part(question: str) -> dict:
    import aurix_core as core

    sql_q, _ = split_both_question(question)
    # Nested under an in-flight request: skip duplicate pre-chat / groupchat setup.
    return core._get_final_answer_impl(sql_q)


def _semantic_part(question: str) -> dict:
    import aurix_core as core

    _, doc_q = split_both_question(question)
    sem_q = doc_q if doc_q != question else question
    return core._get_final_answer_impl(sem_q)


def merge_both_responses(question: str, sql_resp: dict, sem_resp: dict) -> dict:
    sql_fa = sql_resp.get("final_answer") or {}
    sem_fa = sem_resp.get("final_answer") or {}
    q_ans = (sql_fa.get("query_answer") or sql_resp.get("query_answer") or "").strip()
    l_ans = (sem_fa.get("llm_answer") or sem_resp.get("llm_answer") or "").strip()
    merged = {
        "initial_question": question,
        "analysis_type": "Both-independent",
        "query_answer": q_ans,
        "llm_answer": l_ans,
        "final_answer": {"query_answer": q_ans, "llm_answer": l_ans},
        "Reasoning": "Both-independent: SQL aggregate + document retrieval",
        "both_sql_trace": sql_resp.get("jev_trace"),
        "both_semantic_trace": sem_resp.get("jev_trace"),
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


def both_independent_answer(question: str, *, parallel: bool = True) -> dict:
    """Run SQL and semantic pipelines; default parallel with isolated get_final_answer calls."""
    import os

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
        sql_resp = _sql_part(question)
        sem_resp = _semantic_part(question)
        return merge_both_responses(question, sql_resp, sem_resp)

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_sql = pool.submit(_sql_part, question)
        fut_sem = pool.submit(_semantic_part, question)
        sql_resp = fut_sql.result()
        sem_resp = fut_sem.result()
    out = merge_both_responses(question, sql_resp, sem_resp)
    out["jev_trace"]["latency"]["both_parallel"] = True
    return out