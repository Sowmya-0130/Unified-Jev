"""Print call path: Streamlit / acceptance → get_final_answer → orchestrator."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def main() -> int:
    from API_unified import ORCHESTRATOR
    import aurix_core as core

    path = (
        "main.py:get_final_answer(question)"
        " → aurix_core._get_final_answer_impl"
        f" → ORCHESTRATOR={ORCHESTRATOR!r}"
    )
    src = inspect.getsource(core._get_final_answer_impl)
    if ORCHESTRATOR == "pipeline":
        path += " → orchestrator.run_pipeline (not GroupChat)"
    else:
        path += " → user_proxy.initiate_chat(GroupChat)"
    print(path)
    print("eval harness: eval/*_acceptance.py sets os.environ ORCHESTRATOR=pipeline before import")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())