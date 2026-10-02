"""Contract: an agent command never waits on input it cannot get.

Eval c02 (2026-10-02, API Brain + API tool): run_command ran on the session
shell, which reads its own commands from a stdin pipe that a native child
inherits. `python - <<'PY'` swallowed the following lines (the completion
marker too) and waited for the 300 s limit - twice, 566 s of a 636 s reply.

run_isolated gives every agent command its own process with an empty, closed
stdin: a stdin reader ends at once, the exit code and output come back, an
argv list runs with no shell, and the time limit still kills the tree.
"""
from __future__ import annotations

import asyncio
import sys
import time

import pytest

from backend.dev.subprocess_manager import SubprocessManager, agent_shell

PY = f'"{sys.executable}"'


def _run(cmd, timeout=30):
    async def main():
        out = []

        async def sink(line):
            out.append(line)

        t0 = time.monotonic()
        res = await SubprocessManager().run_isolated("contract", cmd, workdir=".", timeout=timeout, on_output=sink)
        return res, out, time.monotonic() - t0
    return asyncio.run(main())


@pytest.mark.parametrize("cmd", [f"{PY} -", f'{PY} -c "input()"', f"{PY} -c \"import sys; sys.stdin.read()\""])
def test_a_stdin_reader_ends_at_once(cmd):
    res, _out, secs = _run(cmd, timeout=60)
    assert res["success"] and secs < 20, (res, secs)


def test_exit_code_and_output_come_back():
    res, out, _ = _run(f'{PY} -c "print(42); import sys; sys.exit(3)"')
    assert res == {"success": True, "exit_code": 3} and out == ["42"]


def test_an_argv_list_runs_without_a_shell():
    res, out, _ = _run([sys.executable, "-c", "print('a b')"])
    assert res["exit_code"] == 0 and out == ["a b"]


@pytest.mark.skipif(agent_shell()[0] != "bash", reason="bash agent shell only")
def test_the_c02_heredoc_runs_under_bash():
    res, out, _ = _run(f"{PY} - <<'PY'\nprint(6*7)\nPY")
    assert res["exit_code"] == 0 and out == ["42"]


def test_the_time_limit_still_kills_the_command():
    res, _out, secs = _run(f'{PY} -c "import time; time.sleep(30)"', timeout=2)
    assert res.get("timed_out") and secs < 15
