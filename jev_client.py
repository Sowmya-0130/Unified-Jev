"""
jev_client.py — OpenJev / Codiv integration for Unified-SingleDB.

Provides a single function: jev_routing_decision()
  - Sends the user question + a short SQL schema summary to the OpenJev
    /v1/systemone endpoint (Codiv hosted or self-hosted).
  - Returns the chosen routing label and the model's confidence.
  - Falls back gracefully (returns confidence 0.0) when JEV_API_KEY is not set,
    the request times out, or any HTTP error occurs.

Enable by setting in .env:
    JEV_API_KEY=sk-codiv-...
    JEV_ROUTING_ENABLED=true
    JEV_CONFIDENCE_THRESHOLD=0.75   # 0.0–1.0; below this falls back to Azure LLM
"""

import json
import logging
import threading
import time

import httpx

logger = logging.getLogger(__name__)

_jev_http: httpx.Client | None = None
_last_jev_failure: str | None = None
_jev_slot_sem: threading.Semaphore | None = None
_last_retry_after_s: float | None = None


def jev_last_failure() -> str | None:
    """Why the last JEV HTTP call failed: timeout | error | malformed | flag_off | http:429."""
    return _last_jev_failure


def jev_last_retry_after_s() -> float | None:
    return _last_retry_after_s


def reset_jev_http() -> None:
    global _jev_http
    if _jev_http is not None:
        try:
            _jev_http.close()
        except Exception:  # noqa: BLE001
            pass
    _jev_http = None


# ---------------------------------------------------------------------------
# Lazy import of API_unified so this module can be imported at any point
# without triggering a double load_dotenv().
# ---------------------------------------------------------------------------
def _get_jev_config():
    from API_unified import JEV_API_KEY, JEV_API_BASE, JEV_MODEL
    return JEV_API_KEY, JEV_API_BASE, JEV_MODEL


def _http_client() -> httpx.Client:
    global _jev_http
    if _jev_http is None:
        from API_unified import JEV_TIMEOUT_MS
        _jev_http = httpx.Client(timeout=max(0.1, JEV_TIMEOUT_MS / 1000.0))
    return _jev_http


# Routing choices must match the labels routing_agent uses in main.py
_ROUTING_CRITERIA = {
    "SQL-based": "Answer needs only structured database columns, counts, or aggregates.",
    "Semantic-based": "Answer needs policies, documents, emails, or unstructured text only.",
    "Both-dependent": "Part 2 of the question depends on the result of Part 1 (SQL first, then docs).",
    "Both-independent": "Both a SQL part and a document part are needed but each can be answered independently.",
}


def jev_routing_decision(question: str, table_schemas_summary: str = "") -> dict:
    """
    Ask OpenJev which pipeline should handle `question`.

    Parameters
    ----------
    question : str
        The user's raw question.
    table_schemas_summary : str
        A short description of available SQL tables (truncated to 2 000 chars
        to keep token count low and latency fast).

    Returns
    -------
    dict with keys:
        choice      (str | None)  — one of the four routing labels, or None on failure
        confidence  (float)       — model confidence 0.0–1.0
        probabilities (dict)      — per-label probabilities (empty dict on failure)
        source      (str)         — "openjev" | "fallback"
    """
    JEV_API_KEY, JEV_API_BASE, JEV_MODEL = _get_jev_config()

    _fallback = {"choice": None, "confidence": 0.0, "probabilities": {}, "source": "fallback"}

    if not JEV_API_KEY:
        return _fallback

    schema_snippet = (table_schemas_summary or "")[:2000]
    state_parts = [f"User question: {question}"]
    if schema_snippet:
        state_parts.append(f"Available SQL tables (summary):\n{schema_snippet}")
    state = "\n\n".join(state_parts)
    questions = {
        "route": {
            "type": "choice",
            "instructions": (
                "Given the user question and the available SQL table summary, "
                "choose the best pipeline to handle this request."
            ),
            "criteria": _ROUTING_CRITERIA,
        }
    }
    answers = _jev_post(state, questions)
    if answers is None:
        return _fallback
    try:
        answer = answers["route"]
        return {
            "choice": answer.get("choice"),
            "confidence": float(answer.get("confidence", 0.0)),
            "probabilities": answer.get("probabilities", {}),
            "source": "openjev",
        }
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("OpenJev response parse error (%s) — falling back.", exc)
        return _fallback


# ===========================================================================
# Shared HTTP helper (all functions below reuse this)
# ===========================================================================

def _jev_confidence_threshold() -> float:
    try:
        from API_unified import JEV_CONFIDENCE_THRESHOLD
        return float(JEV_CONFIDENCE_THRESHOLD)
    except Exception:  # noqa: BLE001
        return 0.8


def _jev_slot() -> threading.Semaphore:
    global _jev_slot_sem
    if _jev_slot_sem is None:
        from API_unified import JEV_MAX_CONCURRENCY

        _jev_slot_sem = threading.Semaphore(max(1, int(JEV_MAX_CONCURRENCY)))
    return _jev_slot_sem


def _parse_retry_after(resp: httpx.Response) -> float:
    global _last_retry_after_s
    raw = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
    if not raw:
        _last_retry_after_s = None
        return 0.0
    try:
        sec = float(raw)
    except ValueError:
        _last_retry_after_s = None
        return 0.0
    _last_retry_after_s = sec
    return max(0.0, sec)


def _jev_post(state: str, questions: dict) -> dict | None:
    """
    POST /v1/systemone with concurrency cap, retries, Retry-After (429/503).
    Returns answers dict or None on failure.
    """
    global _last_jev_failure, _last_retry_after_s
    from API_unified import JEV_RETRY_BASE_MS, JEV_RETRY_MAX

    _last_jev_failure = None
    _last_retry_after_s = None
    JEV_API_KEY, JEV_API_BASE, JEV_MODEL = _get_jev_config()
    if not JEV_API_KEY:
        _last_jev_failure = "flag_off"
        return None

    max_attempts = int(JEV_RETRY_MAX) + 1
    base_ms = float(JEV_RETRY_BASE_MS)
    last_exc: Exception | None = None

    for attempt in range(max_attempts):
        try:
            with _jev_slot():
                resp = _http_client().post(
                    f"{JEV_API_BASE}/v1/systemone",
                    headers={
                        "Authorization": f"Bearer {JEV_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={"model": JEV_MODEL, "state": state, "questions": questions},
                )
            if resp.status_code == 429:
                wait_s = _parse_retry_after(resp) or (base_ms / 1000.0 * (2**attempt))
                _last_jev_failure = "http:429"
                logger.warning("OpenJev HTTP 429; retry in %.2fs (attempt %s).", wait_s, attempt + 1)
                if attempt + 1 >= max_attempts:
                    break
                time.sleep(wait_s)
                continue
            if resp.status_code >= 500:
                _last_jev_failure = f"http:{resp.status_code}"
                wait_s = _parse_retry_after(resp) or (base_ms / 1000.0 * (2**attempt))
                logger.warning("OpenJev HTTP %s; retry in %.2fs.", resp.status_code, wait_s)
                if attempt + 1 >= max_attempts:
                    break
                time.sleep(wait_s)
                continue
            resp.raise_for_status()
            body = resp.json()
            answers = body.get("answers")
            if not isinstance(answers, dict):
                _last_jev_failure = "malformed"
                logger.warning("OpenJev malformed response (no answers dict).")
                return None
            return answers
        except httpx.TimeoutException as e:
            last_exc = e
            _last_jev_failure = "timeout"
            logger.warning("OpenJev timeout (attempt %s).", attempt + 1)
        except httpx.HTTPStatusError as e:
            last_exc = e
            code = e.response.status_code
            _last_jev_failure = f"http:{code}"
            logger.warning("OpenJev HTTP %s.", code)
            if code in (408, 425, 429, 500, 502, 503, 504) and attempt + 1 < max_attempts:
                time.sleep(base_ms / 1000.0 * (2**attempt))
                continue
            break
        except Exception as e:  # noqa: BLE001
            last_exc = e
            _last_jev_failure = "error"
            logger.warning("OpenJev error: %s.", e)
            if attempt + 1 < max_attempts:
                time.sleep(base_ms / 1000.0 * (2**attempt))
                continue
            break
    if last_exc and not _last_jev_failure:
        _last_jev_failure = "error"
    return None


def _noul(answers: dict, key: str) -> float:
    """Extract P(yes) from a noul answer; returns 0.5 (neutral) on missing."""
    try:
        return float(answers[key].get("noul", 0.5))
    except (KeyError, TypeError):
        return 0.5


def _choice(answers: dict, key: str) -> tuple[str | None, float]:
    """Extract (choice, confidence) from a choice answer."""
    try:
        a = answers[key]
        return a.get("choice"), float(a.get("confidence", 0.0))
    except (KeyError, TypeError):
        return None, 0.0


def _score_val(answers: dict, key: str) -> float:
    """Extract probability-weighted score from a score answer; returns 2.5 (mid) on missing."""
    try:
        return float(answers[key].get("score", 2.5))
    except (KeyError, TypeError):
        return 2.5


# ===========================================================================
# STEP 1 — Safety Gate
# ===========================================================================

def _parse_s1_noul_scores(answers: dict) -> dict[str, float] | None:
    out: dict[str, float] = {}
    for key in ("is_toxic", "has_pii", "is_injection"):
        try:
            out[key] = float(answers[key]["noul"])
        except (KeyError, TypeError, ValueError):
            return None
    return out


def jev_safety_check(question: str) -> dict:
    """S1 noul heads; fail-closed → unavailable (never zero-score allow)."""
    _unavail = {
        "is_toxic": None,
        "has_pii": None,
        "is_injection": None,
        "block": True,
        "unavailable": True,
        "source": "jev_unavailable",
        "failure": None,
    }
    state = f"User input to an enterprise AI assistant:\n\n{question[:3000]}"
    questions = {
        "is_toxic": {
            "type": "noul",
            "instructions": "Does this input contain hate speech, violence, abuse, or harmful content?",
        },
        "has_pii": {
            "type": "noul",
            "instructions": "Does this input contain personally identifiable information such as SSN, phone number, email address, or credit card?",
        },
        "is_injection": {
            "type": "noul",
            "instructions": "Is this a prompt injection, jailbreak, or attempt to override the system's instructions?",
        },
    }
    answers = _jev_post(state, questions)
    if answers is None:
        _unavail["failure"] = jev_last_failure()
        return _unavail
    scored = _parse_s1_noul_scores(answers)
    if scored is None:
        global _last_jev_failure
        _last_jev_failure = "malformed"
        _unavail["failure"] = "malformed"
        return _unavail
    p_toxic = scored["is_toxic"]
    p_pii = scored["has_pii"]
    p_inj = scored["is_injection"]
    block = p_toxic > 0.85 or p_inj > 0.85
    return {
        "is_toxic": p_toxic,
        "has_pii": p_pii,
        "is_injection": p_inj,
        "block": block,
        "source": "openjev",
        "unavailable": False,
    }


# ===========================================================================
# STEP 6 — SQL Pre-Execution Guard
# ===========================================================================

def jev_sql_guard(sql_query: str, valid_tables: list) -> dict:
    """
    Check T-SQL safety before hitting Azure SQL.

    Returns
    -------
    dict:
        is_safe          bool   True when all checks pass
        is_select_only   float  P(query is read-only SELECT/WITH)
        tables_valid     float  P(only references known dbo. tables)
        has_top_clause   float  P(uses TOP clause)
        block_reason     str    human-readable reason if blocked
        source           str
    """
    _fallback = {"is_safe": True, "is_select_only": 1.0, "tables_valid": 1.0,
                 "has_top_clause": 1.0, "block_reason": "", "source": "fallback"}
    tables_str = ", ".join(valid_tables[:30]) if valid_tables else "unknown"
    state = (
        f"T-SQL query to execute against Azure SQL Server (dbo schema):\n\n{sql_query[:2000]}\n\n"
        f"Known valid tables: {tables_str}"
    )
    questions = {
        "is_select_only": {
            "type": "noul",
            "instructions": "Does this SQL query perform only read operations (SELECT or WITH ... SELECT)? A query with INSERT, UPDATE, DELETE, DROP, TRUNCATE, or EXEC is NOT read-only.",
        },
        "tables_valid": {
            "type": "noul",
            "instructions": "Does the query reference only the known valid tables listed above? A query that references tables not in the list is INVALID.",
        },
        "has_top_clause": {
            "type": "noul",
            "instructions": "Does the SQL query include a TOP clause to limit results (required for safety on large tables)?",
        },
    }
    answers = _jev_post(state, questions)
    if answers is None:
        return _fallback
    p_sel  = _noul(answers, "is_select_only")
    p_tbl  = _noul(answers, "tables_valid")
    p_top  = _noul(answers, "has_top_clause")
    reasons = []
    if p_sel < 0.25:
        reasons.append("Query may contain write operations (INSERT/UPDATE/DELETE/DROP).")
    if p_tbl < 0.25:
        reasons.append("Query references tables not in the known schema.")
    if p_top < 0.25:
        reasons.append("Query is missing a TOP clause.")
    is_safe = len(reasons) == 0
    return {
        "is_safe": is_safe,
        "is_select_only": p_sel,
        "tables_valid": p_tbl,
        "has_top_clause": p_top,
        "block_reason": " ".join(reasons),
        "source": "openjev",
    }


# ===========================================================================
# STEP 7 — SQL Execution Result Check
# ===========================================================================

def _rows_all_null(rows: list) -> bool:
    for row in rows:
        if not isinstance(row, dict):
            continue
        for v in row.values():
            if v is None:
                continue
            if str(v).strip().lower() in ("", "null", "none"):
                continue
            return False
    return True


def _heuristic_sql_result_check(sql_result: str) -> dict | None:
    raw = str(sql_result or "").strip()
    if not raw:
        return {
            "is_valid": False,
            "error_type": "empty_result",
            "no_matching_data": True,
            "confidence": 0.9,
            "source": "heuristic",
        }
    lower = raw.lower()
    if (
        lower.startswith("error")
        or "an error occurred" in lower[:200]
        or "query blocked" in lower[:200]
        or "traceback" in lower[:300]
        or "hy000" in lower
        or "invalid object" in lower
        or (raw.startswith("{") and "error" in raw[:400].lower())
    ):
        return {
            "is_valid": False,
            "error_type": "unknown_error",
            "confidence": 0.9,
            "source": "heuristic",
        }
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict) and "sql_query" in data:
        return None
    if isinstance(data, list):
        if len(data) == 0:
            return {
                "is_valid": False,
                "error_type": "empty_result",
                "no_matching_data": True,
                "confidence": 0.9,
                "source": "heuristic",
            }
        if all(isinstance(row, dict) for row in data):
            if _rows_all_null(data):
                return {
                    "is_valid": False,
                    "error_type": "empty_result",
                    "no_matching_data": True,
                    "confidence": 0.92,
                    "source": "heuristic",
                }
            return {
                "is_valid": True,
                "error_type": "ok",
                "confidence": 0.95,
                "source": "heuristic",
            }
    return None


def s7_resolve(sql_result: str, *, jev_enabled: bool) -> dict:
    """Heuristic always runs; JEV only if enabled and heuristic inconclusive."""
    pre = _heuristic_sql_result_check(sql_result)
    if pre is not None:
        pre["decision_source"] = "heuristic"
        return pre
    if not jev_enabled:
        return {"is_valid": None, "source": "llm", "decision_source": "llm"}
    return jev_sql_result_check(sql_result)


def jev_sql_result_check(sql_result: str) -> dict:
    """
    Fast check on the raw SQL execution output (JSON rows or error string).

    Returns
    -------
    dict:
        is_valid    bool   True if result is non-empty valid JSON rows
        error_type  str    One of: "empty_result" | "syntax_error" | "timeout" |
                           "permission_error" | "unknown_error" | "ok"
        confidence  float
        source      str
    """
    _fallback = {"is_valid": True, "error_type": "ok", "confidence": 0.5, "source": "fallback"}
    state = f"SQL execution output (first 2000 chars):\n\n{str(sql_result)[:2000]}"
    questions = {
        "is_valid": {
            "type": "noul",
            "instructions": "Does this output look like a valid non-empty JSON array of database rows (not an error message, not an empty array [])?",
        },
        "error_type": {
            "type": "choice",
            "instructions": "If the output is an error or empty result, what type of problem is it?",
            "criteria": {
                "ok":               "Output is a valid, non-empty result with rows.",
                "empty_result":     "Query ran but returned zero rows (empty array []).",
                "syntax_error":     "SQL syntax error or column/table not found.",
                "timeout":          "Query timed out or took too long.",
                "permission_error": "Permission denied or authentication error.",
                "unknown_error":    "Some other error occurred.",
            },
        },
    }
    answers = _jev_post(state, questions)
    if answers is None:
        return _fallback
    p_valid = _noul(answers, "is_valid")
    err_type, confidence = _choice(answers, "error_type")
    return {
        "is_valid": p_valid > 0.60,
        "error_type": err_type or "ok",
        "confidence": confidence,
        "source": "openjev",
        "decision_source": "jev",
    }


# ===========================================================================
# STEP 14 — Output PII / Data Leak Guard
# ===========================================================================

def jev_output_guard(answer: str) -> dict:
    """
    Scan the final answer text before showing it in the Streamlit UI.

    Returns
    -------
    dict:
        leaks_pii       float  P(answer contains PII or sensitive data)
        is_professional float  P(answer is professional in tone)
        block           bool   True if leaks_pii > 0.75
        source          str
    """
    _fallback = {"leaks_pii": 0.0, "is_professional": 1.0, "block": False, "source": "fallback"}
    state = f"Final answer generated by an enterprise AI assistant:\n\n{str(answer)[:3000]}"
    questions = {
        "leaks_pii": {
            "type": "noul",
            "instructions": (
                "Does this answer contain personally identifiable information (PII) such as "
                "email addresses, phone numbers, SSNs, credit card numbers, or passwords that "
                "should NOT be shown to the end user?"
            ),
        },
        "is_professional": {
            "type": "noul",
            "instructions": "Is this answer written in a professional, respectful, and appropriate business tone?",
        },
    }
    answers = _jev_post(state, questions)
    if answers is None:
        return _fallback
    p_pii  = _noul(answers, "leaks_pii")
    p_prof = _noul(answers, "is_professional")
    return {
        "leaks_pii": p_pii,
        "is_professional": p_prof,
        "block": p_pii > 0.75,
        "source": "openjev",
    }


# ===========================================================================
# STEP 2 — Ambiguity / Clarification Gate
# ===========================================================================

def jev_clarity_check(question: str) -> dict:
    """
    Check if the user's question is clear enough to avoid wasted agent turns.

    Returns
    -------
    dict:
        is_clear    float  P(question is clear and specific enough to answer)
        confidence  float  same value (noul confidence)
        source      str
    """
    _fallback = {"is_clear": 1.0, "confidence": 1.0, "source": "fallback"}
    state = (
        f"User question submitted to an enterprise data assistant:\n\n{question[:1500]}\n\n"
        "The assistant has access to SQL tables (inventory, orders, distributors) "
        "and a document store (policies, emails, return procedures)."
    )
    questions = {
        "is_clear": {
            "type": "noul",
            "instructions": (
                "Is this question specific and clear enough that the assistant can answer it "
                "without asking the user to clarify? Vague inputs like 'Show status', "
                "'Tell me something', or single-word queries are NOT clear."
            ),
        },
    }
    answers = _jev_post(state, questions)
    if answers is None:
        return _fallback
    p_clear = _noul(answers, "is_clear")
    return {"is_clear": p_clear, "confidence": p_clear, "source": "openjev"}


# ===========================================================================
# STEP 5 — Dynamic LLM Size Router
# ===========================================================================

def jev_model_complexity(question: str) -> dict:
    """
    Classify query complexity so simple questions use a cheaper/faster LLM.

    Returns
    -------
    dict:
        complexity  str    "simple" | "complex"
        confidence  float
        source      str
    """
    _fallback = {"complexity": "complex", "confidence": 0.0, "source": "fallback"}
    state = f"User question for an enterprise SQL + document assistant:\n\n{question[:1500]}"
    questions = {
        "complexity": {
            "type": "choice",
            "instructions": "How complex is this question for an AI assistant?",
            "criteria": {
                "simple": (
                    "Single-table lookup, single-topic policy question, "
                    "or a direct factual question answerable in one step."
                ),
                "complex": (
                    "Multi-table joins, dependent sub-questions, comparisons across time, "
                    "hybrid SQL+document questions, or multi-step reasoning required."
                ),
            },
        },
    }
    answers = _jev_post(state, questions)
    if answers is None:
        return _fallback
    complexity, confidence = _choice(answers, "complexity")
    return {"complexity": complexity or "complex", "confidence": confidence, "source": "openjev"}


# ===========================================================================
# STEP 10 — Retrieval Mode Picker
# ===========================================================================

def jev_retrieval_mode(question: str) -> dict:
    """
    Choose the retrieval backend for a semantic/document question.

    Returns
    -------
    dict:
        mode        str    "vector" | "graph" | "hybrid"
        confidence  float
        source      str
    """
    _fallback = {"mode": "vector", "confidence": 0.0, "source": "fallback"}
    state = (
        f"Question for a document retrieval system:\n\n{question[:1500]}\n\n"
        "Available backends:\n"
        "- vector: Azure AI Search (fast, good for direct fact/policy lookup)\n"
        "- graph: GraphRAG local search (good for entity relationships, multi-hop)\n"
        "- hybrid: both backends combined with weighted merge"
    )
    questions = {
        "mode": {
            "type": "choice",
            "instructions": "Which retrieval backend should be used to answer this question?",
            "criteria": {
                "vector": (
                    "Direct fact lookup, specific policy, single-topic email search. "
                    "No relationships between entities needed."
                ),
                "graph": (
                    "Question involves relationships, connections, multi-hop reasoning, "
                    "or 'who is connected to whom' type questions."
                ),
                "hybrid": (
                    "Question needs both factual chunks AND entity relationship context. "
                    "Use when neither pure vector nor pure graph is enough."
                ),
            },
        },
    }
    answers = _jev_post(state, questions)
    if answers is None:
        return _fallback
    mode, confidence = _choice(answers, "mode")
    return {"mode": mode or "vector", "confidence": confidence, "source": "openjev"}


# ===========================================================================
# STEP 12 — "Not Found" Short-Circuit
# ===========================================================================

def jev_has_answer(question: str, chunks: list) -> dict:
    """
    Quickly check if any retrieved chunk actually contains the answer.
    If not, skip llm_answer_maker entirely.

    Parameters
    ----------
    question : str
    chunks   : list[str]  retrieved text chunks

    Returns
    -------
    dict:
        has_answer  bool   True if at least one chunk is likely to answer the question
        max_score   float  highest P(has_answer) across all chunks
        scores      list   per-chunk relevance probabilities
        source      str
    """
    _fallback = {"has_answer": True, "max_score": 1.0, "scores": [], "source": "fallback"}
    if not chunks:
        return {"has_answer": False, "max_score": 0.0, "scores": [], "source": "openjev"}

    # Batch all chunks in one /v1/systemone call (parallel questions)
    state = f"User question:\n{question[:500]}\n\nRetrieved document chunks:\n"
    questions: dict = {}
    for i, chunk in enumerate(chunks[:8]):
        state += f"\n---CHUNK_{i}---\n{chunk[:600]}\n"
        questions[f"chunk_{i}"] = {
            "type": "noul",
            "instructions": (
                f"Does CHUNK_{i} above contain information that directly answers the user question?"
            ),
        }

    answers = _jev_post(state, questions)
    if answers is None:
        return _fallback

    scores = [_noul(answers, f"chunk_{i}") for i in range(len(chunks[:8]))]
    max_score = max(scores) if scores else 0.0
    return {
        "has_answer": max_score >= 0.30,
        "max_score": max_score,
        "scores": scores,
        "source": "openjev",
    }


# ===========================================================================
# STEP 9 — Evaluation Agent Quality Gate
# ===========================================================================

def jev_eval_quality(question: str, answer: str) -> dict:
    """
    Score the quality of the final answer before it reaches the LLM evaluator.
    If JEV already finds the answer excellent, skip the heavyweight Evaluation_Agent.

    Returns
    -------
    dict:
        helpfulness   float  0–1
        groundedness  float  0–1
        completeness  float  0–1
        composite     float  weighted average
        skip_llm_eval bool   True if composite >= 0.80
        source        str
    """
    _fallback = {
        "helpfulness": 0.5, "groundedness": 0.5, "completeness": 0.5,
        "composite": 0.5, "skip_llm_eval": False, "source": "fallback",
    }
    state = (
        f"User question:\n{question[:600]}\n\n"
        f"System answer:\n{answer[:1200]}"
    )
    questions = {
        "helpfulness": {
            "type": "noul",
            "instructions": (
                "Does the answer directly address what the user asked? "
                "Score 1.0 if fully helpful, 0.0 if irrelevant."
            ),
        },
        "groundedness": {
            "type": "noul",
            "instructions": (
                "Is the answer grounded in verifiable facts or data? "
                "Score 1.0 if fully grounded, 0.0 if speculative or hallucinated."
            ),
        },
        "completeness": {
            "type": "noul",
            "instructions": (
                "Does the answer cover all parts of the user's question? "
                "Score 1.0 if complete, 0.0 if major parts are missing."
            ),
        },
    }
    answers = _jev_post(state, questions)
    if answers is None:
        return _fallback

    h = _noul(answers, "helpfulness")
    g = _noul(answers, "groundedness")
    c = _noul(answers, "completeness")
    composite = round(0.40 * h + 0.35 * g + 0.25 * c, 4)
    return {
        "helpfulness": h,
        "groundedness": g,
        "completeness": c,
        "composite": composite,
        "skip_llm_eval": composite >= _jev_confidence_threshold(),
        "source": "openjev",
    }


# ===========================================================================
# STEP 11 — Semantic Chunk Reranker
# ===========================================================================

def jev_rerank_chunks(question: str, chunks: list) -> list:
    """
    Re-rank retrieved text chunks by relevance using JEV Noul scores.
    Returns the same list sorted descending by P(relevant).

    Parameters
    ----------
    question : str
    chunks   : list[str]  raw retrieved chunks

    Returns
    -------
    list[str]  reranked (most relevant first)
    """
    if not chunks or len(chunks) <= 1:
        return chunks

    state = f"Question: {question[:500]}\n\n"
    questions: dict = {}
    for i, chunk in enumerate(chunks[:10]):
        state += f"\n---CHUNK_{i}---\n{chunk[:500]}\n"
        questions[f"chunk_{i}"] = {
            "type": "noul",
            "instructions": (
                f"Is CHUNK_{i} directly relevant and useful for answering the question above? "
                "Consider semantic relevance, not just keyword overlap."
            ),
        }

    answers = _jev_post(state, questions)
    if answers is None:
        return chunks  # fallback: original order

    scored = [(chunk, _noul(answers, f"chunk_{i}")) for i, chunk in enumerate(chunks[:10])]
    scored.sort(key=lambda x: x[1], reverse=True)
    # Append any extra chunks (beyond 10) at the end unchanged
    reranked = [c for c, _ in scored] + list(chunks[10:])
    return reranked


# ===========================================================================
# STEP 13 — Critic / Hallucination Detector
# ===========================================================================

def jev_critic_check(question: str, answer: str, context_chunks: list) -> dict:
    """
    Lightweight hallucination check: does the answer stay faithful to the
    retrieved context?  Uses two Noul checks in one forward pass.

    Returns
    -------
    dict:
        is_faithful     float   P(answer is fully supported by context)
        no_hallucination float  P(no made-up facts)
        ok              bool    True if both scores >= 0.50
        concern         str     human-readable concern when ok=False
        source          str
    """
    _fallback = {
        "is_faithful": 1.0, "no_hallucination": 1.0,
        "ok": True, "concern": "", "source": "fallback",
    }
    # Truncate context to avoid massive prompts
    ctx = "\n---\n".join((c or "")[:400] for c in (context_chunks or [])[:5])
    state = (
        f"Question:\n{question[:500]}\n\n"
        f"Retrieved context:\n{ctx[:2000]}\n\n"
        f"System answer:\n{answer[:800]}"
    )
    questions = {
        "is_faithful": {
            "type": "noul",
            "instructions": (
                "Is every factual claim in the System answer directly supported by "
                "the Retrieved context above? Do not penalise format or style."
            ),
        },
        "no_hallucination": {
            "type": "noul",
            "instructions": (
                "Does the System answer avoid introducing facts, figures, or entities "
                "that are NOT mentioned anywhere in the Retrieved context?"
            ),
        },
    }
    answers = _jev_post(state, questions)
    if answers is None:
        return _fallback

    faith = _noul(answers, "is_faithful")
    no_hall = _noul(answers, "no_hallucination")
    ok = faith >= 0.50 and no_hall >= 0.50
    concern = ""
    if not ok:
        parts = []
        if faith < 0.50:
            parts.append(f"low faithfulness ({faith:.0%})")
        if no_hall < 0.50:
            parts.append(f"possible hallucination ({no_hall:.0%})")
        concern = "; ".join(parts)

    return {
        "is_faithful": faith,
        "no_hallucination": no_hall,
        "ok": ok,
        "concern": concern,
        "source": "openjev",
    }


# ===========================================================================
# STEP 3 — Semantic Cache Intent Matcher
# ===========================================================================

def jev_cache_intent_match(new_question: str, cached_question: str) -> dict:
    """
    Determine whether a new question has the same intent as a cached question
    so the cached answer can be reused without re-running the full pipeline.

    Returns
    -------
    dict:
        is_match    float   P(same intent; cached answer would be valid for new question)
        source      str
    """
    _fallback = {"is_match": 0.0, "source": "fallback"}
    state = (
        f"Question A (new):\n{new_question[:600]}\n\n"
        f"Question B (cached):\n{cached_question[:600]}"
    )
    questions = {
        "is_match": {
            "type": "noul",
            "instructions": (
                "Do Question A and Question B have the same intent and would they require "
                "the same data or answer? Minor rephrasing, typos, and language differences "
                "should be ignored. Answer YES only if the answer to B would fully satisfy A."
            ),
        },
    }
    answers = _jev_post(state, questions)
    if answers is None:
        return _fallback
    return {"is_match": _noul(answers, "is_match"), "source": "openjev"}


# ===========================================================================
# STEP 8 — Chart / Visualisation Trigger
# ===========================================================================

def jev_chart_trigger(question: str, sql_result_json: str) -> dict:
    """
    Decide whether the SQL result should be visualised as a chart.

    Returns
    -------
    dict:
        should_chart  bool    True if a chart is recommended
        chart_type    str     "bar" | "line" | "pie" | "table" | "none"
        confidence    float
        source        str
    """
    _fallback = {"should_chart": False, "chart_type": "none", "confidence": 0.0, "source": "fallback"}
    # Truncate large results
    result_preview = (sql_result_json or "")[:1000]
    state = (
        f"User question:\n{question[:500]}\n\n"
        f"SQL query result (JSON, truncated to 1000 chars):\n{result_preview}"
    )
    questions = {
        "should_chart": {
            "type": "noul",
            "instructions": (
                "Should the SQL result be visualised as a chart rather than a plain table? "
                "Score high for time-series, comparisons, rankings, and distributions. "
                "Score low for single-row lookups or non-numeric results."
            ),
        },
        "chart_type": {
            "type": "choice",
            "instructions": "If a chart is appropriate, which chart type would best represent this data?",
            "criteria": {
                "bar": "Categorical comparison (e.g. sales by region, counts by category).",
                "line": "Time-series or ordered numeric data (e.g. monthly revenue trend).",
                "pie": "Part-of-whole proportions with ≤ 8 slices.",
                "table": "Multi-column relational data best presented as a table.",
                "none": "No chart needed; a text summary or single value is sufficient.",
            },
        },
    }
    answers = _jev_post(state, questions)
    if answers is None:
        return _fallback

    p_chart = _noul(answers, "should_chart")
    ctype, confidence = _choice(answers, "chart_type")
    return {
        "should_chart": p_chart >= 0.60,
        "chart_type": ctype or "none",
        "confidence": confidence,
        "source": "openjev",
    }
