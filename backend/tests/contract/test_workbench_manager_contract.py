"""CLM-11 / T7.2 contract: the Workbench manager owns processes per conversation."""
import subprocess
import sys
import threading
import time

import psutil
import pytest

from backend.tests.contract._wb_common import HERE, PKG, PKG_PATH, PYTHON, drop, make_workdir, mod

manager_mod = mod("manager")


@pytest.fixture
def dirs():
    made = []

    def new():
        d = make_workdir()
        made.append(d)
        return d

    yield new
    for d in made:
        drop(d)


@pytest.fixture
def mgrs():
    made = []

    def new(**kw):
        m = manager_mod.WorkbenchManager(**kw)
        made.append(m)
        return m

    yield new
    for m in made:
        m.shutdown()


def wait_for(cond, secs):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def test_lazy_start_and_reuse(mgrs, dirs):
    m, wd = mgrs(), dirs()
    assert m.stats()["live"] == 0 and m.stats()["started"] == 0      # nothing runs at construction
    c = m.workbench_for("conv-a", wd)
    assert c is not None and c.alive and m.stats()["live"] == 1
    assert m.workbench_for("conv-a", wd) is c                          # same conversation, same process
    assert m.stats()["started"] == 1
    assert c.exec("x = 5")["ok"] and m.workbench_for("conv-a", wd).exec("x")["value"] == "5"


def test_no_interpreter_is_none_and_counted(mgrs, dirs):
    m = mgrs(resolver=lambda wd: None)
    assert m.workbench_for("conv-a", dirs()) is None
    assert m.stats()["unavailable"] == 1 and m.stats()["live"] == 0


def test_idle_end_by_reaper_with_short_timeout(mgrs, dirs):
    m = mgrs(idle_s=0.6, reap_every_s=0.1)
    c = m.workbench_for("conv-a", dirs())
    pid = c.pid
    assert wait_for(lambda: m.stats()["live"] == 0, 6)
    assert m.stats()["idle_ended"] == 1
    assert wait_for(lambda: not psutil.pid_exists(pid), 5)


def test_busy_workbench_is_not_ended_by_idle(mgrs, dirs):
    m = mgrs(idle_s=0.5, reap_every_s=0.1)
    c = m.workbench_for("conv-a", dirs())
    rep = c.exec("import time\ntime.sleep(2)\n'done'", timeout_s=10)   # busy for 4x the idle window
    assert rep["value"] == "'done'" and c.alive
    assert m.stats()["idle_ended"] == 0


def test_cap_evicts_the_oldest_idle(mgrs, dirs):
    m = mgrs(max_live=2)
    a = m.workbench_for("conv-a", dirs())
    b = m.workbench_for("conv-b", dirs())
    m.touch("conv-a")                                                   # b is now the oldest idle
    pid_b = b.pid
    c = m.workbench_for("conv-c", dirs())
    assert c is not None and m.stats()["live"] == 2 and m.stats()["cap_evicted"] == 1
    assert a.alive and not b.alive and wait_for(lambda: not psutil.pid_exists(pid_b), 5)


def test_cap_refuses_when_all_busy(mgrs, dirs):
    m = mgrs(max_live=2)
    a, b = m.workbench_for("conv-a", dirs()), m.workbench_for("conv-b", dirs())
    ts = [threading.Thread(target=lambda c=c: c.exec("import time\ntime.sleep(3)", timeout_s=10)) for c in (a, b)]
    for t in ts:
        t.start()
    assert wait_for(lambda: a.busy and b.busy, 5)
    with pytest.raises(manager_mod.WorkbenchCapReached):
        m.workbench_for("conv-c", dirs())
    assert m.stats()["cap_refused"] == 1 and m.stats()["live"] == 2
    for t in ts:
        t.join(timeout=15)


def test_close_leaves_no_child(mgrs, dirs):
    m = mgrs()
    c = m.workbench_for("conv-a", dirs())
    c.exec("import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])")
    pid = c.pid
    kids = [p.pid for p in psutil.Process(pid).children(recursive=True)]
    assert m.close("conv-a") is True and m.close("conv-a") is False
    assert m.stats()["live"] == 0 and m.stats()["closed"] == 1
    assert wait_for(lambda: not psutil.pid_exists(pid), 5)
    assert all(not psutil.pid_exists(k) for k in kids)


def test_workdir_change_restarts(mgrs, dirs):
    m = mgrs()
    first = m.workbench_for("conv-a", dirs())
    first.exec("v = 1")
    pid = first.pid
    second = m.workbench_for("conv-a", dirs())
    assert second is not first and second.pid != pid and m.stats()["workdir_changed"] == 1
    assert second.exec("v")["error"]["type"] == "NameError"            # a fresh namespace
    assert wait_for(lambda: not psutil.pid_exists(pid), 5) and m.stats()["live"] == 1


def test_close_all_and_stats(mgrs, dirs):
    m = mgrs()
    pids = [m.workbench_for(f"conv-{i}", dirs()).pid for i in range(2)]
    st = m.stats()
    assert st["live"] == 2 and st["max_live"] == 2 and {c["conversation_id"] for c in st["conversations"]} == {"conv-0", "conv-1"}
    m.close_all()
    assert m.stats()["live"] == 0 and wait_for(lambda: not any(psutil.pid_exists(p) for p in pids), 5)


def test_process_exit_leaves_no_child(dirs):
    """atexit + stdin EOF: a process that started a Workbench and exits normally leaves none."""
    wd = dirs()
    code = (
        "import sys\n"
        + (f"sys.path.insert(0, {PKG_PATH!r})\n" if PKG_PATH else "")
        + f"import importlib\nm = importlib.import_module({PKG + '.manager'!r})\n"
        + f"c = m.get_manager().workbench_for('conv-x', {wd!r})\nprint(c.pid, flush=True)\n"
    )
    out = subprocess.run([PYTHON, "-c", code], capture_output=True, text=True, timeout=120,
                         cwd=str(HERE.parents[2]))
    assert out.returncode == 0, out.stderr[-800:]
    pid = int(out.stdout.strip().splitlines()[-1])
    assert wait_for(lambda: not psutil.pid_exists(pid), 5)


def test_budget_evicts_the_oldest_idle_then_refuses_when_busy(mgrs, dirs):
    m = mgrs(max_live=4, budget_bytes=200 << 20)                       # room for one 150 MB holder, not two
    a = m.workbench_for("conv-a", dirs())
    assert a.exec("blob = b'x' * (170 * 1024 * 1024)")["ok"]
    pid_a = a.pid
    b = m.workbench_for("conv-b", dirs())                              # a (idle) is evicted for the budget
    assert b is not None and not a.alive and wait_for(lambda: not psutil.pid_exists(pid_a), 5)
    assert m.stats()["budget_evicted"] == 1 and m.stats()["live"] == 1
    assert b.exec("blob = b'x' * (170 * 1024 * 1024)")["ok"]
    t = threading.Thread(target=lambda: b.exec("import time\ntime.sleep(3)", timeout_s=10))
    t.start()
    assert wait_for(lambda: b.busy, 5)
    with pytest.raises(manager_mod.WorkbenchBudgetReached):
        m.workbench_for("conv-c", dirs())
    assert m.stats()["budget_refused"] == 1 and m.stats()["live"] == 1
    t.join(timeout=15)
