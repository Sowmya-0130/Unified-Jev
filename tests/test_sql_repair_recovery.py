from __future__ import annotations

import json
from unittest.mock import patch

import aurix_core as core
from sql_repair_recovery import try_time_window_zero_from_generator_sql


class _GC:
    def __init__(self, messages):
        self.messages = messages


def test_validation_repair_counts_attempts_on_pipeline_error():
    core._reset_sql_loop_guard()
    from jev_trace import reset as trace_reset, take_sql_attempts

    trace_reset()
    bad_sql = (
        "SELECT Product_Name, SUM(Total_Amount) AS s FROM [dupoint_email_data].[Orders] "
        "WHERE Order_Date >= DATEADD(month, -2, GETDATE()) GROUP BY Product_Name"
    )
    gc = _GC(
        [
            {"role": "user", "content": '"question": empty time window test?'},
            {
                "name": "Sql_Generator",
                "role": "assistant",
                "content": json.dumps({"sql_query": bad_sql}),
            },
            {
                "name": "Sql_tool",
                "role": "assistant",
                "content": '{"sql_pipeline_error": true, "class": "unrequested_groupby", "message": "no"}',
            },
        ]
    )
    from request_state import bump_validation_repair, take_validation_repairs

    bump_validation_repair()
    with patch.object(core, "SQL_MAX_REPAIR_ROUNDS", 1):
        with patch(
            "sql_repair_recovery.try_time_window_zero_from_generator_sql",
            return_value=None,
        ):
            nxt = core.state_transition(core.Sql_tool, gc)
    assert take_validation_repairs() >= 1
    assert nxt is core.Insight_Generator


def test_time_window_zero_patches_calendar_year_before_count(monkeypatch):
    from jev_trace import reset as trace_reset, set_request_question

    trace_reset()
    q = "total Total_Amount Kevlar dupoint Orders in 2025"
    set_request_question(q)
    sql = (
        "SELECT SUM(Total_Amount) FROM [dupoint_email_data].[Orders] "
        "WHERE Product_Name LIKE '%Kevlar%'"
    )
    gc = _GC([{"name": "Sql_Generator", "content": json.dumps({"sql_query": sql})}])
    from sql_catalog import SqlCatalog

    cat = SqlCatalog(
        tables={
            ("dupoint_email_data", "orders"): {"Total_Amount", "Product_Name", "Order_Date"},
        },
        display_names={("dupoint_email_data", "orders"): ("dupoint_email_data", "Orders")},
    )
    import pandas as pd

    monkeypatch.setattr("sql_repair_recovery.get_catalog", lambda: cat)
    with patch(
        "sql_repair_recovery.fetch_dataframe_readonly",
        lambda _sql: pd.DataFrame([{"match_row_count": 0}]),
    ):
        n = try_time_window_zero_from_generator_sql(gc)
    assert n == 0


def test_time_window_zero_from_groupby_sql(monkeypatch):
    from jev_trace import reset as trace_reset, set_request_question

    trace_reset()
    q = (
        "What is the total Total_Amount for Chemical Resistant Boots and Kevlar Gloves "
        "orders in dupoint email data Orders in the last 2 months?"
    )
    set_request_question(q)
    sql = (
        "SELECT Product_Name, SUM(Total_Amount) AS Total_Amount_Sum "
        "FROM [dupoint_email_data].[Orders] "
        "WHERE Product_Name IN ('Chemical Resistant Boots', 'Kevlar Gloves') "
        "AND Order_Date >= DATEADD(month, -2, GETDATE()) GROUP BY Product_Name"
    )
    gc = _GC([{"name": "Sql_Generator", "content": json.dumps({"sql_query": sql})}])

    import pandas as pd

    with patch(
        "sql_repair_recovery.fetch_dataframe_readonly",
        lambda _sql: pd.DataFrame([{"match_row_count": 0}]),
    ):
        n = try_time_window_zero_from_generator_sql(gc)
    assert n == 0