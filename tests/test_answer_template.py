from answer_template import build_insight_from_sql_result


def test_null_scalar_no_matching_data():
    out = build_insight_from_sql_result('[{"metric": null}]', "SELECT SUM(x) AS metric FROM [t].[T]")
    assert out and "No matching data" in out["query_answer"]


def test_single_scalar():
    out = build_insight_from_sql_result('[{"total": 17203.8}]', "SELECT SUM(x) AS total FROM [a].[B]")
    assert out and out["query_answer"] == "17203.8"


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