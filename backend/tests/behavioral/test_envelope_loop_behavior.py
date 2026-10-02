"""BT-1..BT-3 (specs/tool-result-envelope Wave 2/3 gate TG-2/TG-3).

Behavioral: drive the REAL finalize path and the REAL streak gate with a
kernel whose heavy collaborators are stubbed, and assert EMERGENT properties:
working memory / fallback reports contain ONLY envelope lines (failure lines
included), a load-bearing mismatch caps the run grade, the gate fires exactly
at threshold and never before, and TOPO_VIOLATION forces fire regardless.
No live web, no live model.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.agent.der_loop import DirectorQueue, QueueItem
from backend.agent.tool_envelope import params_digest


_CONV99_CHROME = "page chrome junk cmake ggml-large-v3 download links " * 40
# A marker at the FAR TAIL of the raw payload — a bounded (≤300-char) envelope
# digest can never contain it; the 8000-char raw window did.
_CONV99_TAIL_MARKER = "END-OF-RAW-PAYLOAD-MARKER-7f3d"
_CONV99_CHROME = _CONV99_CHROME + _CONV99_TAIL_MARKER


class _Kernel:
    """Kernel stand-in binding the REAL finalize + gate + summaries."""

    def __init__(self):
        from backend.agent.agent_kernel import AgentKernel

        self.conversation_id = "conv_bt"
        self._memory_interface = MagicMock()
        self._mcm_orch = None
        self._der_crawled_urls = {}
        self._der_seen_dispatches = {}
        self._der_envelope_registry = {}
        self._der_last_run_grade = None
        self.steering_calls = []
        # bind real methods
        for name in (
            "_der_finalize_step", "_der_build_step_envelope",
            "_der_streak_gate", "_pre_dispatch_guard_alias",
        ):
            if hasattr(AgentKernel, name):
                setattr(self, name, getattr(AgentKernel, name).__get__(self))
        self._der_pre_dispatch_guard = (
            AgentKernel._der_pre_dispatch_guard.__get__(self)
        )
        self._der_apply_steering = self._record_steering
        self._verify_step_result = self._verify
        self._card_envelope = lambda _tid: {"card_id": "card_bt"}
        self._end_tool_wait = lambda _tid: None
        self._smart_excerpt = AgentKernel._smart_excerpt
        self._der_evidence_cap = AgentKernel._der_evidence_cap
        self._der_user_facing_evidence = AgentKernel._der_user_facing_evidence
        self._der_node_record_evidence = (
            AgentKernel._der_node_record_evidence
        )

    def _record_steering(self, text, _session, plan, queue, budget_deadline=None):
        self.steering_calls.append(text)
        return True

    def _verify(self, description, expected, result, tool=None, success=True):
        return self._verify_map.get(description, "VERIFIED")


def _plan(n=3):
    from backend.core_models import ExecutionPlan, PlanStep

    return ExecutionPlan(
        plan_id="p1", original_task="research streaming STT",
        strategy="do_it_myself", reasoning="r", plan_title="research",
        steps=[
            PlanStep(step_id=f"s{i}", step_number=i, description=f"step {i}")
            for i in range(1, n + 1)
        ],
    )


def _run_finalize(k, queue, item, result, success, completed, verified="VERIFIED"):
    k._verify_map = {item.description: verified}
    plan = _plan()
    return k._der_finalize_step(
        item=item,
        step_result=result,
        step_success=success,
        step_outputs=[],
        completed_items=completed,
        _tokens_used=100,
        _token_budget=10000,
        _session="sess",
        _turn_id="t1",
        _phase=2,
        is_mature=False,
        _live_ctx=None,
        plan=plan,
        context_package=None,
        queue=queue,
        verdict=None,
    )


# ── BT-1: envelope-only context flow + honest grade ─────────────────────────


def test_bt1_working_memory_fallback_and_grade():
    """3-step research-shaped run: working memory gets envelope LINES for
    every settled step INCLUDING the failure; no raw crawl chrome anywhere
    user-visible; a load-bearing mismatch caps the run grade."""
    k = _Kernel()
    plan = _plan()
    queue = DirectorQueue(objective=plan.original_task, items=[])
    completed = []

    # Step 1: gather — success, matched, load-bearing
    it1 = QueueItem(step_id="s1", step_number=1,
                    description="research whisper.cpp streaming",
                    tool="crawler_query", params={"query": "whisper.cpp streaming"})
    it1.declared_criticality = "load-bearing"
    _run_finalize(k, queue, it1, "whisper.cpp supports streaming\n--- Source: https://a.com",
                  True, completed, verified="VERIFIED")
    completed.append(it1)

    # Step 2: same tool+params — a REPEAT (digest collision), wrong package
    # (real output but asked terms absent) — load-bearing mismatch seeded
    it2 = QueueItem(step_id="s2", step_number=2,
                    description="research Parakeet streaming",
                    tool="crawler_query", params={"query": "whisper.cpp streaming"})
    it2.declared_criticality = "load-bearing"
    _run_finalize(k, queue, it2, _CONV99_CHROME, True, completed, verified="UNVERIFIED")
    completed.append(it2)

    # Step 3: a FAILURE — must ALSO be written to working memory
    it3 = QueueItem(step_id="s3", step_number=3,
                    description="read docs", tool="fetch_url",
                    params={"url": "https://b.com"})
    it3.declared_criticality = "supporting"
    _run_finalize(k, queue, it3, "[STEP ERROR: connection timed out]",
                  False, completed, verified="FAILED")
    completed.append(it3)

    # Working memory: 3 lines (failure INCLUDED — the old silent-skip bug)
    notes = [
        c.args[1] for c in k._memory_interface.append_to_session.call_args_list
    ]
    assert len(notes) == 3, f"expected 3 envelope lines incl. failure, got {len(notes)}"
    for note in notes:
        # Emergent bound: every note is a bounded envelope line (~<700 chars)
        # — the conv-99 8000-char raw windows are impossible by construction.
        assert len(note) < 700, f"unbounded note ({len(note)} chars)"
    # step 2's note is an ENVELOPE line (wrapper labels present), not the
    # legacy raw excerpt — the raw was 2100+ chars; the note is bounded and
    # carries the wrapper verdict.
    assert len(notes[1]) < 700 and len(_CONV99_CHROME) > 2000
    assert "repeat_of_s1" in notes[1]
    # failure line is honest about the flat tire
    assert "error" in notes[2] and "[Step 3" in notes[2]

    # Fallback report: envelope lines only, grade capped by the load-bearing
    # mismatch on s2
    report = k._der_user_facing_evidence(it2)
    assert len(report) < 700 and len(_CONV99_CHROME) > 2000
    from backend.agent.agent_kernel import AgentKernel

    summary = AgentKernel._der_deterministic_success_summary(plan, completed, queue)
    assert "capped below full pass" in summary, (
        "a load-bearing mismatch MUST cap the run below full pass"
    )
    # and the report is bounded envelope lines — never the raw window
    for line in summary.split("\n"):
        assert len(line) < 700


def test_bt1_grade_full_pass_when_no_load_bearing_mismatch():
    k = _Kernel()
    plan = _plan(1)
    queue = DirectorQueue(objective="x", items=[])
    completed = []
    it1 = QueueItem(step_id="s1", step_number=1,
                    description="research whisper.cpp streaming",
                    tool="crawler_query", params={"query": "q1"})
    it1.declared_criticality = "supporting"
    _run_finalize(k, queue, it1, "whisper.cpp supports streaming\n--- Source: https://a.com",
                  True, completed, verified="VERIFIED")
    completed.append(it1)
    from backend.agent.agent_kernel import AgentKernel

    summary = AgentKernel._der_deterministic_success_summary(plan, completed, queue)
    assert "capped below full pass" not in summary


# ── BT-2: streak gate fires exactly at threshold, TOPO forces ───────────────


def _queue_with_envelopes(shapes):
    """shapes: list of (novelty, match, shape) tuples → completed queue."""
    from backend.agent.tool_envelope import ToolResultEnvelope

    plan = _plan(len(shapes))
    items = []
    for i, (nov, mat, shp) in enumerate(shapes, start=1):
        it = QueueItem(step_id=f"s{i}", step_number=i, description=f"step {i}")
        it.envelope = ToolResultEnvelope(
            status="success" if nov != "empty" else "error",
            summary="summary", match=mat, novelty=nov, stuck_shape=shp,
            step_id=f"s{i}",
        )
        items.append(it)
    queue = DirectorQueue(objective="obj", items=items)
    for it in items:
        queue.completed_ids.append(it.step_id)
    return plan, queue


def test_bt2_nominal_run_blocks_the_gate():
    k = _Kernel()
    plan, queue = _queue_with_envelopes([
        ("new", "matched", "none"),
        ("new", "matched", "none"),
        ("new", "matched", "none"),
    ])
    fired = k._der_streak_gate(plan, queue, "sess")
    assert not fired
    assert k.steering_calls == []
    assert k._envelope_counters["gate_blocked"] == 1
    assert k._envelope_counters["gate_fired"] == 0


def test_bt2_repeat_streak_fires_at_threshold_never_before():
    k = _Kernel()
    # one repeat: below threshold — blocked
    plan, queue = _queue_with_envelopes([
        ("new", "matched", "none"),
        ("repeat_of_s1", "matched", "circling"),
    ])
    assert not k._der_streak_gate(plan, queue, "sess")
    assert k.steering_calls == []
    # second consecutive repeat: AT threshold — fires exactly now
    plan2, queue2 = _queue_with_envelopes([
        ("new", "matched", "none"),
        ("repeat_of_s1", "matched", "circling"),
        ("repeat_of_s1", "matched", "circling"),
    ])
    assert k._der_streak_gate(plan2, queue2, "sess")
    assert len(k.steering_calls) == 1
    assert k._envelope_counters["gate_fired"] == 1
    # AC5.4: the audit names the triggering envelopes
    assert "repeat_of_s1" in k.steering_calls[0]


def test_bt2_mismatch_streak_fires():
    k = _Kernel()
    plan, queue = _queue_with_envelopes([
        ("new", "mismatched", "wrong_package"),
        ("new", "mismatched", "wrong_package"),
    ])
    assert k._der_streak_gate(plan, queue, "sess")


def test_bt2_idling_streak_is_shadow_only():
    """Owner 2026-10-01: the idle arm fired on 5/15 healthy coding runs and
    its replan broke c15 - it logs and counts, it never replans."""
    k = _Kernel()
    plan, queue = _queue_with_envelopes([
        ("new", "matched", "idling"),
        ("new", "matched", "idling"),
    ])
    assert not k._der_streak_gate(plan, queue, "sess")
    assert k.steering_calls == []
    assert k._envelope_counters["idle_shadow"] == 1


def test_bt2_topo_violation_forces_fire_regardless_of_streaks(monkeypatch):
    k = _Kernel()
    plan, queue = _queue_with_envelopes([
        ("new", "matched", "none"),
        ("new", "matched", "none"),
    ])
    import backend.gateway.iris_ffi as ffi

    monkeypatch.setattr(ffi, "ffi_caducean_recommend", lambda _s: 3)
    assert k._der_streak_gate(plan, queue, "sess"), (
        "TOPO_VIOLATION must fire the gate regardless of streak arithmetic"
    )
    assert len(k.steering_calls) == 1


def test_bt2_gate_failure_is_advisory(monkeypatch):
    k = _Kernel()
    plan, queue = _queue_with_envelopes([
        ("repeat_of_s1", "matched", "circling"),
        ("repeat_of_s1", "matched", "circling"),
    ])
    # break the detector import path — the gate must treat it as below-threshold
    import backend.agent.tool_envelope as te

    def _boom(*a, **kw):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr(te, "evaluate_streak", _boom)
    assert not k._der_streak_gate(plan, queue, "sess")
    assert k.steering_calls == []


# ── BT-3: embed warm — failure swallowed, success encodes warmup ────────────


def _extract_warm_coroutine():
    import ast
    import asyncio
    from pathlib import Path

    src = Path(__file__).resolve().parents[3] / "backend" / "main.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_warm_embedding_service":
            code = compile(ast.Module(body=[node], type_ignores=[]), "<warm>", "exec")
            ns = {"asyncio": asyncio, "logger": MagicMock()}
            exec(code, ns)
            return ns["_warm_embedding_service"]
    raise AssertionError("_warm_embedding_service not found in main.py")


def test_bt3_warm_swallows_cold_sidecar_failure():
    import asyncio
    import sys
    import types

    cold = types.ModuleType("backend.memory.embedding")
    cold.get_embedding_service = lambda: (_ for _ in ()).throw(
        RuntimeError("sidecar dead")
    )
    monkeypatch_sys = sys.modules
    saved = monkeypatch_sys.get("backend.memory.embedding")
    monkeypatch_sys["backend.memory.embedding"] = cold
    try:
        warm = _extract_warm_coroutine()
        asyncio.run(warm())  # must NOT raise (AC6.2)
    finally:
        if saved is not None:
            monkeypatch_sys["backend.memory.embedding"] = saved


def test_bt3_warm_encodes_warmup_on_the_shared_singleton():
    import asyncio
    import sys
    import types

    calls = []

    class _Svc:
        def encode(self, text):
            calls.append(text)
            return [0.0] * 8

    warm_mod = types.ModuleType("backend.memory.embedding")
    warm_mod.get_embedding_service = lambda: _Svc()
    saved = sys.modules.get("backend.memory.embedding")
    sys.modules["backend.memory.embedding"] = warm_mod
    try:
        warm = _extract_warm_coroutine()
        asyncio.run(warm())
    finally:
        if saved is not None:
            sys.modules["backend.memory.embedding"] = saved
    assert calls == ["warmup"], "exactly one warmup encode on the singleton"
