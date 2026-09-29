"""Regression (execution audit B11, 2026-09-29): a stray digit 5 is not a 5xx.

The transient keyword list held a bare "5", so any error text containing the
digit 5 - a line number, a port, a file name - was classified "transient" and
retried. These cases fail on that code.
"""

import pytest

from backend.agent.tool_decision import _classify_error


@pytest.mark.parametrize("error", [
    "SyntaxError: invalid syntax at line 15",
    "connection refused on port 5432",
    "[Errno 2] No such file or directory: 'report_2025.md'",
    "expected 5 arguments, got 4",
])
def test_digit_five_is_not_transient(error):
    assert _classify_error(error) != "transient"


@pytest.mark.parametrize("error", [
    "500 internal server error",
    "HTTP 503 Service Unavailable",
    "upstream returned 502 bad gateway",
])
def test_real_5xx_is_transient(error):
    assert _classify_error(error) == "transient"
