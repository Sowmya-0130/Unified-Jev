"""Direct SQL path probe (I-10 prep): same entry as agent tool db_execute_query."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import API_unified

importlib.reload(API_unified)
import aurix_core

importlib.reload(aurix_core)

_QUERIES = [
    ("ping", "SELECT 1 AS ok"),
    ("tables", "SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES ORDER BY 1, 2"),
]


def _preview(text: str, limit: int = 400) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def main() -> int:
    print("sql_probe: db_execute_query (read-only)")
    rc = 0
    for label, sql in _QUERIES:
        print(f"\n--- {label} ---")
        try:
            out = aurix_core.db_execute_query(query=sql, db_name="SQL")
            if "An error occurred" in out or out.startswith("Query blocked"):
                print("FAIL:", _preview(out))
                rc = 1
            else:
                print("OK:", _preview(out))
        except Exception as exc:
            print("EXCEPTION:", type(exc).__name__, _preview(str(exc)))
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())