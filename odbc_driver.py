"""Resolve installed Microsoft ODBC Driver for SQL Server (marketing 17/18 vs DLL 2017/2018 file version)."""
from __future__ import annotations

import logging
import re
from typing import Sequence

import pyodbc

_log = logging.getLogger(__name__)

_PREFERRED: Sequence[str] = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13.1 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "ODBC Driver 11 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server",
)


def installed_sql_server_drivers() -> list[str]:
    return [d for d in pyodbc.drivers() if "sql" in d.lower() or "server" in d.lower()]


def _normalize_requested(name: str) -> str:
    n = (name or "").strip()
    if not n:
        return ""
    # e.g. "18" or "driver 18" -> full marketing name
    m = re.search(r"\b(1[1-8])\b", n)
    if m and "odbc driver" not in n.lower():
        return f"ODBC Driver {m.group(1)} for SQL Server"
    return n


def resolve_odbc_driver(requested: str | None = None) -> str:
    """
    Pick the ODBC driver name pyodbc expects (marketing label, not DLL file version).

    Windows may show file version 2018.0187.0001.01 for marketing "ODBC Driver 18" — that is correct.
    """
    installed = pyodbc.drivers()
    if not installed:
        raise RuntimeError("pyodbc reports no ODBC drivers on this machine.")

    want = _normalize_requested(requested or "")
    if want:
        if want in installed:
            return want
        low = want.lower()
        for d in installed:
            if d.lower() == low:
                return d

    for preferred in _PREFERRED:
        if preferred in installed:
            if want and preferred != want:
                _log.warning(
                    "AZURE_SQL_DRIVER=%r not installed; using %r. Installed: %s",
                    requested,
                    preferred,
                    ", ".join(installed_sql_server_drivers()),
                )
            return preferred

    sqlish = installed_sql_server_drivers()
    if sqlish:
        _log.warning("Using fallback ODBC driver %r", sqlish[0])
        return sqlish[0]

    raise RuntimeError(
        "No Microsoft ODBC Driver for SQL Server found. Install 'ODBC Driver 18 for SQL Server' "
        f"(DLL file version often starts with 2018.x). Installed drivers: {installed!r}"
    )


def describe_driver_binding(resolved: str) -> str:
    """Short note for diagnostics (DLL 2018.x = Driver 18 marketing version)."""
    if "18" in resolved:
        return (
            f"Using {resolved!r} — on Windows, DLL file version 2018.xxx is normal for Driver 18."
        )
    return f"Using ODBC driver {resolved!r}."