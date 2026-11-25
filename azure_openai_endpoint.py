"""Resolve a reachable Azure OpenAI / Cognitive Services endpoint hostname."""
from __future__ import annotations

import logging
import socket
from urllib.parse import urlparse

_log = logging.getLogger(__name__)
_DNS_PATCHED = False


def install_openai_dns_alias_patch() -> None:
    """
    When *.openai.azure.com does not exist in public DNS, resolve via
    *.cognitiveservices.azure.com (same Azure edge). Needed for AutoGen/httpx.
    """
    global _DNS_PATCHED
    if _DNS_PATCHED:
        return
    _orig = socket.getaddrinfo

    def _patched(host, port, *args, **kwargs):
        h = (host or "").lower()
        if h.endswith(".openai.azure.com"):
            stem = h[: -len(".openai.azure.com")]
            alt = f"{stem}.cognitiveservices.azure.com"
            try:
                if _host_resolves(alt):
                    _log.warning("DNS alias applied: %s -> %s", host, alt)
                    return _orig(alt, port, *args, **kwargs)
            except OSError:
                pass
        return _orig(host, port, *args, **kwargs)

    socket.getaddrinfo = _patched  # type: ignore[assignment]
    _DNS_PATCHED = True
    _log.warning(
        "OpenAI DNS alias patch enabled: *.openai.azure.com may resolve via "
        "*.cognitiveservices.azure.com — verify AZURE_OPENAI_API_BASE matches Portal."
    )


def _host_resolves(hostname: str) -> bool:
    if not hostname:
        return False
    try:
        socket.getaddrinfo(hostname, 443)
        return True
    except OSError:
        return False


def _resource_stem(hostname: str) -> str | None:
    for suffix in (
        ".openai.azure.com",
        ".cognitiveservices.azure.com",
        ".services.ai.azure.com",
    ):
        if hostname.endswith(suffix):
            return hostname[: -len(suffix)]
    return None


def endpoint_candidates(base_url: str) -> list[str]:
    """Return URL variants to try (same resource, different public hostnames)."""
    raw = (base_url or "").strip().rstrip("/")
    if not raw:
        return []
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower()
    if not host:
        return [raw]

    stem = _resource_stem(host)
    out: list[str] = [f"https://{host}"]
    if stem:
        for alt_host in (
            f"{stem}.cognitiveservices.azure.com",
            f"{stem}.openai.azure.com",
            f"{stem}.services.ai.azure.com",
        ):
            alt = f"https://{alt_host}"
            if alt not in out:
                out.append(alt)
    return out


def resolve_azure_openai_endpoint(
    base_url: str,
    *,
    extra_candidates: str = "",
) -> tuple[str, str | None]:
    """
    Pick the first hostname that resolves.

    Returns (resolved_url, note) where note explains auto-switching (or None).
    """
    candidates = endpoint_candidates(base_url)
    for part in (extra_candidates or "").split(","):
        part = part.strip().rstrip("/")
        if part:
            url = part if "://" in part else f"https://{part}"
            if url not in candidates:
                candidates.append(url)

    requested = (base_url or "").strip().rstrip("/")
    if requested and "://" not in requested:
        requested = f"https://{requested}"

    for candidate in candidates:
        host = urlparse(candidate).hostname or ""
        if _host_resolves(host):
            resolved = candidate.rstrip("/")
            if resolved != requested.rstrip("/"):
                note = (
                    f"AZURE_OPENAI endpoint switched to {resolved} "
                    f"(hostname for {requested or base_url} does not resolve in DNS; "
                    "this is normal — use Keys and Endpoint from the same resource in Azure Portal)."
                )
                return resolved, note
            return resolved, None

    return requested or base_url, None