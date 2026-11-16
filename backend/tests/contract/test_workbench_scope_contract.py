"""CLM-11 Round 3 / T7.11 contract: personal mode is a SCOPE, not a ban.

- run_python is offered in personal mode (it is not in CapabilitySet._TERMINAL_TOOLS);
- a personal workbench refuses a workdir at or under the IRIS repo with the named case
  `workbench_scope` (a WorkbenchCapReached, so the bridge's handler returns a result);
- a personal workbench in a folder outside the repo works, and a write into the IRIS repo
  from it is refused by the worker's audit hook;
- developer mode is unchanged: workbench_for(conv, <IRIS repo>) works;
- a mode change ends the open workbench; get_manager() reads the live mode.
"""
import shutil
import tempfile
from pathlib import Path

import pytest

from backend.tests.contract._wb_common import HERE, drop, make_workdir, mod

manager_mod = mod("manager")
REPO = HERE.parents[2]          # the directory that holds backend/


@pytest.fixture
def mgr():
    modes = {"now": "personal"}
    m = manager_mod.WorkbenchManager(mode_of=lambda: modes["now"])
    m.modes = modes
    yield m
    m.shutdown()


@pytest.fixture
def outside():
    d = tempfile.mkdtemp(prefix="_wb_scope_")           # the system temp folder: outside the repo
    yield d
    drop(d)


def test_personal_mode_lists_run_python(monkeypatch):
    from backend.agent.tool_bridge import AgentToolBridge
    from backend.capabilities import CapabilitySet

    monkeypatch.setattr(CapabilitySet, "get_mode", classmethod(lambda cls: "personal"))
    assert "run_python" in {t["name"] for t in AgentToolBridge().get_available_tools()}
    assert CapabilitySet.is_tool_allowed("run_python")
    assert not CapabilitySet.is_tool_allowed("run_command")      # unchanged: a separate owner question


@pytest.mark.parametrize("sub", ["", "backend", "backend/tests/contract"])
def test_personal_refuses_the_iris_repo_and_its_subfolders(mgr, sub):
    wd = str(REPO / sub) if sub else str(REPO)
    with pytest.raises(manager_mod.WorkbenchCapReached) as ei:
        mgr.workbench_for("conv-a", wd)
    assert isinstance(ei.value, manager_mod.WorkbenchScopeRefused)
    assert ei.value.case == "workbench_scope"
    assert mgr.stats()["scope_refused"] == 1 and mgr.stats()["live"] == 0


def test_personal_works_outside_the_repo_and_refuses_a_write_into_the_repo(mgr, outside):
    c = mgr.workbench_for("conv-a", outside)
    assert c is not None and c.alive
    assert c.exec("open('mine.txt', 'w').write('x')\n'ok'")["ok"]      # the session folder is writable
    probe = REPO / "backend" / "tests" / "contract" / "_scope_probe.txt"
    try:
        rep = c.exec(f"open({str(probe)!r}, 'w').write('x')")
        assert not rep["ok"] and rep["error"]["type"] == "PermissionError"
        assert not probe.exists()
    finally:
        probe.unlink(missing_ok=True)


def test_developer_mode_workbench_in_the_repo_works(mgr):
    mgr.modes["now"] = "developer"
    c = mgr.workbench_for("conv-a", str(REPO))
    assert c is not None and c.alive
    assert mgr.stats()["scope_refused"] == 0


def test_a_mode_change_ends_the_open_workbench(mgr, outside):
    c = mgr.workbench_for("conv-a", outside)
    assert c.alive
    mgr.modes["now"] = "developer"
    c2 = mgr.workbench_for("conv-a", outside)
    assert c2 is not c and not c.alive and c2.alive
    assert mgr.stats()["mode_changed"] == 1 and mgr.stats()["live"] == 1


def test_the_process_manager_reads_the_live_mode(monkeypatch):
    from backend.capabilities import CapabilitySet

    m = manager_mod.get_manager()
    assert m._mode_of is not None
    for name in ("personal", "developer"):
        monkeypatch.setattr(CapabilitySet, "get_mode", classmethod(lambda cls, n=name: n))
        assert m._mode_of() == name
