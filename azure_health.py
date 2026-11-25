"""Quick Azure OpenAI reachability check before long AutoGen runs."""
from __future__ import annotations

import socket
from urllib.parse import urlparse


def _hostname_from_base(base_url: str) -> str | None:
    host = urlparse(base_url).hostname
    return host


def check_azure_openai_dns(base_url: str) -> str | None:
    """Return user-facing error if hostname does not resolve, else None."""
    from azure_openai_endpoint import endpoint_candidates, install_openai_dns_alias_patch

    install_openai_dns_alias_patch()

    if not (base_url or "").strip():
        return "AZURE_OPENAI_API_BASE is missing or invalid (no hostname)."

    tried: list[str] = []
    for candidate in endpoint_candidates(base_url):
        host = _hostname_from_base(candidate)
        if not host:
            continue
        tried.append(host)
        try:
            socket.getaddrinfo(host, 443)
            return None
        except socket.gaierror:
            continue

    hosts = ", ".join(dict.fromkeys(tried)) or base_url
    return (
        f"Cannot resolve Azure OpenAI host (tried: {hosts}). "
        "In Azure Portal open your Azure OpenAI / AI Services resource → Keys and Endpoint. "
        "Copy the Endpoint into AZURE_OPENAI_API_BASE "
        "(often https://<name>.cognitiveservices.azure.com/ or …openai.azure.com/). "
        "Try VPN if you are off corporate network."
    )


def check_azure_openai_chat(
    api_key: str,
    api_version: str,
    base_url: str,
    deployment: str,
    timeout_sec: float,
) -> str | None:
    """One minimal chat call; return error message or None if OK."""
    dns_err = check_azure_openai_dns(base_url)
    if dns_err:
        return dns_err
    if not api_key or not deployment:
        return "AZURE_OPENAI_API_KEY or GPT4_LLM_MODEL_DEPLOYMENT_NAME is empty."
    try:
        from openai import AzureOpenAI

        client = AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=base_url.rstrip("/"),
            timeout=timeout_sec,
            max_retries=0,
        )
        client.chat.completions.create(
            model=deployment,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
    except Exception as exc:  # noqa: BLE001
        name = type(exc).__name__
        err = str(exc)
        if "401" in err or "Authentication" in name or "invalid subscription key" in err.lower():
            return (
                f"Azure OpenAI rejected the API key for endpoint '{base_url.rstrip('/')}'. "
                "In Azure Portal → same resource → Keys and Endpoint: copy Endpoint and Key 1 "
                f"into AZURE_OPENAI_API_BASE and AZURE_OPENAI_API_KEY. "
                f"Confirm deployment '{deployment}' exists. Detail: {exc}"
            )
        if "404" in err or "DeploymentNotFound" in err:
            return (
                f"Deployment '{deployment}' was not found on '{base_url.rstrip('/')}'. "
                "Set GPT4_LLM_MODEL_DEPLOYMENT_NAME to your exact deployment name from Azure Portal."
            )
        if "Connection" in name or "Connect" in err:
            return (
                f"Azure OpenAI connection failed ({name}). "
                f"Check endpoint, API key, deployment name '{deployment}', and firewall. Detail: {exc}"
            )
        return f"Azure OpenAI test call failed ({name}): {exc}"
    return None