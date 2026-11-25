"""SQL smoke test — uses only API_unified + metadata (no hardcoded credentials)."""
from sqlalchemy import text

from API_unified import AZURE_SQL_DRIVER, AZURE_SQL_DRIVER_REQUESTED, AZURE_SQL_SCHEMA, SQL_AGENT_READ_ONLY
from metadata import engine
from odbc_driver import describe_driver_binding

print(describe_driver_binding(AZURE_SQL_DRIVER))
if AZURE_SQL_DRIVER_REQUESTED and AZURE_SQL_DRIVER_REQUESTED != AZURE_SQL_DRIVER:
    print(f"  Requested in .env: {AZURE_SQL_DRIVER_REQUESTED!r}")
print(f"  SQL_AGENT_READ_ONLY={SQL_AGENT_READ_ONLY}")

with engine.connect() as conn:
    result = conn.execute(
        text(
            "SELECT TOP 3 table_name FROM information_schema.tables "
            "WHERE table_schema = :schema"
        ),
        {"schema": AZURE_SQL_SCHEMA},
    )
    for row in result:
        print("  Table:", row[0])
print("SQL connection OK")