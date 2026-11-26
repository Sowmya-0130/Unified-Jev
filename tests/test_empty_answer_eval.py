from __future__ import annotations

from empty_answer_eval import allowed_numbers_for_question, empty_answer_acceptable


def test_empty_answer_allows_months_from_question():
    q = (
        "What is the total Total_Amount for Chemical Resistant Boots and Kevlar Gloves "
        "orders in dupoint email data Orders in the last 2 months?"
    )
    ans = "No matching data for the last 2 months."
    assert empty_answer_acceptable(ans, q)
    assert 2.0 in allowed_numbers_for_question(q)


def test_empty_answer_rejects_unexpected_amount():
    q = "What is the total in the last 2 months?"
    ans = "No matching data for the filters; the total was 5,000."
    assert not empty_answer_acceptable(ans, q)