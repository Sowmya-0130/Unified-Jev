"""Live SQL path acceptance (11 questions × 3 runs = 33)."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]  # repo root
sys.path.insert(0, str(_ROOT))

os.environ["LLM_RESPONSE_CACHE"] = "false"
os.environ["JEV_S3_CACHE_ENABLED"] = "false"
os.environ.setdefault("ORCHESTRATOR", "pipeline")

RUNS_PER = 3
_RE_BAD_SQL = re.compile(
    r"\bdbo\.[A-Za-z_]+\.[A-Za-z_]+\b|\[[^\]]+\]\.\[[^\]]+\]\.\[",
    re.IGNORECASE,
)
_RE_LOWERCASE_ORDERS = re.compile(r"\[dupoint_email_data\]\.\[orders\]", re.IGNORECASE)


def _accept_questions() -> list[dict[str, Any]]:
    from metadata import fetch_dataframe_readonly

    def metric(sql: str) -> float | None:
        df = fetch_dataframe_readonly(" ".join(sql.split()))
        if df.empty:
            return None
        col = df.columns[-1]
        val = df.iloc[0][col]
        if val is None:
            return None
        return float(val)

    return [
        {
            "id": "boots_total",
            "reference_sql": (
                "SELECT SUM(Total_Amount) AS metric FROM [dupoint_email_data].[Orders] "
                "WHERE Product_Name = N'Chemical Resistant Boots'"
            ),
            "question": "In dupoint email data orders, what is the total Total_Amount for Chemical Resistant Boots?",
            "expect_numbers": [10798.8],
            "require_dupoint_orders_case": True,
            "expected_route": "SQL-based",
        },
        {
            "id": "two_products",
            "reference_sql": (
                "SELECT SUM(Total_Amount) AS metric FROM [dupoint_email_data].[Orders] "
                "WHERE Product_Name IN (N'Chemical Resistant Boots', N'Kevlar Gloves')"
            ),
            "question": (
                "What is the combined Total_Amount in dupoint email data Orders for "
                "Chemical Resistant Boots and Kevlar Gloves?"
            ),
            "expect_numbers": [17203.8],
            "require_dupoint_orders_case": True,
            "expected_route": "SQL-based",
        },
        {
            "id": "order_count",
            "reference_sql": "SELECT COUNT(*) AS metric FROM [dupoint_email_data].[Orders]",
            "question": "How many rows are in dupoint email data Orders?",
            "expect_numbers": [20.0],
            "require_dupoint_orders_case": True,
            "expected_route": "SQL-based",
        },
        {
            "id": "top5_products",
            "reference_sql": (
                "SELECT TOP 5 Product_Name, SUM(Total_Amount) AS metric "
                "FROM [dupoint_email_data].[Orders] GROUP BY Product_Name ORDER BY metric DESC"
            ),
            "question": "List the top 5 product names by total amount in dupoint email data Orders.",
            "shape_only": True,
            "require_dupoint_orders_case": True,
            "expected_route": "SQL-based",
        },
        {
            "id": "top5_customers",
            "reference_sql": (
                "SELECT TOP 5 c.customer_id, SUM(o.total_amount) AS metric "
                "FROM dbo.orders o INNER JOIN dbo.customers c ON o.customer_id = c.customer_id "
                "GROUP BY c.customer_id ORDER BY metric DESC"
            ),
            "question": (
                "Who are the top 5 customers by total order amount? "
                "Use the orders and customers tables."
            ),
            "expect_numbers": [5680.12],
            "shape_only": True,
            "expected_route": "SQL-based",
        },
        {
            "id": "revenue_product_1",
            "reference_sql": (
                "SELECT SUM(oi.quantity * oi.price) AS metric FROM dbo.order_items oi WHERE oi.product_id = 1"
            ),
            "question": (
                "What is the total revenue from order items for product id 1? "
                "Revenue is quantity times price from order_items joined to products."
            ),
            "expect_numbers": [metric(
                "SELECT SUM(oi.quantity * oi.price) AS metric FROM dbo.order_items oi WHERE oi.product_id = 1"
            ) or 31999.68],
            "expected_route": "SQL-based",
        },
        {
            "id": "avg_rel_exp_male",
            "reference_sql": (
                "SELECT AVG(CAST([Total Rel Exp] AS float)) AS metric "
                "FROM Dummy_data_testing WHERE Gender = 'Male'"
            ),
            "question": "What is the average Total Rel Exp for Male records in Dummy_data_testing?",
            "expect_numbers": [metric(
                "SELECT AVG(CAST([Total Rel Exp] AS float)) AS metric FROM Dummy_data_testing WHERE Gender = 'Male'"
            ) or 7.2],
            "expected_route": "SQL-based",
        },
        {
            "id": "clients_europe",
            "reference_sql": (
                "SELECT COUNT(*) AS metric FROM GCC_Hackathon_clients WHERE region = 'Europe'"
            ),
            "question": "How many clients are in the Europe region in GCC_Hackathon_clients?",
            "expect_numbers": [3.0],
            "expected_route": "SQL-based",
        },
        {
            "id": "fine_late_rent",
            "reference_sql": (
                "SELECT SUM(fine_amount) AS metric FROM [dbo].[AMH_Data] "
                "WHERE document_type = N'Late Rent Payment Notice'"
            ),
            "question": "What is the total fine_amount for Late Rent Payment Notice in AMH_Data?",
            "expect_numbers": [1882.5],
            "expected_route": "SQL-based",
        },
        {
            "id": "avg_composite_both",
            "reference_sql": (
                "SELECT AVG(CAST(composite_score AS float)) AS metric "
                "FROM Unified_Eval_Data WHERE analysis_type = 'Both'"
            ),
            "question": (
                "What is the average composite_score in Unified_Eval_Data where analysis_type is Both?"
            ),
            "expect_numbers": [metric(
                "SELECT AVG(CAST(composite_score AS float)) AS metric FROM Unified_Eval_Data WHERE analysis_type = 'Both'"
            ) or 0.92435],
            "expected_route": "SQL-based",
        },
        {
            "id": "empty_boots_2mo",
            "reference_sql": (
                "SELECT SUM(Total_Amount) AS metric FROM [dupoint_email_data].[Orders] "
                "WHERE Product_Name IN (N'Chemical Resistant Boots', N'Kevlar Gloves') "
                "AND Order_Date >= DATEADD(month, -2, GETDATE())"
            ),
            "question": (
                "What is the total Total_Amount for Chemical Resistant Boots and Kevlar Gloves "
                "orders in dupoint email data Orders in the last 2 months?"
            ),
            "expect_empty": True,
            "require_dupoint_orders_case": True,
            "expected_route": "SQL-based",
        },
    ]


def _nums(text: str) -> set[float]:
    out: set[float] = set()
    for m in re.finditer(r"-?\d+(?:\.\d+)?", text or ""):
        try:
            out.add(float(m.group(0)))
        except ValueError:
            pass
    return out


def _answer_text(resp: dict) -> str:
    fa = resp.get("final_answer") or {}
    return " ".join(
        str(x)
        for x in (
            fa.get("query_answer"),
            fa.get("llm_answer"),
            resp.get("query_answer"),
            resp.get("llm_answer"),
        )
        if x
    )


def _agents_from_trace(trace: dict) -> list[str]:
    lat = trace.get("latency") or {}
    return [s.get("name") for s in (lat.get("timeline") or []) if s.get("kind") == "agent_turn"]


def _executed_sqls(resp: dict, trace: dict) -> list[str]:
    lat = trace.get("latency") or {}
    return list(lat.get("executed_sqls") or [])


def _diagnose_llm_turns(agents: list[str], lat: dict) -> str:
    counts: dict[str, int] = {}
    for name in agents:
        counts[name] = counts.get(name, 0) + 1
    parts: list[str] = []
    if counts.get("routing_agent", 0) > 0:
        parts.append("routing_agent(S4_unsure)")
    sg = counts.get("Sql_Generator", 0)
    if sg and sg > 1:
        parts.append(f"Sql_Generator_repair×{sg}")
    if counts.get("Sql_Execution_Critic", 0):
        parts.append("Sql_Execution_Critic")
    if counts.get("Evaluation_Agent", 0):
        parts.append("Evaluation_Agent")
    if counts.get("user_proxy", 0) > 1:
        parts.append("user_proxy_extra")
    if not parts:
        parts.append("baseline_4_turns")
    gates = lat.get("gate_decisions") or []
    for g in gates:
        if g.get("gate") == "S4" and g.get("action") == "run_llm":
            parts.append("S4_run_llm")
            break
    return " + ".join(parts)


def evaluate_one(resp: dict, spec: dict) -> dict:
    trace = resp.get("jev_trace") or {}
    lat = trace.get("latency") or {}
    timeline = lat.get("timeline") or []
    tokens_by = lat.get("llm_tokens_by_agent") or {}
    sg = tokens_by.get("Sql_Generator") or {}
    rt = tokens_by.get("routing_agent") or {}
    agents = _agents_from_trace(trace)

    ans = _answer_text(resp)
    fail: list[str] = []

    if spec.get("expect_empty"):
        from empty_answer_eval import empty_answer_acceptable

        ok_correct = empty_answer_acceptable(ans, spec.get("question") or "")
        insight_path = lat.get("insight_path")
        if ok_correct and insight_path != "template":
            ok_correct = False
            fail.append("a:insight_not_template")
    elif spec.get("shape_only"):
        ok_correct = len(ans.strip()) > 20
        if spec.get("expect_numbers"):
            found = _nums(ans)
            ok_correct = ok_correct and any(
                any(abs(exp - f) <= max(0.05 * abs(exp), 1.0) for f in found)
                for exp in spec["expect_numbers"]
            )
    else:
        found = _nums(ans)
        ok_correct = any(
            any(abs(exp - f) <= max(0.05 * abs(exp), 1.0) for f in found)
            for exp in spec["expect_numbers"]
        )
    if not ok_correct:
        fail.append("a:correct")

    sqls = _executed_sqls(resp, trace)
    bad = [s for s in sqls if _RE_BAD_SQL.search(s)]
    if bad:
        fail.append("b:multipart_sql")
    if not sqls:
        fail.append("b:no_executed_sql")

    if spec.get("require_dupoint_orders_case"):
        for s in sqls:
            if _RE_LOWERCASE_ORDERS.search(s) and "[Orders]" not in s:
                fail.append("g:orders_casing")

    if "Query_Executor" in agents:
        fail.append("e:query_executor_ran")

    from API_unified import (
        ROUTING_LLM_FALLBACK,
        SAFETY_LLM_MODE,
        SEMANTIC_QUERY_TRANSFORMER_LLM,
        SQL_S7_LLM_FALLBACK,
    )
    from flow_conformance import check_trace

    flow_v = check_trace(
        trace,
        safety_llm_mode=SAFETY_LLM_MODE,
        routing_llm_fallback=ROUTING_LLM_FALLBACK,
        sql_s7_llm_fallback=SQL_S7_LLM_FALLBACK,
        semantic_query_transformer=SEMANTIC_QUERY_TRANSFORMER_LLM,
    )
    if flow_v:
        fail.append(f"f:flow:{flow_v[0]}")

    llm_turns = int(lat.get("llm_turn_count") or 99)
    llm_turns_diag = _diagnose_llm_turns(agents, lat)
    llm_over_4 = llm_turns > 4

    sql_att = int(lat.get("sql_attempts") or 0)
    if sqls and sql_att < 1:
        fail.append("c:sql_attempts_zero")
    if sql_att > 2:
        fail.append("c:sql_attempts")

    perm_retries = max(
        (int(s.get("retry_count") or 0) for s in timeline if s.get("name") == "db_execute_query"),
        default=0,
    )
    if perm_retries > 1:
        fail.append("c:permanent_retries")

    sg_pt = int(sg.get("prompt_tokens") or 0)

    gate_failures = [f for f in fail if f.split(":")[0] in ("a", "b", "c", "e", "f", "g")]

    return {
        "correct": ok_correct,
        "failures": gate_failures,
        "pass": len(gate_failures) == 0,
        "insight_path": lat.get("insight_path"),
        "match_row_count": lat.get("match_row_count"),
        "total_ms": lat.get("total_ms"),
        "sql_attempts": sql_att,
        "perm_retries": perm_retries,
        "llm_turns": llm_turns,
        "llm_turns_over_4": llm_over_4,
        "llm_turns_diag": llm_turns_diag,
        "sg_prompt_tokens": sg_pt,
        "route_prompt_tokens": int(rt.get("prompt_tokens") or 0),
        "executed_sqls": sqls,
    }


def _save(out_path: Path, rows: list[dict]) -> None:
    summary = {"passed": sum(1 for r in rows if r.get("pass")), "total": len(rows), "rows": rows}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main() -> int:
    import aurix_core as core

    core.apply_llm_response_cache_setting()
    core.clear_answer_cache()
    questions = _accept_questions()

    raw_argv = list(sys.argv[1:])
    shuffle_order = "--shuffle" in raw_argv
    raw_argv = [a for a in raw_argv if a != "--shuffle"]
    out_path = Path(raw_argv[0]) if raw_argv else _ROOT / ".loop" / "logs" / "accept-guardrails.txt"
    only_ids = [a for a in raw_argv[1:] if not a.startswith("-")]
    question_list = [q for q in questions if not only_ids or q["id"] in only_ids]
    if shuffle_order and not only_ids:
        import random

        random.shuffle(question_list)
        print("question_order_shuffled", [q["id"] for q in question_list], flush=True)
    from eval.accept_watchdog import AcceptWatchdog, run_acceptance_question

    rows: list[dict] = []
    wd = AcceptWatchdog()
    print(f"sql_acceptance ({len(question_list)}×{RUNS_PER}) -> {out_path}", flush=True)

    aborted = False
    for spec in question_list:
        if aborted or wd.suite_expired():
            if not aborted:
                wd.write_abort(out_path, reason="suite_timeout", rows=rows)
                print("ABORT suite_timeout", flush=True)
            break
        for run in range(RUNS_PER):
            if aborted or wd.suite_expired():
                if not aborted:
                    wd.write_abort(out_path, reason="suite_timeout", rows=rows)
                    print("ABORT suite_timeout", flush=True)
                aborted = True
                break

            try:
                resp, terr = run_acceptance_question(
                    spec["question"],
                    wd._limits["question_timeout_s"],  # noqa: SLF001
                )
                if terr:
                    resp = {"error": terr, "jev_trace": {}}
                elif resp is None:
                    resp = {"error": "empty_response", "jev_trace": {}}
            except Exception as exc:  # noqa: BLE001
                resp = {"error": str(exc), "jev_trace": {}}
            ev = (
                {"pass": False, "failures": ["error"], "error": resp.get("error")}
                if resp.get("error")
                else evaluate_one(resp, spec)
            )
            rows.append({"id": spec["id"], "run": run + 1, **ev})
            wd.record_row(bool(ev.get("pass")))
            failed = sum(1 for r in rows if not r.get("pass"))
            abort, reason = wd.should_abort(total_rows=len(rows), failed_rows=failed)
            if abort:
                wd.write_abort(out_path, reason=reason or "abort", rows=rows)
                print(f"ABORT {reason}", flush=True)
                _save(out_path, rows)
                print(f"SUMMARY {sum(1 for r in rows if r.get('pass'))}/{len(rows)}")
                aborted = True
                break
            _save(out_path, rows)
            dnote = ""
            if ev.get("llm_turns_over_4"):
                dnote = f" d>{ev.get('llm_turns')}: {ev.get('llm_turns_diag')}"
            print(
                f"  {spec['id']}#{run+1} pass={ev.get('pass')} fail={ev.get('failures')}{dnote}",
                flush=True,
            )
        if aborted:
            break

    diag_path = out_path.parent / "llm-turns-diag.txt"
    with diag_path.open("w", encoding="utf-8") as dfp:
        for r in rows:
            if r.get("llm_turns_over_4"):
                dfp.write(
                    f"{r.get('id')}#{r.get('run')} turns={r.get('llm_turns')} {r.get('llm_turns_diag')}\n"
                )

    passed = sum(1 for r in rows if r.get("pass"))
    _save(out_path, rows)
    print(f"SUMMARY {passed}/{len(rows)}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    from eval.process_guard import assert_solo_aurix_runtime

    assert_solo_aurix_runtime(role="sql_acceptance")
    raise SystemExit(main())