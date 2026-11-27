"""B1: gate inputs match the messages aurix_core uses."""
from __future__ import annotations

import json

from gate_inputs import (
    latest_sql_tool_result,
    parse_autogen_tool_body,
    parse_vector_context,
    s13_input,
    s4_input,
    s7_input,
    s9_input,
)
from jev_client import _heuristic_sql_result_check


def test_s7_row_count_json_valid():
    out = _heuristic_sql_result_check('[{"row_count": 20}]')
    assert out and out["is_valid"] and out["source"] == "heuristic"


def test_s7_empty_array_no_data():
    out = _heuristic_sql_result_check("[]")
    assert out and not out["is_valid"] and out.get("no_matching_data")


def test_s7_all_null_no_data():
    out = _heuristic_sql_result_check('[{"metric": null}]')
    assert out and not out["is_valid"] and out.get("no_matching_data")


def test_s7_error_text_invalid():
    out = _heuristic_sql_result_check("Error: Invalid object name 'foo'.")
    assert out and not out["is_valid"]
    assert out.get("error_type") == "unknown_error"


def test_s7_sql_pipeline_error_is_validation_class():
    from sql_execute_step import validation_error_body

    body = validation_error_body("SELECT bad", question="q")
    out = _heuristic_sql_result_check(body)
    assert out and out.get("error_type") == "validation"
    assert out.get("pipeline_validation")


def test_s7_db_error_string_invalid():
    out = _heuristic_sql_result_check(
        "An error occurred while executing the query: ('42000', 'bad')"
    )
    assert out and not out["is_valid"] and out["source"] == "heuristic"


def test_s7_rejects_sql_generator_json_not_rows():
    blob = '{"sql_query": "SELECT ' + ("x" * 300) + '", "next_agent": "Sql_Generator"}'
    assert _heuristic_sql_result_check(blob) is None


def test_latest_sql_tool_result_from_tool_wrapper():
    tool = (
        "***** Response from calling tool (call_abc) *****\n"
        '[{"row_count": 20}]\n'
        "**********************************************************************"
    )
    msgs = [
        {"name": "Sql_tool", "content": ""},
        {"name": "Sql_tool", "content": tool},
    ]
    payload, idx = latest_sql_tool_result(msgs)
    assert idx == 1
    assert payload == '[{"row_count": 20}]'


def test_latest_sql_tool_result_skips_generator_json():
    gen = '{"sql_query": "SELECT 1", "next_agent": "Query_Executor"}'
    tool = "***** Response from calling tool *****\n[]\n***** End of response *****"
    msgs = [
        {"name": "Sql_tool", "content": gen},
        {"name": "Sql_tool", "content": tool},
    ]
    payload, idx = latest_sql_tool_result(msgs)
    assert idx == 1 and payload == "[]"


def test_s7_input_records_message_index():
    meta = s7_input("[{}]", message_index=7)
    assert meta["sql_tool_msg_index"] == 7
    assert meta["sql_out_chars"] == 4


def test_parse_autogen_tool_body():
    raw = parse_autogen_tool_body(
        "***** Response from calling tool *****\n[{\"a\":1}]\n***** End of response *****"
    )
    assert raw == '[{"a":1}]'


def test_s13_context_from_retriever_message():
    msgs = [
        {
            "name": "retriever",
            "content": json.dumps({"vector_context": ["return policy text"]}),
        },
    ]
    meta, chunks = s13_input("q", "ans", msgs)
    assert meta["context_chunks"] == 1
    assert chunks == ["return policy text"]


def test_s13_parse_tool_string_body():
    raw = '{"vector_context": ["chunk-a", "chunk-b"]}'
    assert len(parse_vector_context(raw)) == 2


def test_s4_s7_s9_input_sizes_only():
    assert s4_input("hello", "schema")[ "question_len"] == 5
    assert s7_input('[{"x":1}]')["sql_out_chars"] > 0
    assert s9_input("q", "{}")["answer_chars"] == 2