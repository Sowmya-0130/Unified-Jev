"""Acceptance helpers for expect_empty answers (marker + numeric guard)."""
from __future__ import annotations

import re

from question_time import parse_time_window

_EMPTY_MARKERS = (
    "no matching",
    "no data",
    "none",
    "not found",
    "no orders",
    "no records",
    "empty",
)

_NUM_RE = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?")


def _nums(text: str) -> set[float]:
    out: set[float] = set()
    for m in _NUM_RE.finditer(text or ""):
        raw = m.group(0).replace(",", "")
        try:
            out.add(float(raw))
        except ValueError:
            pass
    return out


def allowed_numbers_for_question(question: str) -> set[float]:
    """Numbers echoed from the question text or parsed time-window filters."""
    allowed = _nums(question or "")
    tw = parse_time_window(question or "")
    if tw and tw.months is not None:
        allowed.add(float(tw.months))
    return allowed


def empty_answer_acceptable(answer: str, question: str) -> bool:
    """
    PASS when empty phrasing is present and every numeric literal in the answer
    is allowed (from question / time window) or is zero (count placeholder).
    """
    al = (answer or "").lower()
    if not any(m in al for m in _EMPTY_MARKERS):
        return False
    allowed = allowed_numbers_for_question(question)
    for n in _nums(answer):
        if n == 0.0:
            continue
        if n not in allowed:
            return False
    return True