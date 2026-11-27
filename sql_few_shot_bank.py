"""A6: catalog-aware few-shot selection for Sql_Generator (no live row data)."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

_BANK_PATH = Path(__file__).resolve().parent / "prompts" / "sql_few_shot_bank.json"

_FEW_SHOT_HEADER = (
    "Examples (shape only — use linked schema tables/columns, not example names):\n"
)


def _tags_match_question(tags: list[str], ql: str) -> bool:
    for tag in tags:
        t = tag.lower().replace("_", " ")
        if t in ql or tag.lower() in ql:
            return True
        if tag == "time" and re.search(r"\b20\d{2}\b", ql):
            return True
        if tag == "how many" and "how many" in ql:
            return True
    return False


def catalog_hint_tokens(question: str, catalog: Any) -> set[str]:
    ql = (question or "").lower()
    hits: set[str] = set()
    tables = getattr(catalog, "tables", None) or {}
    display = getattr(catalog, "display_names", None) or {}
    for key in tables:
        sch, tbl = display.get(key, (None, None))
        for token in (tbl, key):
            if token and str(token).lower() in ql:
                hits.add(str(token).lower())
    return hits


def score_entry(entry: Mapping[str, Any], question: str, catalog_hints: set[str]) -> int:
    ql = (question or "").lower()
    score = 0
    tags = list(entry.get("tags") or [])
    if _tags_match_question(tags, ql):
        score += 2 * len(tags)
    pat = entry.get("question_pattern")
    if pat and re.search(str(pat), question or "", re.IGNORECASE):
        score += 6
    for hint in entry.get("catalog_hints") or []:
        if str(hint).lower() in catalog_hints:
            score += 4
    for hint in catalog_hints:
        if hint in ql:
            score += 1
    return score


@lru_cache(maxsize=4)
def load_bank(version: int) -> list[dict[str, Any]]:
    import logging

    raw = json.loads(_BANK_PATH.read_text(encoding="utf-8"))
    file_ver = int(raw.get("version", 0))
    if file_ver != version:
        logging.getLogger(__name__).warning(
            "SQL_FEW_SHOT_BANK_VERSION=%s != bank file version=%s; using file entries",
            version,
            file_ver,
        )
    return list(raw.get("entries") or [])


def select_few_shots(
    question: str,
    *,
    catalog: Any | None = None,
    max_examples: int = 3,
    bank_version: int = 1,
) -> list[dict[str, Any]]:
    entries = load_bank(bank_version)
    hints = catalog_hint_tokens(question, catalog) if catalog is not None else set()
    ranked = sorted(
        ((score_entry(e, question, hints), e) for e in entries),
        key=lambda pair: (-pair[0], str(pair[1].get("id") or "")),
    )
    chosen: list[dict[str, Any]] = []
    for sc, ent in ranked:
        if sc <= 0:
            continue
        chosen.append(ent)
        if len(chosen) >= max_examples:
            break
    if not chosen and entries:
        chosen = [entries[0]]
    return chosen[:max_examples]


def format_few_shot_block(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return ""
    lines = [_FEW_SHOT_HEADER]
    for ent in entries:
        ex = ent.get("example_output") or {}
        lines.append(f"### example_id={ent.get('id')}")
        lines.append(json.dumps(ex, ensure_ascii=False))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n\n"


def prepend_few_shot_examples(
    prompt: str,
    question: str,
    *,
    catalog: Any | None = None,
) -> tuple[str, list[str]]:
    from API_unified import SQL_FEW_SHOT_BANK_VERSION, SQL_FEW_SHOT_ENABLED, SQL_FEW_SHOT_MAX

    if not SQL_FEW_SHOT_ENABLED:
        return prompt, []
    picked = select_few_shots(
        question,
        catalog=catalog,
        max_examples=SQL_FEW_SHOT_MAX,
        bank_version=SQL_FEW_SHOT_BANK_VERSION,
    )
    ids = [str(e.get("id") or "") for e in picked if e.get("id")]
    block = format_few_shot_block(picked)
    if not block:
        return prompt, ids
    return block + prompt, ids


def augment_sql_generator_prompt(
    base: str,
    schema: str,
    user_msg: str,
    question: str,
    *,
    catalog: Any | None = None,
) -> tuple[str, list[str]]:
    core = f"{base}\n{schema}\n\n{user_msg}"
    return prepend_few_shot_examples(core, question, catalog=catalog)