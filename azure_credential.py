"""Azure OpenAI credential sanity check (no secrets in logs)."""
from __future__ import annotations

from urllib.parse import urlparse


def azure_openai_endpoint_auth_user_message(base_url: str, *, status: str = "401") -> str:
    """User-facing text for auth/endpoint failures (host only, never keys)."""
    raw = (base_url or "").strip().rstrip("/")
    host = urlparse(raw if "://" in raw else f"https://{raw}").hostname or raw or "(not set)"
    return (
        f"Can't reach Azure OpenAI: the configured endpoint "
        f"({host}) returned {status} 'invalid key or wrong API endpoint'. "
        "Check AZURE_OPENAI_API_BASE, AZURE_OPENAI_API_KEY, "
        "GPT4_LLM_MODEL_DEPLOYMENT_NAME and AZURE_OPENAI_API_VERSION in .env."
    )


def mask_secret(value: str | None) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}…{value[-2:]} (len={len(value)})"


def probe_azure_openai_chat(
    *,
    api_key: str,
    api_version: str,
    base_url: str,
    deployment: str,
    timeout_sec: float = 25.0,
) -> str | None:
    """Return error message if chat fails, else None. Never logs the key."""
    if not api_key or not base_url or not deployment:
        return (
            "Azure OpenAI is not configured (empty key, endpoint, or deployment in .env)."
        )
    try:
        from openai import AzureOpenAI

        client = AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=base_url.rstrip("/"),
            timeout=timeout_sec,
            max_retries=0,
        )
        _payload = {
            "model": deployment,
            "messages": [{"role": "user", "content": "ping"}],
        }
        try:
            client.chat.completions.create(**_payload, max_tokens=1)
        except Exception as inner:  # noqa: BLE001
            err_in = str(inner)
            if "max_completion_tokens" in err_in or "max_tokens" in err_in:
                client.chat.completions.create(**_payload, max_completion_tokens=16)
            else:
                raise
    except Exception as exc:  # noqa: BLE001
        err = str(exc)
        if "401" in err or "403" in err or "Authentication" in type(exc).__name__:
            status = "403" if "403" in err else "401"
            return azure_openai_endpoint_auth_user_message(base_url, status=status)
        if "DeploymentNotFound" in err or "404" in err:
            return (
                f"Deployment {deployment!r} was not found on the configured endpoint. "
                "Fix `GPT4_LLM_MODEL_DEPLOYMENT_NAME` in `.env`."
            )
        if "getaddrinfo" in err.lower() or "cannot resolve" in err.lower():
            return (
                "Azure OpenAI hostname does not resolve. Restart Streamlit after `.env` changes; "
                "DNS alias to cognitiveservices should apply automatically."
            )
        return f"Azure OpenAI probe failed: {type(exc).__name__}: {exc}"
    return None