from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from request_state import safety_allows_sql_execute, safety_prechat_store, sync_safety_for_request


def test_safety_synced_to_pipeline_worker():
    safety_prechat_store("rid-worker", "allow", {"probe": True})

    def _worker() -> bool:
        sync_safety_for_request("rid-worker")
        return safety_allows_sql_execute()

    with ThreadPoolExecutor(max_workers=1) as ex:
        assert ex.submit(_worker).result() is True