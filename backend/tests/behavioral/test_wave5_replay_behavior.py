"""BT-4..BT-5 (specs/tool-result-envelope Wave 5 gate TG-5).

Behavioral: drive the REAL finalize path with a kernel whose heavy
collaborators are stubbed, replaying the conv-102 trajectory (one wiki seed
dispatched 3x, identical bodies, a dead fetch), and assert EMERGENT
properties: identical evidence recognized across different URLs, the 4th
dispatch refused, the ledger rendered without bodies, recovery opened with
unvisited seeds, grade reported once per turn — plus the hang drive (a stuck
clock fails closed, never silent). No live web, no live model.

Twin fixtures in contract/test_wave5_ledger_contract.py (intertwined rule).
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.agent.der_loop import DirectorQueue, QueueItem
from backend.agent.tool_envelope import evaluate_streak


# ── shared conv-102 trajectory (twin: test_wave5_ledger_contract.py) ─────────

WIKI = "https://github.com/ggerganov/whisper.cpp/wiki"
PARA_NOTES = "https://other.example/parakeet-notes"
BODY_A = (("whisper.cpp streaming support implementation approach limitations " * 12).strip()
          + " see https://github.com/ggml-org/whisper.cpp"
          + " and https://arxiv.org/abs/2400.12345 for background.")
TAIL_MARKER = "TAIL-MARKER-NEVER-IN-PROMPT-9e77"


def _result(seed, body, attempted=None, outlinks=()):
    text = f"--- Source: {seed} ---\n{body}"
    text += "\n\n--- Attempted: " + " ".join(attempted or [seed])
    if outlinks:
        text += "\n--- Outlinks (uncrawled candidates):"
        for u in outlinks:
            text += f"\n  - {u}"
    return text


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Kernel:
    """Kernel stand-in binding the REAL finalize + ledger + recovery + grade."""

    def __init__(self):
        from backend.agent.agent_kernel import AgentKernel

        self.conversation_id = "conv_bt5"
        self._memory_interface = MagicMock()
        self._mcm_orch = None
        self._der_crawled_urls = {}
        self._der_crawled_steps = {}
        self._der_seen_dispatches = {}
        self._der_envelope_registry = {}
        self._der_body_hashes = {}
        self._der_dead_urls = {}
        self._der_recovery_opened = {}
        self._der_last_run_grade = None
        self.steering_calls = []
        for name in (
            "_der_finalize_step", "_der_build_step_envelope",
            "_der_streak_gate", "_der_visited_block",
            "_build_planning_prompt", "_der_maybe_open_recovery",
            "_der_report_run_grade", "_der_tool_deadline",
            # Session-326 added the card-settle emit INSIDE _der_report_run_grade
            # (agent_kernel.py:5976). The stub binds the REAL grade method, so it
            # must carry that method's real dependency or the grade path raises
            # AttributeError and the outer except at :5978 returns "" instead of
            # the computed grade. Fixture drift, not a behavior change: no
            # assertion in this file was touched.
            "_der_emit_card_settle",
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
        item=item, step_result=result, step_success=success, step_outputs=[],
        completed_items=completed, _tokens_used=100, _token_budget=10000,
        _session="sess", _turn_id="t-bt4", _phase=2, is_mature=False,
        _live_ctx=None, plan=plan, context_package=None, queue=queue,
        verdict=None,
    )


def _item(sid, num, desc, query, crit="supporting", expected=""):
    it = QueueItem(
        step_id=sid, step_number=num, description=desc,
        tool="crawler_query", params={"query": query},
    )
    it.declared_criticality = crit
    if expected:
        it.expected_output = expected
    return it


# ── BT-4: conv-102 replay — identical evidence recognized, 4th refused ───────


def test_bt4_replay_recognizes_repeats_refuses_recrawl_renders_ledger():
    k = _Kernel()
    plan = _plan()
    queue = DirectorQueue(objective=plan.original_task, items=[])
    completed = []

    s1 = _item("s1", 1, "research whisper.cpp streaming", "whisper.cpp streaming")
    _run_finalize(k, queue, s1, _result(WIKI, BODY_A), True, completed)
    completed.append(s1)
    # s2: same seed, different query — conv-102's exact shape (URL repeat)
    s2 = _item("s2", 2, "research WhisperX streaming", "WhisperX streaming",
               crit="load-bearing", expected="whisperx vod transcode pricing")
    _run_finalize(k, queue, s2, _result(WIKI, BODY_A), True, completed)
    completed.append(s2)
    # s3: DIFFERENT url, SAME body — the near-duplicate the old system missed
    s3 = _item("s3", 3, "research Parakeet streaming", "Parakeet streaming")
    _run_finalize(k, queue, s3, _result(PARA_NOTES, BODY_A), True, completed)
    completed.append(s3)

    assert s1.envelope.novelty == "new"
    assert s2.envelope.novelty.startswith("repeat_of_")
    # the hash witness: different address, identical groceries
    assert s3.envelope.novelty == "repeat_of_s1", s3.envelope.novelty

    # the 4th dispatch for the same seed is refused in-process
    from backend.crawler.orchestrator import CrawlOrchestrator

    visited = set(k._der_crawled_urls.get("conv_bt5", set()))
    assert WIKI in visited and PARA_NOTES in visited
    assert CrawlOrchestrator()._exclude_visited([WIKI], visited, "j", "t") == []

    # the ledger renders in the planning prompt — pointers only
    prompt = k._build_planning_prompt(
        task="research streaming STT",
        context=[{"role": "user", "content": BODY_A + " " + TAIL_MARKER}],
    )
    # the ledger renders in the planning prompt — pointers only. History
    # legitimately echoes user text, so absence is asserted on the VISITED
    # block itself, not the whole prompt.
    assert "VISITED THIS TURN" in prompt and WIKI in prompt
    block_section = prompt.split("VISITED THIS TURN")[1]
    assert TAIL_MARKER not in block_section and BODY_A not in block_section

    # grade: s2's load-bearing mismatch caps the run; reported once per turn
    from backend.agent.agent_kernel import AgentKernel

    assert s2.envelope.match == "mismatched"
    g1 = k._der_report_run_grade(completed, "t-bt4", "bt4")
    g2 = k._der_report_run_grade(completed, "t-bt4", "bt4")
    assert g1 == g2 == "capped"
    assert k._der_last_run_grade["turn_id"] == "t-bt4"


def test_bt4_no_premature_grade_on_empty_queue():
    # The finalize-complete grade site must not fire on a vacuously
    # complete (empty) queue — that stamped a premature PASS mid-run.
    k = _Kernel()
    plan = _plan()
    queue = DirectorQueue(objective=plan.original_task, items=[])
    completed = []
    s1 = _item("s1", 1, "research whisper.cpp streaming", "whisper.cpp streaming")
    _run_finalize(k, queue, s1, _result(WIKI, BODY_A), True, completed)
    completed.append(s1)
    assert k._der_last_run_grade is None


def test_bt4_dead_fetch_opens_recovery_with_unvisited_seeds():
    k = _Kernel()
    plan = _plan()
    queue = DirectorQueue(objective=plan.original_task, items=[])
    completed = []
    dead_res = (
        "--- Attempted: https://dead.example/old-page ---\n"
        "--- Outlinks (uncrawled candidates):\n"
        "  - https://dead.example/new-page\n"
    )
    s1 = _item("s1", 1, "research dead site docs", "dead site docs")
    _run_finalize(k, queue, s1, dead_res, False, completed, verified="FAILED")
    completed.append(s1)

    recs = [it for it in queue.items if getattr(it, "recovery_of", "")]
    assert len(recs) == 1
    rec = recs[0]
    assert rec.recovery_of == "s1"
    assert "https://dead.example/old-page" not in rec.recovery_seeds
    assert "https://dead.example/new-page" in rec.recovery_seeds


# ── BT-5: hang drive — a stuck clock fails closed ─────────────────────────────


def test_bt5_hanging_tool_settles_as_timeout_and_caps_grade():
    from backend.agent.tool_decision import ToolDecisionBox
    from backend.agent.tool_envelope import build_envelope

    async def _hang():
        await asyncio.sleep(3)  # orphan outlives the test's wait (documented)

    t0 = time.monotonic()
    with pytest.raises(BaseException):
        _run(ToolDecisionBox._run_async(_hang(), timeout_s=0.2))
    assert time.monotonic() - t0 < 10  # fails closed, never hangs the suite

    env = build_envelope(
        result_text="[STEP TIMEOUT after 90s]", step_success=False,
        outcome="FAILED", expected_output="fresh sources",
        tool="crawler_query", params_digest="p", verified_fraction=0.0,
        prev_verified_fraction=None, raw_doc_id="", coords_from=None,
        coords_to=None, turn_memory={}, timeout=True, elapsed_s=90.0,
    )
    assert env.status == "timeout" and env.suggestion == "try_different"
    w = {"status": "timeout", "novelty": "new", "match": "unclear",
         "stuck_shape": "flat_tire"}
    fired, _ = evaluate_streak(
        [{"status": "timeout", "novelty": "empty", "match": "unclear",
          "stuck_shape": "dry_well"}, dict(w)], 2, 2,
    )
    assert fired  # timeouts streak like empties — the gate sees the hang
