"""SQL object catalog (live load; production never uses test fixtures)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


class CatalogUnavailableError(RuntimeError):
    """Live catalog required but not loadable and no prior cache exists."""


@dataclass(frozen=True)
class TableRef:
    schema: str
    name: str

    def bracketed(self) -> str:
        return f"[{self.schema}].[{self.name}]"

    def key(self) -> tuple[str, str]:
        return (self.schema.lower(), self.name.lower())


@dataclass(frozen=True)
class JoinEdge:
    parent: tuple[str, str]
    parent_column: str
    ref: tuple[str, str]
    ref_column: str


@dataclass
class SqlCatalog:
    tables: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    display_names: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)
    join_edges: list[JoinEdge] = field(default_factory=list)
    shadow_keys: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    shadow_targets: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)

    def columns(self, schema: str, table: str) -> set[str]:
        key = self.resolve_table_key(schema, table)
        return set(self.tables.get(key, set()))

    def has_table(self, schema: str, table: str) -> bool:
        key = (schema.lower(), table.lower())
        if key in self.shadow_targets:
            key = self.shadow_targets[key]
        return key in self.tables

    def is_shadow_table(self, schema: str, table: str) -> bool:
        return (schema.lower(), table.lower()) in self.shadow_keys

    def resolve_table_key(self, schema: str, table: str) -> tuple[str, str]:
        key = (schema.lower(), table.lower())
        return self.shadow_targets.get(key, key)

    def bracketed(self, schema: str, table: str) -> str:
        sch, tbl = self.resolve_table_key(schema, table)
        sch, tbl = self.display_names.get((sch, tbl), (sch, tbl))
        return f"[{sch}].[{tbl}]"

    def all_bracketed_names(self) -> list[str]:
        out: list[str] = []
        for key in sorted(self.tables.keys()):
            if key in self.shadow_keys:
                continue
            sch, tbl = self.display_names.get(key, key)
            out.append(f"[{sch}].[{tbl}]")
        return out

    def candidate_tables_with_columns(self, cols: Iterable[str]) -> list[str]:
        need = {c.lower() for c in cols}
        hits: list[str] = []
        for key in self.tables:
            if key in self.shadow_keys:
                continue
            colset = self.tables[key]
            have = {c.lower() for c in colset}
            if need <= have:
                sch, tbl = self.display_names.get(key, key)
                hits.append(f"[{sch}].[{tbl}]")
        return sorted(hits)


def _apply_shadow_metadata(catalog: SqlCatalog) -> SqlCatalog:
    shadow_targets: dict[tuple[str, str], tuple[str, str]] = {}
    for (sch, tbl), cols in catalog.tables.items():
        if sch.lower() != "dbo" or "." not in tbl:
            continue
        parts = tbl.split(".", 1)
        if len(parts) != 2:
            continue
        rsch, rtbl = parts[0], parts[1]
        rkey = (rsch.lower(), rtbl.lower())
        if rkey not in catalog.tables:
            continue
        real_cols = {c.lower() for c in catalog.tables[rkey]}
        enc_cols = {c.lower() for c in cols}
        if enc_cols <= real_cols:
            shadow_targets[(sch.lower(), tbl.lower())] = rkey
    catalog.shadow_targets = shadow_targets
    catalog.shadow_keys = frozenset(shadow_targets.keys())
    return catalog


_catalog_cache: SqlCatalog | None = None
_catalog_loaded_at: float = 0.0
_catalog_load_lock = __import__("threading").Lock()


def load_live_catalog(*, force: bool = False) -> SqlCatalog:
    """Read-only catalog from sys.schemas / sys.tables / sys.columns."""
    import time

    from API_unified import SQL_CATALOG_TTL_SEC

    global _catalog_cache, _catalog_loaded_at
    now = time.time()
    if _catalog_cache is not None and not force and (now - _catalog_loaded_at) < SQL_CATALOG_TTL_SEC:
        return _catalog_cache

    with _catalog_load_lock:
        if _catalog_cache is not None and not force and (now - _catalog_loaded_at) < SQL_CATALOG_TTL_SEC:
            return _catalog_cache

        from metadata import fetch_dataframe_readonly

        sql = """
    SELECT s.name AS schema_name, t.name AS table_name, c.name AS column_name
    FROM sys.tables t
    INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
    INNER JOIN sys.columns c ON c.object_id = t.object_id
  ORDER BY s.name, t.name, c.column_id
    """
        try:
            df = fetch_dataframe_readonly(sql)
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.getLogger("aurix.sql_catalog").warning("live catalog load failed: %s", exc)
            if _catalog_cache is not None and _catalog_cache.tables:
                return _catalog_cache
            raise CatalogUnavailableError(
                "Live SQL catalog unavailable (ODBC failed and no cached catalog). "
                "Retry when the database is reachable."
            ) from exc

        tables: dict[tuple[str, str], set[str]] = {}
        display: dict[tuple[str, str], tuple[str, str]] = {}
        for row in df.itertuples(index=False):
            sch = str(row.schema_name)
            tbl = str(row.table_name)
            key = (sch.lower(), tbl.lower())
            tables.setdefault(key, set()).add(str(row.column_name))
            display.setdefault(key, (sch, tbl))
        joins: list[JoinEdge] = []
        try:
            jdf = fetch_dataframe_readonly(
                """
            SELECT
                OBJECT_SCHEMA_NAME(fk.parent_object_id) AS parent_schema,
                OBJECT_NAME(fk.parent_object_id) AS parent_table,
                COL_NAME(fkc.parent_object_id, fkc.parent_column_id) AS parent_column,
                OBJECT_SCHEMA_NAME(fk.referenced_object_id) AS ref_schema,
                OBJECT_NAME(fk.referenced_object_id) AS ref_table,
                COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) AS ref_column
            FROM sys.foreign_keys fk
            INNER JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
            """
            )
            for row in jdf.itertuples(index=False):
                pk = (str(row.parent_schema).lower(), str(row.parent_table).lower())
                rk = (str(row.ref_schema).lower(), str(row.ref_table).lower())
                if pk in tables and rk in tables:
                    joins.append(
                        JoinEdge(
                            parent=pk,
                            parent_column=str(row.parent_column),
                            ref=rk,
                            ref_column=str(row.ref_column),
                        )
                    )
        except Exception:  # noqa: BLE001
            pass
        _catalog_cache = _apply_shadow_metadata(
            SqlCatalog(tables=tables, display_names=display, join_edges=joins)
        )
        _catalog_loaded_at = now
        return _catalog_cache


def get_catalog_readonly() -> SqlCatalog:
    """Request/query path: never ODBC; use warmed cache only."""
    if _catalog_cache is not None and _catalog_cache.tables:
        return _catalog_cache
    raise CatalogUnavailableError(
        "SQL catalog not warm yet. Call catalog_runtime.bootstrap_catalog() at startup."
    )


def get_catalog(*, force: bool = False, allow_load: bool = True) -> SqlCatalog:
    """Live catalog. Hot path should use get_catalog_readonly()."""
    if force:
        return load_live_catalog(force=True)
    if _catalog_cache is not None and not force:
        try:
            from API_unified import SQL_CATALOG_MIN_TABLES

            if len(_catalog_cache.tables) >= SQL_CATALOG_MIN_TABLES:
                return _catalog_cache
        except Exception:  # noqa: BLE001
            return _catalog_cache
    if not allow_load:
        return get_catalog_readonly()
    cat = load_live_catalog(force=False)
    try:
        from API_unified import SQL_CATALOG_MIN_TABLES

        if len(cat.tables) < SQL_CATALOG_MIN_TABLES:
            cat = load_live_catalog(force=True)
    except CatalogUnavailableError:
        raise
    except Exception:  # noqa: BLE001
        pass
    return cat


def refresh_catalog() -> SqlCatalog:
    return load_live_catalog(force=True)