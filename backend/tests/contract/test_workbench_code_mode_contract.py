"""CLM-11 T7.4: Workbench code mode at node entry (backend/agent/kernel/der/node.py).

- the stated entry rule: flag on, run_python offered (developer mode), a READ or
  RUN step, no external / screen reference, an interpreter available;
- the fallback rule (AC4): unavailable, a sandbox refusal, or two run_python
  failures in a row with the same exception type -> the fine-grained path;
- flag off: never code mode (the fine-grained node is byte-equal - the parity
  harnesses prove that part).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.agent.kernel.der import node


def _tool(name):
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}


DEV = [_tool("read_file"), _tool("run_command"), _tool("run_python")]
PERSONAL = [_tool("read_file")]


@pytest.fixture()
def flag_on(monkeypatch):
    monkeypatch.setenv("IRIS_WORKBENCH", "1")
    from backend.agent.workbench import client

    monkeypatch.setattr(client, "resolve_interpreter", lambda workdir: "python")


@pytest.mark.parametrize("goal,expected", [
    ("Read the 14 service logs and count the ERROR lines per code", True),     # READ
    ("Run the tests and report how many fail", True),                           # RUN
    ("Create calc.py with an add function", False),                             # WRITE
    ("Read https://example.com/docs and summarise it", False),                   # external
])
def test_entry_rule_takes_read_and_run_steps_only(flag_on, goal, expected):
    assert node._wb_code_mode(goal, DEV, ".") is expected


def test_no_code_mode_without_run_python_or_without_the_flag(flag_on, monkeypatch):
    goal = "Read the logs and count the errors"
    assert node._wb_code_mode(goal, PERSONAL, ".") is False                  # personal mode
    monkeypatch.delenv("IRIS_WORKBENCH")
    assert node._wb_code_mode(goal, DEV, ".") is False                       # flag off


def test_no_interpreter_means_no_code_mode_and_is_counted(flag_on, monkeypatch):
    from backend.agent.workbench import client

    monkeypatch.setattr(client, "resolve_interpreter", lambda workdir: None)
    before = node.wb_stats()["unavailable"]
    assert node._wb_code_mode("Read the logs and count the errors", DEV, ".") is False
    assert node.wb_stats()["unavailable"] == before + 1


def _res(*calls, success=False):
    return SimpleNamespace(success=success, calls=[
        {"tool": "run_python", "ok": ok, "out": out} for ok, out in calls])


def test_fallback_rule():
    assert node._wb_needs_fallback(_res((False, "NameError: x"), (False, "NameError: y"))) \
        == "twice NameError"
    assert node._wb_needs_fallback(_res((False, "NameError: x"), (False, "KeyError: y"))) == ""
    assert node._wb_needs_fallback(_res((False, "case workbench_unavailable"))) == "unavailable"
    assert node._wb_needs_fallback(_res(
        (False, "PermissionError: workbench: writing outside the project is refused"))) \
        == "sandbox_refused"
    assert node._wb_needs_fallback(_res((True, "ok"), success=True)) == ""
    assert node._wb_needs_fallback(SimpleNamespace(success=False, calls=[])) == "no_execution"
