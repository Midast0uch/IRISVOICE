"""REQ-12 behavioral — the success path synthesizes, never raw-concatenates.

Drives the REAL ``_execute_plan_der`` loop end-to-end (queue construction,
pre-flight, reviewer gate, step execution, post-loop outcome recording) with
boundary stubs, in the same harness shape as the A1/C1 loop tests — but with
the fix those harnesses lack: ``MagicMock()._cancel_requested.is_set()`` is
truthy, so a bare MagicMock kernel breaks out of the loop before any step
executes. Stubbing ``_cancel_requested`` with a False-returning stub is what
lets the loop actually reach the success return.

Assertions (REQ-12 AC1/AC2/AC3/AC4, design.md:473):
  - a successful task with zero failed steps returns the SYNTHESIZED answer,
    not the raw concatenation of step outputs (AC1)
  - the success synthesis consumes the same evidence the failure path
    consumes (plan.original_task + completed step results) (AC2)
  - ``_synthesize_response`` is wired — called on the success path (AC3)
  - when synthesis is unavailable, the return is the deterministic success
    summary mirroring ``_der_deterministic_failure_summary`` (AC4), with the
    synthesis path logged (REQ-18 AC2)

REQ-8 AC1 (T26, supersedes the REQ-12-era evidence assertion): the synthesis
evidence is the COMPRESSED node record (content_summary | done-when |
remaining), not the raw step output — the harness's raw "RESULT_EVIDENCE_OK"
marker must NOT appear in evidence or summaries. Edge case preserved: an item
with NO node record falls back to the raw summary (REQ-8 Edge Cases).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


class _Step:
    step_id = "s1"
    step_number = 1
    description = "search the web for quantum pricing"
    tool = None
    params = {}
    critical = True
    depends_on = []
    # Real PlanStep shape: T8's plan->queue builder reads expected_output to
    # seed the node record's Awareness field.
    expected_output = "quantum pricing found and summarized"


class _Plan:
    original_task = "find quantum computing pricing"
    plan_title = "test plan"
    strategy = "standard"
    steps = [_Step()]


class _StubLiveCtx:
    """Stand-in for LiveContextPackage so the C.1 mid-loop refresh is a no-op."""

    def __init__(self, *a, **k):
        self.package = None

    def refresh(self, item, completed_items):
        pass


def _build_kernel():
    """AgentKernel-shaped MagicMock whose loop can actually run to completion."""
    kernel = MagicMock()
    kernel.session_id = "sess"
    kernel.conversation_id = "conv"
    # CRITICAL: without this, MagicMock()._cancel_requested.is_set() is truthy
    # and the loop breaks before any step executes (the A1/C1 harness defect).
    kernel._cancel_requested = SimpleNamespace(is_set=lambda: False)
    # Skip C.4 mid-loop episodic retrieval + mycelium/episodic post-loop blocks.
    kernel._memory_interface = None
    kernel.resolve_context_window = lambda: 30000
    kernel.clear_turn_trust_flag = MagicMock()
    kernel._reviewer = MagicMock()
    # verdict is a bare namespace: every enum comparison (VETO/REFINE) is False.
    kernel._reviewer.review.return_value = (SimpleNamespace(), None)
    # Deterministic task-level outcome band: 0.9 -> "success".
    kernel._verified_fraction = lambda *a, **k: 0.9
    # Session 245: signature sync ONLY — production `_der_run_step_execution`
    # gained `queue=` (synthesis starvation fix: prior step results now reach
    # the tool-decision evidence). Same maintenance `_fake_finalize` below
    # already carries. No assertion here changes.
    kernel._der_run_step_execution = lambda item, ctx, session, turn, plan, queue=None: (
        "RESULT_EVIDENCE_OK",
        True,
    )

    def _fake_finalize(
        item, step_result, step_success, step_outputs, completed_items,
        _tokens_used, _token_budget, _session, _turn_id, _phase, is_mature,
        _live_ctx, plan, context_package, queue, verdict, from_voice=False,
    ):
        # Mirrors the real _der_finalize_step's structural contract on the
        # success path: append the output, record the item, mark complete.
        step_outputs.append(step_result)
        completed_items.append(item)
        item.result = step_result
        queue.mark_complete(item.step_id)
        return _tokens_used + 200

    kernel._der_finalize_step = _fake_finalize
    kernel._der_handle_step_failure = MagicMock()
    # Harness fix (2026-08-06): the MagicMock kernel auto-stubs
    # _der_check_steering to return a TRUTHY mock, so the loop's
    # `if _steer: ... _steer.get("stop")` branch (agent_kernel.py:5861-5864)
    # aborts before the first step executes (observed: loop reached the
    # zero-steps crawl-failure branch). Stub it to None (no steering).
    kernel._der_check_steering = lambda *a, **kw: None
    # Bind the REAL success-path synthesis (a MagicMock would otherwise
    # auto-stub it and the test would assert against a mock, not the code).
    from backend.agent import agent_kernel

    kernel._der_synthesize_success_outcome = (
        agent_kernel.AgentKernel._der_synthesize_success_outcome.__get__(
            kernel, agent_kernel.AgentKernel
        )
    )
    # REQ-8 AC1 (T26): bind the real compressed-evidence helper too. Without
    # this, the MagicMock kernel auto-stubs `self._der_node_record_evidence`
    # and the synthesis evidence in `task.step_results` becomes a MagicMock —
    # the same auto-stub defect this harness fixes for the synthesis method
    # above. The assertions below are unchanged: the fake finalize sets
    # `item.result = "RESULT_EVIDENCE_OK"` with no node_record, so the real
    # helper's raw fallback returns exactly that.
    kernel._der_node_record_evidence = (
        agent_kernel.AgentKernel._der_node_record_evidence
    )
    return kernel


def _run(kernel):
    from backend.agent import agent_kernel

    with patch(
        "backend.agent.event_bus.get_event_bus", return_value=MagicMock()
    ), patch(
        "backend.ws_manager.get_websocket_manager", return_value=None
    ), patch(
        "backend.memory.live_context.LiveContextPackage", _StubLiveCtx
    ):
        return agent_kernel.AgentKernel._execute_plan_der.__get__(
            kernel, agent_kernel.AgentKernel
        )(plan=_Plan(), context_package=None, session_id="sess", turn_id="t1")


def test_success_path_synthesizes_not_raw_concat(caplog):
    """REQ-12 AC1/AC2/AC3 + REQ-18 AC2: real loop returns the synthesized
    answer (not the raw step output), consuming failure-path evidence, and
    logs that success synthesis ran."""
    from backend.agent import agent_kernel

    kernel = _build_kernel()
    captured = {}

    def _syn(task, results):
        captured["task"] = task
        captured["results"] = results
        return "SYNTHESIZED_ANSWER"

    kernel._synthesize_response = _syn

    with caplog.at_level("INFO", logger="backend.agent.agent_kernel"):
        out = _run(kernel)

    # AC1: synthesized answer, NOT the raw concatenation of step outputs.
    assert out == "SYNTHESIZED_ANSWER", out
    assert out != "RESULT_EVIDENCE_OK"

    # AC3: _synthesize_response was actually called on the success path.
    assert captured.get("task") is not None, "_synthesize_response must be wired"

    # AC2: same evidence as the failure path — original task + step results.
    # REQ-8 AC1 (T26): the evidence is now the COMPRESSED node record, not the
    # raw step output ("RESULT_EVIDENCE_OK" is the raw marker the harness sets
    # on item.result; the queue builder seeds the node_record from the step's
    # description/expected_output, and that seed is what synthesis reads).
    task = captured["task"]
    assert task.user_message == "find quantum computing pricing"
    assert task.step_results == [
        {
            "tool": None,
            "action": "search the web for quantum pricing",
            "result": (
                "summary: search the web for quantum pricing | "
                "done-when: quantum pricing found and summarized | "
                "remaining: search the web for quantum pricing"
            ),
            "success": True,
        }
    ]
    assert captured["results"][0]["result"] == task.step_results[0]["result"]

    # REQ-18 AC2: the success synthesis path is logged.
    assert any(
        "success synthesis ran" in r.message for r in caplog.records
    ), "success synthesis path must be logged"


def test_success_path_deterministic_fallback_when_synthesis_unavailable():
    """REQ-12 AC4: synthesis down on an otherwise-successful task -> the
    deterministic success summary (mirroring _der_deterministic_failure_summary),
    never the raw concatenation."""
    kernel = _build_kernel()
    kernel._synthesize_response = lambda task, results: ""

    out = _run(kernel)

    assert "1/1 steps finished" in out, out
    assert "search the web for quantum pricing" in out, out
    # REQ-8 AC1 (T26): the deterministic summary shows the COMPRESSED node
    # record (done-when from expected_output), never the raw result marker.
    assert "done-when: quantum pricing found and summarized" in out, out
    assert "RESULT_EVIDENCE_OK" not in out, out
    # Never the raw concatenation standing alone as the answer.
    assert out != "RESULT_EVIDENCE_OK"


def test_synthesis_unavailable_returns_empty_and_summary_is_safe():
    """Direct contract: _der_synthesize_success_outcome returns "" when the
    brain synthesis raises/returns empty (caller falls back to the
    deterministic summary); the deterministic summary handles zero evidence."""
    from backend.agent import agent_kernel
    from backend.agent.der_loop import QueueItem

    plan = _Plan()
    item = QueueItem(step_id="s1", step_number=1, description="search the web")
    item.result = "RESULT_EVIDENCE_OK"

    # 1) Raising synthesis -> "" (mirrors _der_synthesize_outcome's "" contract).
    class _DownKernel:
        _synthesize_response = lambda self, task, results: (_ for _ in ()).throw(
            RuntimeError("provider down")
        )

    out = agent_kernel.AgentKernel._der_synthesize_success_outcome(
        _DownKernel(), plan, [item], MagicMock(), "sess"
    )
    assert out == "", "unavailable synthesis must return '' so AC4 fires"

    # 2) Empty synthesis -> "".
    class _EmptyKernel:
        _synthesize_response = lambda self, task, results: ""

    out = agent_kernel.AgentKernel._der_synthesize_success_outcome(
        _EmptyKernel(), plan, [item], MagicMock(), "sess"
    )
    assert out == ""

    # 3) Deterministic success summary is DER-shaped and safe on empty evidence.
    summary = agent_kernel.AgentKernel._der_deterministic_success_summary(
        plan, [item], MagicMock()
    )
    assert "1/1 steps finished" in summary, summary
    assert "search the web" in summary and "RESULT_EVIDENCE_OK" in summary, summary

    empty = agent_kernel.AgentKernel._der_deterministic_success_summary(
        plan, [], MagicMock()
    )
    assert "(no step output)" in empty, empty


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
