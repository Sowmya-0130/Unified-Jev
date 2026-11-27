"""A7: version stamp for in-process S3 answer cache (invalidate on catalog bump)."""
from __future__ import annotations

import hashlib

_active_version: str | None = None


def _catalog_fingerprint() -> str:
    try:
        from sql_catalog import get_catalog_readonly

        cat = get_catalog_readonly()
        keys = sorted(str(k) for k in (getattr(cat, "tables", None) or {}))
        blob = "|".join(keys[:500])
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    except Exception:  # noqa: BLE001
        return "no-catalog"


def current_s3_cache_version() -> str:
    global _active_version
    from API_unified import JEV_S3_CACHE_VERSION

    base = (JEV_S3_CACHE_VERSION or "").strip() or _catalog_fingerprint()
    _active_version = base
    return base


def stamp_cache_entry(resp: dict) -> dict:
    out = dict(resp)
    out["_s3_cache_version"] = current_s3_cache_version()
    return out


def cache_entry_valid(resp: dict) -> bool:
    if not resp:
        return False
    stored = str(resp.get("_s3_cache_version") or "")
    if not stored:
        return False
    return stored == current_s3_cache_version()