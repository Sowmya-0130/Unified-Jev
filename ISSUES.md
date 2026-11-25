# AURIX issue ledger

| ID | Title | Sev | Status | Root cause | Evidence | Fix | Verify |
|----|-------|-----|--------|------------|----------|-----|--------|
| I-01 | Azure OpenAI auth at first LLM call | P0 | **BLOCKED-ON-HUMAN (KEY)** | Neither main nor graph key authenticates to the configured public endpoint | HTTP **401** (not 403) both keys; error `code` **401** “invalid subscription key or wrong API endpoint”; `apim-request-id` eb384dd9… (main), dbbd8447… (graph); DNS `cognitiveservices` → **20.61.99.32** (public Azure, not privatelink); `openai.azure.com` **NXDOMAIN** | Sowmya: valid Key1 for `aipractices` cognitive resource + deployment `gpt-5.4` (or correct name) | `python scripts/i01_http_probe.py` → HTTP 200 |
| I-02 | JEV skip gates E2E never verified live | P1 | OPEN | Blocked by I-01 | `jev_smoke_trace.py` empty agent sequence | Unblock I-01 | live smoke vs mocks |
| I-03 | S7/S9/S13 unified confidence | P2 | CLOSED | — | `tests/test_jev_gates.py` | `JEV_CONFIDENCE_THRESHOLD` | pytest |
| I-04 | JEV flags at import time | P2 | CLOSED | `.env` once at startup (`override=False`) | `tests/test_i04_flags.py` | Streamlit reload | pytest |
| I-05 | WinError 10054 asyncio noise | P3 | CLOSED | Subprocess regress runner uses separate processes; Streamlit uses default Proactor | `scripts/verify_loop.py` uses `subprocess` | `_call_connection_lost` ConnectionResetError filter in `main.py` | Streamlit reconnect |
| I-06 | No automated JEV tests | P2 | CLOSED | — | `tests/test_jev_gates.py` | mocked gates | pytest |
| I-07 | Per-request JEV trace | P2 | IN-PROGRESS | Wired; empty until pipeline runs | `jev_trace` in response | I-01 unblocked | smoke |

## Classification (I-01): **KEY**

Public DNS reaches West Europe cognitive endpoint (`20.61.99.32`); no private-endpoint pattern. Both **FrYB**** (len 84)** and **098a**** (len 32)** return the same **401** JSON — wrong/inactive keys for this resource, not network lockdown (would typically be **403**) and not deployment/api-version errors (would be **404**/**400**).

## Message for Sowmya (KEY case)

> Hi Sowmya — for AURIX local dev against `https://aipractices.cognitiveservices.azure.com/` (deployment `gpt-5.4`, api-version `2024-12-01-preview`), both the main `AZURE_OPENAI_API_KEY` and `graph_api_key` return **HTTP 401** with `"code": "401", "message": "Access denied due to invalid subscription key or wrong API endpoint..."` (apim-request-id examples: `eb384dd9-7ab5-453f-a2f4-8869d84ddba6`). DNS resolves to public `20.61.99.32` (West Europe). Can you share the **active Key 1** for this Cognitive Services resource and confirm the exact **chat deployment name** we should use in `GPT4_LLM_MODEL_DEPLOYMENT_NAME`?