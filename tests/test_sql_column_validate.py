from __future__ import annotations

from sql_catalog import SqlCatalog
from sql_column_validate import validate_query_columns
from sql_pipeline import validate_sql
from tests.fixtures.catalog_golden import golden_dupont_catalog


def _join_cat() -> SqlCatalog:
    return golden_dupont_catalog()


def test_qualified_wrong_table_rejects_total_amount():
    sql = "SELECT c.total_amount FROM [dbo].[customers] c"
    vr = validate_query_columns(sql, _join_cat())
    assert vr and not vr.ok and vr.error_class == "missing_column"


def test_qualified_alias_accepts_total_amount():
    sql = "SELECT o.total_amount FROM [dbo].[orders] o"
    vr = validate_query_columns(sql, _join_cat())
    assert vr is None or vr.ok


def test_unqualified_single_owner_accepts():
    sql = "SELECT total_amount FROM [dbo].[orders]"
    vr = validate_query_columns(sql, _join_cat())
    assert vr is None or vr.ok


def test_unqualified_ambiguous_customer_id_rejects():
    sql = (
        "SELECT customer_id FROM [dbo].[orders] o "
        "JOIN [dbo].[customers] c ON o.customer_id = c.customer_id"
    )
    vr = validate_query_columns(sql, _join_cat())
    assert vr and not vr.ok and vr.error_class == "ambiguous_column"


def test_join_validate_sql_accepts_qualified():
    sql = """
    SELECT TOP 5 c.customer_id, SUM(o.total_amount) AS total_amount
    FROM [dbo].[orders] o
    INNER JOIN [dbo].[customers] c ON o.customer_id = c.customer_id
    GROUP BY c.customer_id, c.customer_name
    ORDER BY SUM(o.total_amount) DESC
    """
    vr = validate_sql(" ".join(sql.split()), _join_cat())
    assert vr.ok, (vr.error_class, vr.message)