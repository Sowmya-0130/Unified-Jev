"""Apply S14-style PII redaction to final answers."""
from __future__ import annotations

from typing import Any

from data_profile import redact_pii_in_text


def apply_pii_redaction(response: dict[str, Any]) -> dict[str, Any]:
    from API_unified import S14_PII_REDACT_ENABLED

    if not S14_PII_REDACT_ENABLED:
        return response
    redactions: list[str] = []
    for key in ("query_answer", "llm_answer"):
        raw = response.get(key)
        if not raw:
            continue
        redacted, hits = redact_pii_in_text(str(raw))
        if hits:
            response[key] = redacted
            redactions.extend(hits)
    fa = response.get("final_answer")
    if isinstance(fa, dict):
        for k in ("query_answer", "llm_answer"):
            raw = fa.get(k)
            if not raw:
                continue
            redacted, hits = redact_pii_in_text(str(raw))
            if hits:
                fa[k] = redacted
                redactions.extend(hits)
        response["final_answer"] = fa
    if redactions:
        response["s14_pii_redactions"] = sorted(set(redactions))
    return response