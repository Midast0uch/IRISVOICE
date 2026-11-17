"""CLM-11 Round 6 (2026-11-16): the Oracle, the browser and code mode in unison - the NODE side
(design.md "Round 6": C1 latch + budget + cap, C2 claim order, C3 entry rule, C4 handler half,
C6 screenshot strip, C7 needs_sight, C8 scratch workdir, the browser note).

The tests drive the REAL `AgentKernel._der_run_node` over a real worker with a stand-in router and
tool box (the shape of test_workbench_callbacks_contract.py Part 2); a script's `tools.browser_*()`
callbacks reach the box. The node module (WB_NODE_FILE) can be pointed at a deliberately broken
copy for the failure demonstrations. `browser_next_shadow.record_browser_next` is replaced by a
recorder (the `scope=` / `via=` parameters land with the shadow module's own builder)."""
import asyncio
import importlib
import importlib.util
import json
import os
import sys
import threading
import types
from types import SimpleNamespace

import pytest

from backend.tests.contract import _wb_common as common

client_mod = common.mod("client")

OBS = ("Page: \"Shop\" - https://example.com/shop\nText: Widget 19.99\n"
       "Elements (pass the number as element_id to browser_act):\n"
       "[1] Buy now\n[2] Next page\n[3] Back\n")


def _node_module():
    path = os.environ.get("WB_NODE_FILE")
    if not path:
        return importlib.import_module("backend.agent.kernel.der.node")
    spec = importlib.util.spec_from_file_location("_broken_wb_node", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _tool(name, req=(), opt=()):
    props = {k: {"type": "string"} for k in (*req, *opt)}
    return {"type": "function", "function": {"name": name, "description": name, "parameters": {
        "type": "object", "properties": props, "required": list(req)}}}


_BASE = [_tool("read_file", ("path",)), _tool("run_command", ("command",)),
         _tool("run_python", ("code",))]
_BROWSER = [_tool("browser_open", ("url",)), _tool("browser_observe"),
            _tool("browser_act", ("action",), ("element_id", "text")), _tool("browser_read"),
            _tool("browser_explore", ("url",))]


def _marks(n):
    return [{"id": i + 1, "role": "button", "name": f"m{i + 1}", "disabled": False,
             "box": [1, 2, 3, 4], "in_view": True, "selector": "#x"} for i in range(n)]


def _call(i, name, args):
    return {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def _run_call(i, code):
    return _call(i, "run_python", {"code": code, "purpose": f"step {i}"})


@pytest.fixture
def bnode(monkeypatch):
    """A stub kernel whose REAL _der_run_node runs a BROWSER code node over a real worker."""
    from backend.agent import tool_bridge
    from backend.agent.agent_kernel import AgentKernel
    from backend.agent.workbench import manager

    from backend import capabilities

    monkeypatch.setenv("IRIS_WORKBENCH", "1")
    # the persisted launcher mode must not decide these tests: developer unless a test says personal
    monkeypatch.setattr(capabilities.CapabilitySet, "get_mode", classmethod(lambda cls: "developer"))
    workdir = common.make_workdir()
    c = client_mod.WorkbenchClient(common.PYTHON, workdir)
    c.start()
    seeded = []

    def _workbench_for(conv, cwd):
        seeded.append(cwd)
        return c

    monkeypatch.setattr(manager, "get_manager", lambda: SimpleNamespace(
        workbench_for=_workbench_for, touch=lambda conv: None))

    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = "conv-wb-br"
    k._tool_bridge = None
    k._der_turn_id = "turn-1"
    k._der_turn_active = True
    k._der_stop_requested = False
    k._der_card_hold = {"lock": threading.Lock(), "calls": 0, "released": False,
                        "turn": "turn-1", "queue": None, "plan": None}
    br = SimpleNamespace(_active_conversation_id={"sess": "conv-wb-br"})
    st = SimpleNamespace(
        gen_calls=[], gen_kinds=[], dispatched=[], systems=[], scripts=[], menu_calls=[],
        marks_n=4, seeded=seeded, events=[], tools=_BASE + _BROWSER, handlers=[],
        browser_rows=[], workdir=workdir)

    class _Router:
        last_usage = None

        def generate(self, role, messages, **kw):
            st.gen_calls.append(role)
            st.gen_kinds.append(kw.get("call_kind"))
            st.events.append("generate")
            st.systems.append(json.dumps(messages[0]))
            if kw.get("call_kind") == "code_node":
                n = sum(1 for x in st.gen_kinds if x == "code_node")
                if n <= len(st.scripts):
                    return "", "", [_run_call(n, st.scripts[n - 1])]
                return "Done.\nSTATUS: done", "", []
            n = sum(1 for x in st.gen_kinds if x != "code_node")
            if n <= len(st.menu_calls):
                name, args = st.menu_calls[n - 1]
                return "", "", [_call(100 + n, name, args)]
            return "Done.\nSTATUS: done", "", []

        def resolve(self, role):
            return SimpleNamespace(id="same-model")

    class _Box:
        def dispatch(self, decision, **kw):
            name = decision.tool
            st.dispatched.append(name)
            st.events.append(f"dispatch:{name}")
            if name == "run_python":
                raw = asyncio.run(tool_bridge._run_python_tool(br, decision.params, "sess", "."))
            elif name in ("browser_observe", "browser_act", "browser_open"):
                raw = {"success": True, "content": ("Clicked.\n" if name == "browser_act" else "") + OBS,
                       "url": "https://example.com/shop", "title": "Shop", "trust": "untrusted",
                       "marks": _marks(st.marks_n), "marks_seq": 1,
                       "marked_screenshot": {"mime": "image/jpeg", "b64": "A" * 400}}
            elif name == "browser_read":
                raw = {"success": True, "content": "Widget 19.99", "trust": "untrusted"}
            else:
                raw = {"success": True, "content": f"{name} ok"}
            return SimpleNamespace(result=raw, error="")

        def record_shadow_tool_choice(self, **kw):
            pass

        def record_tool_call(self, *a, **kw):
            pass

    k._router = _Router()
    k._get_tool_box = lambda: _Box()
    k._get_openai_tools = lambda: st.tools
    k._accrue_tokens = lambda *a, **kw: None
    k._der_tool_deadline = lambda name: 60.0
    k._format_tool_result_for_step = lambda raw, name: json.dumps(raw, default=str)[:400]
    mod = _node_module()
    k._der_run_node = types.MethodType(mod.DerNodeMixin._der_run_node, k)

    # the handler the node registers, and the order of claim / release events
    real_set = tool_bridge.set_workbench_dispatch

    def _set(conv, handler, node=""):
        st.handlers.append(handler)
        return real_set(conv, handler, node)

    monkeypatch.setattr(tool_bridge, "set_workbench_dispatch", _set)
    real_claim, real_release = mod._der_claim, mod._der_release

    def _claim(self, claim, item):
        st.events.append(f"claim:{claim}")
        return real_claim(self, claim, item)

    def _release(self, claim):
        h = st.handlers[-1] if st.handlers else None
        st.events.append(f"release:{claim}:closed={bool(h is not None and getattr(h, 'closed', False))}")
        return real_release(self, claim)

    monkeypatch.setattr(mod, "_der_claim", _claim)
    monkeypatch.setattr(mod, "_der_release", _release)

    from backend.agent import browser_next_shadow as bn

    def _record(**kw):
        st.browser_rows.append(kw)
        return True

    monkeypatch.setattr(bn, "record_browser_next", _record, raising=False)

    item = SimpleNamespace(
        description="Read the widget price from https://example.com/shop", objective_anchor="",
        expected_output="the price", parent_description="", review_feedback="",
        step_id="s1", check="price", outputs=["price: str"], tools=["browser_observe", "browser_act"],
        node_calls=[], node_call_log=[])
    st.item, st.mod = item, mod
    k.st = st
    try:
        yield k
    finally:
        c.close()
        common.drop(workdir)


def _run(k):
    return k._der_run_node(k.st.item, "sess", "turn-1", [])


# --- C3: the entry rule --------------------------------------------------------------------
@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv("IRIS_WORKBENCH", "1")
    from backend.agent.workbench import client

    monkeypatch.setattr(client, "resolve_interpreter", lambda workdir: "python")


def _brief(tools, outputs=("price: str",), check="price"):
    return SimpleNamespace(outputs=list(outputs), check=check, tools=list(tools))


_DEV_BROWSER = _BASE + _BROWSER
_GOAL = "Read the widget price from https://example.com/shop"


def test_c3_a_briefed_step_naming_a_browser_tool_enters_code_mode(flag_on):
    node = _node_module()
    assert node._wb_code_mode(_GOAL, _DEV_BROWSER, ".", _brief(["browser_observe"])) is True
    assert node._wb_code_mode(_GOAL, _DEV_BROWSER, ".", _brief(["browser_read"])) is True


def test_c3_the_external_exclusion_is_lifted_only_for_such_a_step(flag_on):
    node = _node_module()
    # no brief / a brief that names no browser tool / no check / no outputs: today's refusal
    assert node._wb_code_mode(_GOAL, _DEV_BROWSER, ".") is False
    assert node._wb_code_mode(_GOAL, _DEV_BROWSER, ".", _brief(["read_file"])) is False
    assert node._wb_code_mode(_GOAL, _DEV_BROWSER, ".", _brief(["browser_act"], check="")) is False
    assert node._wb_code_mode(_GOAL, _DEV_BROWSER, ".", _brief(["browser_act"], outputs=())) is False


def test_c3_a_vision_step_and_a_write_step_and_an_after_change_step_still_refuse(flag_on):
    node = _node_module()
    b = _brief(["browser_observe"])
    assert node._wb_code_mode("Take a screenshot of the page and describe what the screen shows",
                              _DEV_BROWSER, ".", b) is False
    assert node._wb_code_mode("Create price.txt with the price from https://example.com/shop",
                              _DEV_BROWSER, ".", b) is False
    after = _brief(["browser_observe"])
    after.wb_after_change = True
    assert node._wb_code_mode(_GOAL, _DEV_BROWSER, ".", after) is False


def test_c3_the_web_toggle_holds_a_step_whose_browser_tool_is_not_offered_stays_out(flag_on):
    node = _node_module()
    # web toggle OFF: the base tool list holds no browser tool, so the brief cannot lift anything
    assert node._wb_code_mode(_GOAL, _BASE, ".", _brief(["browser_observe", "browser_act"])) is False


# --- C1: the latch, the budget, the cap ----------------------------------------------------
def test_c1_after_the_node_returns_the_handler_dispatches_nothing(bnode):
    k = bnode
    k.st.scripts += ["r = tools.browser_observe()\nprice = '19.99'"]
    _run(k)
    h = k.st.handlers[-1]
    assert getattr(h, "closed", False) is True
    before = list(k.st.dispatched)
    assert h("browser_observe", {}) == (False, None, "the step ended")
    assert h("read_file", {"path": "a"}) == (False, None, "the step ended")
    assert k.st.dispatched == before


def test_c1_the_latch_is_set_before_the_claims_are_released(bnode):
    k = bnode
    k.st.scripts += ["price = '19.99'"]
    _run(k)
    released = [e for e in k.st.events if e.startswith("release:")]
    assert released and all(e.endswith("closed=True") for e in released), released


def test_c1_the_browser_wall_budget_ends_the_handler_after_node_budget_minus_20_s():
    node = _node_module()
    seen = []
    h = node._wb_callback_handler(lambda t, a: seen.append(t) or {"success": True}, {"browser_observe"},
                                  [], lambda: None, browser=True, wall_s=0.0)
    assert h("browser_observe", {}) == (False, None, "the step ended")
    assert seen == []


def test_c1_at_most_12_browser_callbacks_run_per_run_python_and_the_general_24_stays(bnode):
    k = bnode
    k.st.scripts += ["n = 0\nfor i in range(14):\n    tools.browser_observe()\n    n += 1\n"]
    _run(k)
    assert k.st.dispatched.count("browser_observe") == 12
    out = k.st.item.node_call_log[0]["out"]
    assert "ToolError" in out and "12" in out
    from backend.agent.workbench import worker

    assert worker.CALLBACK_BUDGET == 24


def test_c1_the_browser_count_starts_again_with_the_next_run_python(bnode):
    k = bnode
    k.st.scripts += ["for i in range(12):\n    tools.browser_observe()\n",
                     "for i in range(12):\n    tools.browser_observe()\nprice = '19.99'"]
    _run(k)
    assert k.st.dispatched.count("browser_observe") == 24


# --- C2: the claim order -------------------------------------------------------------------
def test_c2_a_browser_code_node_takes_browser_then_workbench_before_its_first_model_call(bnode):
    k = bnode
    k.st.scripts += ["price = '19.99'"]
    _run(k)
    ev = k.st.events
    assert ev.index("claim:browser") < ev.index("claim:workbench") < ev.index("generate")


def test_c2_a_non_browser_code_node_does_not_take_the_browser_claim(bnode):
    k = bnode
    k.st.item.tools = ["read_file"]
    k.st.item.description = "Compute the total of the numbers"
    k.st.scripts += ["price = '19.99'"]
    _run(k)
    assert "claim:browser" not in k.st.events and "claim:workbench" in k.st.events


def test_c2_a_non_browser_code_node_refuses_browser_tools(bnode):
    k = bnode
    k.st.item.tools = ["read_file"]
    k.st.item.description = "Compute the total of the numbers"
    k.st.scripts += ["tools.browser_observe()\nafter = 1"]
    _run(k)
    assert "browser_observe" not in k.st.dispatched
    assert "not available in this step" in k.st.item.node_call_log[0]["out"]


# --- C3 (menu intersection): _wb_allowed ----------------------------------------------------
def test_c3_a_tool_the_node_was_not_offered_is_not_available_to_the_script(bnode):
    k = bnode
    k.st.tools = [t for t in _BASE + _BROWSER if t["function"]["name"] != "browser_act"]
    k.st.scripts += ["tools.browser_act(action='click', element_id=1)\nafter = 1"]
    _run(k)
    assert "browser_act" not in k.st.dispatched
    assert "not available" in k.st.item.node_call_log[0]["out"]


def test_c3_browser_read_is_available_to_a_browser_code_node_only(bnode):
    k = bnode
    k.st.scripts += ["t = tools.browser_read()\nprice = t['content']"]
    _run(k)
    assert "browser_read" in k.st.dispatched


def test_c3_browser_read_is_refused_to_a_non_browser_code_node(bnode):
    k = bnode
    k.st.item.tools = ["read_file"]
    k.st.item.description = "Compute the total of the numbers"
    k.st.scripts += ["tools.browser_read()\nafter = 1"]
    _run(k)
    assert "browser_read" not in k.st.dispatched


# --- C6: no picture reaches the worker ------------------------------------------------------
def test_c6_the_handler_strips_the_screenshot_and_trims_marks_but_the_node_keeps_the_full_result():
    node = _node_module()
    raw = {"success": True, "content": OBS, "marks": _marks(3),
           "marked_screenshot": {"mime": "image/jpeg", "b64": "A" * 400}, "other_b64": "B" * 50}
    calls = []
    h = node._wb_callback_handler(lambda t, a: raw, {"browser_observe"}, calls, lambda: None, browser=True)
    ok, value, err = h("browser_observe", {})
    assert ok and err is None
    assert "marked_screenshot" not in value and "b64" not in json.dumps(value)
    assert all(set(m) == {"id", "role", "name", "disabled"} for m in value["marks"])
    assert len(value["marks"]) == 3 and value["content"] == OBS
    # the node's own bookkeeping saw the full result: the original dict is untouched
    assert "marked_screenshot" in raw and "box" in raw["marks"][0]


def test_c6_a_script_never_receives_a_screenshot_through_a_real_node(bnode):
    k = bnode
    k.st.scripts += ["r = tools.browser_observe()\nprice = str(sorted(r)) + str('b64' in str(r))"]
    _run(k)
    out = k.st.item.node_call_log[0]["out"]
    assert "marked_screenshot" not in out and "True" not in out.split("price")[-1]
    # the script's observation reached the node's call log as a browser call
    assert k.st.item.node_call_log[1]["tool"] == "browser_observe"


# --- C7: needs_sight ------------------------------------------------------------------------
def test_c7_a_script_that_raises_needs_sight_reruns_once_on_the_menu_path_holding_the_claim(bnode):
    k = bnode
    k.st.scripts += ["tools.browser_observe()\nraise ToolError('needs sight')"]
    k.st.menu_calls += [("browser_observe", {})]
    before = k.st.mod._wb_stats["fallback"]
    _run(k)
    assert k.st.mod._wb_stats["fallback"] == before + 1
    assert "generate" in k.st.events and k.st.gen_kinds.count(None) == 0
    menu_gens = [x for x in k.st.gen_kinds if x != "code_node"]
    assert len(menu_gens) == 2                       # the menu run: one call, then its answer
    assert k.st.dispatched.count("browser_observe") == 2   # the script's, then the menu path's
    # the claim was held across the menu run: it is released only after the last generate
    last_gen = max(i for i, e in enumerate(k.st.events) if e == "generate")
    assert all(i > last_gen for i, e in enumerate(k.st.events) if e.startswith("release:browser"))


def test_c7_an_observation_with_two_or_fewer_marks_and_a_failed_check_reruns_on_the_menu_path(bnode):
    k = bnode
    k.st.marks_n = 2
    k.st.scripts += ["tools.browser_observe()\nx = 1"]       # `price` never set: the check fails
    k.st.menu_calls += [("browser_observe", {})]
    before = k.st.mod._wb_stats["fallback"]
    _run(k)
    assert k.st.mod._wb_stats["fallback"] == before + 1


def test_c7_enough_marks_and_a_failed_check_is_not_a_sight_fallback(bnode):
    k = bnode
    k.st.marks_n = 6
    k.st.scripts += ["tools.browser_observe()\nx = 1"]
    before = k.st.mod._wb_stats["fallback"]
    _run(k)
    assert k.st.mod._wb_stats["fallback"] == before


def test_c7_needs_fallback_names_the_reason_and_a_passed_check_never_falls_back():
    node = _node_module()
    res = SimpleNamespace(success=False, check_passed=False, calls=[
        {"tool": "run_python", "ok": False, "out": "ToolError: needs sight"}])
    assert node._wb_needs_fallback(res) == "needs_sight"
    res = SimpleNamespace(success=True, check_passed=True, calls=[
        {"tool": "run_python", "ok": False, "out": "ToolError: needs sight"}])
    assert node._wb_needs_fallback(res) == ""
    res = SimpleNamespace(success=False, check_passed=False, calls=[
        {"tool": "run_python", "ok": True, "out": "x"}])
    assert node._wb_needs_fallback(res, sight_poor=True) == "needs_sight"
    assert node._wb_needs_fallback(res) == ""


# --- C4 (handler half): one browser_next row per script act ---------------------------------
def test_c4_each_script_browser_act_with_an_element_id_records_one_browser_next_row(bnode):
    k = bnode
    k.st.scripts += ["tools.browser_observe()\n"
                     "tools.browser_act(action='click', element_id=1)\n"
                     "tools.browser_act(action='click', element_id=2)\n"
                     "tools.browser_act(action='scroll')\n"
                     "price = '19.99'"]
    _run(k)
    rows = k.st.browser_rows
    assert [r["element_id"] for r in rows] == [1, 2]            # none for the act without an id
    for r in rows:
        assert r["via"] == "run_python"
        assert r["scope"].get("turn_id") == "turn-1" and r["scope"].get("step_id") == "s1"
        assert "Elements (pass the number as element_id to browser_act):" in r["page_text"]
        assert r["action"] == "click" and r["brain_ok"] is True
        assert r["done_when"] == "the price" and r["goal"].startswith("Read the widget price")
    assert "browser_observe" in rows[1]["calls_this_step"]


def test_c4_a_script_without_a_browser_act_records_no_row(bnode):
    k = bnode
    k.st.scripts += ["tools.browser_observe()\nprice = '19.99'"]
    _run(k)
    assert k.st.browser_rows == []


# --- C8: the scratch workdir ------------------------------------------------------------------
def _personal(monkeypatch, scratch):
    from backend import capabilities
    from backend.agent.workbench import manager

    monkeypatch.setattr(capabilities.CapabilitySet, "get_mode", classmethod(lambda cls: "personal"))
    monkeypatch.setattr(manager, "scratch_workdir", lambda conv: scratch)


def test_c8_a_personal_conversation_with_no_folder_works_in_its_scratch_folder(bnode, monkeypatch):
    k = bnode
    scratch = common.make_workdir()
    try:
        _personal(monkeypatch, scratch)
        k._tool_bridge = SimpleNamespace(_session_workdirs={},
                                         set_session_workdir=lambda s, w: k._tool_bridge._session_workdirs
                                         .__setitem__(s, w))
        k.st.scripts += ["price = '19.99'"]
        _run(k)
        assert k.st.seeded and k.st.seeded[0] == scratch
        # the binding is undone at the node's end: the next turn resolves its own folder
        assert "sess" not in k._tool_bridge._session_workdirs
    finally:
        common.drop(scratch)


def test_c8_a_bound_folder_is_kept_in_personal_mode(bnode, monkeypatch):
    k = bnode
    scratch = common.make_workdir()
    try:
        _personal(monkeypatch, scratch)
        k._tool_bridge = SimpleNamespace(_session_workdirs={"sess": k.st.workdir},
                                         set_session_workdir=lambda s, w: None)
        k.st.scripts += ["price = '19.99'"]
        _run(k)
        assert k.st.seeded[0] == k.st.workdir
    finally:
        common.drop(scratch)


# --- the browser note -------------------------------------------------------------------------
def test_the_browser_note_is_short_and_only_a_browser_code_node_has_it(bnode):
    node = _node_module()
    note = node._WB_BROWSER_NOTE
    assert 0 < len(note) <= 400
    for word in ("marks", "needs sight"):
        assert word in note
    k = bnode
    k.st.scripts += ["price = '19.99'"]
    _run(k)
    assert "needs sight" in k.st.systems[0]
    k.st.systems.clear()
    k.st.gen_kinds.clear()
    k.st.item.tools = ["read_file"]
    k.st.item.description = "Compute the total of the numbers"
    k.st.scripts.clear()
    k.st.scripts += ["price = '19.99'"]
    _run(k)
    assert "needs sight" not in k.st.systems[0]


def test_the_browser_note_names_browser_reads_result_fields():
    """2026-11-17 smoke run (d03): the script spent 7 runs guessing browser_read's keys and took
    the digest's printout cut for a cut page. The note names the fields and says so."""
    note = _node_module()._WB_BROWSER_NOTE
    assert "browser_read() -> dict: text" in note and "links" in note
    assert "printed output is cut, the page is not" in note
