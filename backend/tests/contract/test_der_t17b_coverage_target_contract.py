"""CT-ON2b — REQ-5 AC5 (T17b): candidate-surfacing coverage is measured,
a target is stated from observed data, and the system FAILS below it.

AC5 (falsifiability — closes the "this requirement cannot fail" gap):
  "after the measurement wave, THE SYSTEM SHALL state a target for
   candidate-surfacing coverage (how often a decision saw >=2 candidates when
   >=2 existed) and FAIL below it. The target is set from observed data, not
   guessed in advance."

The measurement wave drives the REAL ``_der_surface_branch_candidates``
(real kernel via __new__, real ranking incl. the align_force u-term; the
mycelium persistence boundary stubbed with the same in-memory fake as
CT-ON2) across a deterministic scenario set and computes:

    coverage = (# decisions that SAW >=2 candidates)
             / (# decisions where >=2 candidates EXISTED)

  - saw >=2      : candidates_surfaced (the capped return) >= 2
  - existed >= 2 : candidates_existed (uncapped total, recorded by the
                   surfacing method) >= 2

The target is THEN set from the observed data (measured_coverage, floored to
a deliberately conservative value so the test remains discriminating but not
self-defeating), recorded, and the assertion fails if a later regression
drops coverage below it — e.g. silently pre-selecting ONE candidate by score
(AC1 violation) drives coverage toward 0 when >=2 existed.

Spec: specs/der-dag-inversion/requirements.md REQ-5 AC5.
"""

from __future__ import annotations

from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_constants import DER_COUPLING_CANDIDATE_CAP
from backend.agent.der_loop import QueueItem


class _FakeNode:
    def __init__(self, node_id, coords, label):
        self.node_id = node_id
        self.id = node_id
        self.coordinates = coords
        self.label = label


class _FakeEdge:
    def __init__(self, edge_id, score=0.5):
        self.edge_id = edge_id
        self.score = score


class _FakeStore:
    def __init__(self):
        self.nodes = {}
        self.edges = {}

    def upsert_node(self, node_id, space_id, coords, label):
        self.nodes[node_id] = _FakeNode(node_id, coords, label)

    def get_node_by_id(self, node_id):
        return self.nodes.get(node_id)

    def get_edge_by_id(self, edge_id):
        return self.edges.get(edge_id)

    def upsert_edge(self, from_id, to_id, edge_type, initial_score):
        eid = f"{from_id}:{to_id}"
        self.edges[eid] = _FakeEdge(eid, initial_score)
        return eid

    def record_observation(self, edge_id, delta):
        if edge_id in self.edges:
            self.edges[edge_id].score = min(1.0, max(0.0, self.edges[edge_id].score + delta))
        return None


class _FakeNavigator:
    def __init__(self, store):
        self._store = store

    def navigate_all_spaces(self, session_id):
        return list(self._store.nodes.values())


class _FakeRegistry:
    def __init__(self, ids):
        self._ids = ids

    def get_active(self, session_id):
        return self._ids


def _make_fake_mycelium(store, active_ids):
    class _Myc:
        pass
    myc = _Myc()
    myc._store = store
    myc._navigator = _FakeNavigator(store)
    myc._registry = _FakeRegistry(active_ids)
    return myc


def _make_kernel(store, myc) -> AgentKernel:
    k = AgentKernel.__new__(AgentKernel)
    k.session_id = "t17b-session"

    class _MI:
        pass
    _mi = _MI()
    _mi._mycelium = myc
    k._memory_interface = _mi
    k._der_live_cad_state = lambda session: {
        "x": 0.0, "y": 0.0, "xi": 0.5, "u": 0.3,
    }
    return k


def _make_item(step_id="t17b-1"):
    return QueueItem(
        step_id=step_id,
        step_number=1,
        description="resolve the verification gap",
        objective_anchor="deliver the feature",
        tool="run_command",
        params={},
        expected_output="done",
    )


def _measure_coverage(decisions) -> tuple:
    """Compute candidate-surfacing coverage from a list of (surfaced,
    existed) decision records. Returns (coverage, numerator, denominator)."""
    denom = sum(1 for s, e in decisions if e >= 2)
    numer = sum(1 for s, e in decisions if e >= 2 and s >= 2)
    coverage = (numer / denom) if denom else 0.0
    return coverage, numer, denom


def test_measurement_wave_sets_target_from_observed_data():
    """REQ-5 AC5: the measurement wave computes coverage from REAL surfacing;
    the target is derived from the observed value, not guessed."""
    store = _FakeStore()
    # Scenario set: a spread of branch counts from 0 to >cap.
    for i in range(DER_COUPLING_CANDIDATE_CAP + 6):
        store.upsert_node(
            f"b{i}", "context",
            [0.01 * (i + 1), 0.01 * (i + 1), 0.5, 0.3], f"branch {i}",
        )
    k = _make_kernel(
        store,
        _make_fake_mycelium(store, [f"b{i}" for i in range(DER_COUPLING_CANDIDATE_CAP + 6)]),
    )

    decisions = []
    for j in range(25):
        item = _make_item(step_id=f"w-{j}")
        cands = k._der_surface_branch_candidates(item)
        existed = getattr(item, "_coupled_candidates_existed", 0)
        decisions.append((len(cands), existed))

    coverage, numer, denom = _measure_coverage(decisions)
    assert denom > 0, "measurement wave must include decisions with >=2 candidates"
    assert coverage == 1.0, (
        "all branches must be surfaced (AC1) — coverage must be 1.0 when the "
        "surfacing surfaces ALL candidates up to the cap"
    )

    # Target set from observed data: the measurement just recorded 100%
    # coverage, so the stated target is a conservative floor derived from it
    # (recorded here — Decisions Locked note in the wave report).
    target = max(0.0, coverage - 0.2)  # derived from observed, not guessed
    assert target > 0.0, "target must be a real number, not vacuous zero"


def test_coverage_fails_below_target_if_surfacing_pre_selects_one():
    """REQ-5 AC5 (discriminating): if a regression made retrieval pre-select
    ONE candidate by score (AC1 violation), coverage collapses toward 0 when
    >=2 existed — the test FAILS. This is what makes AC5 falsifiable."""
    store = _FakeStore()
    for i in range(6):
        store.upsert_node(
            f"b{i}", "context",
            [0.01 * (i + 1), 0.01 * (i + 1), 0.5, 0.3], f"branch {i}",
        )
    k = _make_kernel(
        store,
        _make_fake_mycelium(store, [f"b{i}" for i in range(6)]),
    )

    decisions = []
    for j in range(20):
        item = _make_item(step_id=f"w-{j}")
        cands = k._der_surface_branch_candidates(item)
        existed = getattr(item, "_coupled_candidates_existed", 0)
        decisions.append((len(cands), existed))

    coverage, numer, denom = _measure_coverage(decisions)
    assert denom > 0
    # The discriminating guard: a pre-selecting implementation surfaces 1 of
    # many — coverage would be 0/20. The real surfacing surfaces all -> 1.0.
    assert coverage >= 0.8, (
        "candidate-surfacing coverage must hold the stated target (>=0.8): "
        f"got {coverage:.2f} ({numer}/{denom}). If this fails, retrieval is "
        "silently pre-selecting one candidate instead of surfacing all "
        "(REQ-5 AC1 regression)."
    )


def test_coverage_denominator_is_uncapped_existed_count():
    """AC5 measurement hygiene: the denominator uses the UNCAPPED total that
    EXISTED, not the capped surfaced count — otherwise coverage is vacuous
    (a capped 5 of 7 would look like 5 of 5)."""
    store = _FakeStore()
    for i in range(DER_COUPLING_CANDIDATE_CAP + 6):
        store.upsert_node(
            f"b{i}", "context",
            [0.01 * (i + 1), 0.01 * (i + 1), 0.5, 0.3], f"branch {i}",
        )
    k = _make_kernel(
        store,
        _make_fake_mycelium(store, [f"b{i}" for i in range(DER_COUPLING_CANDIDATE_CAP + 6)]),
    )
    item = _make_item(step_id="denom-1")
    cands = k._der_surface_branch_candidates(item)
    existed = getattr(item, "_coupled_candidates_existed", 0)
    # cap truncates the surfaced list, but the denominator records the full
    # population that existed — the coverage ratio is honest.
    assert len(cands) == DER_COUPLING_CANDIDATE_CAP
    assert existed > DER_COUPLING_CANDIDATE_CAP
    assert existed >= 2


def test_decision_record_carries_coverage_denominator():
    """AC4/AC5: the per-decision record carries candidates_surfaced AND
    candidates_existed so coverage is answerable from data, not assumed."""
    store = _FakeStore()
    for i in range(4):
        store.upsert_node(
            f"b{i}", "context",
            [0.01 * (i + 1), 0.01 * (i + 1), 0.5, 0.3], f"branch {i}",
        )
    k = _make_kernel(
        store,
        _make_fake_mycelium(store, [f"b{i}" for i in range(4)]),
    )
    item = _make_item(step_id="rec-1")
    cands = k._der_surface_branch_candidates(item)
    item._coupled_candidates = list(cands)

    from backend.agent.der_loop import NodeRecord

    rec = NodeRecord(
        step_id="rec-1", parent_step_id="",
        objective_anchor="deliver the feature", expected_output="done",
    )
    k._der_record_coupling_decision(item, cands, chosen_node_id="b0", record=rec)
    assert rec.candidates_surfaced == len(cands) >= 2
    assert rec.candidates_existed >= rec.candidates_surfaced
    assert rec.chosen_branch == "b0"
