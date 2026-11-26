"""Build get_final_answer response dict from pipeline transcript."""
from __future__ import annotations

import json
from typing import Any


def _parse_json_content(raw: str) -> dict:
    text = str(raw or "").replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def build_response(base: dict, ctx_transcript: list[dict], *, analysis_type: str) -> dict:
    response = dict(base)
    response["analysis_type"] = analysis_type or response.get("analysis_type", "")
    for item in ctx_transcript:
        name = item.get("name")
        content = item.get("content", "")
        if name == "jev_s4_routing":
            parsed = _parse_json_content(content)
            response["analysis_type"] = parsed.get("analysis_type") or response["analysis_type"]
            response["Reasoning"] = parsed.get("Reasoning") or parsed.get("next_step") or response.get("Reasoning", "")
        if name == "Sql_Generator":
            parsed = _parse_json_content(content)
            response["query"] = response.get("query") or parsed.get("sql_query")
            response["query_explanation"] = parsed.get("sql_question") or response.get("query_explanation", "")
        if name == "Sql_tool":
            response["DB_table"] = content
        if name == "Insight_Generator":
            parsed = _parse_json_content(content)
            response["query_answer"] = parsed.get("query_answer") or response.get("query_answer")
            response["query"] = response.get("query") or parsed.get("query") or parsed.get("sql_query")
            response["database_name"] = parsed.get("db_name") or response.get("database_name")
        if name == "llm_answer_maker":
            response["llm_answer"] = content if isinstance(content, str) else str(content)

    response["final_answer"] = {
        "query_answer": response.get("query_answer") or "",
        "llm_answer": response.get("llm_answer") or "",
    }
    return response