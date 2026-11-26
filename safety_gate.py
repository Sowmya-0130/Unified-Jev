"""P0-1 safety choke: regex rules + JEV S1 scores → allow | block | grey_zone."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

Action = Literal["allow", "block", "grey_zone"]

JEV_UNAVAILABLE_USER_MESSAGE = (
    "Safety check is temporarily unavailable, please try again."
)


@dataclass
class SafetyVerdict:
    action: Action
    regex_block: bool
    regex_flags: list[str]
    jev: dict[str, Any]
    max_p_unsafe: float
    p_toxic: float
    p_injection: float
    p_pii: float
    reasons: list[str] = field(default_factory=list)
    blocked_message: str | None = None
    score_semantics: str = (
        "S1 bands use max(is_toxic,is_injection); has_pii blocks only on explicit "
        "identifier requests vs catalog PII tags; else logged"
    )


def regex_safety_blocks(question: str) -> bool:
    """True when regex choke would block before JEV/SQL path (pre-stage network skip)."""
    _flags, force_block = _regex_scan(question)
    return force_block


def _regex_scan(question: str) -> tuple[list[str], bool]:
    text = (question or "").lower()
    flags: list[str] = []
    force_block = False

    toxicity_patterns = [
        r"\b(kill|hate|violence|attack|abuse|harass)\b",
        r"\b(bomb|weapon|murder|terror)\b",
    ]
    if any(re.search(p, text) for p in toxicity_patterns):
        flags.append("toxicity")
        force_block = True

    pii_patterns = [
        r"\b\d{3}-\d{2}-\d{4}\b",
        r"\b(?:ssn|social security number)\b",
        r"\bbulk\b.*\b(email|phone|address)\b",
    ]
    if any(re.search(p, question or "", re.IGNORECASE) for p in pii_patterns):
        flags.append("pii")

    injection_patterns = [
        r"ignore (all )?(previous|prior|above) instructions",
        r"disregard (the )?(system|developer) (prompt|message|instructions)",
        r"you are now (?:in )?(?:dan|developer|admin) mode",
        r"reveal (the )?(system prompt|hidden instructions|api key|secret)",
        r"jailbreak",
        r"prompt injection",
        r"output the system prompt",
        r"पिछले निर्देश",  # Hinglish: previous instructions
        r"system prompt dikhao",
    ]
    if any(re.search(p, text) for p in injection_patterns):
        flags.append("prompt_injection")
        force_block = True

    destructive_patterns = [
        r"\bdelete\s+(all\s+)?(rows\s+from|from)\b",
        r"\bdrop\s+table\b",
        r"\btruncate\s+table\b",
        r"\bupdate\s+.+\s+set\b",
        r"\balter\s+table\b",
    ]
    if any(re.search(p, text) for p in destructive_patterns):
        flags.append("destructive_sql")
        force_block = True

    bulk_exfil_patterns = [
        r"\bexport\b.*\b(ssn|social security)\b",
        r"\bbulk\b.*\b(csv|export|dump)\b",
        r"\b(api\s+key|connection string|secret|credential|password)\b",
        r"\ball\s+(customer|user)\s+(emails?|phones?)\b",
    ]
    cross_tenant = [
        r"\bother\s+tenant",
        r"\bcross[- ]tenant\b",
        r"\ball\s+companies\b.*\bdata\b",
    ]
    if any(re.search(p, text) for p in bulk_exfil_patterns):
        flags.append("bulk_exfil")
        force_block = True
    if any(re.search(p, text) for p in cross_tenant):
        flags.append("cross_tenant")
        force_block = True

    return flags, force_block


def jev_s1_for_question(question: str) -> dict[str, Any]:
    from API_unified import JEV_S1_SAFETY_ENABLED

    if not JEV_S1_SAFETY_ENABLED:
        return {
            "is_toxic": 0.0,
            "is_injection": 0.0,
            "has_pii": 0.0,
            "block": False,
            "source": "disabled",
        }
    try:
        from jev_client import jev_last_failure, jev_safety_check

        return dict(jev_safety_check(question))
    except Exception:  # noqa: BLE001
        return {
            "is_toxic": None,
            "is_injection": None,
            "has_pii": None,
            "block": True,
            "unavailable": True,
            "source": "jev_unavailable",
            "failure": jev_last_failure() or "exception",
        }


def effective_action(verdict: SafetyVerdict) -> Action:
    from API_unified import SAFETY_LLM_MODE

    if SAFETY_LLM_MODE == "off" and verdict.action == "grey_zone":
        return "block"
    return verdict.action


def evaluate_safety(
    question: str,
    *,
    jev: dict[str, Any] | None = None,
    allow_low: float | None = None,
    block_high: float | None = None,
) -> SafetyVerdict:
    from API_unified import SAFETY_JEV_ALLOW_LOW, SAFETY_JEV_BLOCK_HIGH

    allow_low = SAFETY_JEV_ALLOW_LOW if allow_low is None else allow_low
    block_high = SAFETY_JEV_BLOCK_HIGH if block_high is None else block_high

    regex_flags, regex_block = _regex_scan(question)
    if jev is None:
        from API_unified import JEV_S1_SAFETY_ENABLED

        jev = jev_s1_for_question(question) if JEV_S1_SAFETY_ENABLED else {"source": "jev_disabled"}

    if regex_block:
        pass  # handled below; regex wins over unavailable wording
    elif (jev.get("unavailable") or jev.get("source") == "jev_unavailable"):
        from API_unified import JEV_S1_SAFETY_ENABLED

        if JEV_S1_SAFETY_ENABLED:
            from jev_client import jev_last_failure

            fail = str(jev.get("failure") or jev_last_failure() or "unknown")
            return SafetyVerdict(
                action="block",
                regex_block=False,
                regex_flags=regex_flags,
                jev=jev,
                max_p_unsafe=1.0,
                p_toxic=0.0,
                p_injection=0.0,
                p_pii=0.0,
                reasons=["jev_unavailable", fail],
                blocked_message=JEV_UNAVAILABLE_USER_MESSAGE,
            )

    p_toxic = float(jev.get("is_toxic") or 0.0)
    p_inj = float(jev.get("is_injection") or 0.0)
    p_pii = float(jev.get("has_pii") or 0.0)
    s1_risk = max(p_toxic, p_inj)

    from data_profile import question_requests_pii

    pii_explicit = question_requests_pii(question)
    pii_input_block = pii_explicit and p_pii >= block_high

    reasons: list[str] = []
    if regex_block:
        reasons.append("regex:" + ",".join(regex_flags))
    if jev.get("block"):
        reasons.append("jev_legacy_block_bit")
    if p_pii > allow_low and not pii_explicit:
        reasons.append(f"pii_logged_not_blocking:{p_pii:.3f}")

    if regex_block:
        action: Action = "block"
    elif pii_input_block:
        action = "block"
        reasons.append("jev_has_pii_explicit_identifier_request")
    elif s1_risk >= block_high:
        action = "block"
        reasons.append(f"jev_s1_risk>={block_high:.2f}")
    elif s1_risk <= allow_low:
        action = "allow"
    else:
        action = "grey_zone"
        reasons.append(f"grey_s1_{allow_low:.2f}<risk<{block_high:.2f}")

    blocked_message = None
    if action == "block":
        blocked_message = (
            "Your request was blocked by the safety gate (policy or elevated risk score). "
            "Please rephrase without destructive actions, credential requests, or instruction overrides."
        )
    elif action == "grey_zone":
        blocked_message = (
            "Your request was blocked pending clearer intent (elevated safety score in grey zone)."
        )

    v = SafetyVerdict(
        action=action,
        regex_block=regex_block,
        regex_flags=regex_flags,
        jev=jev,
        max_p_unsafe=s1_risk,
        p_toxic=p_toxic,
        p_injection=p_inj,
        p_pii=p_pii,
        reasons=reasons,
        blocked_message=blocked_message,
    )
    eff = effective_action(v)
    if eff != v.action:
        return SafetyVerdict(
            action=eff,
            regex_block=v.regex_block,
            regex_flags=v.regex_flags,
            jev=v.jev,
            max_p_unsafe=v.max_p_unsafe,
            p_toxic=v.p_toxic,
            p_injection=v.p_injection,
            p_pii=v.p_pii,
            reasons=[*v.reasons, "grey_zone_blocked_in_off_mode"],
            blocked_message=v.blocked_message,
        )
    return v


def blocked_response(verdict: SafetyVerdict, question: str) -> dict[str, Any]:
    msg = verdict.blocked_message or "Request blocked by safety policy."
    return {
        "query": "",
        "query_explanation": "",
        "python_code": None,
        "python_code_explanation": None,
        "analysis_type": "",
        "database_name": "",
        "query_answer": "",
        "DB_table": "",
        "updated_question": "",
        "llm_answer": msg,
        "Reasoning": "safety_gate_block",
        "final_answer": {"query_answer": "", "llm_answer": msg},
        "rai_evaluation": {
            "rai_check_passed": False,
            "blocked_reason": "; ".join(verdict.reasons) or "safety_gate",
            "initial_question": question,
        },
    }


def log_s1_gate(verdict: SafetyVerdict, question: str) -> None:
    from API_unified import SAFETY_JEV_ALLOW_LOW, SAFETY_JEV_BLOCK_HIGH
    from jev_trace import log_gate_decision

    jev_unavail = any(r.startswith("jev_unavailable") for r in verdict.reasons)
    log_gate_decision(
        "S1",
        input_summary={
            "question_len": len(question or ""),
            "regex_flags": verdict.regex_flags,
        },
        decision="block" if verdict.action == "block" else (
            "grey" if verdict.action == "grey_zone" else "pass"
        ),
        confidence=verdict.max_p_unsafe,
        confidence_measures=verdict.score_semantics,
        threshold=f"allow<={SAFETY_JEV_ALLOW_LOW:.2f} block>={SAFETY_JEV_BLOCK_HIGH:.2f}",
        action="block" if verdict.action == "block" else "pass",
        jev_block=verdict.action == "block",
        fallback_reason="; ".join(verdict.reasons) if verdict.reasons else None,
        decision_source="jev_unavailable" if jev_unavail else None,
    )


# Per-request: skip RAI LLM when clear allow (thread-local via request_state).
def set_prechat_verdict(request_id: str, verdict: SafetyVerdict, safety_blob: dict) -> None:
    from request_state import safety_prechat_store

    safety_prechat_store(request_id, verdict.action, safety_blob)


def should_skip_rai_llm() -> bool:
    from request_state import safety_skip_rai_llm

    return safety_skip_rai_llm()


def prechat_safety_blob() -> dict | None:
    from request_state import safety_prechat_blob

    return safety_prechat_blob()


def build_azure_safety_payload(question: str, verdict: SafetyVerdict) -> dict:
    """Legacy shape for Responsible_AI_Agent context."""
    flags = list(verdict.regex_flags)
    return {
        "toxicity_detected": verdict.p_toxic > 0.85 or "toxicity" in flags,
        "pii_detected": verdict.p_pii > 0.85 or "pii" in flags,
        "prompt_injection": verdict.p_injection > 0.85 or "prompt_injection" in flags,
        "flags": flags,
        "risk_score": 2 if verdict.action == "block" else 10,
        "azure_safety_result": {
            "toxicity": "unsafe" if verdict.action == "block" else "safe",
            "jailbreak": "prompt_injection" in flags,
            "self_harm": False,
            "pii": "detected" if "pii" in flags else "none",
        },
        "jev_safety": verdict.jev,
        "safety_verdict": verdict.action,
        "max_p_unsafe": verdict.max_p_unsafe,
    }