"""CLM-11 Round 6 (2026-11-17): the Oracle, the browser and code mode in unison - BEHAVIOR.

design.md "Round 6", Tests: the REAL `AgentKernel._der_run_node` + a REAL Workbench worker + a
FAKE browser box (no network): browser_open / browser_read / browser_observe / browser_act answer
canned pages that carry a marked_screenshot b64 and marks. A stub router scripts the tool model's
replies (a script per code_node call, a tool call per menu call). Each test drives a full node:
claims -> model call -> run_python -> callbacks through the node's dispatch -> check -> manifest
-> the evidence the synthesis reads.

Every wait is bounded. Workdirs live under `_wb_common.WB_WORK` (never in the test tree). The
browser_next rows go through the REAL `record_browser_next` on its real lane into a sink.

Run (one file, never the suite):
    .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider backend/tests/behavioral/test_workbench_browser_behavior.py
"""
import asyncio
import json
import os
import threading
import time
import types
from types import SimpleNamespace

import pytest

from backend.tests.contract import _wb_common as common

client_mod = common.mod("client")

SENTINEL = "B64SENTINEL" * 30          # the picture a vision-live result carries
OBS_TAIL = ("Elements (pass the number as element_id to browser_act):\n"
            "[1] Buy now\n[2] Next page\n[3] Back\n")
URL_OF = {"a": "https://shop.test/a", "b": "https://shop.test/b", "c": "https://shop.test/c"}
PRICE_OF = {"a": 19.99, "b": 24.5, "c": 7.25}
GOAL = "Read the widget price from https://shop.test/a"


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


def _wait(pred, bound_s, step=0.05):
    end = time.monotonic() + bound_s
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return pred()


class Rig:
    """One worker + one conversation's page + the event trail; `kernel()` builds a stand-in
    kernel whose REAL _der_run_node runs against them."""

    def __init__(self, monkeypatch, conv="conv-wb-bb", tools=None):
        from backend import capabilities
        from backend.agent import tool_bridge
        from backend.agent.workbench import manager
        import backend.agent.kernel.der.node as mod

        monkeypatch.setenv("IRIS_WORKBENCH", "1")
        # the persisted launcher mode must not decide these tests
        monkeypatch.setattr(capabilities.CapabilitySet, "get_mode", classmethod(lambda cls: "developer"))
        self.mod, self.tool_bridge, self.conv = mod, tool_bridge, conv
        self.workdir = common.make_workdir()
        self.client = client_mod.WorkbenchClient(common.PYTHON, self.workdir)
        self.client.start()
        c = self.client
        monkeypatch.setattr(manager, "get_manager", lambda: SimpleNamespace(
            workbench_for=lambda _conv, _cwd: c, touch=lambda _conv: None))
        self.tools = tools if tools is not None else _BASE + _BROWSER
        self.events = []             # (kind, what, step) - list.append is atomic
        self.dispatched = []         # (tool, params, step)
        self.handlers = []
        self.marks_n = 3
        self.page = None             # the url the conversation's ONE page shows
        self.on_dispatch = None      # hook(name, params, step) run before the box answers
        self.detach_run_python_s = None
        self.bg = []                 # (thread, result dict) of detached run_python calls
        self.threads = []

        real_set = tool_bridge.set_workbench_dispatch

        def _set(conv_, handler, node=""):
            self.handlers.append(handler)
            return real_set(conv_, handler, node)

        monkeypatch.setattr(tool_bridge, "set_workbench_dispatch", _set)
        real_claim, real_release = mod._der_claim, mod._der_release

        def _claim(kself, claim, item):
            ok = real_claim(kself, claim, item)
            self.events.append(("claim_got" if ok else "claim_failed", claim, item.step_id))
            return ok

        def _release(kself, claim):
            self.events.append(("release", claim, kself.step_id_tag))
            return real_release(kself, claim)

        monkeypatch.setattr(mod, "_der_claim", _claim)
        monkeypatch.setattr(mod, "_der_release", _release)

    # ---- the fake browser box ---------------------------------------------------------------
    def _browser_result(self, name, params):
        if name == "browser_open":
            self.page = params.get("url")
        letter = next((k for k, u in URL_OF.items() if u == self.page), "x")
        head = f'Page: "Shop {letter}" - {self.page}\nText: Widget PRICE={PRICE_OF.get(letter, 0)}\n'
        shown = OBS_TAIL if self.marks_n >= 3 else "Elements (pass the number as element_id to browser_act):\n[1] Back\n"
        return {"success": True, "content": ("Clicked.\n" if name == "browser_act" else "") + head + shown,
                "url": self.page, "title": f"Shop {letter}", "trust": "untrusted",
                "marks": _marks(self.marks_n), "marks_seq": 1,
                "marked_screenshot": {"mime": "image/jpeg", "b64": SENTINEL}}

    def kernel(self, step_id, scripts=(), menu_calls=(), item=None, personal_tools=None):
        from backend.agent.agent_kernel import AgentKernel

        rig, mod, tool_bridge = self, self.mod, self.tool_bridge
        k = AgentKernel.__new__(AgentKernel)
        k.conversation_id = self.conv
        k.step_id_tag = step_id
        k._tool_bridge = None
        k._der_turn_id = "turn-1"
        k._der_turn_active = True
        k._der_stop_requested = False
        k._der_card_hold = {"lock": threading.Lock(), "calls": 0, "released": False,
                            "turn": "turn-1", "queue": None, "plan": None}
        br = SimpleNamespace(_active_conversation_id={"sess": self.conv})
        st = SimpleNamespace(scripts=list(scripts), menu_calls=list(menu_calls), gen_kinds=[],
                             gen_tools=[], menu_claim_locked=[], systems=[], step=step_id,
                             done=threading.Event(), out=None, err=None)

        class _Router:
            last_usage = None

            def generate(self, role, messages, **kw):
                kind = kw.get("call_kind")
                st.gen_kinds.append(kind)
                rig.events.append(("generate", kind, step_id))
                st.systems.append(json.dumps(messages[0]))
                if kind == "code_node":
                    n = sum(1 for x in st.gen_kinds if x == "code_node")
                    if n <= len(st.scripts):
                        return "", "", [_run_call(n, st.scripts[n - 1])]
                    return "Done.\nSTATUS: done", "", []
                st.gen_tools.append([t["function"]["name"] for t in (kw.get("tools") or [])])
                st.menu_claim_locked.append(mod._der_claim_lock(k, "browser").locked())
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
                rig.dispatched.append((name, dict(decision.params or {}), step_id))
                rig.events.append(("dispatch", name, step_id))
                if name == "run_python":
                    return self._run_python(decision)
                if rig.on_dispatch:
                    rig.on_dispatch(name, decision.params, step_id)
                if name in ("browser_open", "browser_observe", "browser_act", "browser_read"):
                    raw = rig._browser_result(name, decision.params or {})
                    if name == "browser_read":
                        raw = dict(raw, content=raw["content"].split("Elements")[0])
                else:
                    raw = {"success": True, "content": f"{name} ok"}
                return SimpleNamespace(result=raw, error="")

            def _run_python(self, decision):
                def _go(out):
                    out["raw"] = asyncio.run(tool_bridge._run_python_tool(br, decision.params, "sess", "."))

                if rig.detach_run_python_s is None:
                    out = {}
                    _go(out)
                    return SimpleNamespace(result=out["raw"], error="")
                # a box whose deadline ends the call while the worker's script still runs
                out = {}
                th = threading.Thread(target=_go, args=(out,), daemon=True)
                th.start()
                rig.bg.append((th, out))
                th.join(rig.detach_run_python_s)
                if th.is_alive():
                    return SimpleNamespace(result={"success": False, "error": "timed out", "error_type": "timeout"},
                                           error="")
                return SimpleNamespace(result=out["raw"], error="")

            def record_shadow_tool_choice(self, **kw):
                pass

            def record_tool_call(self, *a, **kw):
                pass

        k._router = _Router()
        k._get_tool_box = lambda: _Box()
        k._get_openai_tools = lambda: rig.tools
        k._accrue_tokens = lambda *a, **kw: None
        k._der_tool_deadline = lambda name: 60.0
        k._format_tool_result_for_step = lambda raw, name: json.dumps(raw, default=str)[:400]
        k._der_run_node = types.MethodType(mod.DerNodeMixin._der_run_node, k)
        k.st = st
        k.item = item or self.browser_item(step_id)
        return k

    @staticmethod
    def browser_item(step_id="s1", **kw):
        d = dict(description=GOAL, objective_anchor="", expected_output="the price", parent_description="",
                 review_feedback="", step_id=step_id, check="price", outputs=["price: str"],
                 tools=["browser_open", "browser_read"], node_calls=[], node_call_log=[])
        d.update(kw)
        return SimpleNamespace(**d)

    @staticmethod
    def file_item(step_id="f1"):
        return SimpleNamespace(
            description="Compute the total of the numbers 1 2 3", objective_anchor="",
            expected_output="the total", parent_description="", review_feedback="", step_id=step_id,
            check="total == 6", outputs=["total: int"], tools=["read_file"], node_calls=[],
            node_call_log=[])

    def run(self, k):
        return k._der_run_node(k.item, "sess", "turn-1", [])

    def start(self, k):
        def _t():
            try:
                k.st.out = self.run(k)
            except BaseException as exc:  # noqa: BLE001 - reported by the test
                k.st.err = exc
            finally:
                k.st.done.set()

        th = threading.Thread(target=_t, daemon=True)
        self.threads.append(th)
        th.start()
        return th

    def inspect(self, expr):
        return self.client.inspect(expr)

    def close(self):
        for th, _out in self.bg:
            th.join(15)
        for th in self.threads:
            th.join(15)
        self.client.close()
        common.drop(self.workdir)


@pytest.fixture
def rig(monkeypatch):
    r = Rig(monkeypatch)
    try:
        yield r
    finally:
        r.close()


# --- 1. the full loop ---------------------------------------------------------------------------
LOOP_SCRIPT = """
prices = {}
seen = None
for name, url in [('a', 'https://shop.test/a'), ('b', 'https://shop.test/b'), ('c', 'https://shop.test/c')]:
    opened = tools.browser_open(url=url)
    seen = opened
    page = tools.browser_read()
    prices[name] = float(page['content'].split('PRICE=')[1].split()[0])
"""


def test_1_one_script_loops_over_three_pages_and_the_node_closes_with_one_model_call(rig):
    from backend.agent.agent_kernel import AgentKernel

    k = rig.kernel("s1", scripts=[LOOP_SCRIPT], item=Rig.browser_item(
        outputs=["prices: dict[str,float]"], check="len(prices) == 3",
        tools=["browser_open", "browser_read"]))
    text, ok = rig.run(k)
    assert ok, text
    # ONE model call: the script, then the check passes and the node closes (no wrap-up call)
    assert k.st.gen_kinds == ["code_node"], k.st.gen_kinds
    # the pages were visited by the script, in order, through the node's dispatch
    names = [(n, p.get("url")) for n, p, _s in rig.dispatched if n != "run_python"]
    assert names == [("browser_open", URL_OF["a"]), ("browser_read", None),
                     ("browser_open", URL_OF["b"]), ("browser_read", None),
                     ("browser_open", URL_OF["c"]), ("browser_read", None)]
    # the step result, as the synthesis reads it: all three prices and the check verdict
    k.item.result = text
    evidence = AgentKernel._der_node_record_evidence(k.item)
    for price in ("19.99", "24.5", "7.25"):
        assert price in evidence, evidence
    assert "check: passed" in evidence, evidence
    assert k.item.wb_check_passed is True
    # the picture never reached the worker: neither the sentinel nor the key is in its namespace
    ns = rig.inspect("repr((prices, sorted(seen), seen))")
    blob = json.dumps(ns, default=str)
    assert "B64SENTINEL" not in blob and "marked_screenshot" not in blob and "'box'" not in blob, blob
    # the task card counter: 1 run_python + 6 callbacks
    assert k._der_card_hold["calls"] == 7
    # claim order: browser then workbench BEFORE the first generate; both released AFTER the last
    ev = rig.events
    i_b, i_w = ev.index(("claim_got", "browser", "s1")), ev.index(("claim_got", "workbench", "s1"))
    i_gen = ev.index(("generate", "code_node", "s1"))
    assert i_b < i_w < i_gen
    last_dispatch = max(i for i, e in enumerate(ev) if e[0] in ("dispatch", "generate"))
    rel = {e[1]: i for i, e in enumerate(ev) if e[0] == "release"}
    assert set(rel) == {"browser", "workbench"} and min(rel.values()) > last_dispatch


# --- 2. one Oracle row per script click ---------------------------------------------------------
class _Engine:
    model_id = "stub"

    def decide(self, consumer_id, options, frame):
        from backend.agent.decision_engine import CandidateScore, DecisionScore

        return DecisionScore(
            consumer_id=consumer_id, chosen=options[0], confidence=0.8,
            distribution=tuple(CandidateScore(o, -0.1, 0.8 if o == options[0] else 0.1) for o in options),
            engine_latency_ms=1)


def test_2_one_browser_next_row_per_script_click_and_none_for_an_element_off_the_page(rig, monkeypatch):
    from backend.agent import browser_next_shadow as bn
    from backend.agent import decision_engine as de

    monkeypatch.setattr(de, "get_decision_engine", lambda *a, **kw: _Engine())
    rows = []
    bn.set_row_sink(rows.append)
    try:
        rig.page = URL_OF["a"]
        k = rig.kernel("s1", scripts=[
            "r = tools.browser_observe()\n"
            "tools.browser_act(action='click', element_id=1)\n"
            "tools.browser_act(action='click', element_id=2)\n"
            "try:\n    tools.browser_act(action='click', element_id=99)\nexcept ToolError:\n    pass\n"
            "tools.browser_act(action='scroll')\n"
            "price = '19.99'"])
        text, ok = rig.run(k)
        assert ok, text
        # the click on 99 and the scroll were still SENT to the page: only the ROW is skipped
        assert [p.get("element_id") for n, p, _s in rig.dispatched if n == "browser_act"] == [1, 2, 99, None]
        assert _wait(lambda: len(rows) >= 2, 10)
        time.sleep(0.7)              # a third row would land on the same lane within this window
    finally:
        bn.set_row_sink(None)
    assert len(rows) == 2, rows
    assert sorted(r["brain_choice"] for r in rows) == ["1", "2"]
    for r in rows:
        assert r["via"] == "run_python" and r["brain_ok"] is True and r["action"] == "click"
        assert r["turn_id"] == "turn-1" and r["step_id"] == "s1"
        assert r["consumer_id"] == "browser_next" and r["shadow"] is True


# --- 3. needs_sight -----------------------------------------------------------------------------
@pytest.mark.parametrize("how", ["tool_error", "poor_marks"])
def test_3_needs_sight_reruns_once_on_the_menu_path_on_the_same_page_holding_the_claim(rig, how):
    mod = rig.mod
    rig.page = URL_OF["a"]
    if how == "tool_error":
        script = "tools.browser_observe()\nraise ToolError('needs sight')"
    else:
        rig.marks_n = 2
        script = "tools.browser_observe()\nx = 1"          # `price` never set: the check fails
    k = rig.kernel("s1", scripts=[script], menu_calls=[("browser_observe", {})])
    before = mod._wb_stats["fallback"]
    text, _ok = rig.run(k)
    assert mod._wb_stats["fallback"] == before + 1                 # ONE re-run, no second
    menu_gens = [x for x in k.st.gen_kinds if x != "code_node"]
    assert len(menu_gens) == 2                                      # the menu run: a call, then its answer
    # the menu path is the tools menu: the browser tools are on it, run_python is not
    assert all("browser_observe" in t and "browser_act" in t for t in k.st.gen_tools), k.st.gen_tools
    assert all("run_python" not in t for t in k.st.gen_tools)
    # the node held the browser claim through the menu run and took it only once
    assert all(k.st.menu_claim_locked), k.st.menu_claim_locked
    assert [e for e in rig.events if e[:2] == ("claim_got", "browser")] == [("claim_got", "browser", "s1")]
    last_gen = max(i for i, e in enumerate(rig.events) if e[0] == "generate")
    assert all(i > last_gen for i, e in enumerate(rig.events) if e[:2] == ("release", "browser"))
    # the same page: no browser_open anywhere, both observations came from the page already open
    assert [n for n, _p, _s in rig.dispatched].count("browser_open") == 0
    assert [n for n, _p, _s in rig.dispatched].count("browser_observe") == 2
    # and the menu run is the LAST run_python-free stretch: no run_python after the first menu generate
    first_menu = next(i for i, e in enumerate(rig.events) if e[:2] == ("generate", None) or
                      (e[0] == "generate" and e[1] != "code_node"))
    assert not [e for e in rig.events[first_menu:] if e[:2] == ("dispatch", "run_python")]
    assert "STATUS" in text or text


# --- 4. parallel --------------------------------------------------------------------------------
def test_4a_a_menu_browser_node_and_a_file_code_node_run_in_parallel_each_with_its_own_claim(rig):
    release_menu = threading.Event()
    in_menu_dispatch = threading.Event()

    def _hook(name, params, step):
        if step == "m1" and name == "browser_observe":
            in_menu_dispatch.set()
            release_menu.wait(15)                   # the menu node sits in its page call

    rig.on_dispatch = _hook
    rig.page = URL_OF["a"]
    menu_item = Rig.browser_item("m1", check="", outputs=[], tools=[])
    km = rig.kernel("m1", menu_calls=[("browser_observe", {})], item=menu_item)
    kf = rig.kernel("f1", scripts=["total = 1 + 2 + 3"], item=Rig.file_item("f1"))
    rig.start(km)
    assert in_menu_dispatch.wait(10), "the menu browser node never reached its page call"
    rig.start(kf)
    # the file node finishes WHILE the menu node still holds the browser page
    assert kf.st.done.wait(20), "the file code node deadlocked behind the browser node"
    assert kf.st.err is None and kf.st.out[1] is True, (kf.st.err, kf.st.out)
    assert rig.mod._der_claim_lock(km, "browser").locked()
    assert not rig.mod._der_claim_lock(kf, "workbench").locked()
    release_menu.set()
    assert km.st.done.wait(20), "the menu browser node did not finish"
    assert km.st.err is None, km.st.err
    got = {}
    for kind, what, step in rig.events:
        if kind in ("claim_got", "release"):
            got.setdefault(step, set()).add(what)
    assert got == {"m1": {"browser"}, "f1": {"workbench"}}, got
    for lock in ("browser", "workbench"):
        assert not rig.mod._der_claim_lock(km, lock).locked()


def test_4b_two_browser_code_nodes_of_one_conversation_run_one_after_the_other(rig):
    rig.page = URL_OF["a"]
    in_a = threading.Event()

    def _hook(name, params, step):
        if step == "a1" and name == "browser_observe":
            in_a.set()

    rig.on_dispatch = _hook
    wait_go = ("tools.browser_observe()\nimport os, time\n"
               "for _ in range(300):\n    if os.path.exists('goA.txt'):\n        break\n    time.sleep(0.05)\n"
               "price = '19.99'")
    ka = rig.kernel("a1", scripts=[wait_go], item=Rig.browser_item("a1"))
    kb = rig.kernel("b1", scripts=["tools.browser_observe()\nprice = '24.5'"], item=Rig.browser_item("b1"))
    rig.start(ka)
    assert in_a.wait(15), "node A never reached its script"
    rig.start(kb)
    time.sleep(1.5)                                   # B must still be waiting for the claims
    assert not [e for e in rig.events if e[2] == "b1"], [e for e in rig.events if e[2] == "b1"]
    assert not kb.st.done.is_set()
    with open(os.path.join(rig.workdir, "goA.txt"), "w") as fh:
        fh.write("go")
    assert ka.st.done.wait(20) and kb.st.done.wait(20), "the two browser nodes did not both finish"
    assert ka.st.err is None and kb.st.err is None, (ka.st.err, kb.st.err)
    assert ka.st.out[1] is True and kb.st.out[1] is True
    ev = rig.events
    for claim in ("browser", "workbench"):
        assert ev.index(("release", claim, "a1")) < ev.index(("claim_got", claim, "b1")), (claim, ev)


# --- 5. a script that outlives its node ---------------------------------------------------------
_LATE_ACT = ("tools.browser_observe()\nimport os, time\n"
             "for _ in range(400):\n    if os.path.exists('go.txt'):\n        break\n    time.sleep(0.05)\n"
             "try:\n    tools.browser_act(action='click', element_id=1)\n    after = 'acted'\n"
             "except ToolError as e:\n    after = 'refused: ' + str(e)\n")


def _sink_rows(monkeypatch):
    from backend.agent import browser_next_shadow as bn
    from backend.agent import decision_engine as de

    monkeypatch.setattr(de, "get_decision_engine", lambda *a, **kw: _Engine())
    rows = []
    bn.set_row_sink(rows.append)
    return rows, bn


def test_5a_a_script_still_running_after_its_node_ended_dispatches_nothing(rig, monkeypatch):
    rows, bn = _sink_rows(monkeypatch)
    try:
        rig.page = URL_OF["a"]
        rig.detach_run_python_s = 2.0            # the box's deadline ends run_python; the script runs on
        k = rig.kernel("s1", scripts=[_LATE_ACT])
        t0 = time.monotonic()
        rig.run(k)
        assert time.monotonic() - t0 < 60
        h = rig.handlers[-1]
        assert h.closed is True                  # the node's finally latched it before it ended
        assert [n for n, _p, _s in rig.dispatched].count("browser_act") == 0
        # NOW the script wakes up and clicks
        with open(os.path.join(rig.workdir, "go.txt"), "w") as fh:
            fh.write("go")
        assert rig.bg, "run_python was never detached"
        th, out = rig.bg[0]
        th.join(30)
        assert not th.is_alive(), "the script never ended"
        after = json.dumps(rig.inspect("after"), default=str)
        assert "refused" in after and "acted" not in after, after
        assert [n for n, _p, _s in rig.dispatched].count("browser_act") == 0
        assert h("browser_act", {"action": "click", "element_id": 1}) == (False, None, "the step ended")
        time.sleep(0.7)
        assert rows == []
    finally:
        bn.set_row_sink(None)


def test_5b_a_script_past_the_browser_wall_budget_is_told_the_step_ended(rig, monkeypatch):
    rows, bn = _sink_rows(monkeypatch)
    try:
        # the node's budget (300 s) minus this margin = a 1.5 s browser wall budget
        monkeypatch.setattr(rig.mod, "_WB_BROWSER_MARGIN_S", 298.5)
        rig.page = URL_OF["a"]
        script = ("tools.browser_observe()\nimport time\ntime.sleep(2.5)\n"
                  "try:\n    tools.browser_act(action='click', element_id=1)\n    after = 'acted'\n"
                  "except ToolError as e:\n    after = 'refused: ' + str(e)\nprice = after")
        k = rig.kernel("s1", scripts=[script])
        rig.run(k)
        assert "refused: the step ended" in json.dumps(rig.inspect("after"), default=str)
        assert [n for n, _p, _s in rig.dispatched].count("browser_act") == 0
        assert [n for n, _p, _s in rig.dispatched].count("browser_observe") == 1
        time.sleep(0.7)
        assert rows == []
    finally:
        bn.set_row_sink(None)


# --- 6. the web toggle off ----------------------------------------------------------------------
def test_6a_with_the_web_toggle_off_a_briefed_browser_step_does_not_enter_code_mode(monkeypatch):
    r = Rig(monkeypatch, tools=list(_BASE))       # the toggle takes the browser tools out of the offer
    try:
        k = r.kernel("s1", scripts=["price = '19.99'"])
        before = r.mod._wb_stats["code_nodes"]
        r.run(k)
        assert r.mod._wb_stats["code_nodes"] == before
        assert "code_node" not in k.st.gen_kinds
        assert not [e for e in r.events if e[:2] == ("claim_got", "workbench") or e[:2] == ("claim_got", "browser")]
        assert [n for n, _p, _s in r.dispatched].count("run_python") == 0
    finally:
        r.close()


def test_6b_with_the_web_toggle_off_no_browser_tool_is_callable_from_a_script(monkeypatch):
    r = Rig(monkeypatch, tools=list(_BASE))
    try:
        k = r.kernel("f1", scripts=[
            "for t in ('browser_open', 'browser_read', 'browser_observe', 'browser_act'):\n"
            "    try:\n        getattr(tools, t)(url='https://shop.test/a', action='click')\n"
            "        got = 'called ' + t\n        break\n"
            "    except ToolError as e:\n        got = str(e)\ntotal = 6"], item=Rig.file_item("f1"))
        r.run(k)
        assert [n for n, _p, _s in r.dispatched if n.startswith("browser")] == []
        assert "not available" in json.dumps(r.inspect("got"), default=str)
    finally:
        r.close()
