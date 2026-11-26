import os
import socket

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "live: requires live Azure SQL catalog and DB")
    config.addinivalue_line(
        "markers",
        "groupchat_legacy: groupchat state_transition; excluded until approved (RUN_GROUPCHAT_TESTS=1)",
    )
    os.environ.setdefault("AURIX_BOTH_STUB", "1")


def pytest_collection_modifyitems(items):
    skip_both, skip_live, skip_gc = [], [], []
    for item in items:
        if "live" in item.keywords:
            item.add_marker(pytest.mark.timeout(900))
        if "both_integration" in item.keywords and not os.environ.get("RUN_BOTH_INTEGRATION"):
            skip_both.append(item)
        if "groupchat_legacy" in item.keywords and not os.environ.get("RUN_GROUPCHAT_TESTS"):
            skip_gc.append(item)
    if skip_both:
        m = pytest.mark.skip(reason="both_integration (set RUN_BOTH_INTEGRATION=1)")
        for item in skip_both:
            item.add_marker(m)
    if skip_gc:
        m = pytest.mark.skip(reason="groupchat_legacy (set RUN_GROUPCHAT_TESTS=1)")
        for item in skip_gc:
            item.add_marker(m)


@pytest.fixture(autouse=True)
def _block_network_outside_live(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        yield
        return

    _orig_connect = socket.socket.connect

    def _guard_connect(self, address):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost"):
            return _orig_connect(self, address)
        raise pytest.fail(f"Non-live test attempted socket.connect({address!r})")

    monkeypatch.setattr(socket.socket, "connect", _guard_connect, raising=False)

    yield