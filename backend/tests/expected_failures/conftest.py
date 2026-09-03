"""Mark all tests in this folder as expected-failure so normal CI stays green.

Run with `pytest backend/tests/expected_failures -v` to see the real failure,
or `pytest --run-expected-failures` (see root conftest) to treat them as normal.
These tests require GPU / live llama-server and are intentionally red without it —
see README.md in this folder and pin_33e6ce48d448.
"""

import pytest

def pytest_collection_modifyitems(config, items):
    # Unless explicitly asked, mark expected failures as xfail so CI stays green
    # but still EXECUTES the test (strict=False) — a passing test becomes XPASS,
    # making it obvious when the harness fix lands and the test can be promoted.
    if config.getoption("--run-expected-failures", default=False):
        return
    for item in items:
        item.add_marker(pytest.mark.xfail(reason="expected failure — needs GPU/live server (see expected_failures/README.md)", strict=False))
