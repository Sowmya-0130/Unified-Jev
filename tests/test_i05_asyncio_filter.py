from __future__ import annotations

from i05_asyncio_filter import suppress_connection_reset_context


def test_suppresses_proactor_connection_lost():
    ctx = {
        "message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)",
        "exception": ConnectionResetError(10054, "reset"),
    }
    assert suppress_connection_reset_context(ctx)


def test_passes_unrelated_errors():
    ctx = {
        "message": "Exception in callback foo",
        "exception": ValueError("bad"),
    }
    assert not suppress_connection_reset_context(ctx)


def test_handler_forwards_other_exceptions():
    import asyncio

    from i05_asyncio_filter import attach_connection_reset_filter

    loop = asyncio.new_event_loop()
    forwarded: list[dict] = []

    def _capture(_loop: asyncio.AbstractEventLoop, context: dict) -> None:
        forwarded.append(context)

    loop.set_exception_handler(_capture)
    attach_connection_reset_filter(loop)
    handler = loop.get_exception_handler()
    assert handler is not None
    ctx = {"message": "unhandled", "exception": RuntimeError("surfaced")}
    handler(loop, ctx)
    assert forwarded == [ctx]