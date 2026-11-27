"""A4: Both-route merge/synthesis node (LLM + concat fallback)."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DbOutput:
    text: str = ""
    sql: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class DocsOutput:
    text: str = ""
    passages: list = field(default_factory=list)


@dataclass
class MergeResult:
    final_text: str
    sources: list[str]
    merge_strategy: str
    grounded: bool
    confidence: float
    query_answer: str = ""
    llm_answer: str = ""


_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "merge_synthesis.txt"


def _concat_fallback(db_text: str, docs_text: str) -> str:
    parts: list[str] = []
    if db_text.strip():
        parts.append(f"[Data] {db_text.strip()}")
    if docs_text.strip():
        parts.append(f"[Context] {docs_text.strip()}")
    if not parts:
        return "No data found for this question in the database or documents."
    return "\n\n".join(parts)


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.is_file() else ""


def _parse_llm_json(raw: str) -> tuple[str, list[str]] | None:
    text = (raw or "").strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"```\s*$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    final = str(data.get("final_text") or "").strip()
    if not final:
        return None
    sources = data.get("sources") or []
    if not isinstance(sources, list):
        sources = []
    return final, [str(s) for s in sources]


def _grounding_check(question: str, final_text: str, docs: DocsOutput) -> tuple[bool, float]:
    try:
        from API_unified import JEV_CONFIDENCE_THRESHOLD, JEV_S13_CRITIC_ENABLED

        if not JEV_S13_CRITIC_ENABLED:
            return True, 0.85
        from jev_client import jev_critic_check

        chunks = docs.passages or []
        cr = jev_critic_check(question, final_text, chunks)
        ok = bool(cr.get("is_grounded")) and float(cr.get("confidence") or 0) >= JEV_CONFIDENCE_THRESHOLD
        return ok, float(cr.get("confidence") or 0.5)
    except Exception:  # noqa: BLE001
        return False, 0.5


def _llm_synthesis(question: str, db: DbOutput, docs: DocsOutput) -> tuple[str, list[str]] | None:
    import aurix_core as core
    from agent_runner import agent_llm_turn

    prompt = (
        f"{_load_prompt()}\n\n"
        f"Question: {question}\n"
        f"DB output:\n{db.text or '(none)'}\n\n"
        f"Documentation output:\n{docs.text or '(none)'}\n"
    )
    raw = agent_llm_turn(core.Insight_Generator, prompt, sender=core.user_proxy)
    parsed = _parse_llm_json(raw)
    return parsed


def synthesize(
    question: str,
    db_output: DbOutput,
    docs_output: DocsOutput,
    trace_id: str | None = None,
) -> MergeResult:
    """Never raises — always returns MergeResult."""
    from API_unified import MERGE_NODE_ENABLED, MERGE_NODE_TIMEOUT_S

    db_text = (db_output.text or "").strip()
    docs_text = (docs_output.text or "").strip()

    if not MERGE_NODE_ENABLED:
        final = _concat_fallback(db_text, docs_text)
        return MergeResult(
            final_text=final,
            sources=["data" if db_text else "", "docs" if docs_text else ""],
            merge_strategy="concat_fallback",
            grounded=True,
            confidence=0.5,
            query_answer=db_text,
            llm_answer=docs_text,
        )

    try:
        from jev_trace import record_step

        record_step("merge", "start", 0.0, status="ok", request_id=trace_id)
    except Exception:  # noqa: BLE001
        pass

    if db_text and not docs_text:
        return MergeResult(
            final_text=db_text,
            sources=["data"],
            merge_strategy="db_only",
            grounded=True,
            confidence=0.9,
            query_answer=db_text,
            llm_answer="",
        )
    if docs_text and not db_text:
        return MergeResult(
            final_text=docs_text,
            sources=["docs"],
            merge_strategy="docs_only",
            grounded=True,
            confidence=0.9,
            query_answer="",
            llm_answer=docs_text,
        )
    if not db_text and not docs_text:
        final = "No data found for this question in the database or documents."
        return MergeResult(
            final_text=final,
            sources=[],
            merge_strategy="concat_fallback",
            grounded=False,
            confidence=0.0,
            query_answer="",
            llm_answer="",
        )

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_llm_synthesis, question, db_output, docs_output)
            parsed = fut.result(timeout=float(MERGE_NODE_TIMEOUT_S))
        if parsed:
            final_text, sources = parsed
            grounded, conf = _grounding_check(question, final_text, docs_output)
            if grounded:
                try:
                    from jev_trace import record_step

                    record_step("merge", "llm_synthesis", 0.0, status="ok", request_id=trace_id)
                except Exception:  # noqa: BLE001
                    pass
                return MergeResult(
                    final_text=final_text,
                    sources=sources or ["data", "docs"],
                    merge_strategy="llm_synthesis",
                    grounded=True,
                    confidence=conf,
                    query_answer=db_text,
                    llm_answer=docs_text,
                )
    except FuturesTimeout:
        pass
    except Exception:  # noqa: BLE001
        pass

    final = _concat_fallback(db_text, docs_text)
    try:
        from jev_trace import record_step

        record_step("merge", "concat_fallback", 0.0, status="ok", request_id=trace_id)
    except Exception:  # noqa: BLE001
        pass
    return MergeResult(
        final_text=final,
        sources=["data", "docs"],
        merge_strategy="concat_fallback",
        grounded=False,
        confidence=0.5,
        query_answer=db_text,
        llm_answer=docs_text,
    )