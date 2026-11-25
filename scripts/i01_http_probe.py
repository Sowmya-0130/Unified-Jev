"""Minimal Azure chat HTTP probe — status, JSON body, selected headers (no keys printed)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import httpx

import API_unified as api


def probe(label: str, api_key: str) -> None:
    base = api.AZURE_OPENAI_API_BASE.rstrip("/")
    deployment = api.GPT4_LLM_MODEL_DEPLOYMENT_NAME
    version = api.AZURE_OPENAI_API_VERSION
    url = f"{base}/openai/deployments/{deployment}/chat/completions"
    print(f"=== {label} ===")
    print("endpoint:", base)
    print("deployment:", deployment)
    print("api_version:", version)
    print("key:", f"{api_key[:4]}**** len={len(api_key.strip())}" if api_key else "(empty)")
    try:
        r = httpx.post(
            url,
            params={"api-version": version},
            headers={"api-key": api_key.strip(), "Content-Type": "application/json"},
            json={
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
            timeout=45.0,
        )
        print("HTTP_STATUS:", r.status_code)
        print("apim-request-id:", r.headers.get("apim-request-id"))
        print("x-ms-region:", r.headers.get("x-ms-region"))
        try:
            body = r.json()
            print("error_json:", json.dumps(body, indent=2))
        except Exception:
            print("error_body:", r.text[:2000])
    except Exception as exc:
        print("REQUEST_FAILED:", type(exc).__name__, str(exc)[:500])


def main() -> None:
    probe("MAIN_AZURE_OPENAI_API_KEY", api.AZURE_OPENAI_API_KEY)
    probe("GRAPH_API_KEY", api.graph_api_key or "")


if __name__ == "__main__":
    main()