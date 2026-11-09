"""Contract: run_command must warn against pipes/redirection.

Measured 2026-11-07: `python -m pytest -v 2>&1 | tail -40` took 52.3 s in the
dev_cli while the same pytest takes 0.26 s. The pipe stalled the shell's
completion detection. The tool captures the full output, so the pipe is never
needed; the description now says so.
"""
from backend.agent.tool_bridge import _run_command_description


def test_run_command_description_forbids_pipes_and_redirection():
    text = _run_command_description()
    assert "Do NOT pipe or redirect" in text
    assert "captures the full output" in text
