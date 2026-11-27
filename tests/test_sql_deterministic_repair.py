"""Regression: GROUP BY + calendar year deterministic repair (Dupont 2025 style)."""
from __future__ import annotations

from sql_catalog import SqlCatalog
from sql_deterministic_repair import repair_sql_until_valid, try_collapse_groupby_scalar
from sql_execute_step import run_validated_sql
from unittest.mock import patch


def _dupont_cat() -> SqlCatalog:
    return SqlCatalog(
        tables={
            ("dupoint_email_data", "orders"): {"Total_Amount", "Product_Name", "Order_Date"},
        },
        display_names={("dupoint_email_data", "orders"): ("dupoint_email_data", "Orders")},
    )


def test_collapse_groupby_scalar_for_total_question():
    q = "What were the total Dupont order amounts for Kevlar Gloves in 2025?"
    sql = (
        "SELECT Product_Name, SUM(Total_Amount) AS Total_Amount "
        "FROM [dupoint_email_data].[Orders] "
        "WHERE Product_Name LIKE '%Kevlar%' GROUP BY Product_Name"
    )
    out = try_collapse_groupby_scalar(sql, q)
    assert out
    assert "GROUP BY" not in out.upper()
    assert "SUM(Total_Amount)" in out


def test_repair_sql_until_valid_groupby_and_year():
    cat = _dupont_cat()
    q = "What were the total Dupont order amounts for Kevlar Gloves in 2025?"
    sql = (
        "SELECT Product_Name, SUM(Total_Amount) AS Total_Amount "
        "FROM [dupoint_email_data].[Orders] "
        "WHERE Product_Name LIKE '%Kevlar%' GROUP BY Product_Name"
    )
    to_run, _ = repair_sql_until_valid(sql, q, cat)
    assert to_run
    assert "2025" in to_run
    assert "GROUP BY" not in to_run.upper()


def test_run_validated_sql_dupont_2025_scenario():
    cat = _dupont_cat()
    q = "What were the total Dupont order amounts for Kevlar Gloves in 2025?"
    sql = (
        "SELECT Product_Name, SUM(Total_Amount) AS total_amt "
        "FROM [dupoint_email_data].[Orders] "
        "WHERE Product_Name LIKE '%Kevlar%' GROUP BY Product_Name"
    )
    with patch("sql_execute_step.get_catalog", return_value=cat):
        to_run, executed = run_validated_sql(sql, question=q)
    assert to_run and executed
    assert "YEAR" in to_run.upper() or "2025" in to_run