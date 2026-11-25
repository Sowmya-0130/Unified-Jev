"""Enforce read-only SQL for LLM-generated queries (SELECT / WITH only)."""
import re

_WRITE_DDL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|EXEC|EXECUTE|"
    r"GRANT|REVOKE|REPLACE|UPSERT|CALL|BACKUP|RESTORE|BULK|OPENROWSET|OPENDATASOURCE|"
    r"RECONFIGURE|DENY|KILL|SHUTDOWN|DBCC)\b",
    re.IGNORECASE,
)
_XP_PATTERN = re.compile(r"\b(xp_|sp_msforeachtable|sp_executesql)\b", re.IGNORECASE)


def assert_readonly_sql(query: str) -> None:
    """Raise ValueError if the statement is not a safe read-only SELECT."""
    if not query or not str(query).strip():
        raise ValueError("Empty SQL is not allowed.")
    normalized = re.sub(r"/\*.*?\*/", "", query, flags=re.DOTALL)
    normalized = re.sub(r"--[^\n]*", "", normalized).strip().rstrip(";")
    if not re.match(r"^(WITH\b|SELECT\b)", normalized, re.IGNORECASE):
        raise ValueError("Only SELECT (or WITH … SELECT) read-only queries are permitted.")
    if _WRITE_DDL.search(normalized):
        raise ValueError("Write/DDL/admin SQL is blocked — database access is read-only.")
    if _XP_PATTERN.search(normalized):
        raise ValueError("Extended stored procedures are blocked — database access is read-only.")
    if ";" in normalized:
        parts = [p.strip() for p in normalized.split(";") if p.strip()]
        if len(parts) > 1:
            raise ValueError("Multiple SQL statements are not allowed.")