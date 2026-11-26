from __future__ import annotations

from safety_gate import evaluate_safety


def test_regex_blocks_drop():
    v = evaluate_safety(
        "DROP TABLE foo",
        jev={"is_toxic": 0, "is_injection": 0, "has_pii": 0, "block": False, "source": "unit"},
    )
    assert v.action == "block"


def test_grey_zone_between_thresholds(monkeypatch):
    import API_unified

    monkeypatch.setattr(API_unified, "SAFETY_LLM_MODE", "always")
    v = evaluate_safety(
        "How many rows?",
        jev={"is_toxic": 0.4, "is_injection": 0.1, "has_pii": 0.05, "block": False, "source": "unit"},
        allow_low=0.25,
        block_high=0.85,
    )
    assert v.action == "grey_zone"


def test_clear_allow_below_low():
    v = evaluate_safety(
        "How many rows?",
        jev={"is_toxic": 0.05, "is_injection": 0.02, "has_pii": 0.01, "block": False, "source": "unit"},
        allow_low=0.25,
        block_high=0.85,
    )
    assert v.action == "allow"