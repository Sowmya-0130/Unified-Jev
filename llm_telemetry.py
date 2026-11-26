"""Hook AutoGen OpenAIWrapper for per-call ids and token usage (no secrets)."""
from __future__ import annotations

from typing import Any

_calls: list[dict[str, Any]] = []


def reset() -> None:
    _calls.clear()


def calls() -> list[dict[str, Any]]:
    return list(_calls)


def _usage_from_response(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    elif not isinstance(usage, dict):
        try:
            usage = dict(usage)
        except Exception:  # noqa: BLE001
            return {}
    out: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens"):
        if key in usage and usage[key] is not None:
            try:
                out[key] = int(usage[key])
            except (TypeError, ValueError):
                pass
    details = usage.get("completion_tokens_details") or {}
    if "reasoning_tokens" in details and details["reasoning_tokens"] is not None:
        try:
            out["reasoning_tokens"] = int(details["reasoning_tokens"])
        except (TypeError, ValueError):
            pass
    return out


def _response_id(response: Any) -> str | None:
    rid = getattr(response, "id", None)
    if rid:
        return str(rid)
    if isinstance(response, dict):
        return response.get("id")
    return None


def _agent_name(config: dict) -> str:
    agent = config.get("agent")
    return getattr(agent, "name", None) or str(agent or "unknown")


def install() -> None:
    from autogen.oai.client import OpenAIWrapper

    if getattr(OpenAIWrapper, "_aurix_telemetry_installed", False):
        return

    original = OpenAIWrapper.create

    def create(self, **config: Any):  # type: ignore[no-untyped-def]
        from jev_trace import record_llm_api_call

        response = original(self, **config)
        usage = _usage_from_response(response)
        rid = _response_id(response)
        cached = bool(getattr(response, "is_cached", 0) if hasattr(response, "is_cached") else False)
        agent = _agent_name(config)
        row = {
            "response_id": rid,
            "agent": agent,
            "cached": cached,
            **usage,
        }
        _calls.append(row)
        record_llm_api_call(agent, response_id=rid, usage=usage, cached=cached)
        return response

    OpenAIWrapper.create = create  # type: ignore[method-assign]
    OpenAIWrapper._aurix_telemetry_installed = True