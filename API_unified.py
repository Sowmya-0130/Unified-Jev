"""
API_unified.py — loads all secrets from .env and exposes them as Python variables.
Every other module imports from here: main.py, config.py, metadata.py, graph_config.py
"""

import os
from pathlib import Path

from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent

# Load .env at import; override=True so local .env edits win over stale shell env (e.g. after pytest).
def _load_dotenv_file() -> None:
    load_dotenv(dotenv_path=_ROOT / ".env", override=True)


_load_dotenv_file()


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int = 0) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float = 0.0) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Azure OpenAI — main (AutoGen agents + search embeddings)
# ---------------------------------------------------------------------------
AZURE_OPENAI_API_KEY = _env("AZURE_OPENAI_API_KEY") or _env("AZURE_OPENAI_KEY")
_AZURE_OPENAI_API_BASE_REQUESTED = (
    _env("AZURE_OPENAI_API_BASE") or _env("AZURE_OPENAI_ENDPOINT")
)
AZURE_OPENAI_API_BASE_FALLBACKS = _env("AZURE_OPENAI_API_BASE_FALLBACKS")
AZURE_OPENAI_API_VERSION = (
    _env("AZURE_OPENAI_API_VERSION") or _env("CHAT_API_VERSION") or "2024-02-15-preview"
)
GPT4_LLM_MODEL_DEPLOYMENT_NAME = (
    _env("GPT4_LLM_MODEL_DEPLOYMENT_NAME")
    or _env("CHAT_DEPLOYMENT")
    or _env("CHAT_MODEL_NAME")
)
# gpt-5* deployments only accept temperature=1 (Azure returns 400 for 0.1).
_temp_raw = _env("AZURE_LLM_TEMPERATURE")
if _temp_raw:
    AZURE_LLM_TEMPERATURE = _env_float("AZURE_LLM_TEMPERATURE", 1.0)
elif "gpt-5" in (GPT4_LLM_MODEL_DEPLOYMENT_NAME or "").lower():
    AZURE_LLM_TEMPERATURE = 1.0
else:
    AZURE_LLM_TEMPERATURE = 0.1
AZURE_LLM_REQUEST_TIMEOUT = _env_int("AZURE_LLM_REQUEST_TIMEOUT", 120)
_llm_req_s = _env("LLM_REQUEST_TIMEOUT_S")
LLM_REQUEST_TIMEOUT_S = max(10, int(_llm_req_s)) if _llm_req_s else AZURE_LLM_REQUEST_TIMEOUT
_req_timeout = _env("REQUEST_TIMEOUT_S")
REQUEST_TIMEOUT_S = max(60, int(_req_timeout)) if _req_timeout else 600
REQUEST_LOCK_WAIT_S = max(5, _env_int("REQUEST_LOCK_WAIT_S", 30))
AZURE_LLM_MAX_RETRIES = _env_int("AZURE_LLM_MAX_RETRIES", 2)


def _parse_llm_price_per_1k(raw: str | None) -> list[float] | None:
    if not raw:
        return None
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    if len(parts) != 2:
        return None
    try:
        return [float(parts[0]), float(parts[1])]
    except ValueError:
        return None


# AutoGen built-in cost table lacks Azure deployment IDs (e.g. gpt-5-mini-*); [0,0] silences the warning.
AZURE_LLM_PRICE_PER_1K = _parse_llm_price_per_1k(_env("AZURE_LLM_PRICE_PER_1K")) or [0.0, 0.0]
AZURE_LLM_PREFLIGHT_ENABLED = _env_bool("AZURE_LLM_PREFLIGHT_ENABLED", False)
# Fast chat probe before AutoGen (clear message on 401/DNS; not the old DNS-only UI block).
AZURE_OPENAI_PROBE_BEFORE_CHAT = _env_bool("AZURE_OPENAI_PROBE_BEFORE_CHAT", False)
# Both spellings accepted; EMBEDDING_MODEL is the canonical .env key
Embedding_Model = (
    _env("EMBEDDING_MODEL")
    or _env("Embedding_Model")
    or _env("EMBEDDING_DEPLOYMENT")
    or _env("EMBEDDING_MODEL_NAME")
)

from azure_openai_endpoint import install_openai_dns_alias_patch, resolve_azure_openai_endpoint

install_openai_dns_alias_patch()
AZURE_OPENAI_API_BASE, _azure_ep_note = resolve_azure_openai_endpoint(
    _AZURE_OPENAI_API_BASE_REQUESTED,
    extra_candidates=AZURE_OPENAI_API_BASE_FALLBACKS,
)

# ---------------------------------------------------------------------------
# Azure AI Search
# ---------------------------------------------------------------------------
AZURE_SEARCH_SERVICE_ENDPOINT = (
    _env("AZURE_SEARCH_SERVICE_ENDPOINT") or _env("AZURE_SEARCH_ENDPOINT")
).rstrip("/")
_search_key = _env("AZURE_SEARCH_ADMIN_KEY") or _env("AZURE_SEARCH_KEY")
azure_search_credential = AzureKeyCredential(_search_key) if _search_key else None

IN_Name = _env("IN_NAME") or _env("SEARCH_INDEX_NAME")

# ---------------------------------------------------------------------------
# GraphRAG Azure OpenAI (falls back to main settings when env vars are empty)
# ---------------------------------------------------------------------------
graph_api_key = _env("GRAPH_API_KEY") or AZURE_OPENAI_API_KEY
_graph_base_req = _env("GRAPH_API_BASE") or AZURE_OPENAI_API_BASE
graph_api_base, _graph_ep_note = resolve_azure_openai_endpoint(
    _graph_base_req,
    extra_candidates=AZURE_OPENAI_API_BASE_FALLBACKS,
)
graph_api_version = _env("GRAPH_API_VERSION") or AZURE_OPENAI_API_VERSION
graph_llm_model = _env("GRAPH_LLM_MODEL")
graph_llm_deployment = _env("GRAPH_LLM_DEPLOYMENT") or graph_llm_model
graph_embedding_model = _env("GRAPH_EMBEDDING_MODEL") or Embedding_Model

# ---------------------------------------------------------------------------
# Azure SQL
# ---------------------------------------------------------------------------
AZURE_SQL_SERVER = _env("AZURE_SQL_SERVER")
AZURE_SQL_DATABASE = _env("AZURE_SQL_DATABASE")
AZURE_SQL_USERNAME = _env("AZURE_SQL_USERNAME")
AZURE_SQL_PASSWORD = _env("AZURE_SQL_PASSWORD")
AZURE_SQL_DRIVER_REQUESTED = _env("AZURE_SQL_DRIVER")
AZURE_SQL_SCHEMA = _env("AZURE_SQL_SCHEMA")
AZURE_SQL_ENCRYPT = _env_bool("AZURE_SQL_ENCRYPT", True)
AZURE_SQL_TRUST_SERVER_CERTIFICATE = _env_bool("AZURE_SQL_TRUST_SERVER_CERTIFICATE", True)
AZURE_SQL_CONNECTION_TIMEOUT = _env_int("AZURE_SQL_CONNECTION_TIMEOUT", 60)
_sql_q_timeout = _env("SQL_QUERY_TIMEOUT_S")
SQL_QUERY_TIMEOUT_S = max(5, int(_sql_q_timeout)) if _sql_q_timeout else AZURE_SQL_CONNECTION_TIMEOUT
AZURE_SQL_ODBC_RETRIES = _env_int("AZURE_SQL_ODBC_RETRIES", 4)
AZURE_SQL_MARS_CONNECTION = _env_bool("AZURE_SQL_MARS_CONNECTION", True)
AZURE_SQL_EVAL_LOG_RETRIES = _env_int("AZURE_SQL_EVAL_LOG_RETRIES", 3)
# Agent SQL: SELECT-only; set false only if you accept LLM write queries (not recommended).
SQL_AGENT_READ_ONLY = _env_bool("SQL_AGENT_READ_ONLY", True)
# Eval INSERT is separate from agent SQL; never on when SQL_AGENT_READ_ONLY (no DB writes from app).
_AZURE_SQL_EVAL_LOG_REQUESTED = _env_bool("AZURE_SQL_EVAL_LOG_ENABLED", False)
AZURE_SQL_EVAL_LOG_ENABLED = _AZURE_SQL_EVAL_LOG_REQUESTED and not SQL_AGENT_READ_ONLY
AZURE_SQL_EVAL_TABLE = _env("AZURE_SQL_EVAL_TABLE") or "Unified_Eval"
AZURE_SQL_EVAL_ID_PREFIX = _env("AZURE_SQL_EVAL_ID_PREFIX") or "EVAL-"
AZURE_SQL_EVAL_ID_SEED = _env_int("AZURE_SQL_EVAL_ID_SEED", 1000)
SQL_SCHEMA_CACHE_ENABLED = _env_bool("SQL_SCHEMA_CACHE_ENABLED", True)
_sql_cache_default = str(_ROOT / ".cache" / "sql_table_schemas.txt")
SQL_SCHEMA_CACHE_PATH = _env("SQL_SCHEMA_CACHE_PATH") or _sql_cache_default
SQL_SCHEMA_CACHE_MAX_AGE_SEC = _env_int("SQL_SCHEMA_CACHE_MAX_AGE_SEC", 86400)
# When cache file exists but is older than max age, use it unless this is true (avoids ODBC on every start).
SQL_SCHEMA_FORCE_LIVE_REFRESH = _env_bool("SQL_SCHEMA_FORCE_LIVE_REFRESH", False)

BENCH_RUNS = max(1, _env_int("BENCH_RUNS", 3))

# AutoGen disk cache for LLM completions (.cache/{seed}); production default mirrors autogen (seed 41).
LLM_RESPONSE_CACHE = _env_bool("LLM_RESPONSE_CACHE", False)
LLM_RESPONSE_CACHE_SEED = _env_int("LLM_RESPONSE_CACHE_SEED", 41)
LLM_RESPONSE_CACHE_DIR = _env("LLM_RESPONSE_CACHE_DIR") or ".cache"

_bench_tol = _env("BENCH_CORRECTNESS_REL_TOLERANCE")
BENCH_CORRECTNESS_REL_TOLERANCE = float(_bench_tol) if _bench_tol else 0.05
SQL_MAX_REPAIR_ROUNDS = max(1, _env_int("SQL_MAX_REPAIR_ROUNDS", 2))
SQL_FEW_SHOT_ENABLED = _env_bool("SQL_FEW_SHOT_ENABLED", True)
SQL_FEW_SHOT_MAX = max(0, min(8, _env_int("SQL_FEW_SHOT_MAX", 3)))
SQL_FEW_SHOT_BANK_VERSION = max(1, _env_int("SQL_FEW_SHOT_BANK_VERSION", 1))
_sql_reasoning = (_env("SQL_GENERATOR_REASONING_EFFORT") or "low").strip()
SQL_GENERATOR_REASONING_EFFORT = _sql_reasoning if _sql_reasoning.lower() not in ("", "none", "off") else ""
ACCEPT_QUESTION_TIMEOUT_S = max(30, _env_int("ACCEPT_QUESTION_TIMEOUT_S", 120))
ACCEPT_USE_WARM_WORKER = _env_bool("ACCEPT_USE_WARM_WORKER", True)
ACCEPT_ISOLATE_SUBPROCESS = _env_bool("ACCEPT_ISOLATE_SUBPROCESS", False)
ACCEPT_SUITE_TIMEOUT_S = max(300, _env_int("ACCEPT_SUITE_TIMEOUT_S", 5400))
ACCEPT_CONSECUTIVE_FAIL_MAX = max(2, _env_int("ACCEPT_CONSECUTIVE_FAIL_MAX", 5))
_accept_fail_rate = _env("ACCEPT_FAIL_RATE_MAX")
ACCEPT_FAIL_RATE_MAX = float(_accept_fail_rate) if _accept_fail_rate else 0.25
ACCEPT_MIN_ROWS_BEFORE_RATE = max(3, _env_int("ACCEPT_MIN_ROWS_BEFORE_RATE", 8))
SQL_CATALOG_TTL_SEC = max(60, _env_int("SQL_CATALOG_TTL_SEC", 3600))
SCHEMA_LINK_TOP_K = max(1, _env_int("SCHEMA_LINK_TOP_K", 8))
SQL_DEFAULT_SCHEMA = _env("SQL_DEFAULT_SCHEMA") or "dbo"
SQL_CATALOG_MIN_TABLES = max(10, _env_int("SQL_CATALOG_MIN_TABLES", 40))

# AutoGen SQLite runtime log — off by default (writing info.db makes Streamlit reload mid-chat).
AUTOGEN_RUNTIME_LOG_ENABLED = _env_bool("AUTOGEN_RUNTIME_LOG_ENABLED", False)
AUTOGEN_RUNTIME_LOG_DB = _env("AUTOGEN_RUNTIME_LOG_DB") or str(_ROOT / ".cache" / "autogen_events.db")

# ---------------------------------------------------------------------------
# Request tracing (jev_trace.py — no hardcoded .loop/)
# ---------------------------------------------------------------------------
TRACE_PRINT_SUMMARY = _env_bool("TRACE_PRINT_SUMMARY", True)
TRACE_PERSIST = _env_bool("TRACE_PERSIST", False)
_trace_dir_default = str(_ROOT / ".cache" / "traces")
TRACE_PERSIST_DIR = _env("TRACE_PERSIST_DIR") or _trace_dir_default

# ---------------------------------------------------------------------------
# UI / AutoGen paths
# ---------------------------------------------------------------------------
_default_logo = "https://acis.affineanalytics.co.in/assets/images/logo_small.png"
AURIX_LOGO_URL = _env("AURIX_LOGO_URL") or _default_logo
AUTOGEN_WORK_DIR = _env("AUTOGEN_WORK_DIR") or "Routing_File"
AZURE_SQL_WARM_ON_STARTUP = _env_bool("AZURE_SQL_WARM_ON_STARTUP", False)
# Optional; some Azure SQL tiers reject ApplicationIntent=ReadOnly (HY000).
AZURE_SQL_USE_READONLY_INTENT = _env_bool("AZURE_SQL_USE_READONLY_INTENT", False)

# ---------------------------------------------------------------------------
# GraphRAG artifacts path
# ---------------------------------------------------------------------------
_input_dir_raw = _env("INPUT_DIR")
INPUT_DIR = str(Path(_input_dir_raw).expanduser()) if _input_dir_raw else str(_ROOT / "artifacts")
GRAPH_COMMUNITY_REPORT_TABLE = _env("GRAPH_COMMUNITY_REPORT_TABLE") or "create_final_community_reports"
GRAPH_ENTITY_TABLE = _env("GRAPH_ENTITY_TABLE") or "create_final_nodes"
GRAPH_ENTITY_EMBEDDING_TABLE = _env("GRAPH_ENTITY_EMBEDDING_TABLE") or "create_final_entities"
GRAPH_RELATIONSHIP_TABLE = _env("GRAPH_RELATIONSHIP_TABLE") or "create_final_relationships"
GRAPH_TEXT_UNIT_TABLE = _env("GRAPH_TEXT_UNIT_TABLE") or "create_final_text_units"
GRAPH_COMMUNITY_LEVEL = _env_int("GRAPH_COMMUNITY_LEVEL", 3)

# ---------------------------------------------------------------------------
# OpenJev / Codiv — shared config
# ---------------------------------------------------------------------------
JEV_API_KEY = _env("JEV_API_KEY")
JEV_API_BASE = (_env("JEV_API_BASE") or "https://api.codiv.ai").rstrip("/")
JEV_MODEL = _env("JEV_MODEL") or "openjev-latest"
_jev_thresh = _env("JEV_CONFIDENCE_THRESHOLD")
JEV_CONFIDENCE_THRESHOLD = float(_jev_thresh) if _jev_thresh else 0.8
_jev_timeout = _env("JEV_TIMEOUT_MS")
JEV_TIMEOUT_MS = max(100, int(_jev_timeout)) if _jev_timeout else 1500
JEV_RETRY_MAX = max(0, _env_int("JEV_RETRY_MAX", 3))
JEV_RETRY_BASE_MS = max(50, _env_int("JEV_RETRY_BASE_MS", 500))
JEV_MAX_CONCURRENCY = max(1, _env_int("JEV_MAX_CONCURRENCY", 2))
JEV_SHADOW_MODE = _env_bool("JEV_SHADOW_MODE", False)
PRESTAGE_PARALLEL_ENABLED = _env_bool("PRESTAGE_PARALLEL_ENABLED", True)
PRESTAGE_WALL_S = max(1.0, float(_env_int("PRESTAGE_WALL_S", 8)))
PRESTAGE_MAX_WORKERS = max(2, _env_int("PRESTAGE_MAX_WORKERS", 5))
_prestage_arm = _env("PRESTAGE_ARM_TIMEOUT_S")
PRESTAGE_ARM_TIMEOUT_S = float(_prestage_arm) if _prestage_arm else 0.0
ASYNC_POSTCHECKS_ENABLED = _env_bool("ASYNC_POSTCHECKS_ENABLED", False)
ASYNC_POSTCHECKS_TIMEOUT_S = max(1.0, float(_env_int("ASYNC_POSTCHECKS_TIMEOUT_S", 30)))
MERGE_NODE_ENABLED = _env_bool("MERGE_NODE_ENABLED", True)
MERGE_NODE_TIMEOUT_S = max(0.5, float(_env_int("MERGE_NODE_TIMEOUT_S", 5)))
MERGE_NODE_MODEL = (_env("MERGE_NODE_MODEL") or "").strip() or None

# Per-step toggles (all default False — existing LLM is always the fallback)
JEV_ROUTING_ENABLED       = _env_bool("JEV_ROUTING_ENABLED",        False)  # S4
ROUTING_LLM_FALLBACK      = _env_bool("ROUTING_LLM_FALLBACK",       False)
SQL_S7_LLM_FALLBACK       = _env_bool("SQL_S7_LLM_FALLBACK",        False)
SEMANTIC_QUERY_TRANSFORMER_LLM = _env_bool("SEMANTIC_QUERY_TRANSFORMER_LLM", False)
RAI_LLM_FALLBACK          = _env_bool("RAI_LLM_FALLBACK",           False)
_orchestrator = (_env("ORCHESTRATOR") or "pipeline").strip().lower()
ORCHESTRATOR = _orchestrator if _orchestrator in ("pipeline", "groupchat") else "pipeline"
DATA_PROFILE_PATH = _env("DATA_PROFILE_PATH") or ".cache/data_profile.json"
DATA_PROFILE_REFRESH_EACH_REQUEST = _env_bool("DATA_PROFILE_REFRESH_EACH_REQUEST", False)
S14_PII_REDACT_ENABLED = _env_bool("S14_PII_REDACT_ENABLED", True)
JEV_S1_SAFETY_ENABLED     = _env_bool("JEV_S1_SAFETY_ENABLED",      False)
# off | grey_zone | always — JEV+regex decide; grey uses RAI LLM only in grey zone (when grey_zone)
SAFETY_LLM_MODE = (_env("SAFETY_LLM_MODE") or "always").strip().lower()
if SAFETY_LLM_MODE not in ("off", "grey_zone", "always"):
    SAFETY_LLM_MODE = "always"
_s1_allow = _env("SAFETY_JEV_ALLOW_LOW")
SAFETY_JEV_ALLOW_LOW = float(_s1_allow) if _s1_allow else 0.05
_s1_block = _env("SAFETY_JEV_BLOCK_HIGH")
SAFETY_JEV_BLOCK_HIGH = float(_s1_block) if _s1_block else 0.85
JEV_S2_CLARITY_ENABLED    = _env_bool("JEV_S2_CLARITY_ENABLED",     False)
JEV_S3_CACHE_ENABLED      = _env_bool("JEV_S3_CACHE_ENABLED",       False)
JEV_S3_CACHE_VERSION      = (_env("JEV_S3_CACHE_VERSION") or "").strip()
STREAMING_ENABLED         = _env_bool("STREAMING_ENABLED", False)
JEV_S5_MODEL_ROUTER_ENABLED = _env_bool("JEV_S5_MODEL_ROUTER_ENABLED", False)
JEV_S6_SQL_GUARD_ENABLED  = _env_bool("JEV_S6_SQL_GUARD_ENABLED",   False)
JEV_S7_SQL_RESULT_ENABLED = _env_bool("JEV_S7_SQL_RESULT_ENABLED",  False)
JEV_S8_CHART_TRIGGER_ENABLED = _env_bool("JEV_S8_CHART_TRIGGER_ENABLED", False)
JEV_S9_EVAL_ENABLED       = _env_bool("JEV_S9_EVAL_ENABLED",        False)
JEV_S10_RETRIEVAL_MODE_ENABLED = _env_bool("JEV_S10_RETRIEVAL_MODE_ENABLED", False)
JEV_S11_RERANKER_ENABLED  = _env_bool("JEV_S11_RERANKER_ENABLED",   False)
JEV_S12_NOT_FOUND_ENABLED = _env_bool("JEV_S12_NOT_FOUND_ENABLED",  False)
JEV_S13_CRITIC_ENABLED    = _env_bool("JEV_S13_CRITIC_ENABLED",     False)
JEV_S14_OUTPUT_GUARD_ENABLED = _env_bool("JEV_S14_OUTPUT_GUARD_ENABLED", False)
JEV_S15_INGEST_TRIAGE_ENABLED = _env_bool("JEV_S15_INGEST_TRIAGE_ENABLED", False)

# Fast/cheap LLM deployment for simple queries (Step 5); empty = disable model switching
FAST_LLM_DEPLOYMENT_NAME = _env("FAST_LLM_DEPLOYMENT_NAME")

# Comma-separated semantic topic hints for Eryl / document routing (optional)
_semantic_hints = _env("SEMANTIC_TOPIC_HINTS")
Vector_Data = [h.strip() for h in _semantic_hints.split(",") if h.strip()] if _semantic_hints else []
_web_hints = _env("WEB_SEARCH_TOPIC_HINTS")
Web_Search_Data = [h.strip() for h in _web_hints.split(",") if h.strip()] if _web_hints else []

# ---------------------------------------------------------------------------
# ODBC driver (pyodbc name, not Windows DLL file version)
# ---------------------------------------------------------------------------
import logging as _logging

from odbc_driver import describe_driver_binding, resolve_odbc_driver

_odbc_log = _logging.getLogger(__name__)
if _azure_ep_note:
    _odbc_log.warning(_azure_ep_note)
if _graph_ep_note:
    _odbc_log.warning("Graph OpenAI: %s", _graph_ep_note)
AZURE_SQL_DRIVER = resolve_odbc_driver(AZURE_SQL_DRIVER_REQUESTED or "ODBC Driver 18 for SQL Server")
if _AZURE_SQL_EVAL_LOG_REQUESTED and SQL_AGENT_READ_ONLY:
    _odbc_log.info(
        "AZURE_SQL_EVAL_LOG_ENABLED ignored while SQL_AGENT_READ_ONLY=true (database stays read-only)."
    )
_odbc_log.info("%s", describe_driver_binding(AZURE_SQL_DRIVER))
