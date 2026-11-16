"""Round 4 (specs/clm-memory/design.md "Round 4", W0 + W1 + the node part of D6), through the
REAL `_der_run_node` + a real Workbench worker (fixtures of test_workbench_repair_contract).

D1  the Brain repair call is cheap and sighted: reasoning_effort="low", call_kind "wb_repair";
    the note the tool model gets SHOWS the skeleton text (not only a variable name).
D6  the tool-model diet: code-node max_tokens 1024; the run_python schema the model sees is
    exactly {code, purpose}; no `tools.` note unless the brief names a tool Python cannot
    replace; a 2,400-char brief costs the first call <= 1,100 estimated tokens.
D7  the `workbench` claim is taken BEFORE run_node starts its clock; the wait is counted in
    `_wb_stats["wb_wait_s"]`; the first run_python does not take the claim a second time.
W0  every model call of a node carries its call_kind ("code_node" for a code node, "node" for a
    menu node); a code node counts its scripts and exploring runs and logs one line at close.

Broken-copy demonstrations: WB_NODE_FILE (a node.py copy), WB_EXECUTOR_FILE (a node_executor
copy), as in test_workbench_repair_contract / test_workbench_live_fixes_contract."""
import dataclasses
import importlib
import json
import logging
import threading
import time
from types import SimpleNamespace

import pytest

from backend.tests.contract.test_workbench_repair_contract import (  # noqa: F401 - fixtures
    _CHECK, _SKELETON, _node_module, _run_call, _tool, _TOOLS, repair_node)


@pytest.fixture(autouse=True)
def _drain_code_rows():
    """Every run_python writes a tool_results row on its lane; wait for the lane after each
    test (see test_workbench_live_fixes_contract)."""
    yield
    from backend import conversation_store as cs

    cs._tr_lane().flush(10.0)


def _loaded(k):
    """The node module the kernel's `_der_run_node` really runs in (a WB_NODE_FILE copy is
    loaded once by the fixture; `_node_module()` would load a second instance with its own
    `_wb_stats`)."""
    g = k._der_run_node.__func__.__globals__
    return SimpleNamespace(wb_stats=g["wb_stats"], _der_claim_lock=g["_der_claim_lock"])


def _spy(k):
    """Record (role, kwargs, messages) of every generate call the node makes."""
    calls = []
    real = k._router.generate

    def generate(role, messages, **kw):
        calls.append((role, dict(kw), messages))
        return real(role, messages, **kw)
    k._router.generate = generate
    k.spied = calls
    return calls


# --- D1 ----------------------------------------------------------------------------
def test_d1_the_repair_call_is_low_effort_tagged_and_its_note_shows_the_skeleton(repair_node):
    k = repair_node
    calls = _spy(k)
    k.scripts += ["result = 1", "result = 2", "exec(skeleton)"]
    _text, ok = k._der_run_node(k.item, "sess", "turn-1", [])
    assert ok is True
    brain = [(kw, m) for role, kw, m in calls if role == "reasoning"]
    assert len(brain) == 1
    kw, messages = brain[0]
    assert kw.get("reasoning_effort") == "low" and kw.get("call_kind") == "wb_repair"
    prompt = messages[0]["content"]
    assert prompt.startswith("A small model is doing one step of a task in a Python workbench")
    assert "at most three sentences" in prompt and "PROJECT FILES:\n\n\nBRIEF:" in prompt  # ground "" for now
    # the tool model's third attempt SEES the script: the skeleton text rides in the note
    third = json.dumps(calls[3][2])
    assert "Starting script (also in the variable `skeleton`" in third
    assert _SKELETON in third and "exec(skeleton)" in third
    assert _SKELETON not in json.dumps(calls[1][2])                    # nothing before the escalation


def _stub_manager(monkeypatch):
    from backend.agent.workbench import manager

    puts = {}
    stub = SimpleNamespace(workbench_for=lambda conv, cwd: SimpleNamespace(
        put=lambda name, value: puts.__setitem__(name, value)))
    monkeypatch.setattr(manager, "get_manager", lambda: stub)
    return puts


def test_d1_the_ground_parameter_reaches_the_repair_prompt(monkeypatch):
    puts = _stub_manager(monkeypatch)
    mod = _node_module()
    seen = []

    class _R:
        def generate(self, role, messages, **kw):
            seen.append(messages[0]["content"])
            return "Fix it.\n```python\nresult = 1\n```", "", []
    hook = mod._wb_escalate(SimpleNamespace(_router=_R()), "conv-x", ".", "the brief", "result == 1",
                            ground="a.py (12 B)\nb.py (7 B)")
    note = hook(2, "result = 0", "check: failed")
    assert "PROJECT FILES:\na.py (12 B)\nb.py (7 B)\n\nBRIEF:\nthe brief" in seen[0]
    assert note.startswith("REPAIR BRIEF (from the planner):\nFix it.")
    assert note.endswith("result = 1") and puts == {"skeleton": "result = 1"}


def test_d1_a_note_with_no_skeleton_has_no_second_part(monkeypatch):
    _stub_manager(monkeypatch)
    mod = _node_module()

    class _R:
        def generate(self, role, messages, **kw):
            return "Set result to 42.", "", []
    note = mod._wb_escalate(SimpleNamespace(_router=_R()), "conv-x", ".", "b", "c")(2, "x", "d")
    assert note == "REPAIR BRIEF (from the planner):\nSet result to 42."


# --- W0: call kinds --------------------------------------------------------------------
def test_w0_a_code_nodes_model_calls_read_code_node(repair_node):
    k = repair_node
    calls = _spy(k)
    k.scripts += ["result = 42"]
    _text, ok = k._der_run_node(k.item, "sess", "turn-1", [])
    assert ok is True
    assert [(r, kw.get("call_kind")) for r, kw, _m in calls] == [("tool_execution", "code_node")]


def test_w0_a_menu_nodes_model_calls_read_node(repair_node, monkeypatch):
    k = repair_node
    monkeypatch.setenv("IRIS_WORKBENCH", "0")                # the menu path
    calls = _spy(k)
    k._router.generate = lambda role, messages, **kw: (
        calls.append((role, dict(kw), messages)) or ("Done.\nSTATUS: done", "", []))
    k._der_run_node(k.item, "sess", "turn-1", [])
    assert calls and {kw.get("call_kind") for _r, kw, _m in calls} == {"node"}


# --- W0: stats and the close line ---------------------------------------------------------
def test_w0_a_code_node_counts_scripts_and_exploring_runs_and_logs_one_close_line(repair_node, caplog):
    k = repair_node
    mod = _loaded(k)
    before = mod.wb_stats()
    k.item.outputs = ["result: int"]
    # run 1 explores (the output is not defined yet); run 2 fills it
    k.scripts += ["print(1)", "result = 42"]
    with caplog.at_level(logging.INFO):
        _text, ok = k._der_run_node(k.item, "sess", "turn-1", [])
    assert ok is True
    after = mod.wb_stats()
    assert after["scripts"] - before["scripts"] == 2
    assert after["exploring"] - before["exploring"] == 1
    lines = [r.getMessage() for r in caplog.records if "scripts=" in r.getMessage()]
    assert lines == ["[workbench] conv=conv-wb-repair step=s1 scripts=2 exploring=1 wait_s=0.0"]


# --- D6 ---------------------------------------------------------------------------------
def test_d6_code_node_max_tokens_is_1024_and_run_python_has_only_code_and_purpose(repair_node):
    k = repair_node
    calls = _spy(k)
    k.scripts += ["result = 42"]
    _text, ok = k._der_run_node(k.item, "sess", "turn-1", [])
    assert ok is True
    _role, kw, _m = calls[0]
    assert kw["max_tokens"] == 1024
    (tool,) = kw["tools"]
    fn = tool["function"]
    assert fn["name"] == "run_python"
    assert set(fn["parameters"]["properties"]) == {"code", "purpose"}
    assert fn["parameters"]["required"] == ["code"]
    assert fn["description"].count(".") == 1 and len(fn["description"]) < 120       # one sentence


def test_d6_no_tools_note_when_the_brief_names_no_tool_python_cannot_replace(repair_node):
    k = repair_node
    calls = _spy(k)
    k.item.tools = ["read_file", "run_command", "grep_files"]            # all replaced by Python
    k.scripts += ["result = 42"]
    k._der_run_node(k.item, "sess", "turn-1", [])
    system = calls[0][2][0]["content"]
    assert system.startswith("You do ONE step of a task by writing Python")
    assert "tools." not in system and "ToolError" not in system
    # owner 2026-11-16: other languages (JavaScript first) run from the same script through sh()
    assert (" Other languages run from the same script: sh('node app.js'), sh('npm test'), "
            "sh('npx tsc --noEmit'), or a JavaScript snippet with sh('node -', input=js_code); "
            "sh() returns a dict with code, stdout, stderr.") in system


def test_d6_a_tool_python_cannot_replace_keeps_the_note_and_its_line(repair_node):
    k = repair_node
    calls = _spy(k)
    k._get_openai_tools = lambda: _TOOLS + [_tool("edit_file", ("path", "old_text", "new_text"))]
    k.item.tools = ["read_file", "edit_file"]
    k.scripts += ["result = 42"]
    k._der_run_node(k.item, "sess", "turn-1", [])
    system = calls[0][2][0]["content"]
    assert "`tools.<name>(**args)`" in system
    assert "tools.edit_file(path, old_text, new_text)" in system
    assert "tools.read_file" not in system                                # only the tool it needs


def test_d6_the_first_call_of_a_2400_char_brief_fits_1100_estimated_tokens(repair_node):
    from backend.agent.inference.router import InferenceRouter

    k = repair_node
    calls = _spy(k)
    k.item.approach = "Read the file, match each line, count by type. " * 80      # > 2,400 chars
    k.scripts += ["result = 42"]
    k._der_run_node(k.item, "sess", "turn-1", [])
    _role, kw, messages = calls[0]
    brief = next(m["content"] for m in messages if m["role"] == "user" and "approach:" in m["content"])
    assert len(brief) >= 2400                                              # the brief really is at its cap
    assert InferenceRouter._estimate_prompt_tokens(messages, kw["tools"]) <= 1100


# --- D7 ---------------------------------------------------------------------------------
def test_d7_the_claim_is_taken_before_the_clock_and_never_twice(repair_node, monkeypatch):
    """A (a real code node) holds the `workbench` claim from its start and sits 2 s in its
    second model call. B starts meanwhile. B must wait for the claim BEFORE run_node starts
    its deadline: run_node (patched to a 6.5 s budget) is entered with the claim held, B's
    wait is counted in wb_wait_s, B's own budget is whole (before D7 the 2 s wait ate it and
    run_node stopped with "node time budget used up"), and B's first run_python does not take
    the claim again (a second take by the same node would never return)."""
    k = repair_node
    mod = _loaded(k)
    ex = importlib.import_module("backend.agent.node_executor")
    k.item.check, k.item.outputs = "", []

    def _item(step, desc):
        return SimpleNamespace(description=desc, objective_anchor="", expected_output="",
                               parent_description="", review_feedback="", step_id=step,
                               check="", node_calls=[], node_call_log=[])
    item_a = _item("sA", "Read the files and compute the result NODE-A")
    item_b = _item("sB", "Read the files and compute the result NODE-B")
    a_in_sleep = threading.Event()
    sent = {"A": 0, "B": 0}

    class _Router:
        last_usage = None

        def generate(self, role, messages, **kw):
            who = "A" if "NODE-A" in json.dumps(messages) else "B"
            sent[who] += 1
            if kw.get("tools") is None:
                return "Done.\nSTATUS: done", "", []
            if sent[who] == 1:
                return "", "", [_run_call(1, f"x_{who} = 1")]
            if who == "A":
                a_in_sleep.set()
                time.sleep(2.0)                    # A keeps the claim for 2 s
            return "Done.\nSTATUS: done", "", []

        def resolve(self, role):
            return SimpleNamespace(id="same-model")
    k._router = _Router()
    entered = {}
    real_run_node = ex.run_node

    def run_node(goal, ctx):
        who = "B" if "NODE-B" in goal else "A"
        entered[who] = (time.monotonic(), mod._der_claim_lock(k, "workbench").locked())
        if who == "B":
            ctx = dataclasses.replace(ctx, budget_s=6.5)   # 6.5 - 2 s of waiting < the 5 s floor
        return real_run_node(goal, ctx)
    monkeypatch.setattr(ex, "run_node", run_node)
    wait_before = mod.wb_stats()["wb_wait_s"]
    out = {}
    ta = threading.Thread(target=lambda: out.__setitem__("A", k._der_run_node(item_a, "sess", "turn-1", [])),
                          daemon=True)    # daemon: a broken node that never returns must not hang the run
    ta.start()
    assert a_in_sleep.wait(30)
    t_b = time.monotonic()
    tb = threading.Thread(target=lambda: out.__setitem__("B", k._der_run_node(item_b, "sess", "turn-1", [])),
                          daemon=True)
    tb.start()
    tb.join(60)
    ta.join(60)
    assert not ta.is_alive() and not tb.is_alive()         # no node took the claim twice
    assert out["A"][1] is True and out["B"][1] is True, out
    assert "time budget" not in out["B"][0]
    assert entered["A"][1] is True and entered["B"][1] is True           # claim held at run_node entry
    assert entered["B"][0] - t_b >= 1.5                    # B's clock began after A's 2 s hold
    assert mod.wb_stats()["wb_wait_s"] - wait_before >= 1.5
    assert not mod._der_claim_lock(k, "workbench").locked()              # both released it


# --- D2 ---------------------------------------------------------------------------------
def test_d2_the_brief_rules_carry_the_quote_rule_before_the_example():
    from backend.agent.kernel import planning

    rules = planning._PLANNER_BRIEF_RULES
    rule = ("Inside 'check', 'inputs' and 'outputs' use single quotes only and no backslashes; "
            "write paths relative with forward slashes.")
    assert rule in rules and rules.index(rule) < rules.index('{"step_id"')


def test_d2_an_unparseable_planner_text_logs_its_head_and_the_conversation(caplog):
    """The log sits at the call site (the parser is a staticmethod with no conversation id)."""
    from backend.tests._kernel_source import kernel_function_source

    src = kernel_function_source("_plan_task")
    i = src.index("self._parse_planner_json(plan_raw)")
    assert "planner text did not parse" in src[i:i + 900] and "plan_raw[:1200]" in src[i:i + 900]
    assert "conv=%s" in src[i:i + 900]
