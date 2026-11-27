# AURIX — corrected JEV orchestration (target)

**Goals:** correct answers · SQL p50 ≤ 5 s, p90 ≤ 10 s · docs/Both p90 ≤ 10 s  
**Principle:** JEV + code decide; LLMs only write. One decision-maker per gate.

## Request flow

```
Question
  │
  ├─► [parallel ~1 s]  S1 (JEV+regex) ║ S4 (JEV) ║ schema link ║ S3 cache ║ doc prefetch
  │                    (Sql_Generator may start speculatively; no SQL EXECUTE before S1=allow)
  │
  ├─ blocked ─────────► code message, stop
  ├─ cache hit ───────► answer (~1 s)
  ├─ ambiguous ───────► clarification template
  │
  ├─ DATABASE ─► Sql_Generator (1 LLM, low reasoning, few-shot bank [A6])
  │              → validator (code) → repair once with error → else template
  │              → Sql_tool exact SQL
  │              → rows? (code) → none → no-data template + coverage
  │              → template (simple) | Insight_Generator streamed (complex)
  │              → grounding (code) [A3] → fail → once regenerate → template
  │
  ├─ DOCUMENTS ► retriever (code, S10) [A4] → llm_answer_maker streamed
  │              → S13 + code → fail → once regenerate → passages template
  │
  ├─ BOTH ─────► parallel DB + docs arms → merge (code, no extra LLM)
  │
  └─► answer streamed [A8] ─ background: evaluation_agent / critic_agent / S9 (quality logs only [A3])
```

## Runtime modes

| Mode | Env | Entry |
|------|-----|--------|
| **Code pipeline (default)** | `ORCHESTRATOR=pipeline` | `orchestrator.py` state machine |
| GroupChat rollback | `ORCHESTRATOR=groupchat` | AutoGen `state_transition` |

Per-request: `request_context.RequestContext` (transcript only for that request). No shared `groupchat.messages`.

## Gates & rollback flags

| Step | Maker | Rollback |
|------|--------|----------|
| S1 | `safety_gate` regex + JEV | `SAFETY_LLM_MODE`, `RAI_LLM_FALLBACK` |
| S4 | `routing_s4.preflight_s4` | `ROUTING_LLM_FALLBACK` |
| SQL valid / rows | code (`sql_pipeline`, S7) | `SQL_S7_LLM_FALLBACK` |
| S9 / S13 | JEV (post-answer async [A3]) | — |

**Must not run (default):** Responsible_AI_Agent (S1 off), routing_agent LLM, Query_Executor LLM, Sql_Execution_Critic, query_transformer, user_proxy reflection LLM.

## Roadmap (measured per cycle)

| ID | Item |
|----|------|
| **A1** | Code orchestrator (`ORCHESTRATOR=pipeline`) |
| A2 | Parallel pre-stage (S1∥S4∥schema∥cache∥prefetch) |
| A3 | Post-checks off critical path |
| A4 | Direct retriever (no Eryl LLM) → pipeline `retriever` + `extract_context` (done) |
| A5 | Honest / clarity / timeout exits → **`pipeline_exits.py`** (done) |
| A6 | SQL few-shot bank + reasoning_effort → **`sql_few_shot_bank.py`** (done) |
| A7 | Versioned S3 cache → **`jev_s3_cache_version.py`** (done) |
| A8 | Streaming first token → **`STREAMING_ENABLED`** + `main._display_answer_text` (done) |

## Conformance & acceptance

- `flow_conformance.check_trace` — forbidden agents, S1/S4 `run_llm`
- `tests/test_flow_conformance.py`, harness in `eval/sql_acceptance.py` / `safety_acceptance.py`
- Suites: SQL 33+33 shuffled, Both 9, semantic + user-style, safety 103/123

Config: `API_unified.py` + `.env`. Traces: `jev_trace` (`TRACE_PERSIST`, `TRACE_PERSIST_DIR`).