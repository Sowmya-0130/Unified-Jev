from __future__ import annotations

from question_sql_normalize import normalize_question_for_sql
from question_time import parse_time_window


def test_dupont_typo_expands_dupoint_orders():
    q = "What were the total Dupont order amounts for Kevlar Gloves in 2025?"
    n = normalize_question_for_sql(q)
    assert "dupoint" in n.lower()
    assert "dupont" not in n.lower()
    assert "dupoint_email_data" in n.lower()
    assert "Orders" in n or "orders" in n.lower()
    assert "Total_Amount" in n


def test_gcc_token_appends_hackathon_clients_table():
    n = normalize_question_for_sql("How many clients are in the Europe region in GCC?")
    assert "GCC_Hackathon_clients" in n


def test_parse_calendar_year_2025_in_phrase():
    q = "total Dupont order amounts for Kevlar Gloves in 2025"
    tw = parse_time_window(q)
    assert tw is not None
    assert tw.kind == "calendar_year"
    assert "2025" in tw.raw_phrase