"""Regression (execution audit, 2026-09-29): attaching the monitor to a DEBUG
root must not let the HTTP client libraries log every request.

httpcore/httpx wrote ~15 DEBUG lines per request into logs/iris.log (2 GB
measured). Fails on the old attach_to_root.
"""

import logging

from backend.monitor.logs import LogManager


def test_http_libraries_are_quieted_but_iris_debug_stays():
    root = logging.getLogger()
    before_handlers = list(root.handlers)
    before_level = root.level
    try:
        LogManager().attach_to_root(level=logging.DEBUG)
        assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
        assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
        assert logging.getLogger("backend.agent.agent_kernel").getEffectiveLevel() == logging.DEBUG
    finally:
        root.handlers[:] = before_handlers
        root.setLevel(before_level)
