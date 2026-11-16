"""CLM-11 Round 2 / T7.8 + T7.10: the Workbench lifetime, the code rows and the spill.

T7.8: no `keep` helper in the namespace, no `kept` in the exec reply; every run_python
execution leaves ONE tool_results row (the code, the purpose, ok/error, wall_ms), queued on
the store's lane (add_tool_result), never inline.

T7.10: `fresh` / `close` and the spill. The values a digest named (`wb:` refs) are written
as tool_results rows when a Workbench ends with a live process (fresh, close, idle end,
cap eviction), so a `wb:` ref of the ended incarnation expands to its spilled text. A crash
or a hard kill spills nothing: `workbench_gone`. The spill goes through add_tool_result, so
its caps hold. close / fresh wait (bounded) for the writes; a timeout is counted, not raised.

The package under test is WORKBENCH_PKG / WORKBENCH_PKG_PATH; the bridge is WB_BRIDGE_FILE and
the registry is WB_REGISTRY_FILE: each can point at a deliberately broken copy (the failure
demonstrations). The bridge tests always use the real package; the package tests use the copy.
"""
import asyncio
import importlib
import importlib.util
import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from backend.tests.contract import _wb_common as common


def _load(env, default):
    path = os.environ.get(env)
    if not path:
        return importlib.import_module(default)
    spec = importlib.util.spec_from_file_location("_broken_" + env.lower(), path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


bridge_mod = _load("WB_BRIDGE_FILE", "backend.agent.tool_bridge")
registry_mod = _load("WB_REGISTRY_FILE", "backend.agent.tool_registry")
manager_mod = common.mod("manager")
digest = common.mod("digest")
protocol = common.mod("protocol")
client_mod = common.mod("client")


# --- fixtures ----------------------------------------------------------------
@pytest.fixture
def cs(tmp_path, monkeypatch):
    """A real conversation store in a temp file (as the tool_results contract does it)."""
    monkeypatch.setenv("IRIS_CONVERSATIONS_DB", str(tmp_path / "conversations.db"))
    import backend.conversation_store as store

    importlib.reload(store)
    yield store
    try:
        drain(store)
    except AssertionError:
        pass
    try:
        store._conn.close()
    except Exception:  # noqa: BLE001
        pass


def drain(store):
    lane = store._tr_lane()
    deadline = time.monotonic() + 10.0
    while lane.pending() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert lane.flush(10.0)


@pytest.fixture
def made():
    """Workdirs and managers, all cleaned up."""
    dirs, mgrs = [], []

    class Made:
        def workdir(self):
            d = common.make_workdir()
            dirs.append(d)
            return d

        def manager(self, **kw):
            m = manager_mod.WorkbenchManager(sink=manager_mod.StoreSink(), **kw)
            mgrs.append(m)
            return m

    yield Made()
    for m in mgrs:
        m.shutdown()
    for d in dirs:
        common.drop(d)


def run(client, code):
    """What the bridge does after an exec: the digest names the changed variables."""
    rep = client.exec(code)
    digest.remember_named(rep)
    return rep


def wait_for(cond, secs):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def rows_of(cs, conv):
    drain(cs)
    return cs.tool_results_for_turn(conv, None)


# --- T7.8: no keep, no kept ------------------------------------------------------
def test_no_keep_helper_and_no_kept_in_the_exec_reply(made):
    wd = made.workdir()
    c = client_mod.WorkbenchClient(common.PYTHON, wd)
    c.start()
    try:
        rep = c.exec("print('keep' in globals(), callable(globals().get('keep')))")
        assert rep["ok"] and rep["stdout"].strip() == "False False"
        assert "kept" not in rep
        protocol.decode(protocol.encode(rep))          # a reply without `kept` is a valid frame
    finally:
        c.close()
    assert "kept" not in protocol.REPLY_KEYS["exec"]


# --- T7.10: a wb ref of an ended incarnation expands to its spilled text ----------
def _live(made, cs, conv="c1", **kw):
    m = made.manager(**kw)
    client = m.workbench_for(conv, made.workdir())
    assert client is not None
    return m, client


def _expanded(m, ref):
    out = manager_mod.expand(ref, manager=m)
    assert out["success"] is True, out
    assert out["spilled"] is True
    return out


def test_ref_expands_after_fresh(made, cs):
    m, c = _live(made, cs)
    rep = run(c, "table = list(range(5000))\nlabel = 'abc'")
    inc1 = rep["incarnation"]
    ref = digest.make_ref(inc1, "table")
    assert manager_mod.expand(ref, manager=m)["success"] and "spilled" not in manager_mod.expand(ref, manager=m)
    info = m.end_spilled("c1", "fresh")
    assert info["ended"] and info["spilled"] == 2 and info["confirmed"] is True
    c2 = m.workbench_for("c1", made.workdir())                # the new incarnation
    assert c2.incarnation != inc1
    assert c2.exec("print('table' in globals())")["stdout"].strip() == "False"
    out = _expanded(m, ref)
    assert out["content"].startswith("[0, 1, 2, 3") and out["chars"] == len(repr(list(range(5000))))
    assert _expanded(m, digest.make_ref(inc1, "label"))["content"] == "abc"


def test_ref_expands_after_close(made, cs):
    m, c = _live(made, cs)
    rep = run(c, "total = sum(range(100))")
    ref = digest.make_ref(rep["incarnation"], "total")
    info = m.end_spilled("c1", "closed")
    assert info["ended"] and info["confirmed"] and m.stats()["live"] == 0
    assert _expanded(m, ref)["content"] == "4950"


def test_ref_expands_after_an_idle_end(made, cs):
    m, c = _live(made, cs, idle_s=0.5)
    rep = run(c, "answer = 'forty-two'")
    ref = digest.make_ref(rep["incarnation"], "answer")
    assert wait_for(lambda: m.stats()["live"] == 0, 20) and m.stats()["idle_ended"] == 1
    assert _expanded(m, ref)["content"] == "forty-two"


def test_ref_expands_after_a_cap_eviction(made, cs):
    m, c = _live(made, cs, max_live=1)
    rep = run(c, "kept_value = [1, 2, 3]")
    ref = digest.make_ref(rep["incarnation"], "kept_value")
    assert m.workbench_for("c2", made.workdir()) is not None   # the one slot goes to c2: c1 is evicted
    assert m.stats()["cap_evicted"] == 1
    assert _expanded(m, ref)["content"] == "[1, 2, 3]"


def test_a_hard_kill_spills_nothing_and_the_ref_is_gone(made, cs):
    m, c = _live(made, cs)
    rep = run(c, "lost = list(range(10))")
    ref = digest.make_ref(rep["incarnation"], "lost")
    digest.remember_origin(rep, "build the list")
    c._proc.kill()                                             # a hard kill: the process is gone
    assert wait_for(lambda: not c.alive, 10)
    assert m.reap_once() == 0                                   # reaped as `process dead`
    assert wait_for(lambda: m.stats()["live"] == 0, 10)
    out = manager_mod.expand(ref, manager=m)
    assert out["success"] is False and out["case"] == "workbench_gone"
    assert out["purpose"] == "build the list"
    assert m.stats()["spilled"] == 0 and rows_of(cs, "c1") == []


def test_a_deleted_name_is_not_spilled_and_the_rest_is(made, cs):
    m, c = _live(made, cs)
    rep = run(c, "a = 1\nb = 2")
    c.exec("del a")
    info = m.end_spilled("c1", "closed")
    assert info["spilled"] == 1
    assert _expanded(m, digest.make_ref(rep["incarnation"], "b"))["content"] == "2"
    assert manager_mod.expand(digest.make_ref(rep["incarnation"], "a"), manager=m)["case"] == "workbench_gone"


# --- the spill respects the tool_results caps ---------------------------------------
def test_spill_keeps_at_most_the_newest_named_values(made, cs):
    m, c = _live(made, cs)
    # Round 4 D8 (2026-11-16): the spill writes DECLARED outputs (a passed check's brief
    # names), not every variable a digest listed - so the 36 names are declared outputs of
    # three passing runs. Same load (36 names > NAMED_MAX), same cap, same "oldest cut".
    for k in range(3):                                          # 36 names: more than the spill keeps
        names = [f"v{k}_{i}" for i in range(12)]
        rep = c.exec("\n".join(f"{n} = {i}" for i, n in enumerate(names)))
        digest.remember_named(rep, outputs=names, passed=True)
    info = m.end_spilled("c1", "closed")
    assert info["confirmed"] and info["spilled"] == digest.NAMED_MAX == 24
    rows = rows_of(cs, "c1")
    assert len(rows) == 24 and all(r["tool"] == "wb_spill" for r in rows)
    assert not any(r["target"].endswith("/v0_0") for r in rows)  # the oldest names were the ones cut


def test_spill_cuts_a_huge_value_at_the_spill_cap(made, cs):
    m, c = _live(made, cs)
    rep = run(c, "big = 'a' * 200_000")
    assert m.end_spilled("c1", "closed")["confirmed"]
    row = cs.get_tool_result(manager_mod.spill_id(rep["incarnation"], "big"), wait_s=0.0)
    assert row is not None and len(row["content"]) <= manager_mod.SPILL_VALUE_CHARS + 80
    assert "[spill cut: first 32000 of 200000 chars]" in row["content"] and row["chars"] <= cs.TOOL_RESULT_MAX_CHARS
    out = manager_mod.expand(digest.make_ref(rep["incarnation"], "big"), manager=m)
    assert out["success"] and len(out["content"]) == manager_mod.EXPAND_PAGE_CHARS and out["next_offset"] == 6000


def test_spill_obeys_the_per_conversation_row_cap(made, cs, monkeypatch):
    monkeypatch.setattr(cs, "TOOL_RESULTS_PER_CONVERSATION", 3)
    m, c = _live(made, cs)
    run(c, "\n".join(f"n{i} = {i}" for i in range(6)))
    assert m.end_spilled("c1", "closed")["spilled"] == 6
    rows = rows_of(cs, "c1")
    assert len(rows) == 3                                       # the store evicted the oldest three
    assert cs.tool_result_stats()["evicted"] >= 3


# --- close / fresh finish the spill before they say done ----------------------------
def test_end_spilled_waits_for_the_writes_and_a_timeout_is_counted(made, cs):
    m, c = _live(made, cs)
    rep = run(c, "x = 1")
    gate, started = threading.Event(), threading.Event()
    cs._tr_lane().submit("gate", lambda: (started.set(), gate.wait(10.0)))   # park the lane
    assert started.wait(5.0)
    t0 = time.monotonic()
    info = m.end_spilled("c1", "closed", wait_s=0.4)             # the write cannot finish: bounded, not raised
    assert info["spilled"] == 1 and info["confirmed"] is False
    assert 0.3 <= time.monotonic() - t0 < 3.0 and m.stats()["spill_unconfirmed"] == 1
    gate.set()
    drain(cs)
    assert cs.get_tool_result(manager_mod.spill_id(rep["incarnation"], "x"), wait_s=0.0) is not None
    # second phase: the lane frees up while end_spilled waits -> it returns only after the write
    m2, c2 = _live(made, cs, conv="c2")
    rep2 = run(c2, "y = 2")
    gate2, started2 = threading.Event(), threading.Event()
    cs._tr_lane().submit("gate", lambda: (started2.set(), gate2.wait(10.0)))
    assert started2.wait(5.0)
    threading.Timer(0.5, gate2.set).start()
    t0 = time.monotonic()
    info2 = m2.end_spilled("c2", "fresh", wait_s=8.0)
    assert info2["confirmed"] is True and time.monotonic() - t0 >= 0.4
    assert cs.get_tool_result(manager_mod.spill_id(rep2["incarnation"], "y"), wait_s=0.0) is not None


# --- the bridge: fresh, close, the code row -----------------------------------------
@pytest.fixture
def call(made, cs, monkeypatch):
    """The REAL _run_python_tool; the process-wide manager is replaced by one with the store sink."""
    real_mgr = importlib.import_module("backend.agent.workbench.manager")
    wd = made.workdir()
    mgr = real_mgr.WorkbenchManager(sink=real_mgr.StoreSink())
    monkeypatch.setattr(real_mgr, "get_manager", lambda: mgr)
    br = SimpleNamespace(_active_conversation_id={})

    def go(params, conv="conv-wb"):
        br._active_conversation_id["s-life"] = conv
        return asyncio.run(bridge_mod._run_python_tool(br, params, "s-life", wd))

    go.mgr, go.real_mgr = mgr, real_mgr
    yield go
    mgr.shutdown()


def test_bridge_fresh_spills_then_runs_in_a_new_incarnation(call, cs):
    first = call({"code": "x = 41", "purpose": "set x"})
    assert first["success"] and "kept" not in first and "fresh" not in first
    second = call({"code": "print('x' in globals())", "purpose": "new space", "fresh": True})
    assert second["success"] and second["fresh"] is True and second["spilled"] == 1
    assert second["spill_confirmed"] is True and "saved" in second["text"]
    assert second["incarnation"] != first["incarnation"] and "False" in second["text"]
    out = call.real_mgr.expand(f"wb:{first['incarnation']}/x", manager=call.mgr)
    assert out["success"] and out["spilled"] and out["content"] == "41"


def test_bridge_close_runs_then_spills_and_ends(call, cs):
    r = call({"code": "y = 'later'", "purpose": "set y", "close": True})
    assert r["success"] and r["closed"] is True and r["spilled"] == 1 and r["spill_confirmed"] is True
    assert call.mgr.stats()["live"] == 0
    out = call.real_mgr.expand(f"wb:{r['incarnation']}/y", manager=call.mgr)
    assert out["success"] and out["content"] == "later"
    again = call({"code": "1 + 1", "purpose": "next"})           # the next call lazily starts a new one
    assert again["success"] and again["incarnation"] != r["incarnation"] and "closed" not in again


def test_bridge_records_one_code_row_per_execution_on_the_lane(call, cs, monkeypatch):
    threads = []
    real_write = cs._write_tool_result

    def spy(*a, **kw):
        threads.append(threading.current_thread())
        return real_write(*a, **kw)

    monkeypatch.setattr(cs, "_write_tool_result", spy)
    caller = threading.current_thread()
    call({"code": "a = 1", "purpose": "first run"})
    call({"code": "raise ValueError('boom')", "purpose": "second run"})
    call({"code": "b = a + 1", "purpose": "third run", "check": "b == 2"})
    rows = rows_of(cs, "conv-wb")
    assert [r["tool"] for r in rows] == ["run_python"] * 3
    assert [r["target"] for r in rows] == ["first run", "second run", "third run"]
    texts = [cs.get_tool_result(r["id"], wait_s=0.0)["content"] for r in rows]
    assert texts[0].startswith("# run_python | purpose: first run | ok | wall_ms: ") and texts[0].endswith("\na = 1")
    assert "error ValueError: boom" in texts[1].splitlines()[0] and texts[1].endswith("raise ValueError('boom')")
    assert texts[2].endswith("b = a + 1") and len(texts[0]) < cs.TOOL_RESULT_MIN_CHARS    # a short script is recorded
    assert len(threads) == 3 and all(t is not caller for t in threads)


def test_bridge_crash_leaves_the_code_row_and_a_gone_ref(call, cs):
    first = call({"code": "z = 5", "purpose": "set z"})
    crashed = call({"code": "import os\nos._exit(1)", "purpose": "die"})
    assert crashed["success"] is False and crashed["error_type"] == "WorkbenchCrashed"
    rows = rows_of(cs, "conv-wb")
    assert len(rows) == 2
    text = cs.get_tool_result(rows[1]["id"], wait_s=0.0)["content"]
    assert "WorkbenchCrashed" in text.splitlines()[0] and text.endswith("os._exit(1)")
    out = call.real_mgr.expand(f"wb:{first['incarnation']}/z", manager=call.mgr)
    assert out["success"] is False and out["case"] == "workbench_gone"


# --- the run_python spec ------------------------------------------------------------
def test_spec_names_fresh_and_close():
    spec = registry_mod.resolve_tool("run_python")
    assert {"code", "purpose", "timeout_s", "fresh", "close"} <= set(spec.parameters)
    for name in ("fresh", "close"):
        p = spec.parameters[name]
        assert p["type"] == "boolean" and p.get("optional") is True
    lines = spec.description.split(". ")
    assert any("fresh=true" in l and "new empty namespace" in l for l in lines)
    assert any("close=true" in l and "end the workbench" in l for l in lines)
