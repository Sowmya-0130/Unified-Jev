"""Canonical JEV gate inputs (mirrors aurix_core wiring for tests)."""
from __future__ import annotations

import json
import re
from typing import Any


def parse_vector_context(message_content: Any) -> list:
    if message_content is None:
        return []
    if isinstance(message_content, dict):
        vc = message_content.get("vector_context")
        return list(vc) if isinstance(vc, list) else []
    text = str(message_content).strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            vc = data.get("vector_context")
            return list(vc) if isinstance(vc, list) else []
    except json.JSONDecodeError:
        pass
    if "vector_context" in text:
        m = re.search(r"vector_context['\"]?\s*:\s*\[", text)
        if m:
            try:
                data = json.loads(text.replace("'", '"'))
                vc = data.get("vector_context")
                return list(vc) if isinstance(vc, list) else []
            except json.JSONDecodeError:
                pass
    return []


def s4_input(question: str, schema_summary: str) -> dict[str, int]:
    return {"question_len": len(question or ""), "schema_chars": len(schema_summary or "")}


def parse_autogen_tool_body(content: str) -> str:
    """Extract payload from AutoGen ***** Response from calling tool ***** wrapper."""
    text = str(content or "").strip()
    marker = "Response from calling tool"
    if marker not in text:
        return text
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if marker not in line:
            continue
        body_lines: list[str] = []
        for rest in lines[i + 1 :]:
            s = rest.strip()
            if s.startswith("*****") and marker not in rest:
                break
            body_lines.append(rest)
        return "\n".join(body_lines).strip()
    return text


def _looks_like_sql_generator_json(raw: str) -> bool:
    try:
        data = json.loads(raw.replace("```json", "").replace("```", "").strip())
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    return "sql_query" in data and "next_agent" in data


def latest_sql_tool_result(messages: list[dict]) -> tuple[str, int]:
    """
    Latest Sql_tool execution payload only (rows JSON, error string, or []).
    Skips empty Sql_tool turns and generator/executor-shaped JSON blobs.
    Returns (payload, message_index) or ("", -1).
    """
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("name") != "Sql_tool":
            continue
        raw = parse_autogen_tool_body(str(msg.get("content") or ""))
        if not raw:
            continue
        if _looks_like_sql_generator_json(raw):
            continue
        return raw, i
    return "", -1


def s7_input(sql_tool_message: str, *, message_index: int | None = None) -> dict[str, int]:
    out: dict[str, int] = {"sql_out_chars": len(str(sql_tool_message or ""))}
    if message_index is not None and message_index >= 0:
        out["sql_tool_msg_index"] = message_index
    return out


def s9_input(question: str, insight_message: str) -> dict[str, int]:
    return {"question_len": len(question or ""), "answer_chars": len(insight_message or "")}


def s13_input(question: str, answer: str, messages: list[dict]) -> tuple[dict[str, int], list]:
    chunks: list = []
    for msg in reversed(messages[-20:]):
        if msg.get("name") in ("retriever", "Eryl_agent", "llm_answer_maker"):
            part = parse_vector_context(msg.get("content"))
            if part:
                chunks = part
                break
    return (
        {
            "question_len": len(question or ""),
            "answer_chars": len(answer or ""),
            "context_chunks": len(chunks),
        },
        chunks,
    )