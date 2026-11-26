"""Column validation: qualified per alias; unambiguous unqualified only."""
from __future__ import annotations

from sql_catalog import SqlCatalog
from sql_pipeline import SqlValidationResult


def validate_query_columns(sql: str, catalog: SqlCatalog) -> SqlValidationResult | None:
    try:
        import sqlglot
        from sqlglot import exp, parse_one
    except ImportError:
        return None

    from API_unified import SQL_DEFAULT_SCHEMA

    try:
        tree = parse_one(sql, read="tsql")
    except Exception:  # noqa: BLE001
        return None

    output_aliases: set[str] = set()
    for node in tree.find_all(exp.Select):
        for expr in node.expressions or []:
            if isinstance(expr, exp.Alias) and expr.alias:
                output_aliases.add(str(expr.alias).strip("[]").lower())
    for node in tree.find_all(exp.Order):
        for expr in node.expressions or []:
            ordered = expr.this if isinstance(expr, exp.Ordered) else expr
            if isinstance(ordered, exp.Column) and ordered.name and not ordered.table:
                output_aliases.add(str(ordered.name).strip("[]").lower())

    alias_map: dict[str, tuple[str, str]] = {}
    for node in tree.find_all(exp.Table):
        sch = (node.db or node.catalog or SQL_DEFAULT_SCHEMA or "").strip("[]")
        tbl = (node.name or "").strip("[]")
        if not tbl:
            continue
        key = catalog.resolve_table_key(sch, tbl)
        if not catalog.has_table(key[0], key[1]):
            continue
        if node.alias:
            alias_map[str(node.alias).strip("[]").lower()] = key
        alias_map[tbl.lower()] = key
        alias_map[f"{sch.lower()}.{tbl.lower()}"] = key

    if not alias_map:
        return None

    for col in tree.find_all(exp.Column):
        if isinstance(col.this, exp.Star):
            continue
        cname = (col.name or "").strip("[]")
        if not cname:
            continue
        qual = (col.table or "").strip("[]").lower() if col.table else ""
        if not qual and cname.lower() in output_aliases:
            continue
        if qual:
            tkey = alias_map.get(qual)
            if not tkey:
                return SqlValidationResult(
                    False,
                    error_class="unknown_alias",
                    message=f"Unknown table alias '{qual}' for column {cname}",
                    identifier=qual,
                )
            have = {x.lower() for x in catalog.columns(*tkey)}
            if cname.lower() not in have:
                return SqlValidationResult(
                    False,
                    error_class="missing_column",
                    message=f"Column {qual}.{cname} not in {catalog.bracketed(*tkey)}",
                    candidates=catalog.candidate_tables_with_columns([cname]),
                    identifier=f"{qual}.{cname}",
                )
            continue
        owners: list[str] = []
        for tkey in set(alias_map.values()):
            have = {x.lower() for x in catalog.columns(*tkey)}
            if cname.lower() in have:
                owners.append(catalog.bracketed(*tkey))
        if not owners:
            return SqlValidationResult(
                False,
                error_class="missing_column",
                message=f"Column {cname} not found on any joined table",
                candidates=catalog.candidate_tables_with_columns([cname]),
                identifier=cname,
            )
        if len(owners) > 1:
            return SqlValidationResult(
                False,
                error_class="ambiguous_column",
                message=f"Column {cname} is ambiguous across {', '.join(owners)}",
                candidates=owners,
                identifier=cname,
            )
    return None