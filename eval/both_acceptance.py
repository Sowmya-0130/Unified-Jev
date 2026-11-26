"""Both-independent acceptance (3 questions × 3 runs = 9)."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

os.environ["LLM_RESPONSE_CACHE"] = "false"
os.environ.setdefault("ORCHESTRATOR", "pipeline")
os.environ["JEV_S3_CACHE_ENABLED"] = "false"

RUNS_PER = 3


def _both_questions() -> list[dict]:
    from metadata import fetch_dataframe_readonly

    def metric(sql: str) -> float:
        df = fetch_dataframe_readonly(" ".join(sql.split()))
        col = df.columns[-1]
        return float(df.iloc[0][col])

    gloves_total = metric(
        "SELECT SUM(Total_Amount) AS metric FROM [dupoint_email_data].[Orders] "
        "WHERE Product_Name = N'Kevlar Gloves'"
    )
    boots_total = metric(
        "SELECT SUM(Total_Amount) AS metric FROM [dupoint_email_data].[Orders] "
        "WHERE Product_Name = N'Chemical Resistant Boots'"
    )
    return [
        {
            "id": "both_gloves_total_returns",
            "question": (
                "What is the total Total_Amount for Kevlar Gloves in dupoint email data Orders, "
                "and what does the documentation say about returns for those products?"
            ),
            "reference_sql": (
                "SELECT SUM(Total_Amount) AS metric FROM [dupoint_email_data].[Orders] "
                "WHERE Product_Name = N'Kevlar Gloves'"
            ),
            "expect_numbers": [gloves_total],
            "doc_must_contain": ["30"],
        },
        {
            "id": "both_boots_total_warranty",
            "question": (
                "What is the total Total_Amount for Chemical Resistant Boots in dupoint email data Orders, "
                "and what does the company documentation say about warranty terms?"
            ),
            "reference_sql": (
                "SELECT SUM(Total_Amount) AS metric FROM [dupoint_email_data].[Orders] "
                "WHERE Product_Name = N'Chemical Resistant Boots'"
            ),
            "expect_numbers": [boots_total],
            "doc_must_contain": ["month", "day"],
        },
        {
            "id": "both_two_product_returns",
            "question": (
                "What is the combined Total_Amount for Chemical Resistant Boots and Kevlar Gloves "
                "in dupoint email data Orders, and what is the return policy for defective Kevlar gloves?"
            ),
            "reference_sql": (
                "SELECT SUM(Total_Amount) AS metric FROM [dupoint_email_data].[Orders] "
                "WHERE Product_Name IN (N'Chemical Resistant Boots', N'Kevlar Gloves')"
            ),
            "expect_numbers": [gloves_total + boots_total],
            "doc_must_contain": ["30"],
        },
    ]


def _nums(text: str) -> list[float]:
    return [float(x.replace(",", "")) for x in re.findall(r"-?\d+(?:\.\d+)?", text or "")]


def evaluate_both(resp: dict, spec: dict) -> dict:
    fail: list[str] = []
    if resp.get("analysis_type") != "Both-independent":
        fail.append("route:not_both")
    fa = resp.get("final_answer") or {}
    q_ans = (fa.get("query_answer") or resp.get("query_answer") or "").strip()
    l_ans = (fa.get("llm_answer") or resp.get("llm_answer") or "").strip()
    if not q_ans:
        fail.append("sql:empty_query_answer")
    if not l_ans:
        fail.append("semantic:empty_llm_answer")
    found = _nums(q_ans)
    ok_num = any(
        any(abs(exp - f) <= max(0.05 * abs(exp), 1.0) for f in found)
        for exp in spec["expect_numbers"]
    )
    if not ok_num:
        fail.append("a:sql_number")
    doc_blob = (l_ans + " " + q_ans).lower()
    for needle in spec.get("doc_must_contain") or []:
        if needle.lower() not in doc_blob:
            fail.append(f"doc:missing_{needle}")
    trace = resp.get("jev_trace") or {}
    lat = trace.get("latency") or {}
    sql_trace = resp.get("both_sql_trace") or {}
    exec_sql = ((sql_trace.get("jev_trace") or {}).get("latency") or {}).get("executed_sqls") or []
    if not exec_sql:
        fail.append("b:no_executed_sql")
    return {
        "pass": len(fail) == 0,
        "failures": fail,
        "correct": len(fail) == 0,
        "total_ms": lat.get("total_ms"),
        "query_answer_len": len(q_ans),
        "llm_answer_len": len(l_ans),
    }


def main() -> int:
    import aurix_core as core

    core.apply_llm_response_cache_setting()
    core.clear_answer_cache()
    out = _ROOT / ".loop" / "logs" / "accept-both-9.txt"
    if len(sys.argv) > 1:
        out = Path(sys.argv[1])
    rows = []
    for spec in _both_questions():
        for run in range(RUNS_PER):
            try:
                resp = core.get_final_answer(spec["question"])
            except Exception as exc:  # noqa: BLE001
                resp = {"error": str(exc)}
            ev = (
                {"pass": False, "failures": ["error"], "error": resp.get("error")}
                if resp.get("error")
                else evaluate_both(resp, spec)
            )
            rows.append({"id": spec["id"], "run": run + 1, **ev})
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                json.dumps(
                    {
                        "passed": sum(1 for r in rows if r.get("pass")),
                        "total": len(rows),
                        "rows": rows,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"  {spec['id']}#{run+1} pass={ev.get('pass')} fail={ev.get('failures')}")
    passed = sum(1 for r in rows if r.get("pass"))
    print(f"SUMMARY {passed}/{len(rows)}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    from eval.process_guard import assert_solo_aurix_runtime

    assert_solo_aurix_runtime(role="both_acceptance")
    raise SystemExit(main())