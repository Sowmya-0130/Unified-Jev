"""B2 loop guard: duplicate successful SQL fingerprint → Insight."""
from __future__ import annotations

import json

import aurix_core as core


def test_sql_fingerprint_and_heuristic_valid():
    from jev_client import _heuristic_sql_result_check

    sample = '[{"row_count": 20}]'
    assert _heuristic_sql_result_check(sample)["is_valid"]
    fp1 = core._sql_result_fingerprint(sample)
    fp2 = core._sql_result_fingerprint(sample)
    assert fp1 == fp2