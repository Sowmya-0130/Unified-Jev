"""Per-thread SQL loop guard (no cross-request leakage)."""
from __future__ import annotations

import threading
from typing import Any

_TLS = threading.local()

# Main thread sets safety at pre-chat; pipeline Sql_tool runs on a worker thread.
_SAFETY_BY_REQUEST: dict[str, dict[str, Any]] = {}

_DEFAULT_GUARD: dict[str, Any] = {
    "request_id": None,
    "result_fp": None,
    "valid": False,
    "insight_done": False,
    "insight_schema_retries": 0,
    "validation_repairs": 0,
    "jev_route": None,
    "jev_next_agent": None,
    "prestaged_schema": None,
    "safety_verdict": None,
    "safety_blob": None,
    "skip_rai_llm": False,
}


def bump_validation_repair() -> int:
    g = _guard()
    g["validation_repairs"] = int(g.get("validation_repairs") or 0) + 1
    return int(g["validation_repairs"])


def take_validation_repairs() -> int:
    return int(_guard().get("validation_repairs") or 0)


def _guard() -> dict[str, Any]:
    g = getattr(_TLS, "sql_loop_guard", None)
    if g is None:
        g = dict(_DEFAULT_GUARD)
        _TLS.sql_loop_guard = g
    return g


def reset_sql_loop_guard(request_id: str | None = None) -> None:
    _TLS.sql_loop_guard = {
        **_DEFAULT_GUARD,
        "request_id": request_id,
    }


def sql_loop_guard() -> dict[str, Any]:
    return _guard()


def guard_matches_current_request() -> bool:
    """Guard dict is scoped to jev_trace request_id (not question/SQL text)."""
    from jev_trace import snapshot

    rid = (snapshot().get("request_id") or "").strip()
    if not rid:
        return True
    return str(_guard().get("request_id") or "") == rid


def ensure_guard_request_id(request_id: str | None) -> None:
    g = _guard()
    if g.get("request_id") != request_id:
        reset_sql_loop_guard(request_id)
    g["safety_verdict"] = None
    g["safety_blob"] = None
    g["skip_rai_llm"] = False


def inherit_prechat_safety(child_request_id: str, parent_request_id: str) -> bool:
    """Copy allow/block store from parent Both request onto a nested leg (no extra JEV S1)."""
    parent = _SAFETY_BY_REQUEST.get(str(parent_request_id))
    if not parent:
        return False
    action = str(parent.get("verdict") or "block")
    blob = dict(parent.get("blob") or {})
    skip_rai = bool(parent.get("skip_rai_llm"))
    _SAFETY_BY_REQUEST[str(child_request_id)] = {
        "verdict": action,
        "blob": blob,
        "skip_rai_llm": skip_rai,
    }
    g = _guard()
    g["request_id"] = child_request_id
    g["safety_verdict"] = action
    g["safety_blob"] = blob
    g["skip_rai_llm"] = skip_rai
    return action != "block"


def safety_prechat_store(request_id: str, verdict_action: str, blob: dict) -> None:
    from API_unified import SAFETY_LLM_MODE

    skip_rai = verdict_action == "allow" and (
        SAFETY_LLM_MODE == "off"
        or (SAFETY_LLM_MODE == "grey_zone" and verdict_action == "allow")
    )
    _SAFETY_BY_REQUEST[str(request_id)] = {
        "verdict": verdict_action,
        "blob": dict(blob),
        "skip_rai_llm": skip_rai,
    }
    g = _guard()
    g["request_id"] = request_id
    g["safety_verdict"] = verdict_action
    g["safety_blob"] = blob
    g["skip_rai_llm"] = skip_rai


def sync_safety_for_request(request_id: str | None) -> None:
    """Copy pre-chat safety from main thread onto pipeline worker TLS."""
    rid = str(request_id or "").strip()
    if not rid:
        return
    snap = _SAFETY_BY_REQUEST.get(rid)
    if not snap:
        return
    g = _guard()
    g["request_id"] = rid
    g["safety_verdict"] = snap.get("verdict")
    g["safety_blob"] = snap.get("blob")
    g["skip_rai_llm"] = bool(snap.get("skip_rai_llm"))


def safety_skip_rai_llm() -> bool:
    return bool(_guard().get("skip_rai_llm"))


def safety_prechat_blob() -> dict | None:
    b = _guard().get("safety_blob")
    return dict(b) if isinstance(b, dict) else None


def set_jev_route(route: str | None, next_agent: str | None) -> None:
    g = _guard()
    g["jev_route"] = route
    g["jev_next_agent"] = next_agent


def jev_route_next_agent() -> str | None:
    return _guard().get("jev_next_agent")


def jev_route_choice() -> str | None:
    return _guard().get("jev_route")


def set_prestaged_schema(block: str | None) -> None:
    b = (block or "").strip()
    _guard()["prestaged_schema"] = b if b else None


def prestaged_schema_block() -> str | None:
    b = _guard().get("prestaged_schema")
    if not b:
        return None
    return str(b)


def safety_allows_sql_execute() -> bool:
    """True after pre-chat safety verdict is not block (SQL path may proceed)."""
    v = _guard().get("safety_verdict")
    if v is None:
        try:
            from jev_trace import snapshot

            rid = (snapshot().get("request_id") or "").strip()
            if rid:
                snap = _SAFETY_BY_REQUEST.get(rid)
                if snap:
                    v = snap.get("verdict")
        except ImportError:
            pass
    if v is None:
        return False
    return str(v) != "block"