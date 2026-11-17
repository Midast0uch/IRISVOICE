"""Workbench sh() contract (owner 2026-11-16: "i want the agent to able perform all coding
languages inside the workbench especially javascript").

sh(command, input=None, timeout=120) runs ANY language's command as a child of the
workbench, in the project folder, and returns {"code", "stdout", "stderr", "timed_out"}.
Pinned here: a list and a shell string both run; a JavaScript snippet runs through
`node -` on stdin; a non-zero exit is a RESULT, not an exception; a timeout kills the
whole process tree (a grandchild never finishes its work); the run's own deadline bounds
sh() so the run returns instead of being stopped; sh is a helper, not a changed variable.
"""
import importlib
import os
import shutil
import sys
import tempfile
import time

import pytest

from backend.tests.contract._wb_common import HERE, PKG, PKG_PATH, PYTHON, WB_WORK
from backend.tests.contract._wb_common import drop as _drop

if PKG_PATH:
    sys.path.insert(0, PKG_PATH)
client_mod = importlib.import_module(PKG + ".client")
WorkbenchClient = client_mod.WorkbenchClient


@pytest.fixture()
def wb():
    workdir = tempfile.mkdtemp(dir=str(WB_WORK), prefix="_wb_")
    c = WorkbenchClient(PYTHON, workdir)
    c.start()
    try:
        yield c, workdir
    finally:
        c.close()
        _drop(workdir)


def _ok(rep):
    assert rep["ok"], rep.get("error")
    return rep


def test_a_list_command_runs_in_the_project_folder(wb):
    c, workdir = wb
    _ok(c.exec("import sys\nr = sh([sys.executable, '-c', 'import os; print(6*7); print(os.getcwd())'])"))
    rep = _ok(c.inspect("r", 0, 4000))
    assert "'code': 0" in rep["text"] and "42" in rep["text"]
    assert os.path.basename(workdir) in rep["text"]                 # cwd = the project folder
    assert "'timed_out': False" in rep["text"]


def test_input_goes_to_the_child_stdin(wb):
    c, _ = wb
    _ok(c.exec("import sys\nr = sh([sys.executable, '-'], input='print(\"from stdin\")')"))
    assert "from stdin" in _ok(c.inspect("r['stdout']", 0, 400))["text"]


def test_a_non_zero_exit_is_a_result_not_an_exception(wb):
    c, _ = wb
    _ok(c.exec("import sys\nr = sh([sys.executable, '-c', 'import sys; sys.stderr.write(\"bad\"); sys.exit(3)'])"))
    rep = _ok(c.inspect("(r['code'], r['stderr'])", 0, 400))
    assert "3" in rep["text"] and "bad" in rep["text"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed on this machine")
def test_javascript_runs_as_a_snippet_and_as_a_shell_command(wb):
    c, _ = wb
    _ok(c.exec("r1 = sh('node -', input='console.log([1,2,3].map(x => x * 2).join(\",\"))')\n"
               "r2 = sh('node -e \"console.log(40 + 2)\"')"))
    assert "2,4,6" in _ok(c.inspect("r1['stdout']", 0, 200))["text"]
    assert "42" in _ok(c.inspect("r2['stdout']", 0, 200))["text"]


def test_a_timeout_kills_the_whole_process_tree(wb):
    """The child starts a grandchild that writes a marker after 3 s; sh() times out at 1 s.
    Killing only the child would leave the grandchild to write the marker."""
    c, workdir = wb
    marker = os.path.join(workdir, "grandchild_wrote.txt")
    grand = (f"import time; time.sleep(3); open({marker!r}, 'w').write('x')")
    child = (f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {grand!r}]); "
             f"time.sleep(30)")
    t0 = time.monotonic()
    _ok(c.exec(f"import sys\nr = sh([sys.executable, '-c', {child!r}], timeout=1)", timeout_s=60))
    took = time.monotonic() - t0
    assert "True" in _ok(c.inspect("r['timed_out']", 0, 50))["text"]
    assert took < 15, took
    time.sleep(4.5)
    assert not os.path.exists(marker), "the grandchild survived the timeout"


def test_the_runs_own_deadline_bounds_sh(wb):
    """sh(timeout=60) inside a run of timeout_s=2 returns before the run is stopped."""
    c, _ = wb
    t0 = time.monotonic()
    rep = c.exec("import sys\nr = sh([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=60)\n"
                 "after = 'reached'", timeout_s=2)
    took = time.monotonic() - t0
    assert rep["ok"], rep.get("error")                              # not stopped by the watchdog
    assert "reached" in _ok(c.inspect("after", 0, 50))["text"]
    assert "True" in _ok(c.inspect("r['timed_out']", 0, 50))["text"]
    assert took < 10, took


def test_sh_is_a_helper_not_a_changed_variable(wb):
    c, _ = wb
    rep = _ok(c.exec("x = 1"))
    names = [v.get("name") if isinstance(v, dict) else v for v in rep.get("vars") or []]
    assert "sh" not in names and "x" in names
