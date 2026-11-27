"""Q0 golden tests — SQL path hardening regression suite."""
from __future__ import annotations

import json

import pytest

from tests.fixtures.catalog_golden import golden_dupont_catalog
from sql_pipeline import (
    INSIGHT_REQUIRED_KEYS,
    assert_answer_grounded,
    assert_execution_query_matches,
    classify_sql_exception,
    max_retries_for_exception,
    validate_insight_schema,
    validate_sql,
)

CAT = golden_dupont_catalog()


def test_dbo_bracket_dupoint_orders_unchanged():
    sql = "SELECT COUNT(*) AS n FROM dbo.[dupoint_email_data.Orders]"
    vr = validate_sql(sql, CAT)
    assert vr.ok and vr.normalized_sql == sql


def test_bracket_dupoint_orders_unchanged():
    sql = "SELECT COUNT(*) AS n FROM [dupoint_email_data].[Orders]"
    vr = validate_sql(sql, CAT)
    assert vr.ok and vr.normalized_sql == sql


def test_three_part_unbracketed_resolves_or_rejects():
    sql = "SELECT COUNT(*) AS n FROM dbo.dupoint_email_data.Orders"
    vr = validate_sql(sql, CAT)
    assert vr.ok
    assert vr.normalized_sql
    assert "dbo.dupoint_email_data.Orders" not in vr.normalized_sql.lower()
    assert "[dupoint_email_data].[Orders]" in vr.normalized_sql


def test_invalid_bracket_dbo_chain_rejected():
    sql = "SELECT COUNT(*) AS n FROM [dupoint_email_data].[dbo].[Orders]"
    vr = validate_sql(sql, CAT)
    assert not vr.ok and vr.error_class == "invalid_identifier"
    assert vr.candidates


def test_bracket_schema_dot_dbo_orders_rejected():
    sql = "SELECT COUNT(*) AS n FROM [dupoint_email_data].dbo.Orders"
    vr = validate_sql(sql, CAT)
    assert not vr.ok and vr.candidates


def test_dbo_orders_missing_product_name_rejected():
    sql = "SELECT Product_Name FROM dbo.Orders"
    vr = validate_sql(sql, CAT)
    assert not vr.ok and vr.error_class == "missing_column"
    assert vr.candidates


def test_executor_must_match_validated_sql():
    validated = "SELECT COUNT(*) AS n FROM [dupoint_email_data].[Orders]"
    with pytest.raises(ValueError):
        assert_execution_query_matches(
            validated_sql=validated,
            attempted_sql="SELECT TOP 5 * FROM [dupoint_email_data].[Orders]",
        )


def test_scalar_total_question_blocks_union():
    q = "What is the total Total_Amount for boots in the last 2 months?"
    sql = (
        "SELECT SUM(Total_Amount) FROM [dupoint_email_data].[Orders] "
        "WHERE Product_Name = 'X' UNION ALL SELECT 0"
    )
    vr = validate_sql(sql, CAT, question=q)
    assert not vr.ok and vr.error_class == "unrequested_union"


def test_top5_fanout_blocked_at_validation():
    sql = "SELECT TOP 5 * FROM [dupoint_email_data].[Orders]"
    vr = validate_sql(sql, CAT)
    assert not vr.ok and vr.error_class == "unrequested_fanout"


def test_grounding_top5_sum_vs_cited_sum_fails():
    executed = "SELECT SUM(Total_Amount) AS total FROM [dupoint_email_data].[Orders]"
    cited = executed
    rows = [{"Total_Amount": 900.0}, {"Total_Amount": 800.0}, {"Total_Amount": 569.84}]
    answer = "Total is 3269.84 from the sum query."
    with pytest.raises(ValueError, match="not grounded"):
        assert_answer_grounded(
            query_answer=answer,
            executed_sql=executed,
            claimed_sql=cited,
            result_rows=rows,
        )


def test_grounding_accepts_full_aggregate():
    executed = "SELECT SUM(Total_Amount) AS total FROM [dupoint_email_data].[Orders]"
    rows = [{"total": 17203.8}]
    assert_answer_grounded(
        query_answer="17203.8",
        executed_sql=executed,
        claimed_sql=executed,
        result_rows=rows,
    )


@pytest.mark.parametrize(
    "err,permanent",
    [
        ("Reference (40515)", True),
        ("(207) Invalid column name", True),
        ("(208)", True),
        ("(102)", True),
        ("(229)", True),
        ("1205 deadlock", False),
        ("connection reset", False),
    ],
)
def test_error_retry_policy(err, permanent):
    assert classify_sql_exception(err) == ("permanent" if permanent else "transient")
    assert max_retries_for_exception(err) == (0 if permanent else 1)


@pytest.mark.live
def test_live_catalog_dupoint_orders_casing():
    from sql_catalog import get_catalog

    from tests.fixtures.catalog_golden import golden_catalog

    cat = golden_catalog()
    assert cat.bracketed("dupoint_email_data", "orders") == "[dupoint_email_data].[Orders]"


@pytest.mark.live
def test_live_validate_emits_orders_casing():
    from tests.fixtures.catalog_golden import golden_catalog

    sql = "SELECT COUNT(*) AS n FROM [dupoint_email_data].[orders]"
    vr = validate_sql(sql, golden_catalog())
    assert vr.ok
    assert "[dupoint_email_data].[Orders]" in (vr.normalized_sql or "")


def test_canonical_brackets_in_fixture():
    sql = "SELECT COUNT(*) FROM [dupoint_email_data].[orders]"
    vr = validate_sql(sql, CAT)
    assert vr.ok
    assert "[dupoint_email_data].[Orders]" in (vr.normalized_sql or "")


def test_insight_schema_requires_canonical_keys():
    bad = {"query_query": "SELECT 1", "query_answer": "1", "scores": "ok"}
    errs = validate_insight_schema(bad)
    assert any("missing:" in e for e in errs)
    assert any("renamed:" in e for e in errs)
    good = {
        "query_answer": "20",
        "inference": "ok",
        "executed_sql": "SELECT COUNT(*) FROM [dupoint_email_data].[Orders]",
    }
    assert validate_insight_schema(good) == []
    assert INSIGHT_REQUIRED_KEYS <= set(good.keys())