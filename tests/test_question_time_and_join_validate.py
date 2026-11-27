"""Regression: time windows + join column pooling (fixture catalog)."""
from __future__ import annotations

import pytest

from question_time import parse_time_window, sql_has_date_predicate
from sql_catalog import SqlCatalog
from sql_pipeline import validate_sql
from tests.fixtures.catalog_golden import golden_dupont_catalog


def test_parse_last_2_months():
    tw = parse_time_window("orders in the last 2 months for boots")
    assert tw and tw.months == 2


def test_join_customer_id_across_tables():
    sql = """
    SELECT TOP 5 c.customer_id, SUM(o.total_amount) AS total_amount
    FROM [dbo].[orders] o
    INNER JOIN [dbo].[customers] c ON o.customer_id = c.customer_id
    GROUP BY c.customer_id
    ORDER BY total_amount DESC
    """
    vr = validate_sql(" ".join(sql.split()), golden_dupont_catalog())
    assert vr.ok, (vr.error_class, vr.message)


def test_missing_time_predicate_rejected():
    cat = SqlCatalog(
        tables={
            ("dupoint_email_data", "orders"): {"Total_Amount", "Product_Name", "Order_Date"},
        },
        display_names={("dupoint_email_data", "orders"): ("dupoint_email_data", "Orders")},
    )
    sql = (
        "SELECT SUM(Total_Amount) FROM [dupoint_email_data].[Orders] "
        "WHERE Product_Name = 'Boots'"
    )
    q = "total for boots in the last 2 months"
    vr = validate_sql(sql, cat, question=q)
    assert not vr.ok and vr.error_class == "missing_time_predicate"


def test_sql_has_date_predicate_detects_order_date():
    assert sql_has_date_predicate(
        "WHERE Order_Date >= DATEADD(month,-2,GETDATE())",
        ["Order_Date"],
    )


def test_calendar_year_filter_passes_validation():
    cat = SqlCatalog(
        tables={
            ("dupoint_email_data", "orders"): {"Total_Amount", "Product_Name", "Order_Date"},
        },
        display_names={("dupoint_email_data", "orders"): ("dupoint_email_data", "Orders")},
    )
    sql = (
        "SELECT SUM(Total_Amount) FROM [dupoint_email_data].[Orders] "
        "WHERE Product_Name LIKE '%Kevlar%' AND YEAR(Order_Date) = 2025"
    )
    q = "Kevlar Gloves dupoint Orders in 2025"
    vr = validate_sql(sql, cat, question=q)
    assert vr.ok, (vr.error_class, vr.message)