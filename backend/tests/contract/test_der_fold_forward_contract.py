"""REQ-13 contract — fold forward, not back.

Pins the split-gate invariant at the REAL ``_der_finalize_step`` boundary
(real instance, stubbed collaborators, event-bus subscription):

  - a weak (non-FAILED) graded score NEVER reaches ``_split_step`` — it folds
    forward to an honest UNVERIFIED label, INCLUDING the REQ-1
    informational-fallback edge where the execution layer reported
    ``success=False`` but the envelope still carried content (AC1/AC2)
  - a genuine unclassified semantic failure (content produced, verification
    judged it wrong) STILL splits (AC3)
  - a classified transport/provider failure (D4/REQ-4) STILL does not split —
    the taxonomy remains the only no-split path for those (AC2)
  - ``queue.mark_complete`` runs exactly once per step regardless of label
    (AC4) — there is no same-step retry

Spec: specs/long-horizon-der-execution/requirements.md REQ-13.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import DirectorQueue, QueueItem


class _CapturingRecorder:
    calls = []

    def __init__(self, *a, **kw):
        pass

    def record_commit(self, **kwargs):
        _CapturingRecorder.calls.append(kwargs)


def _make_stub_kernel(conversation_id: str, split_calls: list) -> AgentKernel:
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = conversation_id
    k._memory_interface = None
    k._trailing_director = None
    k._mcm_orch = None
    k._der_last_u_mag = None
    k._der_work_units = 10
    k._der_live_cad_state = lambda session: {"u": 0.5, "xi": 0.1}
    k._split_step = lambda item, reason, cad, wu, step_result="", verified_fraction=0.0: (
        split_calls.append((item.step_id, reason, wu)) or []
    )
    return k


def _run_finalize(kernel, item, step_result, step_success, queue, verified):
    kernel._verify_step_result = (
        lambda goal, expected, result, tool=None, success=False: verified
    )
    return kernel._der_finalize_step(
        item=item,
        step_result=step_result,
        step_success=step_success,
        step_outputs=[],
        completed_items=[],
        _tokens_used=0,
        _token_budget=10_000,
        _session="sess-t21",
        _turn_id="t1",
        _phase=2,
        is_mature=False,
        _live_ctx=None,
        plan=SimpleNamespace(original_task="do the thing"),
        context_package=None,
        queue=queue,
        verdict=None,
    )


def _make_item(step_id="s1", description="research the topic"):
    return QueueItem(
        step_id=step_id, step_number=1, description=description,
        tool="run_command", params={}, critical=False,
        objective_anchor="do the thing", expected_output="evidence",
    )


@pytest.fixture(autouse=True)
def _patches(monkeypatch):
    _CapturingRecorder.calls = []
    monkeypatch.setattr(
        "backend.agent.caducean_trajectory.get_trajectory_recorder",
        lambda mi: _CapturingRecorder(),
    )
    from backend.agent.event_bus import get_event_bus

    bus = SimpleNamespace(emitted=[])

    def _emit(event, data=None, **kw):
        bus.emitted.append((getattr(event, "value", str(event)), data or {}))

    monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: bus)
    return bus


class TestFoldForwardContract:
    def test_weak_unverified_score_never_reaches_split_step(self, _patches):
        """REQ-13 AC1: UNVERIFIED (weak but non-empty) folds forward — no split,
        honest UNVERIFIED label, exactly-once mark_complete."""
        split_calls = []
        kernel = _make_stub_kernel("conv-unverified", split_calls)
        item = _make_item()
        queue = DirectorQueue(objective="do the thing", items=[item])

        _run_finalize(kernel, item, "found evidence content", True, queue, "UNVERIFIED")

        assert split_calls == [], "a weak UNVERIFIED score must never split"
        assert item.step_id in queue.completed_ids, (
            "the weak step must be marked complete (fold forward), not retried"
        )
        assert len(_CapturingRecorder.calls) == 1
        assert _CapturingRecorder.calls[0]["verified_label"] == "UNVERIFIED", (
            "the fold-forward must carry the honest low-confidence label"
        )

    def test_informational_fallback_envelope_with_weak_score_does_not_split(
        self, _patches
    ):
        """REQ-13 AC1 + REQ-1 AC4 edge: execution layer reported success=False
        but the envelope still carried content and verification judged it weak —
        the explicit `_verified == "FAILED"` gate guard must prevent the split
        that the incidental step_success flag would have allowed."""
        split_calls = []
        kernel = _make_stub_kernel("conv-fallback", split_calls)
        item = _make_item()
        queue = DirectorQueue(objective="do the thing", items=[item])

        _run_finalize(
            kernel, item, "informational fallback content", False, queue, "UNVERIFIED"
        )

        assert split_calls == [], (
            "a content-bearing envelope with a weak score must fold forward, "
            "even when the execution layer flagged success=False"
        )
        assert item.step_id in queue.completed_ids

    def test_genuine_semantic_failure_still_splits(self, _patches):
        """REQ-13 AC3: verification judged the CONTENT wrong (FAILED) with no
        error prefix and no transport class — _split_step stays reachable."""
        split_calls = []
        kernel = _make_stub_kernel("conv-semantic", split_calls)
        item = _make_item()
        queue = DirectorQueue(objective="do the thing", items=[item])

        _run_finalize(
            kernel, item, "substantive but wrong content", True, queue, "FAILED"
        )

        assert split_calls == [("s1", "verify_failed", 10)], split_calls
        assert item.step_id in queue.completed_ids

    def test_classified_transport_failure_does_not_split(self, _patches):
        """REQ-13 AC2: the D4/REQ-4 taxonomy remains the ONLY no-split path for
        classified transport/provider failures — an errored envelope classifies
        (transient) and is recorded, never split."""
        split_calls = []
        kernel = _make_stub_kernel("conv-transport", split_calls)
        item = _make_item()
        queue = DirectorQueue(objective="do the thing", items=[item])

        _run_finalize(
            kernel, item, "error: upstream timed out after 30s", False, queue, "FAILED"
        )

        assert split_calls == [], "a classified transport failure must not split"
        assert item.step_id in queue.completed_ids

    def test_mark_complete_runs_exactly_once_per_label(self, _patches):
        """REQ-13 AC4: every verified label (VERIFIED / UNVERIFIED / FAILED)
        passes through mark_complete exactly once — no same-step retry path."""
        for verified in ("VERIFIED", "UNVERIFIED", "FAILED"):
            split_calls = []
            kernel = _make_stub_kernel(f"conv-{verified}", split_calls)
            item = _make_item(step_id=f"step-{verified}")
            queue = DirectorQueue(objective="do the thing", items=[item])

            _run_finalize(
                kernel, item, "some output content", True, queue, verified
            )

            assert queue.completed_ids.count(item.step_id) == 1, (
                f"{verified}: mark_complete must run exactly once per step"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
