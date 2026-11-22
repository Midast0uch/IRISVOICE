"""Contract: the planner writes each step's BRIEF (inputs, outputs, check,
approach, tools) in the SAME planner call (CLM-11 T7.13, specs/clm-memory/design.md
Round 3), asks for it only with IRIS_WORKBENCH=1, and the five fields reach the
node's QueueItem. A step without them runs as before.

RECORDED_FLAG_OFF_PROMPT is the planner prompt of the UNEDITED code (2026-11-16,
before T7.13), rendered with the planning block stubbed to "PLANNING", no tools and
no personality. Flag off, the prompt must stay byte-equal to it.
"""
from __future__ import annotations

import ast
import json
import types
from pathlib import Path

from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import QueueItem
from backend.agent.kernel import planning as _PLANNING
from backend.agent.kernel.der import run as _run_mod

# Modules under test, read at call time.
_RUN_PATH = Path(_run_mod.__file__)

RECORDED_FLAG_OFF_PROMPT = (
    '\n'
    '\n'
    'PLANNING\n'
    '\n'
    'Respond with JSON only \u2014 no prose, no markdown fences:\n'
    '{"strategy":"do_it_myself|spawn_children|delegate_external","plan_title":"short 2-3 word summary of what the plan does (e.g. \\"Search web for AI news\\")","reasoning":"one sentence explaining the approach","beats":["one-line direction statement","one-line time expectation"],"steps":[{"step_id":"s1","step_number":1,"description":"Search the web for the user request","expected_output":"the concrete result this step must produce","depends_on":["start"],"critical":true,"criticality":"load-bearing|supporting|cosmetic"}]}\n'
    '\n'
    'RULES:\n'
    '- "beats": 1-3 one-line narration lines (why this direction, how long it takes). NEVER narrate mechanics (subtask splitting, tool names, file-by-file). Omit entirely ([]) for single-step tasks.\n'
    '- Vary phrasing, never the same opening twice. Good: "Checking current sources \u2014 usually about half a minute." / "Comparing the two options, then reporting back." Bad: "I will now split this into subtasks."\n'
    '- Findings near completion belong in the reply, not beats. Name artifacts naturally (never identifiers/paths). Failure lines state the cause at direction level plus the next step.\n'
    '- Describe each step as a GOAL in "description". Do NOT name a tool; the runtime resolver picks it when the step executes.\n'
    "- In 'expected_output', state the concrete product of the step: the exact answer, file change or number it must produce. One clause, not a restatement of the goal.\n"
    '- In \'depends_on\', list the step_ids whose RESULT this step needs. A step will not start until those steps have completed. Steps that do not need each other\'s results run at the same time, so do not chain them. Write ["start"] for a step that needs no earlier result. An empty list means "the step before". Example - compare A and B: s1 read A ["start"], s2 read B ["start"], s3 compare them ["s1","s2"].\n'
    '- In \'criticality\', state how load-bearing the step is: "load-bearing" (the task fails without it), "supporting" (helps but alternatives exist), or "cosmetic" (nice to have). Omit for "supporting".\n'
    "- Keep each step MINIMAL. A first step that reads ONE named file is enough. Do NOT plan a step that inspects the project structure, sweeps directories, checks git, or runs the test suite to 'see what exists'.\n"
    '- Do NOT plan a step that only tallies, restates or reports what an earlier step already produced; the final reply does that from the earlier result. A step that CHANGES one file also checks it in the same step (write it, then run a short check and read the output); plan a separate check step only after steps that change several files. When the answer is the exact output of code (what a function returns, what a script prints), plan a step that RUNS it and reads the output; do not work the value out by reading.\n'
)

FIELDS = ("inputs", "outputs", "check", "approach", "tools")


def _render(monkeypatch, flag, reply="{}"):
    """Run the real _plan_task from _PLANNING; return (prompt sent, plan)."""
    if flag:
        monkeypatch.setenv("IRIS_WORKBENCH", "1")
    else:
        monkeypatch.delenv("IRIS_WORKBENCH", raising=False)
    k = AgentKernel.__new__(AgentKernel)
    k._memory_interface = None
    k._tool_bridge = None
    k._personality = None
    k._caducean_modulate_temperature = lambda t, s: t
    k._ensure_tool_bridge = lambda: None
    k._build_planning_prompt = lambda **kw: "PLANNING"
    k._accrue_tokens = lambda *a, **kw: None
    k._is_openai_compat = lambda: False
    k._plan_task = types.MethodType(_PLANNING.PlanningMixin._plan_task, k)
    sent = []

    class _Router:
        last_usage = None

        def generate(self, role, msgs, **kw):
            sent.append(msgs[0]["content"])
            return (reply, "", None)

    k._router = _Router()
    plan = k._plan_task("do x", recall_query="do x")
    return sent[0], plan


def _plan_json(step):
    return json.dumps({"strategy": "do_it_myself", "plan_title": "t", "reasoning": "r",
                       "beats": [], "steps": [step]})


_BASE = {"step_id": "s1", "step_number": 1, "description": "count errors",
         "expected_output": "a count", "depends_on": ["start"]}


def test_flag_off_prompt_is_byte_equal_to_the_recorded_prompt(monkeypatch):
    prompt, _ = _render(monkeypatch, flag=False)
    assert prompt.encode("utf-8") == RECORDED_FLAG_OFF_PROMPT.encode("utf-8")


def test_flag_on_prompt_asks_for_the_five_fields_with_one_example(monkeypatch):
    prompt, _ = _render(monkeypatch, flag=True)
    # the old prompt is untouched; the brief rules are appended after it
    assert prompt.startswith(RECORDED_FLAG_OFF_PROMPT)
    added = prompt[len(RECORDED_FLAG_OFF_PROMPT):]
    for f in FIELDS:
        assert "'%s'" % f in added, f
    # exactly one JSON example, and it parses with all five fields typed right
    assert added.count('{"step_id"') == 1
    example = json.loads(added[added.index('{"step_id"'):].strip())
    assert isinstance(example["inputs"], list) and isinstance(example["outputs"], list)
    assert isinstance(example["tools"], list)
    assert isinstance(example["check"], str) and isinstance(example["approach"], str)
    compile(example["check"], "<check>", "eval")  # ONE Python expression
    assert "expected_output" in example


def test_planner_json_with_the_fields_parses_into_the_plan_step(monkeypatch):
    step = dict(_BASE, inputs=["task", " log "], outputs=["error_counts: dict[str,int]"],
                check="isinstance(error_counts, dict)", approach="Read it. Count it.",
                tools=["read_file", "grep"])
    _, plan = _render(monkeypatch, True, _plan_json(step))
    s = plan.steps[0]
    assert s.inputs == ["task", "log"]
    assert s.outputs == ["error_counts: dict[str,int]"]
    assert s.check == "isinstance(error_counts, dict)"
    assert s.approach == "Read it. Count it."
    assert s.tools == ["read_file", "grep"]
    assert s.expected_output == "a count"  # unchanged


def test_caps_hold(monkeypatch):
    step = dict(_BASE, inputs=["i" * 500] * 12, outputs=["o" * 500] * 12,
                check="c" * 900, approach="a" * 900, tools=["t" * 500] * 12)
    _, plan = _render(monkeypatch, True, _plan_json(step))
    s = plan.steps[0]
    assert len(s.check) == 300 and len(s.approach) == 400
    for name in ("inputs", "outputs", "tools"):
        v = getattr(s, name)
        assert len(v) == 8 and all(len(x) == 120 for x in v), name


def test_json_without_the_fields_parses_as_today(monkeypatch):
    _, plan = _render(monkeypatch, False, _plan_json(_BASE))
    s = plan.steps[0]
    assert (s.inputs, s.outputs, s.check, s.approach, s.tools) == ([], [], "", "", [])
    assert s.description == "count errors" and s.expected_output == "a count"
    assert s.depends_on == []  # ["start"] = no earlier result


def test_bad_types_are_dropped_not_raised(monkeypatch):
    step = dict(_BASE, inputs="task", outputs=5, check=["x"], approach={"a": 1},
                tools=[1, None, "read_file", {"n": 1}])
    _, plan = _render(monkeypatch, True, _plan_json(step))
    s = plan.steps[0]
    assert s.inputs == [] and s.outputs == []
    assert s.check == "" and s.approach == ""
    assert s.tools == ["read_file"]
    assert s.description == "count errors"  # the step itself survives


def _copy_exprs():
    """The keyword expressions of the PlanStep -> QueueItem copy in run.py."""
    tree = ast.parse(_RUN_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "QueueItem"
                and any(k.arg == "expected_output" for k in node.keywords)
                and any(isinstance(k.value, ast.Attribute) and k.value.attr == "original_task"
                        for k in node.keywords)):
            return {k.arg: ast.Expression(k.value) for k in node.keywords}
    raise AssertionError("the plan -> QueueItem copy site was not found in run.py")


def _eval_copy(exprs, step):
    out = {}
    for f in FIELDS:
        assert f in exprs, "run.py does not copy %s onto the QueueItem" % f
        code = compile(ast.fix_missing_locations(exprs[f]), "<copy>", "eval")
        out[f] = eval(code, {}, {"step": step})
    return out


def test_the_fields_reach_the_queue_item_with_the_right_types(monkeypatch):
    step = dict(_BASE, inputs=["task"], outputs=["n: int"], check="n > 0",
                approach="Count.", tools=["read_file"])
    _, plan = _render(monkeypatch, True, _plan_json(step))
    kwargs = _eval_copy(_copy_exprs(), plan.steps[0])
    item = QueueItem(step_id="s1", step_number=1, description="d", **kwargs)
    assert item.inputs == ["task"] and item.outputs == ["n: int"]
    assert item.check == "n > 0" and item.approach == "Count."
    assert item.tools == ["read_file"]
    assert isinstance(item.inputs, list) and isinstance(item.check, str)
    # the copies are not the PlanStep's own lists
    assert item.inputs is not plan.steps[0].inputs


def test_a_step_without_the_fields_gives_an_empty_queue_item(monkeypatch):
    _, plan = _render(monkeypatch, False, _plan_json(_BASE))
    kwargs = _eval_copy(_copy_exprs(), plan.steps[0])
    assert kwargs == {"inputs": [], "outputs": [], "check": "", "approach": "", "tools": []}
    # old-style construction still works and defaults to empty
    q = QueueItem(step_id="s", step_number=1, description="d")
    assert (q.inputs, q.outputs, q.check, q.approach, q.tools) == ([], [], "", "", [])
