"""Per-request pipeline state (no shared AutoGen groupchat)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RequestContext:
    request_id: str
    question: str
    transcript: list[dict[str, Any]] = field(default_factory=list)
    analysis_type: str = ""
    route_reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def append(self, name: str, content: Any, *, role: str = "assistant") -> None:
        self.transcript.append({"name": name, "role": role, "content": content})


class _MessagesProxy:
    """Minimal groupchat.messages stand-in for legacy helpers."""

    def __init__(self, ctx: RequestContext):
        self._ctx = ctx

    @property
    def messages(self) -> list[dict[str, Any]]:
        return self._ctx.transcript