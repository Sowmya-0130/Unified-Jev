# JEV client rate limits (observed)

- **Provider:** Codiv `POST {JEV_API_BASE}/v1/systemone` (one HTTP call per `jev_*` helper that uses `_jev_post`).
- **429:** `Retry-After` header honored when present; else exponential backoff `JEV_RETRY_BASE_MS * 2^attempt`.
- **Concurrency:** `JEV_MAX_CONCURRENCY` (default 2) shared `httpx.Client` session.
- **S1 fail-closed:** after retries, `jev_unavailable` → block, no SQL.

## Typical JEV calls per successful request (flags on)

| Route | Pre-chat | In-pipeline |
|-------|----------|-------------|
| SQL allow | S1 + S4 | S7 (optional), S9 (optional) |
| Semantic | S1 + S4 | S10 (optional), S13 (optional) |
| Blocked @ S1 | **S1 only** | — |

Safety acceptance (off mode): allow → **S1 only**; block → S1 choke via `get_final_answer` (no SQL).

## Capacity (production)

| Knob | Current | Risk |
|------|---------|------|
| `JEV_MAX_CONCURRENCY` | 2 (global) | S1 fail-closed + throttle → user-visible `jev_unavailable` blocks |
| Per-request calls | 2–4+ on SQL allow | S1, S4, optional S7/S9 stacked behind same semaphore |

**Proposed**
1. **Priority queue:** S1 > S4 > S7/S9/S10/S13 (S9/S13 off critical path via code defaults).
2. **S1 verdict cache:** key = normalized question hash, TTL from `JEV_S1_CACHE_TTL_S` (env).
3. **Size concurrency** from observed 429 Retry-After + provider quota, not a fixed 2.
4. **Load test:** `python eval/jev_load_probe.py` — 10 concurrent `get_final_answer` on allow prompts; report `jev_unavailable` count and p50/p90.