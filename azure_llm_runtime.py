"""Keep AutoGen / OpenAI clients on the DNS-resolved Azure endpoint (refresh each request)."""
from __future__ import annotations

from openai import AzureOpenAI

from azure_openai_endpoint import install_openai_dns_alias_patch, resolve_azure_openai_endpoint

_PATCHED = False
_CLIENT_SIG: str | None = None
_CACHED_CLIENT: AzureOpenAI | None = None


def ensure_openai_dns_patch() -> None:
    global _PATCHED
    if not _PATCHED:
        install_openai_dns_alias_patch()
        _PATCHED = True


def refresh_azure_openai_runtime(
    llm_config: dict,
    *,
    openai_client: AzureOpenAI | None = None,
) -> tuple[str, AzureOpenAI]:
    """
    Re-read .env-backed settings and apply to llm_config + AzureOpenAI client.
    Returns (resolved_endpoint, client).
    """
    ensure_openai_dns_patch()
    import API_unified as api

    endpoint, _ = resolve_azure_openai_endpoint(
        api._AZURE_OPENAI_API_BASE_REQUESTED,
        extra_candidates=api.AZURE_OPENAI_API_BASE_FALLBACKS,
    )
    api.AZURE_OPENAI_API_BASE = endpoint

    api_key = api.AZURE_OPENAI_API_KEY
    if not api_key and api.graph_api_key:
        api_key = api.graph_api_key

    deployment = api.GPT4_LLM_MODEL_DEPLOYMENT_NAME
    entry = llm_config["config_list"][0]
    patch = {
        "model": deployment,
        "azure_deployment": deployment,
        "api_type": "azure",
        "base_url": endpoint,
        "api_key": api_key,
        "api_version": api.AZURE_OPENAI_API_VERSION,
        "max_retries": api.AZURE_LLM_MAX_RETRIES,
    }
    if api.AZURE_LLM_PRICE_PER_1K:
        patch["price"] = list(api.AZURE_LLM_PRICE_PER_1K)
    entry.update(patch)
    llm_config["timeout"] = api.AZURE_LLM_REQUEST_TIMEOUT

    global _CLIENT_SIG, _CACHED_CLIENT
    sig = f"{endpoint}|{deployment}|{api.AZURE_OPENAI_API_VERSION}|{api.AZURE_LLM_REQUEST_TIMEOUT}"
    if _CLIENT_SIG == sig and _CACHED_CLIENT is not None:
        return endpoint, _CACHED_CLIENT
    client = AzureOpenAI(
        api_key=api_key,
        api_version=api.AZURE_OPENAI_API_VERSION,
        azure_endpoint=endpoint,
        timeout=api.AZURE_LLM_REQUEST_TIMEOUT,
        max_retries=api.AZURE_LLM_MAX_RETRIES,
    )
    _CLIENT_SIG = sig
    _CACHED_CLIENT = client
    return endpoint, client