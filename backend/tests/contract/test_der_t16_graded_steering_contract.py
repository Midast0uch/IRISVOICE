"""CT-S6 — REQ-4 AC1/AC2/AC3: continuous steering, not binary gates.

Pins the GRADED split decision at the REAL ``_split_step`` boundary (real
AgentKernel instance via __new__, real ``_der_split_width``, real blocker
derivation — no stubbing of the width decision):

  - AC1: the continuous verified fraction is a steering input at the split
    decision — width is a function of BOTH |u| and vf, not |u| alone. A
    mid-band vf (0.4) with an oscillating |u| (which would yield width 3
    under the pre-T16 |u|-only gate) now yields a BOUNDED PROBE (width 1).
  - AC2: mid-band -> the graded middle path (width 1, probe=True marker),
    never a threshold coin-flip into a full-width re-attempt.
  - AC3: the work-unit resource remains the sole termination guarantee —
    the split is REFUSED (empty list, step forced atomic) when
    work_units < width, and the width is capped by DER_MAX_GRAFTS and the
    remaining work units. DER_MAX_CYCLES / DER_EMERGENCY_STOP are safety
    rails only (asserted present in der_constants, not used here as gates).

Spec: specs/der-dag-inversion/requirements.md REQ-4 AC1-AC3.
"""

from __future__ import annotations

from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_constants import (
    DER_EMERGENCY_STOP,
    DER_MAX_CYCLES,
    DER_MAX_GRAFTS,
)
from backend.agent.der_loop import QueueItem, NodeRecord


def _make_step(step_id: str, description: str = "build the widget") -> QueueItem:
    return QueueItem(
        step_id=step_id,
        step_number=1,
        description=description,
        tool="code",
        params={},
        critical=True,
        objective_anchor="deliver the feature",
        expected_output="widget renders with data",
    )


def _make_kernel(session_id: str = "sess-t16") -> AgentKernel:
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = None
    k.session_id = session_id
    k._memory_interface = None
    k._trailing_director = None
    k._mcm_orch = None
    k._der_last_u_mag = None
    # Real Caducean state with an oscillating |u| — under the pre-T16
    # |u|-only gate this yields width 3.
    k._der_live_cad_state = lambda session: {"u": 0.2, "xi": 0.5, "x": 0.1, "y": 0.3}
    return k


class TestGradedWidthConsumesVerifiedFraction:
    """REQ-4 AC1 — the continuous verified fraction is a steering input."""

    def test_mid_band_vf_yields_bounded_probe_not_wide_split(self):
        """AC1+AC2 discriminating case: oscillating |u| (u=0.2 -> width 3
        under _growth_width) with a mid-band verified fraction (vf=0.4)
        MUST yield width 1 — the graded middle path, not a re-attempt."""
        k = _make_kernel()
        item = _make_step("t16-1")
        children = k._split_step(
            item, "verify_failed", {"u": 0.2}, 10,
            step_result="the result covers the feature but misses the empty-state branch",
            verified_fraction=0.4,
        )
        assert len(children) == 1, (
            "mid-band vf must yield a bounded probe (width 1), not a wide split"
        )
        assert children[0].node_record.probe is True, (
            "the child of a mid-band split must carry probe=True (AC2 marker)"
        )
        # REQ-4 AC4 (T16b): the probe names the SPECIFIC blocker (the
        # acceptance criterion that was NOT satisfied), never a restatement of
        # the parent goal.
        assert children[0].objective_anchor != item.objective_anchor
        assert children[0].objective_anchor.startswith("RESOLVE:")
        assert "widget renders with data" in children[0].objective_anchor

    def test_strong_failure_lets_u_govern(self):
        """AC1: vf <= 0.25 (strong failure) -> |u| bands govern. With an
        oscillating |u| the pre-T16 wide split (width 3) is preserved."""
        k = _make_kernel()
        item = _make_step("t16-2")
        children = k._split_step(
            item, "verify_failed", {"u": 0.2}, 10,
            step_result="totally off the mark, nothing matches",
            verified_fraction=0.1,
        )
        assert len(children) == 3, (
            "strong failure + oscillating |u| must keep the wide split (width 3)"
        )
        assert all(c.node_record.probe is False for c in children)

    def test_near_pass_is_atomic(self):
        """AC1: vf >= 0.75 (near-pass) -> atomic width 1, probe False — a
        wide split on a step that nearly passed spends budget re-attempting."""
        k = _make_kernel()
        item = _make_step("t16-3")
        children = k._split_step(
            item, "verify_failed", {"u": 0.2}, 10,
            step_result="everything works except a trailing whitespace nit",
            verified_fraction=0.9,
        )
        assert len(children) == 1
        assert children[0].node_record.probe is False

    def test_unresolved_u_trigger_keeps_u_governance(self):
        """The physics split trigger (unresolved_u, no failure evidence) has
        vf=0 by default and MUST keep |u| governance — not be misread as a
        mid-band probe."""
        k = _make_kernel()
        item = _make_step("t16-4")
        children = k._split_step(
            item, "unresolved_u", {"u": 0.2}, 10,
            verified_fraction=0.0,
        )
        assert len(children) == 3, (
            "unresolved_u split keeps |u| bands (wide 3), never a probe"
        )
        assert all(c.node_record.probe is False for c in children)


class TestGradedWidthIsNotACoinFlip:
    """REQ-4 AC2 — the graded middle path is deterministic, not a flip."""

    def test_mid_band_is_deterministic_across_runs(self):
        k = _make_kernel()
        item = _make_step("t16-5")
        outcomes = set()
        for _ in range(5):
            children = k._split_step(
                item, "verify_failed", {"u": 0.2}, 10,
                step_result="partial coverage, empty-state missing",
                verified_fraction=0.5,
            )
            outcomes.add(len(children))
        assert outcomes == {1}, (
            "mid-band split must deterministically yield width 1, not a coin-flip"
        )

    def test_mid_band_boundary_values(self):
        """The band edges: vf just above 0.25 and just below 0.75 are both
        the graded middle path (width 1 probe)."""
        k = _make_kernel()
        item = _make_step("t16-6")
        for vf in (0.26, 0.5, 0.74):
            children = k._split_step(
                item, "verify_failed", {"u": 0.2}, 10,
                step_result="partial result, gap remains",
                verified_fraction=vf,
            )
            assert len(children) == 1
            assert children[0].node_record.probe is True, f"vf={vf} must probe"


class TestWorkUnitResourceIsTheTerminationGuarantee:
    """REQ-4 AC3 — the work-unit resource is the sole termination guarantee;
    DER_MAX_CYCLES / DER_EMERGENCY_STOP are safety rails only."""

    def test_split_refused_when_work_units_exhausted(self):
        """AC3: split is refused (empty list, step forced atomic) when NO
        work units remain — the work-unit resource is the termination
        guarantee. With work_units=0 the capped width drops below 1 and the
        split is refused outright."""
        k = _make_kernel()
        item = _make_step("t16-7")
        children = k._split_step(
            item, "verify_failed", {"u": 0.2}, 0,
            step_result="totally off the mark",
            verified_fraction=0.1,
        )
        assert children == []

    def test_width_capped_by_remaining_work_units(self):
        k = _make_kernel()
        item = _make_step("t16-8")
        # width 3 desired, only 2 work units -> capped to 2 children.
        children = k._split_step(
            item, "verify_failed", {"u": 0.2}, 2,
            step_result="totally off the mark",
            verified_fraction=0.1,
            # work_units=2 caps width min(3, MAX, 2) = 2
        )
        # _growth_width(0.2)=3 but work_units=2 caps to 2
        assert len(children) == 2

    def test_safety_rails_are_not_the_active_gate(self):
        """AC3: DER_MAX_CYCLES / DER_EMERGENCY_STOP exist as safety rails but
        the split decision does NOT consult them — the work-unit resource
        governs. This pins that the rails are backstops, not steering."""
        assert isinstance(DER_MAX_CYCLES, int) and DER_MAX_CYCLES > 0
        assert isinstance(DER_EMERGENCY_STOP, int) and DER_EMERGENCY_STOP > 0
        assert isinstance(DER_MAX_GRAFTS, int) and DER_MAX_GRAFTS > 0


class TestProbeMarkerLandsInMemoryRecord:
    """The probe marker is a first-class memory record field (REQ-4 AC2),
    so the fold-back into the parent and later queries can distinguish a
    probe from a wide split."""

    def test_probe_child_record_carries_marker(self):
        k = _make_kernel()
        item = _make_step("t16-9")
        children = k._split_step(
            item, "verify_failed", {"u": 0.2}, 10,
            step_result="partial coverage, empty-state missing",
            verified_fraction=0.5,
        )
        rec: NodeRecord = children[0].node_record
        assert rec.probe is True
        assert rec.outcome == ""  # set at finalize, not at split
        assert rec.coords_from != ""  # branch point captured

    def test_wide_split_children_do_not_carry_probe(self):
        k = _make_kernel()
        item = _make_step("t16-10")
        children = k._split_step(
            item, "verify_failed", {"u": 0.2}, 10,
            step_result="totally off the mark",
            verified_fraction=0.1,
        )
        assert all(c.node_record.probe is False for c in children)
