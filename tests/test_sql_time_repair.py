"""Regression: catalog-backed time repair hints after missing_time_predicate."""
from __future__ import annotations

import json

import pytest

from question_time import parse_time_window, sql_has_date_predicate
from sql_catalog import SqlCatalog
from sql_pipeline import validate_sql
from sql_time_repair import (
    enrich_validation_repair_reason,
    time_predicate_repair_hint,
    try_patch_missing_time_predicate,
)
from tests.fixtures.catalog_golden import golden_dupont_catalog


def test_parse_calendar_year_in_2025():
    tw = parse_time_window("Kevlar Gloves dupoint orders in 2025")
    assert tw and tw.kind == "calendar_year"


def test_sql_has_date_predicate_year_function():
    assert sql_has_date_predicate(
        "WHERE YEAR(Order_Date) = 2025",
        ["Order_Date"],
    )


def test_time_repair_hint_uses_catalog_date_column(monkeypatch):
    cat = SqlCatalog(
        tables={
            ("dupoint_email_data", "orders"): {"Total_Amount", "Product_Name", "Order_Date"},
        },
        display_names={("dupoint_email_data", "orders"): ("dupoint_email_data", "Orders")},
    )
    monkeypatch.setattr("sql_time_repair.get_catalog_readonly", lambda: cat)
    q = (
        "total Total_Amount Kevlar Gloves dupoint email data Orders in 2025"
    )
    hint = time_predicate_repair_hint(q)
    assert "2025" in hint
    assert "Order_Date" in hint
    assert "YEAR" in hint


def test_try_patch_missing_time_predicate_calendar_year():
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
    q = "Kevlar dupoint Orders in 2025"
    patched = try_patch_missing_time_predicate(sql, q, cat)
    assert patched and "YEAR(Order_Date) = 2025" in patched
    vr = validate_sql(patched, cat, question=q)
    assert vr.ok, (vr.error_class, vr.message)


def test_enrich_validation_repair_reason_appends_hint(monkeypatch):
    cat = golden_dupont_catalog()
    monkeypatch.setattr("sql_time_repair.get_catalog_readonly", lambda: cat)
    body = json.dumps(
        {
            "sql_pipeline_error": True,
            "class": "missing_time_predicate",
            "message": "Question time window 'in 2025' requires a WHERE on Order_Date",
        }
    )
    reason = "SQL validation failed (missing_time_predicate): requires time filter"
    q = "Kevlar dupoint Orders Total_Amount in 2025"
    out = enrich_validation_repair_reason(reason, body, q)
    assert "Time filter (required)" in out
    assert "2025" in out