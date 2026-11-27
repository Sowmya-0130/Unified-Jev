from answer_template import build_insight_from_sql_result


def test_null_scalar_no_matching_data():
    out = build_insight_from_sql_result('[{"metric": null}]', "SELECT SUM(x) AS metric FROM [t].[T]")
    assert out and "No matching data" in out["query_answer"]


def test_single_scalar():
    out = build_insight_from_sql_result('[{"total": 17203.8}]', "SELECT SUM(x) AS total FROM [a].[B]")
    assert out and "17,203.8" in out["query_answer"]


def test_multi_metric_row_prose():
    payload = '[{"Total_Amount_Sum": 6405.0, "Order_Count": 6}]'
    out = build_insight_from_sql_result(
        payload,
        "SELECT SUM(Total_Amount) AS Total_Amount_Sum, COUNT(*) AS Order_Count FROM [t].[T]",
    )
    assert out
    qa = out["query_answer"]
    assert "6,405" in qa
    assert "6" in qa
    assert "1. Total_Amount" not in qa


def test_coalesce_sum_zero_no_matching_data():
    out = build_insight_from_sql_result(
        '[{"Total_Amount": 0}]',
        "SELECT COALESCE(SUM(Total_Amount), 0) AS Total_Amount FROM [a].[B]",
    )
    assert out and out["query_answer"] == "No matching data."


def test_sum_and_count_zero_no_matching_data():
    payload = '[{"Total_Amount_Sum": null, "Order_Count": 0}]'
    out = build_insight_from_sql_result(
        payload,
        "SELECT SUM(Total_Amount) AS Total_Amount_Sum, COUNT(*) AS Order_Count FROM [t].[T]",
    )
    assert out and "No matching data" in out["query_answer"]