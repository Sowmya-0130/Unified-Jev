"""
ingest_triage.py — Step 15: Offline document triage using OpenJev.

Usage (run as a script):
    python ingest_triage.py --input ./raw_docs --output ./artifacts/triaged

Usage (import):
    from ingest_triage import triage_document, batch_triage_directory

The module classifies incoming documents BEFORE they are indexed into Azure AI Search
or the GraphRAG artifact store.  For each document it determines:
  - document_type  : "policy" | "email" | "contract" | "report" | "noise"
  - should_index   : bool — whether the document is worth indexing at all
  - target_store   : "vector" | "graph" | "both" | "skip"
  - sensitivity    : "public" | "internal" | "confidential" | "restricted"

Enable by setting in .env:
    JEV_API_KEY=sk-codiv-...
    JEV_S15_INGEST_TRIAGE_ENABLED=true
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from API_unified import (
    JEV_API_BASE,
    JEV_API_KEY,
    JEV_CONFIDENCE_THRESHOLD,
    JEV_MODEL,
    JEV_S15_INGEST_TRIAGE_ENABLED,
)

JEV_S15_ENABLED = JEV_S15_INGEST_TRIAGE_ENABLED

# ---------------------------------------------------------------------------
# Internal HTTP helper (mirrors jev_client._jev_post)
# ---------------------------------------------------------------------------

def _jev_post(state: str, questions: dict) -> Optional[dict]:
    """POST to /v1/systemone and return the answers dict, or None on failure."""
    if not JEV_API_KEY:
        return None
    try:
        import httpx
        payload = {"model": JEV_MODEL, "state": state, "questions": questions}
        headers = {"Authorization": f"Bearer {JEV_API_KEY}", "Content-Type": "application/json"}
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(f"{JEV_API_BASE}/v1/systemone", json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json().get("answers", {})
    except Exception as exc:  # noqa: BLE001
        logger.warning("JEV S15 POST failed: %s", exc)
        return None


def _choice(answers: dict, key: str) -> tuple[Optional[str], float]:
    item = answers.get(key, {}) if isinstance(answers, dict) else {}
    return item.get("label"), float(item.get("confidence", 0.0))


def _noul(answers: dict, key: str) -> float:
    item = answers.get(key, {}) if isinstance(answers, dict) else {}
    return float(item.get("probability", 0.5))


# ---------------------------------------------------------------------------
# STEP 15 — jev_classify_document
# ---------------------------------------------------------------------------

def jev_classify_document(filename: str, text_preview: str) -> dict:
    """
    Classify a single document snippet for ingest routing.

    Parameters
    ----------
    filename     : str   Original filename (hints for type)
    text_preview : str   First ~2000 characters of the document

    Returns
    -------
    dict:
        document_type   str    "policy" | "email" | "contract" | "report" | "noise"
        should_index    bool   False → skip indexing entirely
        target_store    str    "vector" | "graph" | "both" | "skip"
        sensitivity     str    "public" | "internal" | "confidential" | "restricted"
        confidence      float
        source          str    "openjev" | "fallback"
    """
    _fallback = {
        "document_type": "report",
        "should_index": True,
        "target_store": "vector",
        "sensitivity": "internal",
        "confidence": 0.0,
        "source": "fallback",
    }

    state = (
        f"Filename: {filename}\n\n"
        f"Document preview (first 2000 chars):\n{text_preview[:2000]}"
    )

    questions = {
        "document_type": {
            "type": "choice",
            "instructions": "What type of document is this?",
            "criteria": {
                "policy":   "Company policy, procedure, guideline, compliance rule, or handbook section.",
                "email":    "An email thread, message, or correspondence between people.",
                "contract": "A legal contract, agreement, SLA, or vendor document.",
                "report":   "A data report, analysis, summary, or business intelligence document.",
                "noise":    "Junk, test data, system log, or document with no business value.",
            },
        },
        "should_index": {
            "type": "noul",
            "instructions": (
                "Is this document worth indexing in an enterprise knowledge base? "
                "Score low for noise, duplicate, or trivial content."
            ),
        },
        "target_store": {
            "type": "choice",
            "instructions": "Where should this document be stored for retrieval?",
            "criteria": {
                "vector": "Best served by keyword/semantic search (Azure AI Search). Most documents.",
                "graph":  "Rich in entity relationships, org charts, connections. Good for GraphRAG.",
                "both":   "Contains both factual policy content AND rich entity relationships.",
                "skip":   "Should not be stored anywhere (noise, duplicate, restricted).",
            },
        },
        "sensitivity": {
            "type": "choice",
            "instructions": "What is the data sensitivity level of this document?",
            "criteria": {
                "public":       "No sensitive information; could be shared externally.",
                "internal":     "Internal business content, not for external sharing.",
                "confidential": "Contains financial, strategic, or HR-sensitive content.",
                "restricted":   "Contains PII, legal secrets, or regulatory data requiring strict access.",
            },
        },
    }

    answers = _jev_post(state, questions)
    if answers is None:
        return _fallback

    doc_type, doc_conf    = _choice(answers, "document_type")
    store_type, _         = _choice(answers, "target_store")
    sensitivity, sens_conf = _choice(answers, "sensitivity")
    p_index = _noul(answers, "should_index")

    # If JEV says noise or skip-store, don't index
    should_index = p_index >= 0.40 and doc_type != "noise" and store_type != "skip"

    return {
        "document_type": doc_type or "report",
        "should_index":  should_index,
        "target_store":  store_type or "vector",
        "sensitivity":   sensitivity or "internal",
        "confidence":    round((doc_conf + sens_conf) / 2, 4),
        "source":        "openjev",
    }


# ---------------------------------------------------------------------------
# Batch helpers
# ---------------------------------------------------------------------------

def _read_text_preview(path: Path, max_chars: int = 2000) -> str:
    """Read the first max_chars characters from a text-like file."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return fh.read(max_chars)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read %s: %s", path, exc)
        return ""


def batch_triage_directory(
    input_dir: str | Path,
    output_dir: Optional[str | Path] = None,
    extensions: tuple = (".txt", ".md", ".pdf", ".docx", ".html", ".csv"),
    delay_ms: int = 200,
) -> list[dict]:
    """
    Triage all documents in input_dir and return a list of classification results.

    Parameters
    ----------
    input_dir   : directory containing raw documents
    output_dir  : optional; if set, writes a triage_results.json here
    extensions  : file extensions to consider
    delay_ms    : ms to sleep between API calls to avoid rate-limiting

    Returns
    -------
    list[dict]  one result dict per file, each containing:
        filename, document_type, should_index, target_store, sensitivity, confidence, source
    """
    input_dir = Path(input_dir)
    results: list[dict] = []

    files = [f for f in input_dir.rglob("*") if f.suffix.lower() in extensions]
    logger.info("Triaging %d documents in %s ...", len(files), input_dir)

    for f in files:
        preview = _read_text_preview(f)
        result = jev_classify_document(f.name, preview)
        result["filename"] = str(f.relative_to(input_dir))
        results.append(result)
        logger.info(
            "[%s] type=%s store=%s sensitivity=%s index=%s conf=%.2f source=%s",
            f.name, result["document_type"], result["target_store"],
            result["sensitivity"], result["should_index"],
            result["confidence"], result["source"],
        )
        if delay_ms > 0:
            time.sleep(delay_ms / 1000)

    if output_dir:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        triage_path = out / "triage_results.json"
        with open(triage_path, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2)
        logger.info("Triage results written to %s", triage_path)

    return results


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="OpenJev Step 15 — offline document ingest triage",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--input",  required=True,  help="Directory of raw documents to classify")
    p.add_argument("--output", default=None,   help="Directory to write triage_results.json")
    p.add_argument("--ext",    nargs="+",
                   default=[".txt", ".md", ".pdf", ".docx", ".html", ".csv"],
                   help="File extensions to process")
    p.add_argument("--delay",  type=int, default=200,
                   help="Milliseconds between API calls (rate-limit safety)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print results to stdout only; do not write JSON")
    return p


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    args = _build_parser().parse_args()

    if not JEV_S15_ENABLED and not JEV_API_KEY:
        logger.warning(
            "JEV_S15_INGEST_TRIAGE_ENABLED is not set or JEV_API_KEY is missing. "
            "Running in fallback mode (all documents get default classification)."
        )

    output_dir = None if args.dry_run else args.output
    results = batch_triage_directory(
        input_dir=args.input,
        output_dir=output_dir,
        extensions=tuple(args.ext),
        delay_ms=args.delay,
    )

    if args.dry_run or not args.output:
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
