"""Align natural-language SQL questions with live catalog tokens (no SQL hardcoding)."""
from __future__ import annotations

import re


def normalize_question_for_sql(question: str) -> str:
    """
    Expand common typos/aliases so schema linking and validation see catalog names.
    Original user wording is unchanged elsewhere; use only for SQL path + validation.
    """
    q = (question or "").strip()
    if not q:
        return q

    if re.search(r"\bdupont\b", q, re.IGNORECASE) and not re.search(
        r"\bdupoint\b", q, re.IGNORECASE
    ):
        q = re.sub(r"\bdupont\b", "dupoint", q, flags=re.IGNORECASE)

    ql = q.lower()
    if "dupoint" in ql and "dupoint_email_data" not in ql.replace("-", "_"):
        if re.search(r"\borders?\b", ql):
            q = f"{q} dupoint_email_data Orders"

    if re.search(r"\b(total|sum|amount)\b", ql) and "total_amount" not in ql.replace(" ", "_"):
        q = f"{q} Total_Amount"

    ql = q.lower()
    if re.search(r"\bgcc\b", ql) and "gcc_hackathon_clients" not in ql.replace(" ", "_").replace("-", "_"):
        q = f"{q} GCC_Hackathon_clients"

    q = _catalog_token_hints(q)
    return q


def _catalog_token_hints(q: str) -> str:
    """When question names a dataset token, append matching live catalog table if missing."""
    ql = q.lower()
    try:
        from sql_catalog import get_catalog_readonly

        cat = get_catalog_readonly()
    except Exception:
        return q
    for needle in ("aon", "mutual"):
        if needle not in ql:
            continue
        for key in cat.tables:
            sch, tbl = cat.display_names.get(key, key)
            blob = f"{sch} {tbl}".lower()
            if needle not in blob:
                continue
            compact = ql.replace(" ", "_").replace("-", "_")
            if tbl.lower().replace(" ", "_") in compact or f"{sch.lower()}_{tbl.lower()}" in compact:
                continue
            q = f"{q} {sch} {tbl}"
            break
    return q