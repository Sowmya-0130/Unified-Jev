"""Live catalog PII tags for S1 input policy and S14 output redaction."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent

_PII_COLUMN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"email", re.I), "email"),
    (re.compile(r"e_mail", re.I), "email"),
    (re.compile(r"phone|mobile|cell|telephone|\btel\b", re.I), "phone"),
    (re.compile(r"ssn|social.?security", re.I), "ssn"),
    (re.compile(r"\baddress\b|street|postal|zip.?code", re.I), "address"),
    (re.compile(r"passport", re.I), "passport"),
    (re.compile(r"date_of_birth|dob|birth_date", re.I), "dob"),
    (re.compile(r"first_name|last_name|full_name|customer_name", re.I), "name"),
    (re.compile(r"national_id|pan_no|aadhaar", re.I), "government_id"),
]

_EXPLICIT_REQUEST = re.compile(
    r"\b("
    r"list|show|give|export|dump|print|display|fetch|provide|send|share|all|every|bulk|each"
    r")\b",
    re.I,
)

_TAG_TERMS: dict[str, list[str]] = {
    "email": ["email", "e-mail", "mail id", "email address", "email addresses"],
    "phone": ["phone", "mobile", "cell", "telephone", "phone number", "phone numbers"],
    "ssn": ["ssn", "social security", "social security number"],
    "address": ["home address", "mailing address", "street address", "addresses"],
    "name": ["personal name", "full name", "first name", "last name"],
    "government_id": ["national id", "aadhaar", "pan number"],
    "passport": ["passport"],
    "dob": ["date of birth", "birth date", "dob"],
}

_profile_cache: dict[str, Any] | None = None
_profile_mtime: float = 0.0


def _profile_path() -> Path:
    from API_unified import DATA_PROFILE_PATH

    p = Path(DATA_PROFILE_PATH)
    return p if p.is_absolute() else _ROOT / p


def tag_column(column_name: str) -> list[str]:
    tags: list[str] = []
    for pat, tag in _PII_COLUMN_PATTERNS:
        if pat.search(column_name):
            tags.append(tag)
    return sorted(set(tags))


def build_profile_from_catalog(catalog) -> dict[str, Any]:
    pii_columns: list[dict[str, str]] = []
    tag_set: set[str] = set()
    for key, cols in catalog.tables.items():
        sch, tbl = catalog.display_names.get(key, key)
        for col in cols:
            tags = tag_column(col)
            if not tags:
                continue
            for t in tags:
                tag_set.add(t)
            pii_columns.append(
                {
                    "schema": sch,
                    "table": tbl,
                    "column": col,
                    "tags": tags,
                }
            )
    return {
        "generated_at": time.time(),
        "pii_columns": pii_columns,
        "pii_tags": sorted(tag_set),
        "column_count": len(pii_columns),
    }


def refresh_data_profile(*, force: bool = False) -> dict[str, Any]:
    global _profile_cache, _profile_mtime
    from sql_catalog import get_catalog

    cat = get_catalog(force=force)
    profile = build_profile_from_catalog(cat)
    path = _profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    _profile_cache = profile
    _profile_mtime = path.stat().st_mtime
    return profile


def load_data_profile(*, force: bool = False) -> dict[str, Any]:
    global _profile_cache, _profile_mtime
    path = _profile_path()
    if not force and _profile_cache is not None:
        return _profile_cache
    if path.is_file():
        if not force and _profile_mtime == path.stat().st_mtime and _profile_cache:
            return _profile_cache
        _profile_cache = json.loads(path.read_text(encoding="utf-8"))
        _profile_mtime = path.stat().st_mtime
        return _profile_cache
    return refresh_data_profile(force=True)


def question_requests_pii(question: str, profile: dict[str, Any] | None = None) -> bool:
    """True when the user explicitly asks for personal identifiers (not aggregate dupoint rows)."""
    q = (question or "").strip()
    if not q:
        return False
    ql = q.lower()
    if not _EXPLICIT_REQUEST.search(q):
        if re.search(r"\b(ssn|social security number|all customer emails?|bulk.*email)\b", ql):
            return True
        return False
    prof = profile if profile is not None else load_data_profile()
    for col in prof.get("pii_columns") or []:
        cn = str(col.get("column") or "").lower().replace("_", " ")
        if len(cn) > 3 and cn in ql:
            return True
        for tag in col.get("tags") or []:
            for term in _TAG_TERMS.get(tag, [tag]):
                if term in ql:
                    return True
    for tag in prof.get("pii_tags") or []:
        for term in _TAG_TERMS.get(tag, []):
            if term in ql:
                return True
    return False


_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def redact_pii_in_text(text: str) -> tuple[str, list[str]]:
    if not text:
        return text, []
    redactions: list[str] = []
    out = text

    def _sub(pattern: re.Pattern[str], label: str, s: str) -> str:
        nonlocal redactions

        def repl(_: re.Match[str]) -> str:
            redactions.append(label)
            return f"[REDACTED:{label}]"

        return pattern.sub(repl, s)

    out = _sub(_EMAIL_RE, "email", out)
    out = _sub(_SSN_RE, "ssn", out)
    out = _sub(_PHONE_RE, "phone", out)
    return out, redactions