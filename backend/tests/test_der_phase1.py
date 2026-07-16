"""Phase 1 tests — memory-coupled acting prompt + single runtime tool resolver.

Validates D1.1–D1.6 of docs/DER_COUPLED_ACTION_CYCLE_SPEC.md:
  F1 fixed : evidence block present in acting prompt
  F6 fixed : exactly ONE tool-resolution authority; regex override deleted
  No hand-holding: planner output has no `tool` field
  G1 preserved: stub rate = 0 under new path
  Deterministic backstop: garbage LLM => top-1 pheromone tool, not stub
"""

import os
import re
import types

import pytest


def _load_kernel_module(monkeypatch):
    """Import agent_kernel with heavy deps stubbed so we can unit-test methods."""
    import backend.agent.agent_kernel as ak

    return ak


def _make_kernel():
    """Build an AgentKernel without running __init__ (avoids DB/LLM wiring)."""
    from backend.agent.agent_kernel import AgentKernel

    k = AgentKernel.__new__(AgentKernel)
    k._memory_interface = None
    k._tool_bridge = None
    k._personality = None
    k._der_task_class = "full"
    k._der_completed_tools = []
    k.conversation_id = "test-conv"
    k.session_id = "test-session"
    # Stub planning helpers that touch external state.
    k._caducean_modulate_temperature = lambda base, sid: base
    k._get_failure_warnings = lambda text: "None"
    k._build_planning_prompt = lambda **kw: "PLAN PROMPT"
    return k


# ── Test 1: evidence block present in acting prompt (F1) ────────────────────
def test_evidence_in_prompt(monkeypatch):
    from backend.agent.evidence import assemble_evidence

    class _Myc:
        class _Store:
            _conn = None

        class _Registry:
            def get_active(self, sid):
                return []

        _store = _Store()
        _registry = _Registry()

    ev = assemble_evidence(
        goal="create a function that sorts a list",
        session_id="test-session",
        myc=_Myc(),
        completed_tools=[],
        task_class="full",
        memory_interface=None,
    )
    assert "PREDICTED NEXT" in ev, "evidence must carry PREDICTED NEXT"
    assert "PROVEN PATH" in ev, "evidence must carry PROVEN PATH"
    assert "AVOID" in ev, "evidence must carry AVOID"
    assert "CONTRACTS" in ev, "evidence must carry CONTRACTS"
    # fenced block
    assert ev.strip().startswith("```evidence")
    assert ev.strip().endswith("```")


# ── Test 2: single authority — regex override deleted ──────────────────────
def test_single_authority(monkeypatch):
    spec_path = os.path.join(
        os.path.dirname(__file__), "..", "agent", "agent_kernel.py"
    )
    src = open(spec_path, encoding="utf-8").read()
    # The deleted web-intent regex forced crawler_query via re.search on the
    # conversational query. Confirm that override is gone.
    assert 'crawler_query' not in src.split("# Phase 1 (D1.4)")[0][-4000:], \
        "web-intent regex override must be deleted (D1.4)"
    # The only runtime resolver entry point is explorer.propose.
    assert "from backend.agent.explorer import propose" in src, \
        "resolver must be wired via explorer.propose"


# ── Test 3: planner emits goals only (no tool field) ───────────────────────
def test_planner_no_tool_field(monkeypatch):
    k = _make_kernel()

    # LLM returns steps that DO include a tool — planner must ignore it (D1.3).
    _PLAN_JSON = (
        '{"steps": ['
        '{"step_id": "s1", "step_number": 1, "description": "write file", '
        '"tool": "write_file", "params": {"path": "x"}},'
        '{"step_id": "s2", "step_number": 2, "description": "run tests", '
        '"tool": "run_command", "params": {"cmd": "pytest"}}'
        ']}'
    )

    class _Router:
        def generate(self, *a, **kw):
            return (_PLAN_JSON, "", None)

    k._router = _Router()

    plan = k._plan_task("build a feature", session_id="test-session")
    assert plan is not None
    assert len(plan.steps) == 2
    for step in plan.steps:
        # Planner must NOT propagate the LLM's tool/params (pure goals now).
        assert step.tool is None, "planner must not assign tool"
        assert step.params == {}, "planner must not assign params"
        assert step.description in ("write file", "run tests")


# ── Test 4: deterministic backstop — garbage LLM => top-1 pheromone, not stub ─
def test_resolver_fallback(monkeypatch):
    from backend.agent.explorer import propose

    # Garbage LLM output (unparseable)
    class _Resp:
        raw_text = "I am not sure what to do here."

    def _infer(*a, **kw):
        return _Resp()

    # Myc with a predictor that returns a known registry tool as top-1.
    class _Myc:
        class _Store:
            _conn = None

        class _Registry:
            def get_active(self, sid):
                return []

        _store = _Store()
        _registry = _Registry()

    # Patch BehavioralPredictor.predict to return a real registry tool.
    import backend.agent.explorer as ex

    monkeypatch.setattr(
        ex, "_pheromone_top1", lambda *a, **kw: "run_command"
    )

    live_tools = [{"name": "run_command"}, {"name": "write_file"}]
    decision = propose(
        goal="do something",
        evidence="```evidence\nPREDICTED NEXT : n/a\n```",
        live_tools=live_tools,
        infer=_infer,
        myc=_Myc(),
        session_id="test-session",
        task_class="full",
        completed_tools=[],
    )
    assert decision["kind"] == "tool"
    assert decision["tool"] == "run_command", "garbage LLM must fall back to top-1"
    assert decision["tool"] is not None
    # Never a stub
    assert not decision["tool"].startswith("[") and "stub" not in decision["tool"].lower()


# ── Test 5: crawler_query still routable for web intent (research class) ────
def test_crawler_still_routable(monkeypatch):
    from backend.agent.explorer import propose

    class _Resp:
        raw_text = "um, I guess search the web?"  # unparseable

    def _infer(*a, **kw):
        return _Resp()

    class _Myc:
        class _Store:
            _conn = None

        class _Registry:
            def get_active(self, sid):
                return []

        _store = _Store()
        _registry = _Registry()

    # Make the web fallback resolve crawler_query as capability-allowed.
    import backend.agent.tool_registry as tr

    class _Spec:
        name = "crawler_query"

    monkeypatch.setattr(tr, "resolve_tool", lambda n: _Spec() if n == "crawler_query" else None)
    monkeypatch.setattr(tr, "capability_allowed", lambda spec: True)

    live_tools = [{"name": "crawler_query"}, {"name": "run_command"}]
    decision = propose(
        goal="research the latest Rust async runtimes",
        evidence="```evidence\nPREDICTED NEXT : n/a\n```",
        live_tools=live_tools,
        infer=_infer,
        myc=_Myc(),
        session_id="test-session",
        task_class="research",  # research class triggers web fallback
        completed_tools=[],
    )
    assert decision["kind"] == "tool"
    assert decision["tool"] == "crawler_query", \
        "research-class web intent must route to crawler_query via registry"


# ── Test 6: stub rate = 0 under new path (resolver never emits a stub) ──────
def test_stub_rate_zero(monkeypatch):
    from backend.agent.explorer import propose

    # Adversarial: LLM returns a stub-like string AND no predictor fallback.
    class _Resp:
        raw_text = "[step 1 completed]"

    def _infer(*a, **kw):
        return _Resp()

    class _Myc:
        class _Store:
            _conn = None

        class _Registry:
            def get_active(self, sid):
                return []

        _store = _Store()
        _registry = _Registry()

    import backend.agent.explorer as ex

    monkeypatch.setattr(ex, "_pheromone_top1", lambda *a, **kw: None)

    live_tools = [{"name": "run_command"}, {"name": "write_file"}]
    stubs = 0
    for goal in ["a", "b", "c", "do x", "finish"]:
        decision = propose(
            goal=goal,
            evidence="```evidence\nPREDICTED NEXT : n/a\n```",
            live_tools=live_tools,
            infer=_infer,
            myc=_Myc(),
            session_id="test-session",
            task_class="full",
            completed_tools=[],
        )
        tool = decision.get("tool")
        if tool is None:
            # reasoning/done is allowed (no tool needed) — not a stub
            continue
        if tool.startswith("[") or "stub" in tool.lower() or not tool:
            stubs += 1
    assert stubs == 0, "resolver must never emit a stub"
