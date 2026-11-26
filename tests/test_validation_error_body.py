from __future__ import annotations

from sql_execute_step import validation_error_body


def test_validation_error_body_union_includes_pipeline_flag_with_question():
    q = (
        "What is the total Total_Amount for Chemical Resistant Boots and Kevlar Gloves "
        "orders in dupoint email data Orders in the last 2 months?"
    )
    sql = (
        "SELECT 1 FROM [dupoint_email_data].[Orders] WHERE Product_Name IN ('A') "
        "UNION ALL SELECT 2"
    )
    body = validation_error_body(sql, question=q)
    assert "sql_pipeline_error" in body
    assert "unrequested_union" in body or "UNION" in body