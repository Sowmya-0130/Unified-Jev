## SQL
import logging
import threading
import time
from pathlib import Path
from typing import Callable, TypeVar

import pyodbc
from azure.search.documents import SearchClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool

from API_unified import *

_log = logging.getLogger(__name__)
_odbc_lock = threading.RLock()
T = TypeVar("T")


search_client = SearchClient(
    endpoint=AZURE_SEARCH_SERVICE_ENDPOINT,
    index_name=IN_Name,
    credential=azure_search_credential,
)
                            
# Parameters — from .env via API_unified (AZURE_SQL_*)
server = AZURE_SQL_SERVER
database = AZURE_SQL_DATABASE
username = AZURE_SQL_USERNAME
password = AZURE_SQL_PASSWORD
driver = AZURE_SQL_DRIVER
encoding = "ISO-8859-1"
category_name = AZURE_SQL_SCHEMA
#hr
def _build_odbc_str(*, read_only_intent: bool = False) -> str:
    """Build fresh ODBC string from current .env-backed vars (password special chars safe)."""
    encrypt = "yes" if AZURE_SQL_ENCRYPT else "no"
    trust = "yes" if AZURE_SQL_TRUST_SERVER_CERTIFICATE else "no"
    parts = [
        f"DRIVER={{{driver}}};",
        f"SERVER={server};",
        f"DATABASE={database};",
        f"UID={username};",
        f"PWD={password};",
        f"Encrypt={encrypt};",
        f"TrustServerCertificate={trust};",
        f"Connection Timeout={AZURE_SQL_CONNECTION_TIMEOUT};",
    ]
    if AZURE_SQL_MARS_CONNECTION:
        parts.append("MARS_Connection=Yes;")
    if read_only_intent and AZURE_SQL_USE_READONLY_INTENT:
        parts.append("ApplicationIntent=ReadOnly;")
    return "".join(parts)


def _pyodbc_connect(*, read_only_intent: bool = False, attempts: int = 1):
    """Direct ODBC connect (single attempt by default — outer layers own retry loops)."""
    last_err: Exception | None = None
    tries = max(1, attempts)
    for attempt in range(tries):
        try:
            with _odbc_lock:
                return pyodbc.connect(_build_odbc_str(read_only_intent=read_only_intent))
        except pyodbc.Error as exc:
            last_err = exc
            if tries > 1:
                _log.warning("ODBC connect attempt %s/%s failed: %s", attempt + 1, tries, exc)
                time.sleep(0.75 * (attempt + 1))
    assert last_err is not None
    raise last_err


# NullPool = new physical connection per checkout (avoids stale ODBC pool after graphrag)
def _engine_creator():
    return _pyodbc_connect(read_only_intent=False)


engine = create_engine(
    "mssql+pyodbc://",
    creator=_engine_creator,
    poolclass=NullPool,
)


def warm_odbc_connection() -> bool:
    """Lightweight ping; returns True on success (optional at startup)."""
    try:
        with _odbc_lock:
            conn = pyodbc.connect(_build_odbc_str(read_only_intent=False))
            try:
                conn.cursor().execute("SELECT 1")
                return True
            finally:
                conn.close()
    except pyodbc.Error as exc:
        _log.debug("ODBC warm failed: %s", exc)
        return False


def fetch_dataframe_readonly(sql: str):
    """Run a validated SELECT (NullPool engine — same path as test_sql.py)."""
    import pandas as pd
    from sqlalchemy import text

    from sql_safety import assert_readonly_sql, normalize_agent_sql_identifiers

    assert_readonly_sql(sql)
    sql = normalize_agent_sql_identifiers(sql)
    last_err: Exception | None = None
    attempts = max(1, AZURE_SQL_ODBC_RETRIES)
    for attempt in range(attempts):
        try:
            with _odbc_lock:
                with engine.connect() as conn:
                    return pd.read_sql(text(sql), conn)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            try:
                from jev_trace import bump_sql_attempt

                bump_sql_attempt()
            except ImportError:
                pass
            _log.warning("read_sql attempt %s failed: %s", attempt + 1, exc)
            dispose_sql_engine()
            if attempt + 1 < attempts:
                time.sleep(1.0 * (attempt + 1))
    assert last_err is not None
    raise last_err


def dispose_sql_engine() -> None:
    """Release ODBC handles after heavy introspection (fixes HY000 on Windows)."""
    try:
        engine.dispose(close=True)
    except Exception as exc:  # noqa: BLE001
        _log.debug("engine.dispose failed: %s", exc)


def run_sql_with_retry(operation: Callable[[], T], *, attempts: int | None = None) -> T:
    """Run a DB operation with retries (ODBC HY000 after long AutoGen runs on Windows)."""
    tries = max(1, attempts or AZURE_SQL_ODBC_RETRIES)
    last_err: Exception | None = None
    for attempt in range(tries):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            try:
                from jev_trace import bump_sql_attempt

                bump_sql_attempt()
            except ImportError:
                pass
            _log.warning("SQL operation attempt %s/%s failed: %s", attempt + 1, tries, exc)
            if attempt + 1 < tries:
                time.sleep(1.25 * (attempt + 1))
    assert last_err is not None
    raise last_err

# Step 2: Fetch tables from the specified schema dynamically
def get_schema_tables(engine, schema_name):
    inspector = inspect(engine)
    tables = inspector.get_table_names(schema=schema_name)
    
    schema_details = ""
    for table_name in tables:
        columns = inspector.get_columns(table_name, schema=schema_name)
        schema = (
            f'schema = "{schema_name}", '
            f'table_name = "[{schema_name}].[{table_name}]", '
            f"{table_name}_table = Table(\n"
        )
        for column in columns:
            col_name = column['name']
            col_type = column['type']
            primary_key = "primary_key=True" if column.get("primary_key", False) else ""
            nullable = "nullable=False" if not column["nullable"] else ""
            schema += f'    Column("{col_name}", {col_type}, {primary_key} {nullable}),\n'
        schema = schema.rstrip(',\n')  # Remove the last comma and newline
        schema += "\n)\n\n"
        schema_details += schema

    return schema_details

# Loaded on demand via ensure_table_schemas_loaded() (fast Streamlit first paint).
all_table_schemas: str = ""


def _schema_cache_path() -> Path:
    return Path(SQL_SCHEMA_CACHE_PATH)


def _read_schema_cache() -> str | None:
    if not SQL_SCHEMA_CACHE_ENABLED:
        return None
    path = _schema_cache_path()
    if not path.is_file():
        return None
    age = time.time() - path.stat().st_mtime
    if age > SQL_SCHEMA_CACHE_MAX_AGE_SEC:
        return None
    try:
        text = path.read_text(encoding="utf-8")
        return text if text.strip() else None
    except OSError as exc:
        _log.warning("Could not read SQL schema cache %s: %s", path, exc)
        return None


def _write_schema_cache(text: str) -> None:
    if not SQL_SCHEMA_CACHE_ENABLED or not text.strip():
        return
    path = _schema_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        _log.warning("Could not write SQL schema cache %s: %s", path, exc)


def ensure_table_schemas_loaded(*, live: bool = True) -> str:
    """Fetch SQL table metadata once per process (optional disk cache)."""
    global all_table_schemas
    if all_table_schemas:
        return all_table_schemas

    cached = _read_schema_cache()
    if cached is not None:
        all_table_schemas = cached
        _log.info("SQL schemas loaded from cache (%s chars)", len(all_table_schemas))
        return all_table_schemas

    if not SQL_SCHEMA_FORCE_LIVE_REFRESH:
        stale = _read_schema_cache_ignore_age()
        if stale is not None:
            all_table_schemas = stale
            _log.info(
                "SQL schemas loaded from stale cache (%s chars); "
                "set SQL_SCHEMA_FORCE_LIVE_REFRESH=true to refresh via ODBC",
                len(all_table_schemas),
            )
            return all_table_schemas

    if not live:
        _log.info("Skipping live SQL introspection (cache miss; live=False).")
        return all_table_schemas

    try:
        all_table_schemas = get_schema_tables(engine, category_name)
        _write_schema_cache(all_table_schemas)
        dispose_sql_engine()
    except Exception as _schema_err:  # noqa: BLE001
        _log.error("SQL schema introspection failed: %s", _schema_err)
        # Stale cache beats empty schema when ODBC blips (common on Windows after long runs).
        stale = _read_schema_cache_ignore_age()
        if stale is not None:
            all_table_schemas = stale
            _log.warning("Using stale SQL schema cache after introspection failure")
        else:
            all_table_schemas = ""
        dispose_sql_engine()
    return all_table_schemas


def _read_schema_cache_ignore_age() -> str | None:
    path = _schema_cache_path()
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        return text if text.strip() else None
    except OSError:
        return None
# Eryl / semantic hints: Vector_Data, Web_Search_Data from API_unified / .env
