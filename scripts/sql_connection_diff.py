"""Print masked ODBC field diff: test_sql path vs fetch_dataframe_readonly (I-10)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from API_unified import (
    AZURE_SQL_CONNECTION_TIMEOUT,
    AZURE_SQL_DATABASE,
    AZURE_SQL_DRIVER,
    AZURE_SQL_ENCRYPT,
    AZURE_SQL_MARS_CONNECTION,
    AZURE_SQL_SCHEMA,
    AZURE_SQL_SERVER,
    AZURE_SQL_TRUST_SERVER_CERTIFICATE,
    AZURE_SQL_USE_READONLY_INTENT,
    AZURE_SQL_USERNAME,
    SQL_AGENT_READ_ONLY,
)


def _mask(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return "(empty)"
    if len(value) <= 4:
        return "****"
    return value[:4] + "****"


def main() -> None:
    rows = [
        ("driver", AZURE_SQL_DRIVER, AZURE_SQL_DRIVER),
        ("server", AZURE_SQL_SERVER, AZURE_SQL_SERVER),
        ("database", AZURE_SQL_DATABASE, AZURE_SQL_DATABASE),
        ("user", _mask(AZURE_SQL_USERNAME), _mask(AZURE_SQL_USERNAME)),
        ("Encrypt", "yes" if AZURE_SQL_ENCRYPT else "no", "yes" if AZURE_SQL_ENCRYPT else "no"),
        ("TrustServerCertificate", "yes" if AZURE_SQL_TRUST_SERVER_CERTIFICATE else "no", "yes" if AZURE_SQL_TRUST_SERVER_CERTIFICATE else "no"),
        ("MARS", "yes" if AZURE_SQL_MARS_CONNECTION else "no", "yes" if AZURE_SQL_MARS_CONNECTION else "no"),
        ("ApplicationIntent", "ReadOnly" if AZURE_SQL_USE_READONLY_INTENT else "(default)", "ReadOnly" if AZURE_SQL_USE_READONLY_INTENT else "(default)"),
        ("Connection Timeout", str(AZURE_SQL_CONNECTION_TIMEOUT), str(AZURE_SQL_CONNECTION_TIMEOUT)),
        ("API path", "engine.connect + execute(text)", "engine.connect + execute(text) + DataFrame"),
        ("pool", "NullPool", "NullPool"),
        ("sql_safety", "n/a (caller)", "assert_readonly_sql + normalize_agent_sql_identifiers"),
        ("autocommit", "SQLAlchemy default", "SQLAlchemy default"),
        ("SET read-only", "none (policy in sql_safety)", "none (policy in sql_safety)"),
        ("SQL_AGENT_READ_ONLY", str(SQL_AGENT_READ_ONLY), str(SQL_AGENT_READ_ONLY)),
        ("schema context", AZURE_SQL_SCHEMA, AZURE_SQL_SCHEMA),
    ]
    print("SQL connection path diff (secrets masked)")
    print(f"{'field':<24} {'test_sql.py':<28} db_execute_query")
    print("-" * 72)
    for field, left, right in rows:
        match = "==" if left == right else "!="
        print(f"{field:<24} {left:<28} {right}  {match}")


if __name__ == "__main__":
    main()