"""Workbench round 5 worker contract.

S1: the worker runs `python -I`, so the project folder is not on sys.path by itself. The worker
APPENDS it at startup: a script can `from cipher import encode`, and a project file named like a
stdlib module (json.py) never shadows the standard library.
K1a: digest(stdout_max=None) is today's digest byte for byte; stdout_max=12000 shows a 10,000-char
stdout whole; assigned(reply, names) lists which brief outputs a run assigned.
"""
import importlib
import os
import sys
import tempfile

import pytest

from backend.tests.contract._wb_common import HERE, PKG, PKG_PATH, PYTHON, WB_WORK
from backend.tests.contract._wb_common import drop as _drop

if PKG_PATH:
    sys.path.insert(0, PKG_PATH)
client_mod = importlib.import_module(PKG + ".client")
digest_mod = importlib.import_module(PKG + ".digest")
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


def test_a_script_imports_a_project_module(wb):
    c, workdir = wb
    with open(os.path.join(workdir, "cipher.py"), "w", encoding="utf-8") as f:
        f.write("def encode(s): return s[::-1]\n")
    _ok(c.exec("from cipher import encode; r = encode('abc')"))
    assert "cba" in _ok(c.inspect("r", 0, 100))["text"]


def test_a_project_json_py_does_not_shadow_the_standard_library(wb):
    c, workdir = wb
    with open(os.path.join(workdir, "json.py"), "w", encoding="utf-8") as f:
        f.write("SHADOW = True\n")
    _ok(c.exec("import json; r = (hasattr(json, 'dumps'), hasattr(json, 'SHADOW'))"))
    assert "(True, False)" in _ok(c.inspect("r", 0, 100))["text"]


def test_a_shadowing_file_loses_for_a_stdlib_module_the_worker_has_not_loaded(wb):
    # json is already in sys.modules when a script starts, so json.py alone cannot prove the order;
    # colorsys is imported fresh by the script, so an INSERTED project path would pick the shadow.
    c, workdir = wb
    with open(os.path.join(workdir, "colorsys.py"), "w", encoding="utf-8") as f:
        f.write("SHADOW = True\n")
    _ok(c.exec("import colorsys; r = (hasattr(colorsys, 'rgb_to_hsv'), hasattr(colorsys, 'SHADOW'))"))
    assert "(True, False)" in _ok(c.inspect("r", 0, 100))["text"]


def _reply(stdout, **kw):
    r = {"ok": True, "wall_ms": 1, "stdout": stdout, "out_n": 3, "incarnation": "inc", "vars": []}
    r.update(kw)
    return r


def test_stdout_max_none_is_the_old_digest_byte_for_byte():
    d = digest_mod.digest
    for n in (50, 1200, 1201, 10_000):
        r = _reply("x" * n)
        assert d(r, stdout_max=None) == d(r)
    r = _reply("H" * 600 + "m" * 5000 + "T" * 600)
    out = d(r)
    assert out == (f"run_python ok (1 ms)\nstdout:\n{'H' * 600}\n... [5000 chars cut] ...\n{'T' * 600}\n"
                   "full output: [wb out:inc/out3] (recall_memory expand=\"wb:inc/out3\")")


def test_stdout_max_12000_shows_a_10000_char_stdout_whole():
    text = "".join(f"{i % 10}" for i in range(10_000))
    out = digest_mod.digest(_reply(text), stdout_max=12_000)
    assert "stdout:\n" + text in out and "cut" not in out and "full output" not in out
    assert "cut" in digest_mod.digest(_reply(text))               # the default still cuts it


def test_stdout_max_splits_head_and_tail_when_over():
    text = "A" * 3000 + "B" * 3000
    out = digest_mod.digest(_reply(text), stdout_max=2000)
    assert "A" * 1000 + "\n... [4000 chars cut] ...\n" + "B" * 1000 in out


def test_assigned_lists_the_outputs_this_run_assigned(wb):
    c, _ = wb
    rep = _ok(c.exec("a = 1"))
    assert digest_mod.assigned(rep, ["a", "b"]) == ["a"]
    assert digest_mod.assigned(rep, ["b"]) == []
    assert digest_mod.assigned(rep, None) == []


def test_worker_output_cap_holds_the_largest_stdout_budget():
    worker = importlib.import_module(PKG + ".worker")
    assert worker.OUTPUT_CAP >= 12_000


@pytest.mark.skipif(os.name != "nt", reason="the working-set trim is a Windows behaviour")
def test_held_memory_survives_a_working_set_trim():
    """2026-11-16: the workbench caps and the digest's "holds N MB" line read the working
    set (rss); Windows trims an idle process, so a worker holding 300 MB read ~1 MB and
    test_digest_warns_when_the_worker_tree_passes_256_mb failed whenever the machine was
    busy. Force the trim and require the held size to stay above 256 MB."""
    import ctypes
    import tempfile as _tf

    import psutil

    wd = _tf.mkdtemp(prefix="_wb_trim_")
    c = WorkbenchClient(PYTHON, wd)
    c.start()
    try:
        assert c.exec("blob = b'x' * (300 * 1024 * 1024)")["ok"]
        k32 = ctypes.WinDLL("kernel32")
        p = psutil.Process(c.pid)
        for x in [p] + p.children(recursive=True):
            h = k32.OpenProcess(0x0100 | 0x0400, False, x.pid)
            k32.SetProcessWorkingSetSize(h, ctypes.c_size_t(-1), ctypes.c_size_t(-1))
            k32.CloseHandle(h)
        assert c.rss_mb() > 256
    finally:
        c.close()


def test_the_change_preview_never_reprs_a_whole_large_value(wb):
    """2026-11-16: _preview called repr() on the WHOLE value after every script (a 300 MB
    bytes value peaked the worker at 611 MB and tripped the 512 MB cap). A str whose full
    repr raises proves the preview slices first."""
    c, _ = wb
    rep = c.exec("class Big(str):\n    def __repr__(self):\n        raise RuntimeError('whole repr')\n"
                 "big = Big('y' * 1000)")
    assert rep["ok"], rep.get("error")
    pv = {v["name"]: v["preview"] for v in rep["vars"]}
    assert pv["big"].startswith("'yyy") and "repr failed" not in pv["big"]
