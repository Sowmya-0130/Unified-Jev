"""Top-K schema snippets for Sql_Generator (live catalog, no hardcoded table names)."""
from __future__ import annotations

import re

from question_time import date_columns_from_catalog, hint_line, parse_time_window
from sql_catalog import SqlCatalog, TableRef, get_catalog


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]+", text or "") if len(t) > 2}


def _table_words_in_question(question: str) -> set[str]:
    q = (question or "").lower()
    words = set(re.findall(r"\b[a-z][a-z0-9_]*\b", q))
    return {w for w in words if len(w) > 2 and w not in ("the", "and", "use", "who", "what", "how", "top", "are", "for", "from", "with", "last", "months")}


def tables_mentioned_in_question(question: str, catalog: SqlCatalog) -> list[TableRef]:
    """Tables whose catalog name (or schema.name) appears in the question text."""
    q = (question or "").lower()
    q_compact = q.replace(" ", "_").replace("-", "_")
    tw = _table_words_in_question(question)
    found: list[tuple[float, TableRef]] = []
    for key, (sch, tbl) in catalog.display_names.items():
        tl = tbl.lower()
        sl = sch.lower()
        score = 0.0
        if tl in q_compact or tl.replace("_", " ") in q:
            score += 100.0
        if tl in tw:
            score += 60.0
        if sl in tw and tl in tw:
            score += 40.0
        if f"{sl}_{tl}" in q_compact.replace(".", "_"):
            score += 80.0
        if score <= 0:
            continue
        cols = catalog.columns(sch, tbl)
        col_tok = {c.lower() for c in cols}
        score += len(tw & col_tok) * 8
        found.append((score, TableRef(key[0], key[1])))
    found.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in found]


def score_tables(question: str, catalog: SqlCatalog) -> list[tuple[float, TableRef]]:
    qtok = _tokens(question)
    tw = _table_words_in_question(question)
    scored: list[tuple[float, TableRef]] = []
    for (sch, tbl) in catalog.tables:
        ref = TableRef(sch, tbl)
        cols = catalog.columns(sch, tbl)
        col_tok = {c.lower() for c in cols}
        names = _tokens(sch) | _tokens(tbl) | {sch.lower(), tbl.lower()}
        hint = 0.0
        qlower = (question or "").lower()
        if tbl.lower() in tw:
            hint += 50.0
        if tbl.lower() in qlower.replace(" ", "_").replace("-", "_"):
            hint += 80.0
        elif tbl.lower().replace("_", " ") in qlower:
            hint += 80.0
        if sch.lower() in qlower.replace(" ", "_"):
            hint += 40.0
        if catalog.is_shadow_table(sch, tbl):
            hint -= 200.0
        overlap = len(qtok & names) * 3 + len(qtok & col_tok) * 2 + len(tw & col_tok) * 5 + hint
        if overlap > 0:
            scored.append((float(overlap), ref))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def _shared_join_columns(catalog: SqlCatalog, key_a: tuple[str, str], key_b: tuple[str, str]) -> list[str]:
    ca = {c.lower(): c for c in catalog.columns(*key_a)}
    cb = {c.lower(): c for c in catalog.columns(*key_b)}
    return sorted({ca[k] for k in ca.keys() & cb.keys()})


def _join_lines(catalog: SqlCatalog, refs: list[TableRef]) -> list[str]:
    keys = [(r.schema.lower(), r.name.lower()) for r in refs]
    lines: list[str] = []
    seen: set[str] = set()
    for edge in catalog.join_edges:
        if edge.parent not in keys or edge.ref not in keys:
            continue
        left = f"{catalog.bracketed(*edge.parent)}.{edge.parent_column}"
        right = f"{catalog.bracketed(*edge.ref)}.{edge.ref_column}"
        sig = f"{left}={right}"
        if sig in seen:
            continue
        seen.add(sig)
        lines.append(f"- JOIN {left} = {right}")
    for i, ka in enumerate(keys):
        for kb in keys[i + 1 :]:
            shared = _shared_join_columns(catalog, ka, kb)
            for col in shared:
                if not (col.lower().endswith("_id") or "id" == col.lower() or col.lower().endswith("id")):
                    continue
                left = f"{catalog.bracketed(*ka)}.{col}"
                right = f"{catalog.bracketed(*kb)}.{col}"
                sig = f"{left}={right}"
                if sig in seen:
                    continue
                seen.add(sig)
                lines.append(f"- likely JOIN {left} = {right}")
    return lines[:12]


def linked_schema_block(question: str, *, k: int, catalog: SqlCatalog | None = None) -> str:
    catalog = catalog or get_catalog()
    forced = tables_mentioned_in_question(question, catalog)
    ranked = score_tables(question, catalog)
    merged: list[TableRef] = []
    seen: set[tuple[str, str]] = set()
    for ref in forced + [r for _, r in ranked]:
        key = ref.key()
        if catalog.is_shadow_table(ref.schema, ref.name):
            continue
        if key in seen:
            continue
        seen.add(key)
        merged.append(ref)
    nouns = _table_words_in_question(question)
    must_keep = [r for r in merged if r.name.lower() in nouns or r.schema.lower() in nouns]
    limit = max(k, len(must_keep), min(len(merged), k + len(nouns)))
    merged = (must_keep + [r for r in merged if r not in must_keep])[:limit]
    lines: list[str] = ["**Linked schema (canonical 2-part names only)**:"]
    keys_for_dates: list[tuple[str, str]] = []
    for ref in merged:
        cols = sorted(catalog.columns(ref.schema, ref.name))
        col_preview = ", ".join(cols[:20])
        if len(cols) > 20:
            col_preview += ", …"
        lines.append(f"- {catalog.bracketed(ref.schema, ref.name)}: {col_preview}")
        keys_for_dates.append((ref.schema, ref.name))
    joins = _join_lines(catalog, merged)
    if joins:
        lines.append("**Likely joins (shared keys from catalog)**:")
        lines.extend(joins)
    tw = parse_time_window(question)
    if tw:
        dcols = date_columns_from_catalog(question, catalog, keys_for_dates)
        lines.append(hint_line(tw, dcols))
    lines.append(
        "Rules: SELECT/WITH read-only only; use exactly these bracketed names; no dbo.Schema.Table; always set sql_query when tables are listed."
    )
    return "\n".join(lines)