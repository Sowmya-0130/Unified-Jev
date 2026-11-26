from __future__ import annotations

from sql_match_count import build_filter_count_sql, count_from_result_payload


def test_build_filter_count_from_sum_query():
    sql = (
        "SELECT SUM(Total_Amount) AS metric FROM [dupoint_email_data].[Orders] "
        "WHERE Product_Name IN ('A','B') AND Order_Date >= DATEADD(month, -2, GETDATE())"
    )
    count_sql = build_filter_count_sql(sql)
    assert count_sql
    assert "COUNT(*)" in count_sql.upper()
    assert "WHERE" in count_sql.upper()


def test_count_from_payload_order_count_column():
    n = count_from_result_payload(
        '[{"Total_Amount_Sum": null, "Order_Count": 0}]',
        "SELECT SUM(Total_Amount), COUNT(*) AS Order_Count FROM t",
    )
    assert n == 0


def test_union_returns_no_count_sql():
    sql = "SELECT 1 UNION ALL SELECT 2"
    assert build_filter_count_sql(sql) is None


def test_union_plain_select_derives_count_sql():
    sql = (
        "SELECT Product_Name, SUM(Total_Amount) AS Total_Amount "
        "FROM [dupoint_email_data].[Orders] "
        "WHERE Product_Name IN ('A','B') AND Order_Date >= DATEADD(month, -2, GETDATE()) "
        "GROUP BY Product_Name "
        "UNION ALL "
        "SELECT 'Combined', SUM(Total_Amount) FROM [dupoint_email_data].[Orders] "
        "WHERE Product_Name IN ('A','B') AND Order_Date >= DATEADD(month, -2, GETDATE())"
    )
    count_sql = build_filter_count_sql(sql)
    assert count_sql
    assert "COUNT(*)" in count_sql.upper()
    assert "GROUP BY" not in count_sql.upper()


def test_union_cte_derives_count_sql():
    sql = (
        "WITH filtered AS (\n"
        "  SELECT Order_ID FROM [dupoint_email_data].[Orders]\n"
        "  WHERE Order_Date >= DATEADD(month, -2, GETDATE())\n"
        "    AND Product_Name IN ('A','B')\n"
        ")\n"
        "SELECT 1 FROM filtered UNION ALL SELECT 2"
    )
    count_sql = build_filter_count_sql(sql)
    assert count_sql
    assert "COUNT(*)" in count_sql.upper()
    assert "[dupoint_email_data].[Orders]" in count_sql