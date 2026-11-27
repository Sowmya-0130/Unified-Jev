from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from sql_few_shot_bank import augment_sql_generator_prompt, score_entry, select_few_shots
from sql_generator_prompt import SQL_GENERATOR_BASE

_BANK = Path(__file__).resolve().parent.parent / "prompts" / "sql_few_shot_bank.json"


def test_select_scalar_year_deterministic():
    cat = SimpleNamespace(
        tables={"dbo.T1": {}},
        display_names={"dbo.T1": ("dbo", "SampleOrders")},
    )
    q = "What was the total amount in 2025?"
    ids1 = [e["id"] for e in select_few_shots(q, catalog=cat, max_examples=3)]
    ids2 = [e["id"] for e in select_few_shots(q, catalog=cat, max_examples=3)]
    assert ids1 == ids2
    assert "scalar_sum_with_year" in ids1


def test_disabled_flag_unchanged_prompt(monkeypatch):
    monkeypatch.setattr("API_unified.SQL_FEW_SHOT_ENABLED", False, raising=False)
    schema = "[dbo].[SampleOrders](Id int)"
    user = json.dumps({"initial_question": "x", "analysis_type": "SQL-based"})
    baseline = f"{SQL_GENERATOR_BASE}\n{schema}\n\n{user}"
    out, ids = augment_sql_generator_prompt(
        SQL_GENERATOR_BASE, schema, user, "total in 2024", catalog=None
    )
    assert ids == []
    assert out == baseline


def test_enabled_injects_example_ids(monkeypatch):
    monkeypatch.setattr("API_unified.SQL_FEW_SHOT_ENABLED", True, raising=False)
    cat = SimpleNamespace(tables={}, display_names={})
    schema = "[dbo].[SampleOrders](Id int)"
    user = json.dumps({"initial_question": "how many rows in 2023", "analysis_type": "SQL-based"})
    out, ids = augment_sql_generator_prompt(
        SQL_GENERATOR_BASE, schema, user, "how many rows in 2023", catalog=cat
    )
    assert ids
    assert "example_id=" in out
    assert "ExampleSchema" in out
    assert "dupoint_email_data" not in out.lower()


def test_bank_has_no_production_table_literals():
    text = _BANK.read_text(encoding="utf-8").lower()
    assert "dupoint" not in text
    assert "gcc_hackathon" not in text


def test_score_entry_prefers_pattern():
    ent = {
        "id": "t",
        "tags": ["count"],
        "question_pattern": "\\bhow many\\b",
        "catalog_hints": [],
    }
    assert score_entry(ent, "How many items?", set()) >= 6