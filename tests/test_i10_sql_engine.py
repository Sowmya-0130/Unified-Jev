"""I-10: SQL engine must work after aurix_core import (schema load + dispose)."""
from __future__ import annotations

import pytest


def test_db_execute_after_aurix_import():
    import aurix_core
    from metadata import fetch_dataframe_readonly

    try:
        fetch_dataframe_readonly("SELECT 1 AS ok")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"live ODBC unavailable: {exc}")

    out = aurix_core.db_execute_query(query="SELECT 1 AS ok", db_name="SQL")
    assert "An error occurred" not in out
    assert "ok" in out