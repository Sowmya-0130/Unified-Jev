"""JEV feature flags reload when API_unified is re-imported with override=True .env."""
from __future__ import annotations

import importlib
import os

import API_unified


def test_reload_picks_up_env_flag(monkeypatch):
    """Simulate process restart: skip .env re-read so only os.environ applies."""
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("JEV_ROUTING_ENABLED", "false")
    importlib.reload(API_unified)
    assert API_unified.JEV_ROUTING_ENABLED is False
    monkeypatch.setenv("JEV_ROUTING_ENABLED", "true")
    importlib.reload(API_unified)
    assert API_unified.JEV_ROUTING_ENABLED is True