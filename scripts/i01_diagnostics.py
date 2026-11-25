"""I-01 Azure OpenAI diagnostics (never prints full secrets)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def mask(v: str | None) -> str:
    if not v:
        return "(empty)"
    v = v.strip()
    return f"{v[:4]}**** len={len(v)} repr_tail={repr(v[-2:]) if len(v) > 2 else ''}"


def main() -> int:
    names = [
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_API_BASE",
        "OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_VERSION",
    ]
    print("=== (a) os.environ BEFORE load_dotenv ===")
    for n in names:
        print(n, mask(os.environ.get(n)))

    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env", override=True)
    print("=== (a) os.environ AFTER load_dotenv override=True ===")
    for n in names:
        print(n, mask(os.environ.get(n)))

    import importlib
    import API_unified as api

    api = importlib.reload(api)

    print("=== (b) API_unified resolved ===")
    print("AZURE_OPENAI_API_BASE", api.AZURE_OPENAI_API_BASE)
    print("AZURE_OPENAI_API_VERSION", api.AZURE_OPENAI_API_VERSION)
    print("GPT4_LLM_MODEL_DEPLOYMENT_NAME", api.GPT4_LLM_MODEL_DEPLOYMENT_NAME)
    print("AZURE_OPENAI_API_KEY", mask(api.AZURE_OPENAI_API_KEY))
    print("graph_api_key", mask(api.graph_api_key))

    print("=== (c) key sources differ?", api.AZURE_OPENAI_API_KEY != api.graph_api_key)

    print("=== (d) whitespace check ===")
    raw = api._env("AZURE_OPENAI_API_KEY")
    print("raw len", len(raw), "stripped eq", raw == raw.strip())

    print("=== (e) minimal AzureOpenAI chat ===")
    from openai import AzureOpenAI

    try:
        client = AzureOpenAI(
            api_key=api.AZURE_OPENAI_API_KEY,
            api_version=api.AZURE_OPENAI_API_VERSION,
            azure_endpoint=api.AZURE_OPENAI_API_BASE.rstrip("/"),
            max_retries=0,
            timeout=45.0,
        )
        client.chat.completions.create(
            model=api.GPT4_LLM_MODEL_DEPLOYMENT_NAME,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
        print("RESULT: 200 OK")
        return 0
    except Exception as exc:
        err = str(exc)
        if "401" in err or "403" in err:
            print("RESULT: 401/403 auth")
        elif "DeploymentNotFound" in err or ("404" in err and "deployment" in err.lower()):
            print("RESULT: 404 deployment")
        elif "404" in err:
            print("RESULT: 404")
        else:
            print("RESULT:", type(exc).__name__, err[:200])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())