from __future__ import annotations

import httpx
import pytest

from safety_gate import JEV_UNAVAILABLE_USER_MESSAGE, evaluate_safety, jev_s1_for_question


def test_jev_429_blocks_no_allow(monkeypatch):
    import jev_client

    monkeypatch.setattr(jev_client, "_jev_post", lambda *_a, **_k: None)
    monkeypatch.setattr("API_unified.JEV_S1_SAFETY_ENABLED", True)

    jev = jev_s1_for_question("How many rows?")
    v = evaluate_safety("How many rows?", jev=jev)
    assert v.action == "block"
    assert "jev_unavailable" in v.reasons[0]
    assert v.blocked_message == JEV_UNAVAILABLE_USER_MESSAGE


def test_jev_malformed_blocks(monkeypatch):
    import jev_client

    monkeypatch.setattr(jev_client, "_jev_post", lambda *_a, **_k: {"is_toxic": {"bad": 1}})
    monkeypatch.setattr("API_unified.JEV_S1_SAFETY_ENABLED", True)

    jev = jev_s1_for_question("hello")
    assert jev.get("unavailable")
    v = evaluate_safety("hello", jev=jev)
    assert v.action == "block"


def test_jev_timeout_blocks(monkeypatch):
    jev = {
        "unavailable": True,
        "source": "jev_unavailable",
        "failure": "timeout",
        "is_toxic": None,
        "is_injection": None,
        "has_pii": None,
    }
    monkeypatch.setattr("API_unified.JEV_S1_SAFETY_ENABLED", True)
    v = evaluate_safety("hello", jev=jev)
    assert v.action == "block"


def test_jev_500_blocks(monkeypatch):
    import jev_client

    monkeypatch.setattr(jev_client, "_jev_post", lambda *_a, **_k: None)
    jev_client._last_jev_failure = "http:500"
    monkeypatch.setattr("API_unified.JEV_S1_SAFETY_ENABLED", True)
    jev = jev_s1_for_question("test")
    v = evaluate_safety("test", jev=jev)
    assert v.action == "block"


def test_regex_still_blocks_when_jev_unavailable():
    jev = {
        "unavailable": True,
        "source": "jev_unavailable",
        "failure": "http:429",
    }
    v = evaluate_safety("DROP TABLE foo", jev=jev)
    assert v.action == "block"
    assert v.regex_block