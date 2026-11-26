"""Single-turn LLM calls for the code orchestrator (no GroupChat loop)."""
from __future__ import annotations

import threading
from typing import Any

from jev_trace import mark_agent_transition

_AGENT_GEN_LOCK = threading.Lock()


def agent_llm_turn(agent: Any, user_prompt: str, *, sender: Any) -> str:
    mark_agent_transition(agent)
    with _AGENT_GEN_LOCK:
        reply = agent.generate_reply(
            messages=[{"role": "user", "content": user_prompt}],
            sender=sender,
        )
    mark_agent_transition(agent)
    return str(reply or "")