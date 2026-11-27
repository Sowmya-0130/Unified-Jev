"""Sql_Generator prompt token inventory (C3/C4 input)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _tok(chars: int) -> int:
    return max(1, int(chars / 4))


def main() -> int:
    import aurix_core as core

    sys_msg = str(getattr(core.Sql_Generator, "system_message", ""))
    schema = core.SQL_Meta_Data or ""
    inst = sys_msg.split("**Meta_Data**")[0] if "**Meta_Data**" in sys_msg else sys_msg
    examples = sys_msg if "SELECT TOP 1 city_name" in sys_msg else ""
    table_refs = sorted(set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z0-9_.]+\b", schema)))[:20]
    blob = {
        "system_total_chars": len(sys_msg),
        "approx_tokens_total_system_message": _tok(len(sys_msg)),
        "breakdown": {
            "instructions_chars": len(inst),
            "instructions_approx_tokens": _tok(len(inst)),
            "schema_chars": len(schema),
            "schema_approx_tokens": _tok(len(schema)),
            "example_block_chars": len(examples),
            "example_approx_tokens": _tok(len(examples)),
            "chat_history_note": "AutoGen adds full GroupChat history per turn (not in system_message)",
        },
        "hardcoded_samples": [
            "SELECT TOP 1 city_name, population FROM city_stats",
            "city_stats table in Sql_Generator example",
        ],
        "schema_table_refs_sample": table_refs,
    }
    out = _ROOT / ".loop" / "logs" / "sql-gen-prompt-inventory.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    print(json.dumps(blob, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())