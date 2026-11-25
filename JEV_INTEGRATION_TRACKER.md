# JEV Integration Tracker — AURIX Pipeline

> **15 hooks wired in code** · **5 core gates ON** in `.env` (S1, S4, S7, S9, S13) · **10 optional hooks OFF**  
> Last updated: 2026-11-24  
> Runtime code lives in **`aurix_core.py`** (not `main.py`). Streamlit **`main.py`** only loads the backend.

---

## Quick Status Dashboard

| # | Layer | Hook Point | File | Gate | Status | Speed Gain | Cost Saving |
|---|-------|-----------|------|------|--------|-----------|-------------|
| 1 | Pre-agent | Input safety / moderation | `aurix_core.py · azure_safety_check()` | Core | **ON** | 25× | 95% |
| 2 | Pre-agent | Ambiguity / clarity gate | `aurix_core.py · get_final_answer()` | Optional | OFF | Skips full pipeline | 100% on vague |
| 3 | Pre-agent | Semantic answer cache | `aurix_core.py · get_final_answer()` | Optional | OFF | Instant replay | 100% on hit |
| 4 | Pre-agent | Routing decision | `aurix_core.py · state_transition()` | Core | **ON** | 20× | 90% |
| 5 | Pre-agent | Dynamic LLM size router | `aurix_core.py · get_final_answer()` | Optional | OFF | 10× | 70% simple |
| 6 | SQL path | SQL pre-execution guard | `aurix_core.py · db_execute_query()` | Optional | OFF | 22× | 95% |
| 7 | SQL path | SQL result validation | `aurix_core.py · state_transition()` | Core | **ON** | 27× | 95% |
| 8 | SQL path | Chart / visualisation trigger | `aurix_core.py · get_final_answer()` | Optional | OFF | Instant signal | — |
| 9 | Eval path | Quality gate (skip LLM eval) | `aurix_core.py · state_transition()` | Core | **ON** | 30× | 95% |
| 10 | Semantic path | Retrieval mode picker | `aurix_core.py · extract_context()` | Optional | OFF | — | 40% |
| 11 | Semantic path | Chunk reranker | `aurix_core.py · extract_context()` | Optional | OFF | — | — |
| 12 | Semantic path | "Not Found" short-circuit | `aurix_core.py · extract_context()` | Optional | OFF | Skips LLM | 100% miss |
| 13 | Semantic path | Critic / hallucination check | `aurix_core.py · state_transition()` | Core | **ON** | 25× | 95% |
| 14 | Post-agent | Output PII / data-leak guard | `aurix_core.py · get_final_answer()` | Optional | OFF | +0.08 s | — |
| 15 | Offline | Document ingest triage | `ingest_triage.py` | Optional | OFF | — | — |

See **`docs/ARCHITECTURE_JEV.md`** for the Mermaid flow and Azure endpoint notes.

---

## Enable Flags (`.env`)

```env
JEV_API_KEY=sk-codiv-...            # Codiv / OpenJev (not Azure)
JEV_API_BASE=https://api.codiv.ai
JEV_MODEL=openjev-latest
JEV_CONFIDENCE_THRESHOLD=0.75

# Core gates (ON)
JEV_S1_SAFETY_ENABLED=true
JEV_ROUTING_ENABLED=true
JEV_S7_SQL_RESULT_ENABLED=true
JEV_S9_EVAL_ENABLED=true
JEV_S13_CRITIC_ENABLED=true

# Optional hooks (OFF)
JEV_S2_CLARITY_ENABLED=false
JEV_S3_CACHE_ENABLED=false
JEV_S5_MODEL_ROUTER_ENABLED=false
JEV_S6_SQL_GUARD_ENABLED=false
JEV_S8_CHART_TRIGGER_ENABLED=false
JEV_S10_RETRIEVAL_MODE_ENABLED=false
JEV_S11_RERANKER_ENABLED=false
JEV_S12_NOT_FOUND_ENABLED=false
JEV_S14_OUTPUT_GUARD_ENABLED=false
JEV_S15_INGEST_TRIAGE_ENABLED=false
```

---

## Per-Step Implementation Details

### S1 — Input Safety (Core)
- **Hook:** `aurix_core.py → azure_safety_check()` (~L177)
- **Function:** `jev_safety_check`
- **Decides:** Toxic / PII / injection Noul scores; may tighten regex `risk_score`
- **OFF / low conf:** Regex-only safety; Responsible_AI_Agent always runs
- **Fallback:** `try/except` → regex only

### S2 — Clarity (Optional)
- **Hook:** `get_final_answer()` (~L1667)
- **Function:** `jev_clarity_check`
- **OFF:** Full AutoGen pipeline always runs

### S3 — Cache (Optional)
- **Hook:** `get_final_answer()` (~L1686, ~L1891)
- **Function:** `jev_cache_intent_match`
- **OFF:** No cache read/write

### S4 — Routing (Core)
- **Hook:** `state_transition()` after Responsible_AI_Agent (~L1252)
- **Function:** `jev_routing_decision`
- **Confident:** Synthetic `routing_agent` message; skips LLM `routing_agent`
- **Low conf / error:** `routing_agent` LLM (`source=fallback` or `< JEV_CONFIDENCE_THRESHOLD`)

### S5 — Model router (Optional)
- **Hook:** `get_final_answer()` (~L1698); needs `FAST_LLM_DEPLOYMENT_NAME`
- **OFF or empty FAST_LLM:** Original deployment only

### S6 — SQL guard (Optional)
- **Hook:** `db_execute_query()` (~L1188)
- **Function:** `jev_sql_guard`
- **OFF:** `sql_safety.assert_readonly_sql` + `fetch_dataframe_readonly` only (no JEV block)

### S7 — SQL result (Core)
- **Hook:** `state_transition()` after `Sql_tool` (~L1303)
- **Function:** `jev_sql_result_check`
- **PASS (`source=openjev`, valid):** Skip `Sql_Execution_Critic` → `Insight_Generator`
- **FAIL / API error / `source=fallback`:** `Sql_Execution_Critic` LLM

### S8 — Chart (Optional)
- **Hook:** `get_final_answer()` Sql_tool branch (~L1796)
- **OFF:** No `jev_chart` metadata

### S9 — Eval quality (Core)
- **Hook:** after `Insight_Generator` (~L1349)
- **Function:** `jev_eval_quality`
- **skip_llm_eval:** Synthetic `Evaluation_Agent` PASS
- **Else:** `Evaluation_Agent` LLM

### S10 — Retrieval mode (Optional)
- **Hook:** `extract_context()` (~L1091)
- **OFF:** `selector = "vector"` default

### S11 — Rerank (Optional)
- **Hook:** `extract_context()` (~L1144, ~L1163)
- **OFF:** Azure Search order unchanged

### S12 — Not found (Optional)
- **Hook:** `extract_context()` (~L1129)
- **OFF:** `llm_answer_maker` always runs

### S13 — Critic (Core)
- **Hook:** after `llm_answer_maker` (~L1404)
- **Function:** `jev_critic_check`
- **ok:** Skip `critic_agent` LLM
- **not ok / error:** `critic_agent` LLM

### S14 — Output guard (Optional)
- **Hook:** end of `get_final_answer()` (~L1898)
- **OFF:** Answers returned unredacted by JEV

### S15 — Ingest (Optional, offline)
- **File:** `ingest_triage.py` → `jev_classify_document`
- **OFF:** Script warns; no online pipeline hook

---

## Files

| File | Role |
|------|------|
| `jev_client.py` | S1–S14 client functions; Codiv HTTP only |
| `aurix_core.py` | All runtime hooks |
| `ingest_triage.py` | S15 offline |
| `API_unified.py` | `JEV_*` flags from `.env` |
| `main.py` | Streamlit; reloads `API_unified` + `aurix_core` |
| `docs/ARCHITECTURE_JEV.md` | Architecture + Mermaid |