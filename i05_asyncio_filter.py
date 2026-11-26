"""I-05: suppress benign WinError 10054 Proactor _call_connection_lost noise (Streamlit on Windows)."""
from __future__ import annotations

import asyncio
import sys


def suppress_connection_reset_context(context: dict) -> bool:
    exc = context.get("exception")
    if not isinstance(exc, ConnectionResetError):
        return False
    msg = str(context.get("message", ""))
    return "_call_connection_lost" in msg


def attach_connection_reset_filter(loop: asyncio.AbstractEventLoop) -> None:
    prior = loop.get_exception_handler()

    def _handler(inner: asyncio.AbstractEventLoop, context: dict) -> None:
        if suppress_connection_reset_context(context):
            return
        if prior is not None:
            prior(inner, context)
        else:
            inner.default_exception_handler(context)

    loop.set_exception_handler(_handler)


class _FilteringProactorPolicy(asyncio.WindowsProactorEventLoopPolicy):
    def new_event_loop(self) -> asyncio.AbstractEventLoop:
        loop = super().new_event_loop()
        attach_connection_reset_filter(loop)
        return loop


def install_win_connection_reset_filter() -> None:
    if sys.platform != "win32":
        return
    if not isinstance(asyncio.get_event_loop_policy(), _FilteringProactorPolicy):
        asyncio.set_event_loop_policy(_FilteringProactorPolicy())
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    attach_connection_reset_filter(loop)