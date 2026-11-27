"""A2: parallel pre-chat stage (S1 ∥ S4 ∥ schema link ∥ S3 cache)."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any

from routing_s4 import S4Preflight


@dataclass
class PrestageResult:
    jev_s1: dict[str, Any] | None = None
    s4: S4Preflight | None = None
    schema_block: str | None = None
    cache_response: dict[str, Any] | None = None
    cache_scan_complete: bool = False
    data_profile_refreshed: bool = False
    arm_ms: dict[str, float] = field(default_factory=dict)
    arm_status: dict[str, str] = field(default_factory=dict)
    wall_ms: float = 0.0


def _arm_timeout_s() -> float:
    from API_unified import JEV_TIMEOUT_MS, PRESTAGE_ARM_TIMEOUT_S

    if PRESTAGE_ARM_TIMEOUT_S > 0:
        return float(PRESTAGE_ARM_TIMEOUT_S)
    return max(0.5, float(JEV_TIMEOUT_MS) / 1000.0 * 2.0)


def _run_s1(question: str) -> tuple[dict[str, Any] | None, float, str]:
    from API_unified import JEV_S1_SAFETY_ENABLED

    if not JEV_S1_SAFETY_ENABLED:
        return None, 0.0, "skipped"
    t0 = time.perf_counter()
    try:
        from jev_client import jev_safety_check
        from jev_trace import jev_timed

        out = jev_timed("S1", lambda: jev_safety_check(question))
        return out, (time.perf_counter() - t0) * 1000, "ok"
    except Exception:  # noqa: BLE001
        return None, (time.perf_counter() - t0) * 1000, "error"


def _run_s4(question: str, schema_summary: str) -> tuple[S4Preflight | None, float, str]:
    from routing_s4 import preflight_s4

    t0 = time.perf_counter()
    try:
        out = preflight_s4(question, schema_summary=schema_summary)
        return out, (time.perf_counter() - t0) * 1000, "ok"
    except Exception:  # noqa: BLE001
        return None, (time.perf_counter() - t0) * 1000, "error"


def _run_schema_link(question: str) -> tuple[str | None, float, str]:
    from API_unified import SCHEMA_LINK_TOP_K
    from schema_linker import linked_schema_block
    from sql_catalog import get_catalog_readonly

    t0 = time.perf_counter()
    try:
        block = linked_schema_block(
            question, k=SCHEMA_LINK_TOP_K, catalog=get_catalog_readonly()
        )
        return block, (time.perf_counter() - t0) * 1000, "ok"
    except Exception:  # noqa: BLE001
        return None, (time.perf_counter() - t0) * 1000, "error"


def _scan_answer_cache(
    question: str, answer_cache: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any] | None, float, str]:
    from API_unified import JEV_S3_CACHE_ENABLED

    t0 = time.perf_counter()
    if not JEV_S3_CACHE_ENABLED or not question:
        return None, (time.perf_counter() - t0) * 1000, "skipped"
    try:
        if question in answer_cache:
            hit = dict(answer_cache[question])
            from jev_s3_cache_version import cache_entry_valid

            if not cache_entry_valid(hit):
                return None, (time.perf_counter() - t0) * 1000, "stale"
            hit["jev_cache_hit"] = True
            return hit, (time.perf_counter() - t0) * 1000, "ok"
        from jev_client import jev_cache_intent_match

        for cached_q, cached_resp in list(answer_cache.items()):
            try:
                match = jev_cache_intent_match(question, cached_q)
                if match.get("source") == "openjev" and float(match.get("is_match") or 0.0) > 0.85:
                    hit = dict(cached_resp)
                    from jev_s3_cache_version import cache_entry_valid

                    if not cache_entry_valid(hit):
                        continue
                    hit["jev_cache_hit"] = True
                    return hit, (time.perf_counter() - t0) * 1000, "ok"
            except Exception:  # noqa: BLE001
                continue
        return None, (time.perf_counter() - t0) * 1000, "ok"
    except Exception:  # noqa: BLE001
        return None, (time.perf_counter() - t0) * 1000, "error"


def _refresh_profile() -> tuple[bool, float, str]:
    t0 = time.perf_counter()
    try:
        from API_unified import DATA_PROFILE_REFRESH_EACH_REQUEST
        from data_profile import load_data_profile, refresh_data_profile

        if DATA_PROFILE_REFRESH_EACH_REQUEST:
            refresh_data_profile()
        else:
            load_data_profile()
        return True, (time.perf_counter() - t0) * 1000, "ok"
    except Exception:  # noqa: BLE001
        return False, (time.perf_counter() - t0) * 1000, "error"


def record_prestage_trace(result: PrestageResult) -> None:
    from jev_trace import record_step

    for arm, ms in sorted(result.arm_ms.items()):
        record_step(
            "prestage",
            arm,
            ms,
            status=result.arm_status.get(arm, "ok"),
        )
    record_step("prestage", "wall", result.wall_ms, status="ok")
    try:
        from jev_trace import trace_stdout

        arms = ", ".join(f"{k}={result.arm_status.get(k, '?')}" for k in sorted(result.arm_ms))
        trace_stdout(f"prestage {result.wall_ms:.0f}ms ({arms})")
    except Exception:  # noqa: BLE001
        pass


def run_prestage(
    question: str,
    *,
    schema_summary: str,
    answer_cache: dict[str, dict[str, Any]],
    network_arms: bool = True,
) -> PrestageResult:
    from API_unified import PRESTAGE_MAX_WORKERS, PRESTAGE_PARALLEL_ENABLED, PRESTAGE_WALL_S

    wall0 = time.perf_counter()
    res = PrestageResult()
    arm_to = _arm_timeout_s()
    wall_s = float(PRESTAGE_WALL_S)

    if not PRESTAGE_PARALLEL_ENABLED:
        if network_arms:
            jev, ms, st = _run_s1(question)
            res.jev_s1 = jev
            res.arm_ms["s1"] = ms
            res.arm_status["s1"] = st
            s4, ms, st = _run_s4(question, schema_summary)
            res.s4 = s4
            res.arm_ms["s4"] = ms
            res.arm_status["s4"] = st
        else:
            res.arm_status["s1"] = "skipped_regex"
            res.arm_status["s4"] = "skipped_regex"
        schema, ms, st = _run_schema_link(question)
        res.schema_block = schema
        res.arm_ms["schema"] = ms
        res.arm_status["schema"] = st
        if network_arms:
            hit, ms, st = _scan_answer_cache(question, answer_cache)
            res.cache_response = hit
            res.cache_scan_complete = True
            res.arm_ms["cache"] = ms
            res.arm_status["cache"] = st
        else:
            res.cache_scan_complete = True
            res.arm_status["cache"] = "skipped_regex"
        ok, ms, st = _refresh_profile()
        res.data_profile_refreshed = ok
        res.arm_ms["data_profile"] = ms
        res.arm_status["data_profile"] = st
        res.wall_ms = (time.perf_counter() - wall0) * 1000
        return res

    deadline = wall0 + wall_s
    tasks: list[tuple[str, Any]] = [
        ("schema", lambda: _run_schema_link(question)),
        ("data_profile", lambda: _refresh_profile()),
    ]
    if network_arms:
        tasks = [
            ("s1", lambda: _run_s1(question)),
            ("s4", lambda: _run_s4(question, schema_summary)),
            ("cache", lambda: _scan_answer_cache(question, answer_cache)),
            *tasks,
        ]

    with ThreadPoolExecutor(max_workers=PRESTAGE_MAX_WORKERS) as ex:
        futs = {name: ex.submit(fn) for name, fn in tasks}
        for name, fut in futs.items():
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                fut.cancel()
                res.arm_status[name] = "wall_timeout"
                res.arm_ms[name] = 0.0
                continue
            try:
                payload = fut.result(timeout=min(remaining, arm_to))
                res.arm_ms[name] = float(payload[1])
                res.arm_status[name] = str(payload[2])
                if name == "s1":
                    res.jev_s1 = payload[0]
                elif name == "s4":
                    res.s4 = payload[0]
                elif name == "schema":
                    res.schema_block = payload[0]
                elif name == "cache":
                    res.cache_response = payload[0]
                    res.cache_scan_complete = res.arm_status["cache"] in ("ok", "skipped")
                elif name == "data_profile":
                    res.data_profile_refreshed = bool(payload[0])
            except FuturesTimeout:
                fut.cancel()
                res.arm_status[name] = "timeout"
                res.arm_ms[name] = arm_to * 1000.0
            except BaseException:  # noqa: BLE001 (pytest.fail / worker faults)
                fut.cancel()
                res.arm_status[name] = "error"

    res.wall_ms = (time.perf_counter() - wall0) * 1000
    return res