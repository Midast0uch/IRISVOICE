"""Round 3 live fixes (TG-7 cloud arm, first run), through the REAL `_der_run_node` + a real
worker (fixtures of test_workbench_repair_contract):

F1  a passing check puts the VALUES of the brief's outputs in the step result.
F2  the callback slot is per NODE, not per conversation (parallel code nodes).
F3  a repair_route row keeps its evidence in the stored decision block.
F4  a check that fails only because an output is not defined yet is an exploration:
    it is not a failed attempt (no count, no row, no escalation).

Broken-copy demonstrations: WB_EXECUTOR_FILE (a node_executor copy), WB_NODE_FILE (a node.py
copy); F2/F3 revert tool_bridge in place (see the report)."""
import json
import threading
import time
import types
from types import SimpleNamespace

import pytest

from backend.tests.contract.test_workbench_repair_contract import (  # noqa: F401 - fixtures
    _node_module, _run, _run_call, repair_node, shadow)


@pytest.fixture(autouse=True)
def _drain_code_rows():
    """Every run_python writes a tool_results row on its lane; conftest's sessionfinish closes
    the chat store WITHOUT the store lock, so a row still being written when the session ends
    is an access violation (seen once in test_workbench_repair_contract's baseline run too).
    Wait for the lane after each test."""
    yield
    from backend import conversation_store as cs

    cs._tr_lane().flush(10.0)


# --- F1 --------------------------------------------------------------------------
def test_f1_a_passing_check_puts_the_output_values_in_the_step_result(repair_node):
    k = repair_node
    k.item.outputs = ["total: float", "codes: list[str]"]
    k.item.check = "total > 0 and len(codes) > 0"
    k.scripts += ["total = 117726.63\ncodes = ['E101', 'E202', 'E303']"]
    text, ok = k._der_run_node(k.item, "sess", "turn-1", [])
    assert ok is True and k.roles == ["tool_execution"]          # one model call, no summarising call
    assert "117726.63" in text
    assert all(c in text for c in ("E101", "E202", "E303"))
    assert "Outputs:" in text and "total = 117726.63" in text


def test_f1_a_name_not_in_the_namespace_reads_not_set_and_a_long_value_says_it_was_cut(repair_node):
    k = repair_node
    k.item.outputs = ["big: str", "ghost: int", "not an identifier", "x-y"]
    k.item.check = "len(big) > 0"
    k.scripts += ["big = 'a' * 9000"]
    text, ok = k._der_run_node(k.item, "sess", "turn-1", [])
    assert ok is True
    assert "ghost = (not set)" in text
    assert "[cut: 4000 of 9000 chars]" in text
    assert "not an identifier" not in text and "x-y" not in text


def test_f1_without_a_brief_the_result_has_no_outputs_section(repair_node):
    k = repair_node
    k.item.outputs, k.item.check = [], "result == 42"
    k.scripts += ["result = 42"]
    text, ok = k._der_run_node(k.item, "sess", "turn-1", [])
    assert ok is True and "Outputs:" not in text


# --- F2 --------------------------------------------------------------------------
def test_f2_two_code_nodes_in_one_conversation_each_reach_their_own_handler(repair_node):
    """A registers; B starts while A is still in its first model call. Keyed by
    conversation, A's callback met B's handler (wrong calls list) or an empty slot
    ("tools are not available here").
    STATED CHANGE (Round 4 D7, 2026-11-16): a code node now takes the `workbench` claim
    BEFORE its clock starts, so two code nodes of one conversation never overlap - B waits
    for the claim until A ends. The old setup (A waits inside its model call for B to
    FINISH) is a deadlock by design now; A waits only until B has STARTED, and the test
    also pins the new order (B's script runs after A's node ended)."""
    from backend.agent import tool_bridge

    k = repair_node
    k.item.check, k.item.outputs = "", []
    a_waiting, b_started = threading.Event(), threading.Event()
    seen, order = [], []

    def _item(step, desc):
        return SimpleNamespace(description=desc, objective_anchor="", expected_output="",
                               parent_description="", review_feedback="", step_id=step,
                               check="", node_calls=[], node_call_log=[])
    item_a = _item("sA", "Read the files and compute the result NODE-A")
    item_b = _item("sB", "Read the files and compute the result NODE-B")
    sent = set()

    class _Router:
        last_usage = None

        def generate(self, role, messages, **kw):
            blob = json.dumps(messages)
            who = "A" if "NODE-A" in blob else "B"
            if who in sent or kw.get("tools") is None:
                return "Done.\nSTATUS: done", "", []
            sent.add(who)
            if who == "A":
                a_waiting.set()
                assert b_started.wait(30), "B never started"
                time.sleep(0.5)                          # B now tries to overlap A
            return "", "", [_run_call(1, f"r = tools.read_file(path='{who}1')\nr")]

        def resolve(self, role):
            return SimpleNamespace(id="same-model")
    k._router = _Router()
    real_dispatch = k._get_tool_box().dispatch

    class _Box:
        def dispatch(self, decision, **kw):
            if decision.tool == "run_python":
                order.append(("run", "A" if "A1" in str(decision.params.get("code")) else "B"))
                return real_dispatch(decision, **kw)
            seen.append(decision.params.get("path"))
            return SimpleNamespace(result={"success": True, "content": "ok"}, error="")

        def record_shadow_tool_choice(self, **kw):
            pass

        def record_tool_call(self, *a, **kw):
            pass
    k._get_tool_box = lambda: _Box()
    out = {}

    def _go(name, item):
        if name == "B":
            b_started.set()
        out[name] = k._der_run_node(item, "sess", "turn-1", [])
        order.append(f"{name}:end")
    ta = threading.Thread(target=_go, args=("A", item_a))
    ta.start()
    assert a_waiting.wait(30)
    tb = threading.Thread(target=_go, args=("B", item_b))
    tb.start()
    tb.join(60)
    ta.join(60)
    assert not ta.is_alive() and not tb.is_alive()      # no deadlock on the shared client
    for name, item, path in (("A", item_a, "A1"), ("B", item_b, "B1")):
        log = item.node_call_log
        assert out[name][1] is True, (name, out[name], log)
        assert [c["tool"] for c in log] == ["run_python", "read_file"], (name, log[0].get("out"))
        assert log[1]["target"] == path and log[1]["via"] == "run_python"
        assert "not available" not in log[0]["out"]
    assert sorted(seen) == ["A1", "B1"]
    assert order.index(("run", "B")) > order.index("A:end"), order   # D7: no overlap
    assert not tool_bridge._wb_dispatch                 # both registrations cleared


# --- F3 --------------------------------------------------------------------------
def _wait_for(pred, seconds=10.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not pred():
        time.sleep(0.05)


def test_f3_a_repair_route_row_keeps_its_evidence_in_the_stored_decision_block(shadow, monkeypatch):
    import backend.agent.tool_bridge as tb
    import backend.gateway.iris_ffi as ffi
    from backend.agent.kernel.planning import PlanningMixin

    k = shadow
    stored = []
    monkeypatch.setattr(ffi, "ffi_ingest_event",
                        lambda **kw: stored.append(json.loads(kw["payload_json"])) or True)
    tb._SHADOW_DEDUP.clear()
    k._tool_bridge = tb.AgentToolBridge()
    k.session_id = "sess"
    k._shadow_row_sink = types.MethodType(PlanningMixin._shadow_row_sink, k)   # the real sink
    k.item.check = "result['k'] == 42"
    k.scripts += ["result = 1", "result = {'k': 42}"]
    _text, ok = _run(k)
    assert ok is True
    k.drain()
    _wait_for(lambda: any("attempt" in (p.get("decision") or {}) for p in stored))
    blocks = [p["decision"] for p in stored
              if (p.get("decision") or {}).get("consumer_id") == "repair_route"]
    assert blocks, stored
    d = next(b for b in blocks if "attempt" in b)
    assert d["attempt"] == 1 and d["error_type"] == "CheckFailed"
    assert d["check_error"].startswith("TypeError") and d["rule_choice"] == "REPAIR"
    assert d["chosen"] in ("REPAIR", "ESCALATE") and d["consumer_id"] == "repair_route"


def test_f3_another_consumers_row_keeps_its_shape(monkeypatch):
    import backend.agent.tool_bridge as tb
    import backend.gateway.iris_ffi as ffi

    stored = []
    monkeypatch.setattr(ffi, "ffi_ingest_event",
                        lambda **kw: stored.append(json.loads(kw["payload_json"])) or True)
    tb._SHADOW_DEDUP.clear()
    tb.AgentToolBridge().record_decision(
        {"consumer_id": "tool_choice", "chosen": "read_file", "confidence": 0.9,
         "attempt": 3, "error_type": "X", "check_error": "y", "rule_choice": "z"},
        "shadow", session_id="s1")
    _wait_for(lambda: stored, 5.0)
    d = stored[0]["decision"]
    assert d["chosen"] == "read_file"
    assert not {"attempt", "error_type", "check_error", "rule_choice"} & set(d)


# --- F4 --------------------------------------------------------------------------
def test_f4_exploring_scripts_before_the_outputs_exist_never_escalate(shadow):
    k = shadow
    k.item.check, k.item.outputs = "result == 42", ["result: int"]
    k.scripts += ["files = ['a', 'b']", "n = len(files)", "result = 42"]
    _text, ok = _run(k)
    assert ok is True
    assert k.roles == ["tool_execution"] * 3                 # ZERO reasoning calls
    assert k.drain() == []                                   # no repair_route row for an exploration
    assert "check: failed - NameError" in k.prompts[1]       # the model still sees it did not pass


def test_f4_two_scripts_that_define_the_outputs_wrongly_escalate_once(repair_node):
    k = repair_node
    k.item.check, k.item.outputs = "result == 42", ["result: int"]
    k.scripts += ["result = 1", "result = 2", "exec(skeleton)"]
    _text, ok = _run(k)
    assert ok is True and k.roles.count("reasoning") == 1
    assert k.roles == ["tool_execution", "tool_execution", "reasoning", "tool_execution"]


def test_f4_exploration_does_not_use_up_a_real_attempt(shadow):
    k = shadow
    k.item.check, k.item.outputs = "result == 42", ["result: int"]
    k.scripts += ["peek = 1", "result = 1", "result = 2", "exec(skeleton)"]
    _text, ok = _run(k)
    assert ok is True and k.roles.count("reasoning") == 1
    assert k.roles[:4] == ["tool_execution"] * 3 + ["reasoning"]   # after the 2nd REAL failure
    assert [r["attempt"] for r in k.drain()] == [1, 2]


def test_f4_a_nameerror_for_a_name_that_is_not_an_output_is_a_real_failure(repair_node):
    k = repair_node
    k.item.check, k.item.outputs = "undefined_thing == 1", ["result: int"]
    k.scripts += ["result = 1", "result = 2", "exec(skeleton)"]
    _run(k)
    assert k.roles.count("reasoning") == 1


def test_f4_a_node_that_only_explores_ends_at_max_calls_with_no_escalation(repair_node):
    k = repair_node
    k.item.check, k.item.outputs = "result == 42", ["result: int"]
    k.scripts += [f"peek = {i}" for i in range(10)]
    _text, ok = _run(k)
    assert ok is False                                       # DER recovery, as today
    assert k.roles.count("reasoning") == 0
    assert [c["tool"] for c in k.item.node_call_log] == ["run_python"] * 6
