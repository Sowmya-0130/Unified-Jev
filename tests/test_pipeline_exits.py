from __future__ import annotations

import re

import pytest

from pipeline_exits import (
    EXIT_REGISTRY,
    apply_exit_fields,
    operator_detail,
    resolve_exit,
    shows_in_ui,
)


@pytest.mark.parametrize("reason", sorted(EXIT_REGISTRY.keys()))
def test_registry_user_messages_safe(reason: str):
    out = resolve_exit(reason, question="sample question", context={"last_sql_out": "{}"})
    for field in ("query_answer", "llm_answer"):
        val = str(out.get(field) or "")
        assert "sql_pipeline_error" not in val
        assert not re.search(r"sk-[a-z0-9]", val, re.I)


@pytest.mark.parametrize("reason", sorted(EXIT_REGISTRY.keys()))
def test_registry_message_or_empty(reason: str):
    out = resolve_exit(reason, question="q", context={})
    if shows_in_ui(reason):
        assert (out.get("query_answer") or out.get("llm_answer") or "").strip()
    assert out.get("Reasoning")


def test_jev_s2_clarity_block_hints():
    out = apply_exit_fields("jev_s2_clarity_block", question="help")
    msg = out.get("llm_answer") or ""
    assert "more detail" in msg.lower() or "specific" in msg.lower()


def test_request_timeout_stable_user_copy():
    out = apply_exit_fields("request_timeout", question="q", context={"timeout_s": 120})
    assert "too long" in (out.get("llm_answer") or "").lower()
    detail = operator_detail("request_timeout", question="q", context={"timeout_s": 120})
    assert "REQUEST_TIMEOUT" in detail


def test_safety_jev_unavailable_copy():
    out = apply_exit_fields("safety_jev_unavailable", question="q")
    assert "unavailable" in (out.get("llm_answer") or "").lower()


def test_pipeline_sql_exit_uses_friendly_message():
    out = apply_exit_fields(
        "pipeline_sql_exit",
        question="Dupont Kevlar",
        context={"last_sql_out": '{"sql_pipeline_error": true, "class": "empty"}'},
    )
    assert "database" in (out.get("query_answer") or "").lower()
    assert out.get("Reasoning") == "pipeline_sql_exit"