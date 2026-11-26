from __future__ import annotations

from data_profile import question_requests_pii, redact_pii_in_text
from safety_gate import evaluate_safety


def test_high_pii_on_row_count_allows():
    v = evaluate_safety(
        "How many rows are in dupoint email data Orders?",
        jev={"is_toxic": 0.01, "is_injection": 0.02, "has_pii": 0.9, "block": False, "source": "unit"},
        allow_low=0.20,
        block_high=0.55,
    )
    assert v.action == "allow"
    assert any("pii_logged" in r for r in v.reasons)


def test_explicit_email_list_blocks_with_high_pii():
    q = "List all customer email addresses from dupoint orders"
    v = evaluate_safety(
        q,
        jev={"is_toxic": 0.05, "is_injection": 0.05, "has_pii": 0.85, "block": False, "source": "unit"},
        allow_low=0.20,
        block_high=0.55,
    )
    assert question_requests_pii(q, profile={"pii_columns": [{"column": "Customer_Email", "tags": ["email"]}], "pii_tags": ["email"]})
    assert v.action == "block"


def test_redact_email_in_answer():
    text = "Contact jane.doe@example.com for details."
    out, hits = redact_pii_in_text(text)
    assert "[REDACTED:email]" in out
    assert "email" in hits