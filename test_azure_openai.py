"""Azure OpenAI DNS + minimal chat test (reads .env via API_unified)."""
from API_unified import (
    AZURE_OPENAI_API_BASE,
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_API_VERSION,
    GPT4_LLM_MODEL_DEPLOYMENT_NAME,
    _AZURE_OPENAI_API_BASE_REQUESTED,
)
from azure_health import check_azure_openai_chat, check_azure_openai_dns
from azure_openai_endpoint import endpoint_candidates

print("Requested .env base:", _AZURE_OPENAI_API_BASE_REQUESTED or "(empty)")
print("Resolved base:    ", AZURE_OPENAI_API_BASE)
print("Candidates:", ", ".join(endpoint_candidates(_AZURE_OPENAI_API_BASE_REQUESTED or AZURE_OPENAI_API_BASE)))

dns = check_azure_openai_dns(AZURE_OPENAI_API_BASE)
if dns:
    print("DNS:", dns)
else:
    print("DNS: OK")

err = check_azure_openai_chat(
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_API_VERSION,
    AZURE_OPENAI_API_BASE,
    GPT4_LLM_MODEL_DEPLOYMENT_NAME,
    45.0,
)
if err:
    print("Chat test FAILED:")
    print(err)
    raise SystemExit(1)
print("Chat test OK (deployment:", GPT4_LLM_MODEL_DEPLOYMENT_NAME, ")")