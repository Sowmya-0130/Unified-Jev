"""Recheck script — verifies all 15 JEV integration points."""
import ast

PASS = "  OK "
FAIL = "  MISSING "

def check_syntax(path):
    try:
        src = open(path, encoding="utf-8").read()
        ast.parse(src)
        lines = src.count("\n")
        print(f"{PASS} syntax  {path}  ({lines} lines)")
        return src
    except SyntaxError as e:
        print(f"{FAIL} syntax  {path}  {e}")
        return ""

# ---- Syntax ----------------------------------------------------------------
print("=" * 60)
print("SYNTAX CHECK")
print("=" * 60)
check_syntax("main.py")
core_src     = check_syntax("aurix_core.py")
api_src      = check_syntax("API_unified.py")
jev_src      = check_syntax("jev_client.py")
ingest_src   = check_syntax("ingest_triage.py")

# ---- jev_client functions --------------------------------------------------
print()
print("=" * 60)
print("JEV CLIENT FUNCTIONS  (jev_client.py + ingest_triage.py)")
print("=" * 60)
funcs = [
    ("S1",  "jev_safety_check",       jev_src),
    ("S2",  "jev_clarity_check",      jev_src),
    ("S3",  "jev_cache_intent_match", jev_src),
    ("S4",  "jev_routing_decision",   jev_src),
    ("S5",  "jev_model_complexity",   jev_src),
    ("S6",  "jev_sql_guard",          jev_src),
    ("S7",  "jev_sql_result_check",   jev_src),
    ("S8",  "jev_chart_trigger",      jev_src),
    ("S9",  "jev_eval_quality",       jev_src),
    ("S10", "jev_retrieval_mode",     jev_src),
    ("S11", "jev_rerank_chunks",      jev_src),
    ("S12", "jev_has_answer",         jev_src),
    ("S13", "jev_critic_check",       jev_src),
    ("S14", "jev_output_guard",       jev_src),
    ("S15", "jev_classify_document",  ingest_src),
]
all_ok = True
for step, fn, src in funcs:
    if f"def {fn}" in src:
        print(f"{PASS} {step}  {fn}()")
    else:
        print(f"{FAIL} {step}  {fn}()")
        all_ok = False

# ---- main.py flags ---------------------------------------------------------
print()
print("=" * 60)
print("FLAGS WIRED IN aurix_core.py")
print("=" * 60)
flags = [
    ("S1",  "JEV_S1_SAFETY_ENABLED"),
    ("S2",  "JEV_S2_CLARITY_ENABLED"),
    ("S3",  "JEV_S3_CACHE_ENABLED"),
    ("S4",  "JEV_ROUTING_ENABLED"),
    ("S5",  "JEV_S5_MODEL_ROUTER_ENABLED"),
    ("S6",  "JEV_S6_SQL_GUARD_ENABLED"),
    ("S7",  "JEV_S7_SQL_RESULT_ENABLED"),
    ("S8",  "JEV_S8_CHART_TRIGGER_ENABLED"),
    ("S9",  "JEV_S9_EVAL_ENABLED"),
    ("S10", "JEV_S10_RETRIEVAL_MODE_ENABLED"),
    ("S11", "JEV_S11_RERANKER_ENABLED"),
    ("S12", "JEV_S12_NOT_FOUND_ENABLED"),
    ("S13", "JEV_S13_CRITIC_ENABLED"),
    ("S14", "JEV_S14_OUTPUT_GUARD_ENABLED"),
]
for step, flag in flags:
    if flag in core_src:
        print(f"{PASS} {step}  {flag}")
    else:
        print(f"{FAIL} {step}  {flag}")
        all_ok = False

# ---- .env keys -------------------------------------------------------------
print()
print("=" * 60)
print(".ENV KEYS")
print("=" * 60)
env_src = open(".env", encoding="utf-8").read()
env_keys = [
    "JEV_API_KEY", "JEV_API_BASE", "JEV_MODEL", "JEV_CONFIDENCE_THRESHOLD",
    "JEV_ROUTING_ENABLED",
    "JEV_S1_SAFETY_ENABLED", "JEV_S2_CLARITY_ENABLED", "JEV_S3_CACHE_ENABLED",
    "JEV_S5_MODEL_ROUTER_ENABLED", "JEV_S6_SQL_GUARD_ENABLED",
    "JEV_S7_SQL_RESULT_ENABLED", "JEV_S8_CHART_TRIGGER_ENABLED",
    "JEV_S9_EVAL_ENABLED", "JEV_S10_RETRIEVAL_MODE_ENABLED",
    "JEV_S11_RERANKER_ENABLED", "JEV_S12_NOT_FOUND_ENABLED",
    "JEV_S13_CRITIC_ENABLED", "JEV_S14_OUTPUT_GUARD_ENABLED",
    "JEV_S15_INGEST_TRIAGE_ENABLED", "FAST_LLM_DEPLOYMENT_NAME",
]
for k in env_keys:
    if k in env_src:
        print(f"{PASS} {k}")
    else:
        print(f"{FAIL} {k}")
        all_ok = False

# ---- API_unified exports ---------------------------------------------------
print()
print("=" * 60)
print("API_unified.py EXPORTS")
print("=" * 60)
api_exports = [
    "JEV_ROUTING_ENABLED",
    "JEV_S1_SAFETY_ENABLED", "JEV_S2_CLARITY_ENABLED", "JEV_S3_CACHE_ENABLED",
    "JEV_S5_MODEL_ROUTER_ENABLED", "JEV_S6_SQL_GUARD_ENABLED",
    "JEV_S7_SQL_RESULT_ENABLED", "JEV_S8_CHART_TRIGGER_ENABLED",
    "JEV_S9_EVAL_ENABLED", "JEV_S10_RETRIEVAL_MODE_ENABLED",
    "JEV_S11_RERANKER_ENABLED", "JEV_S12_NOT_FOUND_ENABLED",
    "JEV_S13_CRITIC_ENABLED", "JEV_S14_OUTPUT_GUARD_ENABLED",
    "JEV_S15_INGEST_TRIAGE_ENABLED", "FAST_LLM_DEPLOYMENT_NAME",
]
for k in api_exports:
    if k in api_src:
        print(f"{PASS} {k}")
    else:
        print(f"{FAIL} {k}")
        all_ok = False

# ---- Structural patterns in main.py ----------------------------------------
print()
print("=" * 60)
print("STRUCTURAL PATTERNS IN aurix_core.py")
print("=" * 60)
patterns = [
    ("_answer_cache dict",   "_answer_cache: dict = {}"),
    ("_CACHE_MAX constant",  "_CACHE_MAX = 100"),
    ("S3 cache populate",    "_answer_cache[question]"),
    ("S5 model restore",     "_original_model"),
    ("S8 jev_chart stored",  "jev_chart"),
    ("S14 REDACTED block",   "REDACTED"),
    ("S9 skip_llm_eval",     "skip_llm_eval"),
    ("S13 jev_s13 key",      "jev_s13"),
    ("S11 rerank_chunks",    "jev_rerank_chunks"),
    ("S12 not_found flag",   "not_found"),
]
for label, pat in patterns:
    if pat in core_src:
        print(f"{PASS} {label}")
    else:
        print(f"{FAIL} {label}  (pattern: {pat})")
        all_ok = False

# ---- Final result ----------------------------------------------------------
print()
print("=" * 60)
print("RESULT:", "ALL CHECKS PASSED ✅" if all_ok else "SOME CHECKS FAILED ❌")
print("=" * 60)
