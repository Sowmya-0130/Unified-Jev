from __future__ import annotations

from unittest.mock import patch

from sql_catalog import SqlCatalog
from sql_execute_step import run_validated_sql


def test_run_validated_sql_patches_missing_time_predicate():
    cat = SqlCatalog(
        tables={
            ("dupoint_email_data", "orders"): {"Total_Amount", "Product_Name", "Order_Date"},
        },
        display_names={("dupoint_email_data", "orders"): ("dupoint_email_data", "Orders")},
    )
    sql = (
        "SELECT SUM(Total_Amount) FROM [dupoint_email_data].[Orders] "
        "WHERE Product_Name LIKE '%Kevlar%'"
    )
    q = "Kevlar Orders dupoint in 2025"
    with patch("sql_execute_step.get_catalog", return_value=cat):
        to_run, executed = run_validated_sql(sql, question=q)
    assert to_run
    assert "2025" in to_run
    assert executed == to_run