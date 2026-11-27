"""A test that runs for a long time is named while it still runs, so a run
that hangs says where."""

from __future__ import annotations

import threading
from collections.abc import Generator
from typing import Any

import pytest

# How long a test runs before it is named, in seconds.
LONG = 60.0


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item: pytest.Item) -> Generator[None, Any, Any]:
    plugins = item.config.pluginmanager
    reporter = plugins.get_plugin("terminalreporter")
    capture = plugins.get_plugin("capturemanager")

    def name() -> None:
        if reporter is None:
            return
        line = f"still running after {LONG:g} s: {item.nodeid}"
        # What a test writes is kept from the terminal while it runs, and
        # this is not the test's.
        if capture is None:
            reporter.write_line(line)
        else:
            with capture.global_and_fixture_disabled():
                reporter.ensure_newline()
                reporter.write_line(line)

    timer = threading.Timer(LONG, name)
    timer.daemon = True
    timer.start()
    try:
        return (yield)
    finally:
        timer.cancel()
