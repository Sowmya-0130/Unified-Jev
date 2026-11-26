"""sqlglot T-SQL validation against live catalog (Q2)."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sql_catalog import SqlCatalog

from sql_pipeline import SqlValidationResult


def validate_with_sqlglot(sql: str, catalog: "SqlCatalog") -> SqlValidationResult | None:
    try:
        import sqlglot
        from sqlglot import exp, parse_one
    except ImportError:
        return None

    raw = (sql or "").strip().rstrip(";")
    if not raw:
        return SqlValidationResult(False, error_class="empty", message="Empty SQL")
    try:
        tree = parse_one(raw, read="tsql")
    except Exception as exc:  # noqa: BLE001
        return SqlValidationResult(False, error_class="parse", message=str(exc)[:200])

    normalized = tree.sql(dialect="tsql")
    tables = [t for t in tree.find_all(exp.Table)]
    for node in tables:
        parts = [p for p in (node.catalog, node.db, node.name) if p]
        if len(parts) >= 3:
            resolved: str | None = None
            if len(parts) == 3 and parts[0].lower() == "dbo":
                sch, tbl = parts[1], parts[2]
                if catalog.has_table(sch, tbl):
                    resolved = f"[{sch}].[{tbl}]"
                elif catalog.has_table("dbo", f"{sch}.{tbl}"):
                    resolved = f"[dbo].[{sch}.{tbl}]"
            if not resolved:
                cands = catalog.all_bracketed_names()[:12]
                return SqlValidationResult(
                    False,
                    error_class="invalid_identifier",
                    message="Three- or four-part table name not allowed",
                    candidates=cands[:12],
                    identifier=".".join(parts),
                )
            sch_m = re.match(r"\[(.+)\]\.\[(.+)\]", resolved)
            if sch_m:
                node.set("catalog", None)
                node.set("db", exp.to_identifier(sch_m.group(1), quoted=True))
                node.set("this", exp.to_identifier(sch_m.group(2), quoted=True))
            continue
        sch = (node.db or node.catalog or "").strip("[]")
        tbl = (node.name or "").strip("[]")
        if not tbl:
            continue
        if not sch:
            from API_unified import SQL_DEFAULT_SCHEMA

            sch = SQL_DEFAULT_SCHEMA
        if not catalog.has_table(sch, tbl):
            if sch != SQL_DEFAULT_SCHEMA and catalog.has_table(SQL_DEFAULT_SCHEMA, tbl):
                sch = SQL_DEFAULT_SCHEMA
            else:
                continue
        if not catalog.has_table(sch, tbl):
            return SqlValidationResult(
                False,
                error_class="unknown_table",
                message=f"Unknown [{sch}].[{tbl}]",
                candidates=catalog.all_bracketed_names()[:12],
            )
        bracketed = f"[{sch}].[{tbl}]"
        node.set("db", exp.to_identifier(sch, quoted=True))
        node.set("this", exp.to_identifier(tbl, quoted=True))

    return SqlValidationResult(True, normalized_sql=tree.sql(dialect="tsql"))