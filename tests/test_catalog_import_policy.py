"""Production code must not call get_catalog(live=False)."""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SKIP_DIRS = {"tests", ".venv", "node_modules", ".git", ".cache"}
_PATTERN = re.compile(r"get_catalog\s*\(\s*[^)]*\blive\s*=\s*False", re.IGNORECASE)


def test_no_live_false_get_catalog_outside_tests():
    offenders: list[str] = []
    for path in _ROOT.rglob("*.py"):
        parts = set(path.relative_to(_ROOT).parts)
        if parts & _SKIP_DIRS:
            continue
        if path.name == "sql_catalog.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if _PATTERN.search(text):
            offenders.append(str(path.relative_to(_ROOT)))
    assert not offenders, f"get_catalog(live=False) in production paths: {offenders}"