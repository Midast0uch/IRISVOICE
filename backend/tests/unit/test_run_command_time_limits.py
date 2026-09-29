"""Regression (execution audit B6, 2026-09-29): long commands get the time
they need, the tool's own timeout decides, and a timed-out step is not re-run.

Before: run_command had a fixed 120 s timeout under a 90 s DER step deadline,
so a full test suite or build always timed out, and the "[STEP TIMEOUT ...]"
text matched the retry keywords, so the step was started up to twice more
while the first worker kept running. Each test below fails on that code.
"""

from unittest.mock import patch

from backend.agent.agent_kernel import AgentKernel
from backend.agent.tool_bridge import _command_timeout


def test_command_timeout_default_and_bounds():
    assert _command_timeout(None) >= 300
    assert _command_timeout(450) == 450
    assert _command_timeout(99999) == 600
    assert _command_timeout("junk") >= 300


def test_step_deadline_exceeds_the_longest_command_timeout():
    kernel = AgentKernel.__new__(AgentKernel)
    # Auto-approve path: no consent window is added to the deadline.
    with patch("backend.agent.permissions.get_auto_approve", return_value=True):
        deadline = kernel._der_tool_deadline("run_command")
    assert deadline > _command_timeout(99999)


def test_a_step_timeout_is_not_retried():
    err = "[STEP TIMEOUT after 90s — tool=run_command abandoned]"
    assert AgentKernel._der_step_error_is_retryable(err) is False


def test_connection_errors_still_retry():
    assert AgentKernel._der_step_error_is_retryable("ConnectionError: reset by peer") is True
