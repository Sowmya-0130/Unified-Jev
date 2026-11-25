"""Per-request JEV / pipeline trace (no secrets, no PII bodies)."""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

_log = logging.getLogger("aurix.jev_trace")

_events: list[dict[str, Any]] = []
_request_id: str = ""
_t0: float = 0.0


def reset() -> str:
    global _request_id, _events, _t0
    _request_id = uuid.uuid4().hex[:12]
    _events = []
    _t0 = time.perf_counter()
    return _request_id


def event(gate: str, **fields: Any) -> None:
    fields = {k: v for k, v in fields.items() if v is not None}
    row = {
        "gate": gate,
        "t_ms": round((time.perf_counter() - _t0) * 1000, 1),
        **fields,
    }
    _events.append(row)
    _log.info(json.dumps({"request_id": _request_id, **row}, default=str))


def snapshot() -> dict[str, Any]:
    return {"request_id": _request_id, "events": list(_events)}


def summarize_chat_agents(chat_history) -> dict[str, Any]:
    names: list[str] = []
    try:
        for item in chat_history.chat_history:
            n = item.get("name")
            if n:
                names.append(n)
    except Exception:  # noqa: BLE001
        pass
    llm_like = {
        "routing_agent",
        "Sql_Execution_Critic",
        "Evaluation_Agent",
        "evaluation_agent",
        "critic_agent",
        "Responsible_AI_Agent",
        "Sql_Generator",
        "Insight_Generator",
        "llm_answer_maker",
        "Eryl_agent",
        "Query_Executor",
    }
    run = [n for n in names if n in llm_like]
    skipped_markers = {
        "routing_agent": "S4",
        "Sql_Execution_Critic": "S7",
        "evaluation_agent": "S9",
        "critic_agent": "S13",
    }
    synthetic = []
    for item in getattr(chat_history, "chat_history", []) or []:
        body = str(item.get("content", ""))
        for agent, gate in skipped_markers.items():
            if item.get("name") == agent and "jev" in body.lower():
                synthetic.append(gate)
    return {
        "agent_messages": names,
        "llm_agent_turns": run,
        "llm_turn_count": len(run),
        "jev_synthetic_skip_gates": synthetic,
    }