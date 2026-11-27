"""Single-turn LLM calls for the code orchestrator (no GroupChat loop)."""
from __future__ import annotations

import threading
from typing import Any

from jev_trace import mark_agent_transition

_AGENT_GEN_LOCK = threading.Lock()


def agent_llm_turn(agent: Any, user_prompt: str, *, sender: Any) -> str:
    name = getattr(agent, "name", None) or type(agent).__name__
    try:
        from jev_trace import trace_stdout

        trace_stdout(f"LLM turn: {name}…")
    except Exception:  # noqa: BLE001
        pass
    mark_agent_transition(agent)
    with _AGENT_GEN_LOCK:
        reply = agent.generate_reply(
            messages=[{"role": "user", "content": user_prompt}],
            sender=sender,
        )
    mark_agent_transition(agent)
    try:
        from jev_trace import trace_stdout

        trace_stdout(f"LLM turn: {name} done ({len(str(reply or ''))} chars)")
    except Exception:  # noqa: BLE001
        pass
    return str(reply or "")