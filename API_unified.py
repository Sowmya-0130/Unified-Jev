"""
API_unified.py — loads all secrets from .env and exposes them as Python variables.
Every other module imports from here: main.py, config.py, metadata.py, graph_config.py
"""

import os
from pathlib import Path

from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent

# Always load .env from the project root (works regardless of cwd)
load_dotenv(dotenv_path=_ROOT / ".env", override=True)


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


# ---------------------------------------------------------------------------
# Azure OpenAI — main (AutoGen agents + search embeddings)
# ---------------------------------------------------------------------------
AZURE_OPENAI_API_KEY = _env("AZURE_OPENAI_API_KEY")
_AZURE_OPENAI_API_BASE_REQUESTED = _env("AZURE_OPENAI_API_BASE")
AZURE_OPENAI_API_BASE_FALLBACKS = _env("AZURE_OPENAI_API_BASE_FALLBACKS")
AZURE_OPENAI_API_VERSION = _env("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
GPT4_LLM_MODEL_DEPLOYMENT_NAME = _env("GPT4_LLM_MODEL_DEPLOYMENT_NAME")
AZURE_LLM_REQUEST_TIMEOUT = _env_int("AZURE_LLM_REQUEST_TIMEOUT", 120)
AZURE_LLM_MAX_RETRIES = _env_int("AZURE_LLM_MAX_RETRIES", 2)
AZURE_LLM_PREFLIGHT_ENABLED = _env_bool("AZURE_LLM_PREFLIGHT_ENABLED", False)
# Fast chat probe before AutoGen (clear message on 401/DNS; not the old DNS-only UI block).
AZURE_OPENAI_PROBE_BEFORE_CHAT = _env_bool("AZURE_OPENAI_PROBE_BEFORE_CHAT", False)
# Both spellings accepted; EMBEDDING_MODEL is the canonical .env key
Embedding_Model = _env("EMBEDDING_MODEL") or _env("Embedding_Model")

from azure_openai_endpoint import install_openai_dns_alias_patch, resolve_azure_openai_endpoint

install_openai_dns_alias_patch()
AZURE_OPENAI_API_BASE, _azure_ep_note = resolve_azure_openai_endpoint(
    _AZURE_OPENAI_API_BASE_REQUESTED,
    extra_candidates=AZURE_OPENAI_API_BASE_FALLBACKS,
)

# ---------------------------------------------------------------------------
# Azure AI Search
# ---------------------------------------------------------------------------
AZURE_SEARCH_SERVICE_ENDPOINT = _env("AZURE_SEARCH_SERVICE_ENDPOINT").rstrip("/")
_search_key = _env("AZURE_SEARCH_ADMIN_KEY")
azure_search_credential = AzureKeyCredential(_search_key) if _search_key else None

IN_Name = _env("IN_NAME")

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

# AutoGen SQLite runtime log — off by default (writing info.db makes Streamlit reload mid-chat).
AUTOGEN_RUNTIME_LOG_ENABLED = _env_bool("AUTOGEN_RUNTIME_LOG_ENABLED", False)
AUTOGEN_RUNTIME_LOG_DB = _env("AUTOGEN_RUNTIME_LOG_DB") or str(_ROOT / ".cache" / "autogen_events.db")

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

# Per-step toggles (all default False — existing LLM is always the fallback)
JEV_ROUTING_ENABLED       = _env_bool("JEV_ROUTING_ENABLED",        False)  # S4
JEV_S1_SAFETY_ENABLED     = _env_bool("JEV_S1_SAFETY_ENABLED",      False)
JEV_S2_CLARITY_ENABLED    = _env_bool("JEV_S2_CLARITY_ENABLED",     False)
JEV_S3_CACHE_ENABLED      = _env_bool("JEV_S3_CACHE_ENABLED",       False)
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
