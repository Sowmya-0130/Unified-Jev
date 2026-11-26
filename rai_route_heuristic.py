"""Deterministic RAI override for in-scope read-only SQL analytics (LLM flakiness)."""
from __future__ import annotations

import re

_BLOCK_VERBS = re.compile(
    r"\b(drop|delete|truncate|insert\s+into|update\s+\w|grant\s+|revoke\s+|exec\s|xp_)\b",
    re.IGNORECASE,
)
_SQL_ANALYTICS = re.compile(
    r"\b(total|sum|how many|count|average|avg|top\s+\d+|list the|what is the)\b",
    re.IGNORECASE,
)


def should_allow_routing_despite_rai_block(question: str, azure_safety_message: dict) -> bool:
    """
    When Azure content safety is clean and the question is a standard analytics
    request (no write ops), proceed to routing instead of aborting on RAI LLM noise.
    """
    q = (question or "").strip()
    if not q or _BLOCK_VERBS.search(q):
        return False
    if not _SQL_ANALYTICS.search(q):
        return False
    az = (azure_safety_message or {}).get("azure_safety_result") or {}
    if str(az.get("toxicity") or "").lower() not in ("", "safe"):
        return False
    if az.get("jailbreak") or az.get("self_harm"):
        return False
    if (azure_safety_message or {}).get("flags"):
        heavy = {"toxicity", "prompt_injection", "destructive_sql", "bulk_exfil"}
        if heavy & set(azure_safety_message.get("flags") or []):
            return False
    return True