"""Deterministic correctness checks for benchmarks (no LLM)."""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from API_unified import BENCH_CORRECTNESS_REL_TOLERANCE
from metadata import fetch_dataframe_readonly

_NUM_RE = re.compile(
    r"(?<![A-Za-z0-9_.])(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+\.\d+|\d+)(?![A-Za-z0-9_])"
)


def _normalize_num(text: str) -> float:
    return float(text.replace(",", ""))


def _numbers_in_text(text: str) -> list[float]:
    vals: list[float] = []
    for m in _NUM_RE.finditer(text or ""):
        try:
            vals.append(_normalize_num(m.group(1)))
        except ValueError:
            continue
    return vals


def _reference_metrics(reference_sql: str) -> list[float]:
    df = fetch_dataframe_readonly(reference_sql)
    metrics: list[float] = []
    for _, row in df.iterrows():
        for v in row:
            if v is None:
                continue
            if isinstance(v, (int, float, Decimal)):
                metrics.append(float(v))
            else:
                try:
                    metrics.append(float(str(v).replace(",", "")))
                except ValueError:
                    pass
    return metrics


def final_user_visible_text(out: dict[str, Any]) -> str:
    """Final user-facing text: final_answer + Inference; never DB_table."""
    fa = out.get("final_answer")
    parts: list[str] = []
    if isinstance(fa, dict):
        for key in ("query_answer", "Inference", "inference", "llm_answer"):
            v = str(fa.get(key) or "").strip()
            if v:
                parts.append(v)
    if not parts:
        for key in ("query_answer", "Inference", "inference", "llm_answer"):
            v = str(out.get(key) or "").strip()
            if v:
                parts.append(v)
    return " ".join(parts).strip()


def _answer_text(out: dict[str, Any]) -> str:
    text = final_user_visible_text(out)
    if not text:
        return ""
    return text


def _retrieved_context(out: dict[str, Any]) -> str:
    trace = out.get("jev_trace") or {}
    for row in trace.get("events") or []:
        if row.get("retrieved_context"):
            return str(row["retrieved_context"])
    return ""


def check_correctness(out: dict[str, Any], validation: dict[str, Any]) -> tuple[bool, str]:
    vtype = validation.get("type", "")
    text = _answer_text(out)
    if not text.strip():
        term = (out.get("jev_trace") or {}).get("latency", {}).get("termination") or {}
        if str(term.get("reason")) == "jev_s2_clarity_block" and vtype == "vague_ok":
            pass
        elif vtype not in ("vague_ok",):
            return False, "no_final_answer"
    term = (out.get("jev_trace") or {}).get("latency", {}).get("termination") or {}
    reason = str(term.get("reason") or "")

    if vtype == "sql_reference":
        ref_sql = (validation.get("reference_sql") or "").strip()
        if not ref_sql:
            return False, "missing reference_sql"
        try:
            expected = _reference_metrics(ref_sql)
        except Exception as exc:  # noqa: BLE001
            return False, f"reference_sql failed: {exc}"
        if not expected:
            if "no matching" in text.lower() or "no rows" in text.lower():
                return True, "ok (empty reference, explicit no-data answer)"
            return False, "reference returned no metrics"
        found = _numbers_in_text(text)
        if not found:
            if any(e == 0 for e in expected) and ("no matching" in text.lower() or "null" in text.lower()):
                return True, "ok (zero/null explained)"
            return False, f"no numbers in answer; expected one of {expected[:5]}"
        for exp in expected:
            for got in found:
                tol = BENCH_CORRECTNESS_REL_TOLERANCE * max(abs(exp), 1.0) + 0.01
                if abs(got - exp) < tol:
                    return True, f"ok (matched {got} ~ {exp})"
        return False, f"numbers {found[:8]} not in reference metrics {expected}"

    if vtype == "sql_shape":
        ref_sql = (validation.get("reference_sql") or "").strip()
        min_rows = int(validation.get("min_rows", 1))
        try:
            df = fetch_dataframe_readonly(ref_sql)
        except Exception as exc:  # noqa: BLE001
            return False, f"reference_sql failed: {exc}"
        if len(df) < min_rows:
            return False, f"reference has {len(df)} rows < {min_rows}"
        if not text.strip():
            return False, "empty answer"
        return True, "ok (non-empty answer, reference shape ok)"

    if vtype == "semantic_grounded":
        ctx = _retrieved_context(out)
        if not ctx and not text.strip():
            return False, "empty answer and no context"
        if not ctx:
            return True, "ok (no context captured; manual review)"
        words = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", text)}
        ctx_words = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", ctx)}
        if not words:
            return False, "no substantive words in answer"
        overlap = len(words & ctx_words) / max(len(words), 1)
        min_ov = float(validation.get("min_chunk_overlap", 0.1))
        if overlap >= min_ov:
            return True, f"ok (token overlap {overlap:.2f})"
        if reason == "rai_blocked":
            return False, "rai_blocked"
        return False, f"low overlap {overlap:.2f} < {min_ov}"

    if vtype == "must_not_invent":
        phrases = validation.get("required_phrases") or []
        match_any = validation.get("match_any", True)
        lower = text.lower()
        hits = [p for p in phrases if p.lower() in lower]
        if match_any and hits:
            return True, f"ok (matched: {hits[0]})"
        if not match_any and len(hits) == len(phrases):
            return True, "ok (all phrases)"
        invent_red_flags = re.search(
            r"\b(2099|coloniz|martian policy|official policy states)\b", lower
        )
        if invent_red_flags and not hits:
            return False, "possible invented content without not-found phrasing"
        if not text.strip():
            return False, "empty answer"
        return False, f"missing not-found phrasing; need one of {phrases[:4]}"

    if vtype == "vague_ok":
        if reason in ("jev_s2_clarity_block",):
            return True, "ok (clarity block)"
        if text.strip():
            return True, "ok (answered or redirected)"
        return False, "empty response"

    return False, f"unknown validation type {vtype!r}"