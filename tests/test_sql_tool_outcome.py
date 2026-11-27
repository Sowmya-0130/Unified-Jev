from __future__ import annotations

import json

from jev_client import _heuristic_sql_result_check
from sql_execute_step import validation_error_body
from sql_tool_outcome import (
    is_validation_error_body,
    pipeline_failure_detail,
    s7_indicates_validation,
    user_message_for_failed_pipeline,
)


def test_s7_pipeline_validation_not_unknown_error():
    body = validation_error_body("SELECT 1", question="count rows")
    assert is_validation_error_body(body)
    out = _heuristic_sql_result_check(body)
    assert out and out.get("error_type") == "validation"
    assert out.get("pipeline_validation")
    assert out.get("error_type") != "unknown_error"


def test_s7_indicates_validation_from_rcheck():
    assert s7_indicates_validation({"pipeline_validation": True, "error_type": "validation"})
    assert not s7_indicates_validation({"error_type": "unknown_error"})


def test_failed_pipeline_user_message_not_empty():
    body = json.dumps({"sql_pipeline_error": True, "class": "x", "message": "bad"})
    msg = user_message_for_failed_pipeline(
        question="How many clients in Europe?",
        last_sql_out=body,
    )
    assert msg
    assert "catalog" not in msg.lower()
    assert "schema" not in msg.lower()
    detail = pipeline_failure_detail(question="How many clients in Europe?", last_sql_out=body)
    assert "validation" in detail.lower()
    assert "Europe" in detail