# AURIX issue ledger

| ID | Title | Sev | Status | Root cause | Evidence | Fix | Verify |
|----|-------|-----|--------|------------|----------|-----|--------|
| I-01 | Azure OpenAI auth at first LLM call | P0 | **BLOCKED-ON-HUMAN (ENDPOINT)** | Host/key mismatch: `aipractices.openai.azure.com` **NXDOMAIN**; keys rejected with explicit “wrong API endpoint” | HTTP **401** both keys (`scripts/i01_http_probe.py`); JSON `code` **401**; `aipractices.cognitiveservices.azure.com` → CNAME `20.61.99.32` (WE) but fake stem `aurix-nonexistent-zq7x91.cognitiveservices.azure.com` → **NXDOMAIN** (no wildcard) | Portal **Endpoint** + **Keys** from same OpenAI-capable resource; correct `*.openai.azure.com` or Portal host | `i01_http_probe.py` → 200 |
| I-02 | JEV skip gates E2E never verified live | P1 | OPEN | Blocked by I-01 | smoke trace | Unblock I-01 | live smoke |
| I-03 | S7/S9/S13 unified confidence | P2 | CLOSED | — | pytest | — | pytest |
| I-04 | JEV flags at import time | P2 | CLOSED | — | pytest | — | pytest |
| I-05 | WinError 10054 asyncio noise | P3 | CLOSED | — | `main.py` handler | — | Streamlit |
| I-06 | No automated JEV tests | P2 | CLOSED | — | `test_jev_gates.py` | — | pytest |
| I-07 | Per-request JEV trace | P2 | IN-PROGRESS | — | `jev_trace` | I-01 | smoke |
| I-08 | DNS alias patch may hide wrong endpoint | P1 | OPEN | `install_openai_dns_alias_patch()` can resolve `*.openai.azure.com` via `*.cognitiveservices.azure.com` when stem exists in DNS | I-01: openai host NXDOMAIN but cognitiveservices stem resolves yet 401 “wrong API endpoint”; see `azure_openai_endpoint.py` | Warning logs on patch install + per alias; do not remove patch yet | Log lines on import |

## I-01 classification: **ENDPOINT** (revised from KEY)

**Reasoning**

1. **`aipractices.openai.azure.com` is NXDOMAIN** on public DNS — the usual Portal hostname for an Azure OpenAI resource is missing; we may be calling a **cognitiveservices** URL that is not the paired OpenAI endpoint for these keys.
2. Azure’s error text says **“invalid subscription key or wrong API endpoint”** (HTTP **401**, not **403**) for **both** keys — consistent with **endpoint/resource name wrong**, deleted, or not OpenAI-capable, not only a bad key on the correct host.
3. **Wildcard test (step 1):** `aurix-nonexistent-zq7x91.cognitiveservices.azure.com` → **NXDOMAIN** (does **not** hit the West Europe `20.61.99.32` gateway). So there is **no** public `*.cognitiveservices.azure.com` wildcard that explains `aipractices` — but **`aipractices.cognitiveservices.azure.com` resolving does NOT prove** the `aipractices` Cognitive/OpenAI resource is correct for our keys (resource-specific CNAME exists; still 401).
4. **Not NETWORK** (no 403 / no privatelink pattern on this host). **Not DEPLOYMENT/API-VERSION** (would be 404/400, not this 401 body).

## DNS evidence (2026-11-25)

| Hostname | Result |
|----------|--------|
| `aurix-nonexistent-zq7x91.cognitiveservices.azure.com` | NXDOMAIN |
| `aurix-nonexistent-zq7x91.openai.azure.com` | NXDOMAIN |
| `aipractices.cognitiveservices.azure.com` | `20.61.99.32` (WE, resource-specific CNAME) |
| `aipractices.openai.azure.com` | NXDOMAIN |
| `aipractices.services.ai.azure.com` | NXDOMAIN |

## Distinct Azure OpenAI endpoint hostnames (repo + git history, no keys)

| Hostname | Source |
|----------|--------|
| `aipractices.cognitiveservices.azure.com` | `.env`, `docs/ARCHITECTURE_JEV.md` |
| `aipractices.openai.azure.com` | `azure_openai_endpoint.py` candidate (NXDOMAIN) |
| `aipractices.services.ai.azure.com` | `azure_openai_endpoint.py` candidate (NXDOMAIN) |
| `placeholder.openai.azure.com` | `tests/test_i04_flags.py` / dev commit fixture (`20.232.91.180` East US) |
| `placeholder.cognitiveservices.azure.com` | Azure doc placeholder (`20.208.144.211`) |
| `YOUR-RESOURCE.cognitiveservices.azure.com` | `.env.example` template |
| `<name>.openai.azure.com` | `azure_health.py` help text |
| `cognitiveservices.azure.com` | DefaultAzureCredential scope in `aurix_core.py` (not a resource host) |
| “east2 host” | `.env` comment only — no hostname in repo |

**`*.openai.azure.com` nslookup:** only `placeholder.openai.azure.com` resolves publicly; `aipractices.openai.azure.com` does not — **no alternate live OpenAI hostname for `aipractices` in public DNS**.

## Remediation (I-01 ENDPOINT)

- Copy **Endpoint** and **Key** from the same Azure OpenAI / Cognitive Services resource in Azure Portal into `.env` (`AZURE_OPENAI_API_BASE`, `AZURE_OPENAI_API_KEY`).
- Prefer the Portal hostname (often `https://<resource>.openai.azure.com/`); if public DNS is NXDOMAIN for `openai.azure.com`, verify the cognitiveservices hostname matches that resource.
- Align `GPT4_LLM_MODEL_DEPLOYMENT_NAME` and `AZURE_OPENAI_API_VERSION` with that resource’s deployment and API version.