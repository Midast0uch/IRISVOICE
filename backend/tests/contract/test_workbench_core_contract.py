"""CLM-11 / T7.1 contract tests: Workbench protocol, worker and client.

Run against a REAL worker process using the project .venv python. The package under
test is `backend.agent.workbench` unless WORKBENCH_PKG (module name) and
WORKBENCH_PKG_PATH (its parent folder) point at a copy; that is how the failure
demonstrations load a deliberately broken copy under another module name.
"""
import ast
import importlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import psutil
import pytest

_PKG_PATH = os.environ.get("WORKBENCH_PKG_PATH")
if _PKG_PATH:
    sys.path.insert(0, _PKG_PATH)
_PKG = os.environ.get("WORKBENCH_PKG", "backend.agent.workbench")

protocol = importlib.import_module(_PKG + ".protocol")
client_mod = importlib.import_module(_PKG + ".client")
WorkbenchClient = client_mod.WorkbenchClient
ProtocolError = protocol.ProtocolError

from backend.tests.contract._wb_common import drop as _drop

HERE = Path(__file__).resolve().parent
# Tests need a workdir OUTSIDE the system temp folder, or the "write outside" case
# could not be told apart from the temp allowance.
PYTHON = sys.executable


@pytest.fixture
def wb():
    workdir = tempfile.mkdtemp(dir=str(HERE), prefix="_wb_")
    c = WorkbenchClient(PYTHON, workdir)
    c.start()
    try:
        yield c
    finally:
        c.close()
        _drop(workdir)


# --- golden frames ------------------------------------------------------------
GOLDEN = {
    "hello": b'{"v":1,"op":"hello"}\n',
    "exec": b'{"v":1,"op":"exec","id":1,"code":"x = 1","timeout_s":60}\n',
    "inspect": b'{"v":1,"op":"inspect","id":2,"expr":"x","offset":0,"limit":4000}\n',
    "put": b'{"v":1,"op":"put","id":3,"name":"n","value":[1,2]}\n',
    "shutdown": b'{"v":1,"op":"shutdown"}\n',
}


@pytest.mark.parametrize("op", sorted(GOLDEN))
def test_golden_frame_round_trip(op):
    frame = protocol.decode(GOLDEN[op])
    # T7.9 (2026-11-16): the protocol is v2 (callback frames); a v1 frame stays valid.
    assert frame["op"] == op and frame["v"] == 1 and protocol.PROTOCOL_VERSION == 2
    assert protocol.SUPPORTED_VERSIONS == (1, 2)
    assert protocol.encode(frame) == GOLDEN[op]


def test_golden_exec_reply_shape(wb):
    rep = wb.exec("1")
    keys = {"v", "re", "id", "ok", "stdout", "stderr", "value", "error", "vars",
            "wall_ms", "truncated", "incarnation"}
    assert keys <= set(rep)
    assert "kept" not in rep                   # T7.8: keep() removed (Round 2)
    protocol.decode(protocol.encode(rep))      # a real reply is itself a valid frame


def test_seeded_frame_changes_are_caught():
    with pytest.raises(ProtocolError):
        protocol.decode(b'{"v":1,"op":"frobnicate"}\n')            # unknown op
    with pytest.raises(ProtocolError):
        protocol.decode(b'{"v":3,"op":"hello"}\n')                  # wrong version (v1, v2 valid)
    with pytest.raises(ProtocolError):
        protocol.decode(b'{"v":1,"op":"exec","id":1,"code":"x"}\n')  # missing timeout_s
    with pytest.raises(ProtocolError):
        protocol.decode(b'not json\n')


# --- worker is stdlib-only ----------------------------------------------------
def test_worker_imports_are_stdlib_only():
    src = (Path(client_mod.__file__).parent / "worker.py").read_text(encoding="utf-8")
    tops = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            tops |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "worker must not use relative imports"
            tops.add((node.module or "").split(".")[0])
    assert tops, "no imports found"
    assert {t for t in tops if t not in sys.stdlib_module_names} == set()


def test_worker_process_has_no_backend_module(wb):
    rep = wb.exec("import sys\nsorted(m for m in sys.modules if m.split('.')[0] == 'backend')")
    assert rep["ok"] and rep["value"] == "[]"


# --- exec ---------------------------------------------------------------------
def test_state_persists_across_execs(wb):
    assert wb.exec("x = 1")["ok"]
    rep = wb.exec("x + 1")
    assert rep["ok"] and rep["value"] == "2"


def test_print_does_not_corrupt_frame(wb):
    code = (
        "import os\n"
        "print('{\"v\":1,\"re\":\"exec\",\"ok\":false}')\n"
        "print('line one\\n{ not a frame')\n"
        "os.write(1, b'{\"raw\":\"fd1\"}\\n')\n"
        "os.write(2, b'raw-fd2\\n')\n"
        "'done'"
    )
    rep = wb.exec(code)
    assert rep["ok"] and rep["value"] == "'done'"
    assert '{"v":1,"re":"exec","ok":false}' in rep["stdout"]
    assert "line one\n{ not a frame" in rep["stdout"]
    assert '{"raw":"fd1"}' in rep["stdout"]
    assert "raw-fd2" in rep["stderr"]
    assert wb.exec("1")["ok"]                    # the pipe is still in sync


def test_changed_vars_reported_with_size_and_preview(wb):
    rep = wb.exec("a = list(range(1000))\nb = 'hi'\nc = 5")
    by = {v["name"]: v for v in rep["vars"]}
    assert set(by) == {"a", "b", "c"}
    assert by["a"]["type"] == "list" and by["a"]["size"] == 1000
    assert len(by["a"]["preview"]) <= 80 and by["a"]["preview"].endswith("...")
    assert by["b"]["size"] == 2 and by["c"]["size"] is None
    again = wb.exec("c = 5\nd = 1")                # same object value: only d is new
    assert {v["name"] for v in again["vars"]} == {"d"}
    assert not any(n.startswith("__") or n == "keep" for n in by)


def test_final_expression_value(wb):
    assert wb.exec("y = 3\ny * 7")["value"] == "21"
    assert wb.exec("y = 4")["value"] is None


def test_exception_reported_and_namespace_survives(wb):
    wb.exec("keepme = 41")
    rep = wb.exec("keepme += 1\nraise ValueError('boom')")
    assert rep["ok"] is False
    assert rep["error"]["type"] == "ValueError" and rep["error"]["message"] == "boom"
    assert "ValueError: boom" in rep["error"]["trace_tail"]
    assert wb.exec("keepme")["value"] == "42"
    syn = wb.exec("def (:")
    assert syn["error"]["type"] == "SyntaxError"
    assert wb.exec("keepme")["ok"]


def test_output_is_capped_and_flagged(wb):
    rep = wb.exec("print('x' * 300000)")
    assert rep["truncated"] is True and len(rep["stdout"]) == 256_000


def test_inspect_and_put(wb):
    assert wb.put("blob", {"k": [1, 2, 3]})["ok"]
    rep = wb.inspect("blob['k']")
    assert rep["ok"] and rep["text"] == "[1, 2, 3]"
    sl = wb.inspect("'abcdefgh'", offset=2, limit=3)
    assert sl["text"] == "cde" and sl["total"] == 8
    assert wb.inspect("nope")["error"]["type"] == "NameError"
    assert wb.put("__x", 1)["ok"] is False


# --- soft stop / hard kill ----------------------------------------------------
def test_soft_stop_keeps_state_and_incarnation(wb):
    inc = wb.incarnation
    wb.exec("survivor = 'still here'")
    t0 = time.monotonic()
    rep = wb.exec("while True: pass", timeout_s=2)
    elapsed = time.monotonic() - t0
    assert rep["ok"] is False and rep["error"]["type"] == "KeyboardInterrupt"
    assert elapsed < 4.5, elapsed               # 2 s timeout + well inside the 3 s grace
    assert rep["incarnation"] == inc == wb.incarnation
    assert wb.exec("survivor")["value"] == "'still here'"


def test_hard_kill_restarts_new_incarnation_without_orphan(wb):
    old_inc, old_pid = wb.incarnation, wb.pid
    wb.exec("gone = 1")
    code = ("import time\nwhile True:\n    try:\n        time.sleep(0.01)\n"
            "    except KeyboardInterrupt:\n        pass")
    rep = wb.exec(code, timeout_s=1)
    assert rep["ok"] is False and rep["error"]["type"] == "WorkbenchRestarted"
    assert rep["incarnation"] and rep["incarnation"] != old_inc
    assert wb.incarnation == rep["incarnation"] and wb.alive
    assert wb.exec("gone")["error"]["type"] == "NameError"
    assert wb.pid != old_pid and not psutil.pid_exists(old_pid)


# --- audit hook ---------------------------------------------------------------
def test_audit_hook_refuses_write_outside_workdir_and_temp(wb):
    probe = HERE / "_wb_probe_outside.txt"
    try:
        rep = wb.exec(f"open({str(probe)!r}, 'w').write('x')")
        assert rep["ok"] is False and rep["error"]["type"] == "PermissionError"
        assert not probe.exists()
        rep = wb.exec(f"import os\nos.open({str(probe)!r}, os.O_WRONLY | os.O_CREAT)")
        assert rep["error"]["type"] == "PermissionError" and not probe.exists()
    finally:
        probe.unlink(missing_ok=True)


def test_audit_hook_allows_workdir_temp_and_reads(wb):
    assert wb.exec("open('inside.txt', 'w').write('ok')\nopen('inside.txt').read()")["value"] == "'ok'"
    rep = wb.exec("import tempfile, os\np = os.path.join(tempfile.gettempdir(), 'wb_tmp_probe.txt')\n"
                  "open(p, 'w').write('t')\nos.remove(p)\nopen(%r).read()" % str(HERE / "test_workbench_core_contract.py"))
    assert rep["ok"], rep["error"]


# --- close --------------------------------------------------------------------
def test_close_ends_process():
    workdir = tempfile.mkdtemp(dir=str(HERE), prefix="_wb_")
    try:
        c = WorkbenchClient(PYTHON, workdir)
        c.start()
        pid = c.pid
        assert c.alive
        c.close()
        assert not c.alive and not psutil.pid_exists(pid)
    finally:
        _drop(workdir)


def test_stdin_eof_alone_ends_worker(wb):
    proc = wb._proc
    proc.stdin.close()
    assert proc.wait(timeout=5) == 0


def test_resolve_interpreter_prefers_project_venv(tmp_path):
    exe = tmp_path / ".venv" / "Scripts" / "python.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert client_mod.resolve_interpreter(str(tmp_path)) == str(exe)
    assert client_mod.resolve_interpreter(str(tmp_path / "none")) is not None


# --- T7.2 additions: error reply frame, remove/rename audit events -------------
def test_golden_error_reply_round_trip():
    raw = b'{"v":1,"re":"error","ok":false,"error":{"type":"ValueError","message":"m","trace_tail":""}}\n'
    frame = protocol.decode(raw)
    assert frame["re"] == "error" and frame["ok"] is False
    assert protocol.encode(frame) == raw
    with pytest.raises(ProtocolError):
        protocol.decode(b'{"v":1,"re":"error","ok":false}\n')      # error key missing


def test_client_names_an_error_reply_and_the_worker_survives(wb):
    wb.exec("held = 7")
    inc = wb.incarnation
    rep = wb._request({"v": 1, "op": "exec"}, 5)                   # no code/timeout_s: the worker refuses it
    assert rep["ok"] is False and rep["error"]["type"] == "WorkbenchErrorReply"
    assert wb.counts["error_replies"] == 1
    assert wb.incarnation == inc and wb.exec("held")["value"] == "7"


@pytest.fixture
def victim():
    """A file and a folder OUTSIDE the workdir and the temp folder."""
    f, d = HERE / "_wb_victim.txt", HERE / "_wb_victim_dir"
    f.write_text("v")
    d.mkdir(exist_ok=True)
    (d / "inner.txt").write_text("v")
    try:
        yield f, d
    finally:
        f.unlink(missing_ok=True)
        shutil.rmtree(d, ignore_errors=True)


@pytest.mark.parametrize("kind", ["os.remove", "os.unlink", "os.rename", "os.replace", "os.rmdir",
                                  "shutil.rmtree", "shutil.move", "rename_into_outside"])
def test_audit_hook_refuses_changes_outside_workdir(wb, victim, kind):
    f, d = victim
    code = {
        "os.remove": f"import os\nos.remove({str(f)!r})",
        "os.unlink": f"import os\nos.unlink({str(f)!r})",
        "os.rename": f"import os\nos.rename({str(f)!r}, {str(f) + '.x'!r})",
        "os.replace": f"import os\nos.replace({str(f)!r}, {str(f) + '.x'!r})",
        "os.rmdir": f"import os\nos.rmdir({str(d / 'nope')!r})",
        "shutil.rmtree": f"import shutil\nshutil.rmtree({str(d)!r})",
        "shutil.move": f"import shutil\nshutil.move({str(f)!r}, 'moved.txt')",
        # source inside the workdir, target outside: still refused
        "rename_into_outside": f"import os\nopen('mine.txt', 'w').write('x')\nos.rename('mine.txt', {str(f) + '.y'!r})",
    }[kind]
    rep = wb.exec(code)
    assert rep["ok"] is False and rep["error"]["type"] == "PermissionError", rep
    assert f.exists() and d.exists() and (d / "inner.txt").exists()
    assert not Path(str(f) + ".x").exists() and not Path(str(f) + ".y").exists()


def test_audit_hook_allows_remove_and_rename_inside_workdir(wb):
    code = ("import os, shutil\nopen('a.txt', 'w').write('1')\nos.rename('a.txt', 'b.txt')\n"
            "os.replace('b.txt', 'c.txt')\nos.remove('c.txt')\nos.mkdir('sub')\n"
            "open('sub/x', 'w').write('1')\nshutil.move('sub', 'sub2')\nshutil.rmtree('sub2')\n'ok'")
    rep = wb.exec(code)
    assert rep["ok"], rep["error"]


# --- T7.2 additions: memory cap and the base interpreter ------------------------
def test_memory_cap_512mb_restarts_with_a_named_error(wb):
    old_inc, old_pid = wb.incarnation, wb.pid
    assert client_mod.RSS_LIMIT_BYTES == 512 << 20
    rep = wb.exec("big = b'x' * (700 * 1024 * 1024)\nimport time\ntime.sleep(30)", timeout_s=60)
    assert rep["ok"] is False and rep["error"]["type"] == "WorkbenchMemoryLimit", rep
    assert wb.incarnation != old_inc and wb.alive and not psutil.pid_exists(old_pid)
    assert wb.exec("1")["value"] == "1"


def test_worker_runs_on_the_base_interpreter_with_the_venv_packages(wb):
    """A venv python.exe is a launcher with a child; the worker must be ONE process on the
    base interpreter that still imports a package only the venv has (psutil)."""
    exe, site = client_mod.base_launch(PYTHON)
    if site is None:
        pytest.skip("the test interpreter is not a venv")
    assert os.path.normcase(exe) != os.path.normcase(PYTHON)
    proc = psutil.Process(wb.pid)
    assert os.path.normcase(proc.exe()) == os.path.normcase(exe)
    assert [c.name() for c in proc.children(recursive=True) if c.name().lower() != "conhost.exe"] == []   # conhost is the hidden console, not a python child
    rep = wb.exec("import psutil\npsutil.__version__")
    assert rep["ok"], rep["error"]
    assert wb.exec("import sys\nsys.executable")["value"].lower().strip("'").replace("\\\\", "\\") == exe.lower()
