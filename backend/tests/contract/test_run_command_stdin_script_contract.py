"""Contract: run_command refuses a command that reads its script from stdin.

Eval c02 (2026-10-02, Brain mercury-2.5 + tool mercury-2): the tool model
ran `python - <<'PY' ...`. The session shell (PowerShell) reads its own
commands from a stdin pipe that a native child inherits, so python swallowed
the following lines - including the shell's completion marker - and the call
waited for the 300 s limit. Two such calls took 566 s of a 636 s reply.
"""
from __future__ import annotations

import os

import pytest

from backend.agent import tool_bridge as tb

pytestmark = pytest.mark.skipif(os.name != "nt", reason="the PowerShell session shell")

_C02 = "python - <<'PY'\nimport textutils, sys\n\ndef test(val, expected):\n    pass\nPY"


@pytest.mark.parametrize("cmd", [_C02, "python -", "py - < x.py", "python3 -", "node -", "python", "cat <<EOF\nx\nEOF"])
def test_a_stdin_script_is_refused(cmd):
    assert tb._STDIN_SCRIPT.search(cmd)


@pytest.mark.parametrize("cmd", [
    "python -m pytest -q", "python check.py", "pytest -q test_durations.py",
    "python -c \"import textutils; print(textutils.slugify('A b'))\"",
    "npm test", "git status", "py -3 script.py",
])
def test_ordinary_commands_run(cmd):
    assert not tb._STDIN_SCRIPT.search(cmd)


def test_the_refusal_says_what_to_do_instead():
    assert "write_file" in tb._STDIN_SCRIPT_ERROR and "PowerShell" in tb._STDIN_SCRIPT_ERROR
