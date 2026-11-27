from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_stale_cache_rejected(monkeypatch):
    monkeypatch.setattr("API_unified.JEV_S3_CACHE_VERSION", "v2", raising=False)
    from jev_s3_cache_version import cache_entry_valid, current_s3_cache_version, stamp_cache_entry

    current_s3_cache_version()
    stamped = stamp_cache_entry({"llm_answer": "x"})
    monkeypatch.setattr("API_unified.JEV_S3_CACHE_VERSION", "v3", raising=False)
    current_s3_cache_version()
    assert not cache_entry_valid(stamped)


def test_fresh_stamped_valid(monkeypatch):
    monkeypatch.setattr("API_unified.JEV_S3_CACHE_VERSION", "fixed", raising=False)
    from jev_s3_cache_version import cache_entry_valid, current_s3_cache_version, stamp_cache_entry

    current_s3_cache_version()
    stamped = stamp_cache_entry({"query_answer": "ok"})
    assert cache_entry_valid(stamped)


def test_catalog_fingerprint_changes(monkeypatch):
    from jev_s3_cache_version import _catalog_fingerprint

    monkeypatch.setattr(
        "sql_catalog.get_catalog_readonly",
        lambda: SimpleNamespace(tables={"a": 1}, display_names={}),
        raising=True,
    )
    a = _catalog_fingerprint()
    monkeypatch.setattr(
        "sql_catalog.get_catalog_readonly",
        lambda: SimpleNamespace(tables={"a": 1, "b": 2}, display_names={}),
        raising=True,
    )
    b = _catalog_fingerprint()
    assert a != b