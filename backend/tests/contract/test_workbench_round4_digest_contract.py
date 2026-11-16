"""Round 4 / D6 + D8 contract.

D6: when a run carries `outputs` (the brief's names), the digest lists those names FIRST in its
changed-variable lines, then at most 4 others; without outputs it lists up to 12 in change order.
D8: the spill writes DECLARED outputs only: the brief's output names registered when a check
PASSES, plus the `out<n>` refs a digest handed out. A run with no brief spills only its LAST
script's named values. Loop temporaries (m, ln, f ...) never reach the spill.

The package under test is WORKBENCH_PKG / WORKBENCH_PKG_PATH, the bridge is WB_BRIDGE_FILE: each
can point at a deliberately broken copy (the failure demonstrations).
"""
import asyncio
import importlib
import importlib.util
import os
import sys
import time
from types import SimpleNamespace

import pytest

from backend.tests.contract import _wb_common as common


def _load(env, default):
    path = os.environ.get(env)
    if not path:
        return importlib.import_module(default)
    spec = importlib.util.spec_from_file_location("_broken_r4_" + env.lower(), path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bridge_mod = _load("WB_BRIDGE_FILE", "backend.agent.tool_bridge")
digest = common.mod("digest")


def _reply(names, inc="inc1", out_n=None, stdout=""):
    return {"ok": True, "incarnation": inc, "wall_ms": 1, "stdout": stdout, "out_n": out_n,
            "vars": [{"name": n, "type": "int", "size": None, "preview": "1"} for n in names]}


def _var_lines(text):
    return [l.split(":", 1)[0] for l in text.splitlines() if l.endswith("]") and "  [wb:" in l]


# --- D6 ---------------------------------------------------------------------------
def test_digest_lists_outputs_first_then_at_most_four_others():
    names = [f"tmp{i}" for i in range(10)] + ["result", "summary"]       # outputs set LAST
    rep = _reply(names)
    text = digest.digest(rep, outputs=["summary", "result"])
    assert _var_lines(text) == ["summary", "result", "tmp0", "tmp1", "tmp2", "tmp3"]
    assert "... and 6 more" in text
    assert [digest.parse_ref(r)[1] for r in digest.refs(rep, outputs=["summary", "result"])] == \
        ["summary", "result", "tmp0", "tmp1", "tmp2", "tmp3"]


def test_digest_without_outputs_is_today_up_to_twelve_in_change_order():
    rep = _reply([f"v{i}" for i in range(20)])
    text = digest.digest(rep)
    assert _var_lines(text) == [f"v{i}" for i in range(12)] and "... and 8 more" in text
    assert digest.digest(rep, outputs=[]) == text and digest.digest(rep, outputs=None) == text
    assert len(digest.refs(rep)) == 12


def test_outputs_that_did_not_change_are_not_invented():
    rep = _reply(["a", "b"])
    text = digest.digest(rep, outputs=["never_set"])
    assert _var_lines(text) == ["a", "b"] and "never_set" not in text


# --- D8: the spill, through the REAL bridge --------------------------------------
@pytest.fixture
def cs(tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_CONVERSATIONS_DB", str(tmp_path / "conversations.db"))
    import backend.conversation_store as store

    importlib.reload(store)
    yield store
    try:
        lane = store._tr_lane()
        deadline = time.monotonic() + 10.0
        while lane.pending() and time.monotonic() < deadline:
            time.sleep(0.01)
        lane.flush(10.0)
        store._conn.close()
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture
def call(cs, monkeypatch):
    real_mgr = importlib.import_module("backend.agent.workbench.manager")
    wd = common.make_workdir()
    mgr = real_mgr.WorkbenchManager(sink=real_mgr.StoreSink())
    monkeypatch.setattr(real_mgr, "get_manager", lambda: mgr)
    br = SimpleNamespace(_active_conversation_id={})

    def go(params, conv="conv-r4"):
        br._active_conversation_id["s-r4"] = conv
        return asyncio.run(bridge_mod._run_python_tool(br, params, "s-r4", wd))

    go.mgr, go.real_mgr, go.cs = mgr, real_mgr, cs
    yield go
    mgr.shutdown()
    common.drop(wd)


def _spilled_names(cs, conv="conv-r4"):
    lane = cs._tr_lane()
    assert lane.flush(10.0)
    return sorted(r["target"].rsplit("/", 1)[1] for r in cs.tool_results_for_turn(conv, None)
                  if r["tool"] == "wb_spill")


LOOP = ("error_codes = []\nfor ln in ['E-1 a', 'E-2 b']:\n    m = ln.split()\n    f = m[0]\n"
        "    error_codes.append(f)\n")


def test_a_brief_run_spills_only_its_declared_output_when_the_check_passes(call):
    r = call({"code": LOOP, "purpose": "collect codes", "check": "len(error_codes) == 2",
              "outputs": ["error_codes"], "close": True})
    assert r["success"] and r["check_ok"] is True and r["closed"] is True
    assert r["spilled"] == 1 and r["spill_confirmed"] is True
    assert _spilled_names(call.cs) == ["error_codes"]               # not m, ln, f
    out = call.real_mgr.expand(f"wb:{r['incarnation']}/error_codes", manager=call.mgr)
    assert out["success"] and out["spilled"] and "E-1" in out["content"]
    assert _var_lines(r["text"])[0] == "error_codes"                # D6 through the bridge


def test_a_failed_check_declares_nothing(call):
    r = call({"code": LOOP, "purpose": "collect codes", "check": "len(error_codes) == 99",
              "outputs": ["error_codes"], "close": True})
    assert r["check_ok"] is False and r["spilled"] == 0
    assert _spilled_names(call.cs) == []


def test_a_passing_check_after_a_failing_one_spills_the_outputs_once(call):
    first = call({"code": LOOP, "purpose": "try", "check": "len(error_codes) == 99", "outputs": ["error_codes"]})
    assert first["check_ok"] is False
    r = call({"code": "error_codes = ['E-1', 'E-2', 'E-3']\ntmp = 1", "purpose": "fix",
              "check": "len(error_codes) == 3", "outputs": ["error_codes"], "close": True})
    assert r["check_ok"] is True and r["spilled"] == 1
    assert _spilled_names(call.cs) == ["error_codes"]


def test_a_cut_stdout_ref_is_spilled_with_the_declared_outputs(call):
    r = call({"code": "print('s' * 5000)\nanswer = 42\ntmp = 1", "purpose": "noisy", "check": "answer == 42",
              "outputs": ["answer"], "close": True})
    assert r["check_ok"] is True and r["spilled"] == 2
    names = _spilled_names(call.cs)
    assert "answer" in names and any(n.startswith("out") for n in names) and "tmp" not in names


def test_no_brief_spills_only_the_last_scripts_named_values(call):
    call({"code": "a1 = 1\na2 = 2", "purpose": "first"})
    second = call({"code": "b1 = 'x'", "purpose": "second", "close": True})
    assert second["spilled"] == 1
    assert _spilled_names(call.cs) == ["b1"]
    gone = call.real_mgr.expand(f"wb:{second['incarnation']}/a1", manager=call.mgr)
    assert gone["success"] is False and gone["case"] == "workbench_gone"


# --- D8 at the package level (digest.named is what the spill reads) ----------------
def test_named_is_declared_outputs_only_for_a_brief_run():
    rep = _reply(["error_codes", "m", "ln", "f"], inc="r4-brief")
    digest.remember_named(rep, outputs=["error_codes"], passed=False)
    assert digest.named("r4-brief") == []                           # a check that has not passed declares nothing
    digest.remember_named(rep, outputs=["error_codes"], passed=True)
    assert digest.named("r4-brief") == ["error_codes"]


def test_named_without_a_brief_is_the_last_scripts_values_plus_out_refs():
    digest.remember_named(_reply(["a1", "a2"], inc="r4-nobrief"))
    digest.remember_named(_reply(["b1"], inc="r4-nobrief", out_n=3, stdout="s" * 5000))
    assert digest.named("r4-nobrief") == ["out3", "b1"]
