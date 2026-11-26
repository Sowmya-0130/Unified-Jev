"""Unit tests for deterministic benchmark correctness (no LLM)."""
from __future__ import annotations

from eval.bench_correctness import check_correctness


def test_boots_total_visible_answer():
    out = {
        "DB_table": "[[secret rows]]",
        "final_answer": {"query_answer": "The total amount is 10798.8.", "llm_answer": ""},
    }
    validation = {
        "type": "sql_reference",
        "reference_sql": (
            "SELECT SUM(Total_Amount) AS metric FROM dupoint_email_data.Orders "
            "WHERE Product_Name = N'Chemical Resistant Boots'"
        ),
    }
    ok, msg = check_correctness(out, validation)
    assert ok, msg


def test_comma_number_equivalent():
    out = {
        "final_answer": {"query_answer": "Total 10,798.80 dollars", "llm_answer": ""},
    }
    validation = {
        "type": "sql_reference",
        "reference_sql": (
            "SELECT SUM(Total_Amount) AS metric FROM dupoint_email_data.Orders "
            "WHERE Product_Name = N'Chemical Resistant Boots'"
        ),
    }
    ok, msg = check_correctness(out, validation)
    assert ok, msg


def test_sql_reference_matches_number():
    out = {
        "query_answer": "The total is 10798.8 dollars.",
        "llm_answer": "",
        "final_answer": {"query_answer": "10798.8", "llm_answer": ""},
    }
    validation = {
        "type": "sql_reference",
        "reference_sql": "SELECT SUM(Total_Amount) AS metric FROM dupoint_email_data.Orders WHERE Product_Name = N'Chemical Resistant Boots'",
    }
    ok, msg = check_correctness(out, validation)
    assert ok, msg


def test_tool_output_number_wrong_final_fails():
    """DB/tool may hold the right number; only the user-visible answer counts."""
    out = {
        "DB_table": "10798.8",
        "query_answer": "",
        "llm_answer": "",
        "final_answer": {"query_answer": "99999", "llm_answer": ""},
    }
    validation = {
        "type": "sql_reference",
        "reference_sql": (
            "SELECT SUM(Total_Amount) AS metric FROM dupoint_email_data.Orders "
            "WHERE Product_Name = N'Chemical Resistant Boots'"
        ),
    }
    ok, msg = check_correctness(out, validation)
    assert not ok
    assert "not in reference" in msg


def test_missing_final_answer_fails():
    out = {"DB_table": "42 rows", "query_answer": "", "llm_answer": ""}
    validation = {"type": "sql_shape", "reference_sql": "SELECT 1", "min_rows": 1}
    ok, msg = check_correctness(out, validation)
    assert not ok
    assert msg == "no_final_answer"


def test_must_not_invent():
    out = {"llm_answer": "I do not have enough information to answer that.", "query_answer": ""}
    validation = {
        "type": "must_not_invent",
        "required_phrases": ["enough information", "not found"],
        "match_any": True,
    }
    ok, msg = check_correctness(out, validation)
    assert ok, msg