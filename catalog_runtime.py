"""Warm SQL catalog at startup; background TTL refresh (daemon)."""
from __future__ import annotations

import logging
import threading
import time

_log = logging.getLogger("aurix.catalog_runtime")
_bg_started = False
_bg_lock = threading.Lock()


def ensure_catalog_warm(*, force: bool = False) -> None:
    from sql_catalog import load_live_catalog

    load_live_catalog(force=force)


def start_background_catalog_refresh() -> None:
    global _bg_started
    with _bg_lock:
        if _bg_started:
            return
        _bg_started = True

    def _loop() -> None:
        from API_unified import SQL_CATALOG_TTL_SEC
        from sql_catalog import load_live_catalog

        while True:
            time.sleep(max(60, int(SQL_CATALOG_TTL_SEC)))
            try:
                load_live_catalog(force=True)
            except Exception as exc:  # noqa: BLE001
                _log.warning("background catalog refresh failed: %s", exc)

    threading.Thread(target=_loop, daemon=True, name="catalog-refresh").start()


def bootstrap_catalog() -> None:
    ensure_catalog_warm(force=False)
    start_background_catalog_refresh()