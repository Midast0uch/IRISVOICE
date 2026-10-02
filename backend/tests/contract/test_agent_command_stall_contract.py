"""Contract: an agent command that waits never holds the agent blind.

Owner 2026-10-02: "commands that could hang or stall without the agent being
notified" - common to every harness. Before: a stalled command cost the full
time limit (300 s), and the timeout result dropped its output.

Pins (the real SubprocessManager.run_isolated, a short stall window):
  - no output AND no CPU for the stall window -> the call returns at once with
    running=True, a handle and the output so far; the command keeps running;
  - a busy command (CPU in use, no output) is never cut short;
  - command_status reads new output, stop kills and reports;
  - a timeout carries the output so far;
  - tools cannot stop to ask (git editor / prompts), Python output is unbuffered;
  - every status change reaches the display callback.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import time

import pytest

from backend.dev import subprocess_manager as sm

PY = f'"{sys.executable}"'


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(sm, "STALL_SECONDS", 3.0)
    monkeypatch.setattr(sm, "WATCH_TICK_SECONDS", 0.5)


def _go(coro_fn):
    async def main():
        m = sm.SubprocessManager()
        m.note_home_loop()          # the live app's home loop: backgrounding allowed
        return await coro_fn(m)
    return asyncio.run(main())


def test_a_stalled_command_returns_early_with_a_handle_and_keeps_running():
    events = []

    async def body(m):
        t0 = time.monotonic()
        res = await m.run_isolated("s", f'{PY} -c "print(\'listening on 8000\'); import time; time.sleep(60)"',
                                   workdir=".", timeout=120, on_event=events.append)
        took = time.monotonic() - t0
        st = await m.command_status("s", res["handle"])
        stop = await m.command_status("s", res["handle"], stop=True)
        await asyncio.sleep(0.2)
        return res, took, st, stop

    res, took, st, stop = _go(body)
    assert res["running"] and res["handle"].startswith("cmd-") and took < 15
    assert "listening on 8000" in res["stdout"]
    assert st["running"] is True
    assert stop["running"] is False and stop["status"] == "stopped"
    assert [e["status"] for e in events] == ["running", "waiting", "stopped"]


def test_a_busy_command_is_not_cut_short():
    async def body(m):
        return await m.run_isolated(
            "s", f'{PY} -c "import time; t=time.time()\nwhile time.time()-t<6: pass\nprint(\'built\')"',
            workdir=".", timeout=60)
    res = _go(body)
    assert res == {"success": True, "exit_code": 0}


def test_a_timeout_keeps_the_output_so_far():
    async def body(m):
        m._home_loop = None          # no home loop: no backgrounding, the limit applies
        return await m.run_isolated(
            "s", f'{PY} -c "print(\'step 1 done\'); import time; time.sleep(30)"', workdir=".", timeout=3)
    res = _go(body)
    assert res.get("timed_out") and "step 1 done" in res["stdout"]


def test_tools_cannot_stop_to_ask_and_python_output_is_unbuffered():
    out = []

    async def body(m):
        async def sink(line):
            out.append(line)
        return await m.run_isolated(
            "s", f'{PY} -c "import os; print(os.environ[\'GIT_TERMINAL_PROMPT\'], os.environ[\'PYTHONUNBUFFERED\'], os.environ[\'GIT_EDITOR\'])"',
            workdir=".", timeout=30, on_output=sink)
    res = _go(body)
    assert res["exit_code"] == 0 and out == ["0 1 true"]


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_git_commit_without_a_message_does_not_open_an_editor(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

    async def body(m):
        t0 = time.monotonic()
        res = await m.run_isolated("s", ["git", "-c", "user.name=t", "-c", "user.email=t@t",
                                         "commit", "--allow-empty"],
                                   workdir=str(tmp_path), timeout=60)
        return res, time.monotonic() - t0
    res, took = _go(body)
    assert res["success"] and res["exit_code"] != 0 and took < 15


def test_an_unknown_handle_is_a_clear_error():
    res = _go(lambda m: m.command_status("s", "cmd-nope"))
    assert res["success"] is False and "no running command" in res["error"]


def test_the_user_can_stop_a_running_command_and_the_display_hears_it():
    """Workspace Stop button (agent_command_stop): foreground or background."""
    events = []

    async def body(m):
        async def stop_soon():
            await asyncio.sleep(1.0)
            handle = next(e["id"] for e in events if e["status"] == "running")
            return await m.stop_handle(handle)
        stopper = asyncio.ensure_future(stop_soon())
        t0 = time.monotonic()
        res = await m.run_isolated("s", f'{PY} -c "import time\nwhile True: time.sleep(0.01); sum(range(5000))"',
                                   workdir=".", timeout=60, on_event=events.append)
        return res, await stopper, time.monotonic() - t0, await m.stop_handle("cmd-gone")

    res, found, took, gone = _go(body)
    assert found is True and gone is False and took < 10
    assert res["success"] is False and res.get("aborted")
    assert events[-1]["status"] == "stopped"
    # the display contract the workspace store reads
    assert {"id", "command", "status", "elapsed_s"} <= set(events[0])
