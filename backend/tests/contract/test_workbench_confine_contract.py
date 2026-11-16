"""Workbench OS confinement contract (owner 2026-11-16: "Yes, confine them").

Personal mode = coding on the user's OWN project with the IRIS source out of reach. The
worker's Python audit hook confines Python writes only; sh('node ...'), a subprocess, npm
and ctypes are outside it. On Windows the worker therefore lowers its own token to LOW
integrity (Mandatory Integrity Control) at startup - every child inherits it - and the parent
first labels the project folder Low, so that folder stays writable.

Pinned here (Windows):
- a personal workbench can write INSIDE the project folder with a Python script, with
  sh('node ...'), with a subprocess python child (new files AND files that existed before);
- the same three, and a raw ctypes CreateFileW, CANNOT write into a medium-integrity folder
  outside it (a scratch folder stands in for the IRIS repo / another user folder);
- the worker reports itself confined; its TEMP is a Low folder that is removed at close;
  the project can still run node and npm;
- developer mode is NOT confined and its folder is not labelled;
- a lowering failure -> case `workbench_confine_failed`, no worker left running;
- a drive root, the user profile folder and a folder that contains the IRIS repo are refused
  (the label is inheritable), before anything is labelled.
"""
import os
import shutil
import subprocess
import tempfile
import textwrap
import types

import pytest

from backend.tests.contract._wb_common import HERE, drop, mod

manager_mod = mod("manager")
client_mod = mod("client")
REPO = HERE.parents[2]          # the directory that holds backend/

pytestmark = pytest.mark.skipif(os.name != "nt", reason="OS confinement is Windows-only")
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _js(path, content="x", append=False):
    fn = "appendFileSync" if append else "writeFileSync"
    p = str(path).replace("\\", "/")
    return f"node -e \"require('fs').{fn}('{p}','{content}')\""


@pytest.fixture
def folders():
    """(project, outside): two sibling folders in the system temp folder (outside the repo).
    `outside` is an ordinary medium-integrity folder: the stand-in for the IRIS repo."""
    project = tempfile.mkdtemp(prefix="_wbc_proj_")
    outside = tempfile.mkdtemp(prefix="_wbc_out_")
    with open(os.path.join(project, "pre.txt"), "w") as f:      # exists BEFORE the label
        f.write("a")
    os.mkdir(os.path.join(project, "sub"))
    with open(os.path.join(project, "sub", "inner.txt"), "w") as f:
        f.write("b")
    yield project, outside
    drop(project)
    drop(outside)


def _manager(mode):
    return manager_mod.WorkbenchManager(mode_of=lambda: mode)


@pytest.fixture
def personal(folders):
    m = _manager("personal")
    c = m.workbench_for("conv-confine", folders[0])
    assert c is not None
    yield c, folders[0], folders[1]
    m.shutdown()


def _run(c, code):
    rep = c.exec(code)
    assert rep["ok"], rep.get("error")
    return rep


def _child_code(target):
    """A script that starts a python child process to write `target` (not the worker itself)."""
    child = f"open({target!r}, 'w').write('x')"
    return ("import subprocess, sys\n"
            f"p = subprocess.run([sys.executable, '-c', {child!r}], capture_output=True)\n"
            "p.returncode")


def _sh_code(command):
    return f"r = sh({command!r})\nr['code']"


# --- inside the project folder: everything works -----------------------------------------
def test_python_script_writes_inside_the_project(personal):
    c, project, _ = personal
    _run(c, "open('mine.txt', 'w').write('x')\nopen('pre.txt', 'a').write('y')\n"
            "open('sub/inner.txt', 'a').write('y')\nimport os\nos.mkdir('newdir')")
    assert os.path.isfile(os.path.join(project, "mine.txt"))
    assert open(os.path.join(project, "pre.txt")).read() == "ay"         # an existing file changed
    assert os.path.isdir(os.path.join(project, "newdir"))


@needs_node
def test_sh_node_writes_inside_the_project_new_and_existing(personal):
    c, project, _ = personal
    for name, append in (("n.txt", False), ("pre.txt", True), ("sub/inner.txt", True)):
        rep = _run(c, _sh_code(_js(os.path.join(project, name), "z", append)))
        assert rep["value"] == "0", (name, c.inspect("r", 0, 600)["text"])
    assert os.path.isfile(os.path.join(project, "n.txt"))
    assert open(os.path.join(project, "pre.txt")).read().endswith("z")
    assert open(os.path.join(project, "sub", "inner.txt")).read().endswith("z")


def test_a_subprocess_python_child_writes_inside_the_project(personal):
    c, project, _ = personal
    target = os.path.join(project, "child.txt")
    rep = _run(c, _child_code(target))
    assert rep["value"] == "0" and os.path.isfile(target)


# --- outside the project folder: the OS refuses every route ------------------------------
def test_python_script_cannot_write_outside(personal):
    c, _, outside = personal
    target = os.path.join(outside, "py.txt")
    rep = c.exec(f"open({target!r}, 'w').write('x')")
    assert not rep["ok"] and rep["error"]["type"] == "PermissionError"
    assert not os.path.exists(target)


@needs_node
def test_sh_node_cannot_write_outside(personal):
    c, _, outside = personal
    target = os.path.join(outside, "n.txt")
    rep = _run(c, _sh_code(_js(target)))
    assert rep["value"] != "0", "node wrote outside the project folder"
    assert "EPERM" in c.inspect("r['stderr']", 0, 2000)["text"]
    assert not os.path.exists(target)


def test_a_subprocess_python_child_cannot_write_outside(personal):
    c, _, outside = personal
    target = os.path.join(outside, "child.txt")
    rep = _run(c, _child_code(target))
    assert rep["value"] != "0", "a child process wrote outside the project folder"
    assert not os.path.exists(target)


def test_ctypes_cannot_write_outside(personal):
    """ctypes skips the audit hook entirely: only the OS stands between it and the folder."""
    c, _, outside = personal
    target = os.path.join(outside, "ct.txt")
    code = textwrap.dedent(f"""
        import ctypes
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.CreateFileW.restype = ctypes.c_void_p
        h = k.CreateFileW({target!r}, 0x40000000, 0, None, 2, 0x80, None)
        ok = h not in (None, ctypes.c_void_p(-1).value)
        if ok:
            k.CloseHandle(ctypes.c_void_p(h))
        (ok, ctypes.get_last_error())
    """)
    rep = _run(c, code)
    assert rep["value"].startswith("(False, 5)"), rep["value"]       # ERROR_ACCESS_DENIED
    assert not os.path.exists(target)


# --- the worker says it is confined; its temp is a Low folder -----------------------------
def test_the_worker_reports_itself_confined(personal):
    c, _, _ = personal
    assert c.confined is True


def test_the_confined_temp_is_a_low_folder_removed_at_close(folders):
    m = _manager("personal")
    c = m.workbench_for("conv-confine", folders[0])
    tmp = _run(c, "import tempfile\nwith tempfile.NamedTemporaryFile() as f:\n    pass\ntempfile.gettempdir()")["value"]
    tmp = tmp.strip("'").replace("\\\\", "\\")
    assert os.path.normcase(os.path.dirname(tmp)) == os.path.normcase(client_mod.low_root())
    assert os.path.isdir(tmp)
    m.shutdown()
    assert not os.path.exists(tmp)


@needs_node
def test_the_confined_worker_can_run_node_and_npm(personal):
    c, _, _ = personal
    assert _run(c, _sh_code("node -e \"console.log(1+1)\""))["value"] == "0"
    rep = _run(c, "r = sh('npm --version', timeout=60)\nr['code']")
    assert rep["value"] == "0", c.inspect("r", 0, 800)["text"]


# --- developer mode: unchanged ------------------------------------------------------------
@needs_node
def test_developer_mode_is_not_confined_and_its_folder_is_not_labelled(folders):
    project, outside = folders
    m = _manager("developer")
    try:
        c = m.workbench_for("conv-dev", project)
        assert c is not None and c.confined is False
        target = os.path.join(outside, "dev.txt")
        assert _run(c, _sh_code(_js(target)))["value"] == "0"
        assert os.path.isfile(target)                    # the test tells the two modes apart
        acl = subprocess.run(["icacls", project], capture_output=True, text=True).stdout
        assert "Mandatory Label" not in acl
    finally:
        m.shutdown()


# --- fail closed --------------------------------------------------------------------------
def _failing_worker(tmp_path):
    """A worker entry point whose ctypes cannot load a DLL: the lowering raises."""
    p = tmp_path / "failing_worker.py"
    p.write_text(textwrap.dedent(f"""
        import ctypes, runpy, sys
        def boom(*a, **k):
            raise OSError('forced lowering failure')
        ctypes.WinDLL = boom
        sys.argv[0] = {client_mod.WORKER_PATH!r}
        runpy.run_path({client_mod.WORKER_PATH!r}, run_name='__main__')
    """))
    return str(p)


def test_a_lowering_failure_is_a_named_case_and_no_worker_stays_running(folders, tmp_path, monkeypatch):
    procs = []
    real_popen = client_mod.subprocess.Popen

    def spy(*a, **k):
        p = real_popen(*a, **k)
        procs.append(p)
        return p

    monkeypatch.setattr(client_mod, "WORKER_PATH", _failing_worker(tmp_path))
    monkeypatch.setattr(client_mod.subprocess, "Popen", spy)
    m = _manager("personal")
    try:
        with pytest.raises(manager_mod.WorkbenchCapReached) as ei:
            m.workbench_for("conv-confine", folders[0])
        assert isinstance(ei.value, manager_mod.WorkbenchConfineFailed)
        assert ei.value.case == "workbench_confine_failed"
        assert "forced lowering failure" in str(ei.value)
        st = m.stats()
        assert st["confine_failed"] == 1 and st["live"] == 0 and st["start_failed"] == 0
        assert procs and all(p.poll() is not None for p in procs)    # nothing left running
    finally:
        m.shutdown()


def test_a_worker_that_does_not_report_confined_is_refused(folders, monkeypatch):
    """The parent does not trust a silent worker: no `confined: true` in hello -> refused."""
    real = client_mod.WorkbenchClient._roundtrip

    def no_flag(self, frame, wait_s, rss=True, on_call=None):
        rep = real(self, frame, wait_s, rss, on_call)
        if rep.get("re") == "hello":
            rep["confined"] = False
        return rep

    monkeypatch.setattr(client_mod.WorkbenchClient, "_roundtrip", no_flag)
    m = _manager("personal")
    try:
        with pytest.raises(manager_mod.WorkbenchConfineFailed):
            m.workbench_for("conv-confine", folders[0])
        assert m.stats()["live"] == 0
    finally:
        m.shutdown()


# --- the label is inheritable: refuse the folders it must never reach ----------------------
@pytest.mark.parametrize("which", ["drive_root", "profile", "repo_parent"])
def test_personal_refuses_folders_the_label_must_not_reach(which, monkeypatch):
    def never(path):
        raise AssertionError(f"labelled {path!r}")

    monkeypatch.setattr(manager_mod, "label_low", never)
    wd = {"drive_root": os.path.splitdrive(os.getcwd())[0] + "\\",
          "profile": os.environ["USERPROFILE"],
          "repo_parent": str(REPO.parent)}[which]
    m = _manager("personal")
    try:
        with pytest.raises(manager_mod.WorkbenchScopeRefused) as ei:
            m.workbench_for("conv-confine", wd)
        assert ei.value.case == "workbench_scope"
        assert m.stats()["scope_refused"] == 1 and m.stats()["live"] == 0
    finally:
        m.shutdown()


# --- non-Windows: today's behaviour, said once --------------------------------------------
def test_off_windows_personal_mode_says_once_that_confinement_is_windows_only(monkeypatch, caplog):
    monkeypatch.setattr(manager_mod, "os", types.SimpleNamespace(name="posix"))
    monkeypatch.setattr(manager_mod, "_NOT_WINDOWS_LOGGED", False)
    with caplog.at_level("WARNING"):
        assert manager_mod._confines() is False
        assert manager_mod._confines() is False
    said = [r for r in caplog.records if "Windows-only" in r.getMessage()]
    assert len(said) == 1
