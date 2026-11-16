"""Round 4 wave W3 (specs/clm-memory/design.md "Round 4": D3 wiring, D4 plan shape + entry rule,
D5 the step result is the outputs manifest), through the REAL `_der_run_node` + a real
Workbench worker (fixtures of test_workbench_repair_contract) and the REAL `_plan_task`.

D3  a code node's FIRST user message carries the ground (PROJECT FILES) and no MEMORY block;
    the namespace holds `files` (and `memory`); the Brain repair prompt carries the ground; the
    flag-on planner prompt carries the ground of the bound folder BEFORE the brief example
    (flag off: byte-equal to the recorded prompt).
D4  the planner rule "ONE step per data product" is in the flag-on prompt; `_wb_code_mode`
    admits a step with outputs + a check or a READ/RUN class, never a WRITE class, never a
    browser / web goal.
D5  a passing check returns the outputs manifest: each output in full when <= 600 chars,
    else 600 chars + "[type, N chars, wb:<inc>/<name>]", then "check: passed"; no stdout, no
    changed-variable lines, no "Tool results:".

Broken-copy demonstrations: WB_NODE_FILE (node.py), WB_EXECUTOR_FILE (node_executor.py),
WB_BRIDGE_FILE (tool_bridge.py; only `_wb_outputs_text` is taken from it), WB_PLANNING_FILE
(kernel/planning.py)."""
import importlib
import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.tests.contract import _wb_common as common
from backend.tests.contract.test_workbench_repair_contract import (  # noqa: F401 - fixtures
    _node_module, repair_node)
from backend.tests.contract.test_planner_brief_fields_contract import RECORDED_FLAG_OFF_PROMPT

DEV = [{"type": "function", "function": {"name": n, "parameters": {"type": "object"}}}
       for n in ("read_file", "run_command", "run_python")]


@pytest.fixture(autouse=True)
def _drain_code_rows():
    """Every run_python writes a tool_results row on its lane; wait for the lane after each
    test (see test_workbench_live_fixes_contract)."""
    yield
    from backend import conversation_store as cs

    cs._tr_lane().flush(10.0)


@pytest.fixture
def svc_folder():
    """A bound project folder: service-logs/svc-01.txt .. svc-14.txt (an x01-like task)."""
    folder = common.make_workdir()
    logs = Path(folder, "service-logs")
    logs.mkdir()
    for i in range(1, 15):
        (logs / f"svc-{i:02d}.txt").write_text(f"2026-11-16 ERROR E{i:03d} svc-{i:02d} down\n" * 5,
                                               encoding="utf-8")
    try:
        yield folder
    finally:
        common.drop(folder)


def _bind(k, folder):
    """The turn's session ("sess") has this folder bound, as tool_bridge._session_workdirs holds it."""
    k._tool_bridge = SimpleNamespace(_session_workdirs={"sess": folder})


# --- D3: the code node -------------------------------------------------------------------
def test_d3_the_first_message_carries_the_ground_no_memory_and_files_is_in_the_namespace(
        repair_node, svc_folder, monkeypatch):
    k = repair_node
    _bind(k, svc_folder)
    from backend.agent import evidence

    monkeypatch.setattr(evidence, "_memory_facts", lambda goal, mi: "the user said: zebra rule")
    # the script proves the namespace: `files` lists the folder, `memory` still holds the fact
    k.scripts += ["result = 42 if (len(files) == 14 and 'service-logs/svc-01.txt' in files "
                  "and 'zebra' in memory) else -1"]
    text, ok = k._der_run_node(k.item, "sess", "turn-1", [])
    assert ok is True and k.roles == ["tool_execution"]          # the check (result == 42) passed
    first = json.loads(k.prompts[0])
    user = next(m["content"] for m in first if m["role"] == "user")
    assert "svc-01.txt .. svc-14.txt" in user and "PROJECT FILES" in user
    assert "MEMORY (earlier statements" not in user and "zebra" not in user
    assert user.index("BRIEF (from the planner)") < user.index("PROJECT FILES")   # right after the brief


def test_d3_the_seeded_names_hold_their_values_not_the_policy_reason(repair_node):
    """_wb_seed put admit_put's reason ("ok") for every name: task, goal, steps, memory and files
    all read the text 'ok' in the namespace. Found while wiring `files` (Round 4 W3)."""
    k = repair_node
    k.scripts += ["result = 42 if (task == 'Count the ERROR lines per code' "
                  "and goal.startswith('Read the files') and steps == [] and memory == '') else -1"]
    _text, ok = k._der_run_node(k.item, "sess", "turn-1", [], task="Count the ERROR lines per code")
    assert ok is True and k.roles == ["tool_execution"]


def test_d3_the_repair_prompt_receives_the_ground(repair_node, svc_folder):
    k = repair_node
    _bind(k, svc_folder)
    k.scripts += ["result = 1", "result = 2", "exec(skeleton)"]
    _text, ok = k._der_run_node(k.item, "sess", "turn-1", [])
    assert ok is True
    brain = [p for r, p in zip(k.roles, k.prompts) if r == "reasoning"]
    assert len(brain) == 1
    assert "PROJECT FILES:\\nPROJECT FILES (the current folder" in brain[0]
    assert "svc-01.txt .. svc-14.txt" in brain[0]


def test_d3_a_node_with_no_bound_folder_has_no_ground_and_an_empty_files_list(repair_node):
    k = repair_node                                              # k._tool_bridge is None: workdir ""
    k.scripts += ["result = 42 if files == [] else -1"]
    _text, ok = k._der_run_node(k.item, "sess", "turn-1", [])
    assert ok is True
    user = next(m["content"] for m in json.loads(k.prompts[0]) if m["role"] == "user")
    assert "PROJECT FILES" not in user


# --- D3 + D4: the planner ----------------------------------------------------------------
def _planning_module():
    path = os.environ.get("WB_PLANNING_FILE")
    if not path:
        return importlib.import_module("backend.agent.kernel.planning")
    spec = importlib.util.spec_from_file_location("_broken_planning", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _plan_prompt(monkeypatch, flag, folder=None, session="sess"):
    from backend.agent.agent_kernel import AgentKernel

    if flag:
        monkeypatch.setenv("IRIS_WORKBENCH", "1")
    else:
        monkeypatch.delenv("IRIS_WORKBENCH", raising=False)
    k = AgentKernel.__new__(AgentKernel)
    k._memory_interface = None
    k._tool_bridge = SimpleNamespace(_session_workdirs={session: folder}) if folder else None
    k._personality = None
    k._caducean_modulate_temperature = lambda t, s: t
    k._ensure_tool_bridge = lambda: None
    k._build_planning_prompt = lambda **kw: "PLANNING"
    k._accrue_tokens = lambda *a, **kw: None
    k._is_openai_compat = lambda: False
    k._plan_task = types.MethodType(_planning_module().PlanningMixin._plan_task, k)
    sent = []

    class _Router:
        last_usage = None

        def generate(self, role, msgs, **kw):
            sent.append(msgs[0]["content"])
            return ("{}", "", None)

    k._router = _Router()
    k._plan_task("Count the ERROR lines per code in service-logs", recall_query="x", session_id=session)
    return sent[0]


def test_d3_d4_the_flag_on_planner_prompt_has_the_ground_and_the_one_step_rule_before_the_example(
        monkeypatch, svc_folder):
    prompt = _plan_prompt(monkeypatch, True, svc_folder)
    assert prompt.startswith(RECORDED_FLAG_OFF_PROMPT)
    added = prompt[len(RECORDED_FLAG_OFF_PROMPT):]
    ex = added.index("Example step with a brief:")
    assert "ONE step per data product" in added[:ex]
    assert "Never plan parallel steps that each read one file." in added[:ex]
    assert "svc-01.txt .. svc-14.txt" in added[:ex]
    # ground (the data) after the rules that refer to it, the example still LAST and the only JSON
    assert added.index("PROJECT FILES (the current folder") > added.index("ONE step per data product")
    assert added.count('{"step_id"') == 1
    json.loads(added[added.index('{"step_id"'):].strip())          # parsed to the end


def test_d4_the_rule_text_is_in_the_prompt_without_a_bound_folder(monkeypatch):
    added = _plan_prompt(monkeypatch, True)[len(RECORDED_FLAG_OFF_PROMPT):]
    assert "ONE step per data product" in added and "PROJECT FILES (the current folder" not in added
    assert "'outputs' are the values the reply will quote" in added
    assert "'check' must test completeness, not only the type" in added


def test_d3_the_flag_off_planner_prompt_stays_byte_equal_even_with_a_bound_folder(
        monkeypatch, svc_folder):
    prompt = _plan_prompt(monkeypatch, False, svc_folder)
    assert prompt.encode("utf-8") == RECORDED_FLAG_OFF_PROMPT.encode("utf-8")


# --- D4: the entry rule ------------------------------------------------------------------
@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv("IRIS_WORKBENCH", "1")
    from backend.agent.workbench import client

    monkeypatch.setattr(client, "resolve_interpreter", lambda workdir: "python")


def _item(goal_outputs=("cost: dict",), check="len(cost) == 12"):
    return SimpleNamespace(outputs=list(goal_outputs), check=check)


def test_d4_a_step_with_outputs_and_a_check_enters_code_mode_whatever_its_first_verb(flag_on):
    node = _node_module()
    goal = "Compute the shipping cost per order"          # first verb is in no class list
    assert node._wb_code_mode(goal, DEV, ".", _item()) is True
    assert node._wb_code_mode(goal, DEV, ".") is False    # no brief: today's rule (class None)
    assert node._wb_code_mode(goal, DEV, ".", _item((), "")) is False
    assert node._wb_code_mode(goal, DEV, ".", _item(("cost: dict",), "")) is False   # needs both


def test_d4_a_write_class_step_never_enters_code_mode_even_with_a_brief(flag_on):
    node = _node_module()
    for goal in ("Edit config.yaml to set the port to 8080", "Create calc.py with an add function",
                 "Update the config file", "Write the totals to report.txt"):
        assert node._wb_code_mode(goal, DEV, ".", _item()) is False, goal


def test_d4_a_browser_or_web_goal_never_enters_code_mode_even_with_a_brief(flag_on):
    node = _node_module()
    assert node._wb_code_mode("Compute the totals from https://example.com/prices", DEV, ".",
                              _item()) is False
    assert node._wb_code_mode("Read https://example.com/docs and summarise it", DEV, ".",
                              _item()) is False


def test_d4_read_and_run_steps_keep_entering_without_a_brief(flag_on):
    node = _node_module()
    assert node._wb_code_mode("Read the 14 service logs and count the ERROR lines", DEV, ".") is True
    assert node._wb_code_mode("Run the tests and report how many fail", DEV, ".") is True


# --- D5: the step result is the outputs manifest -----------------------------------------
@pytest.fixture
def bridge_under_test(monkeypatch):
    """WB_BRIDGE_FILE: take `_wb_outputs_text` from a broken tool_bridge copy."""
    path = os.environ.get("WB_BRIDGE_FILE")
    if not path:
        return
    from backend.agent import tool_bridge

    spec = importlib.util.spec_from_file_location("_broken_bridge", path)
    broken = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = broken
    spec.loader.exec_module(broken)
    monkeypatch.setattr(tool_bridge, "_wb_outputs_text", broken._wb_outputs_text)


def _run_node_result(k, monkeypatch):
    """The NodeResult of the real run_node, to read its SUMMARY (as_step_result adds the calls).
    `_der_run_node` imports run_node from backend.agent.node_executor at call time, so the module
    in sys.modules (the real one, or the WB_EXECUTOR_FILE copy the fixture installed) is wrapped."""
    ex = sys.modules["backend.agent.node_executor"]
    real, got = ex.run_node, {}

    def spy(goal, ctx):
        got["res"] = real(goal, ctx)
        return got["res"]
    monkeypatch.setattr(ex, "run_node", spy)
    text, ok = k._der_run_node(k.item, "sess", "turn-1", [])
    return got["res"], text, ok


def test_d5_a_passing_check_returns_the_manifest_not_the_digest(repair_node, bridge_under_test,
                                                                 monkeypatch):
    k = repair_node
    k.item.outputs = ["a: str", "b: str", "ghost: int"]
    k.item.check = "len(a) == 20 and len(b) == 10000"
    k.scripts += ["a = 'x' * 20\nb = 'y' * 10000\nprint('noisy stdout line')"]
    res, text, ok = _run_node_result(k, monkeypatch)
    assert ok is True and k.roles == ["tool_execution"]
    s = res.summary
    assert "Outputs:" in s
    assert "a = " + "x" * 20 + "\n" in s + "\n"                      # a in full
    assert "b = " + "y" * 600 in s and "y" * 601 not in s            # 600 chars of b, no more
    m = [ln for ln in s.splitlines() if ln.startswith("b = ")][0]
    assert m.endswith("  [str, 10000 chars, wb:" + m.split("wb:")[1])
    inc, name = m.split("wb:")[1].rstrip("]").split("/")
    assert name == "b" and inc                                        # the ref names the incarnation
    assert "ghost = (not set)" in s
    assert s.rstrip().endswith("check: passed")
    assert "stdout" not in s and "noisy stdout line" not in s
    assert "changed variables" not in s and "Tool results:" not in s
    assert "run_python ok (" not in s                                 # no digest header either
