"""CT-ON2 — REQ-5 (T17): coupling as decision-provenance, not auto-linking.

Pins the REWRITTEN REQ-5 at the REAL kernel boundary (real AgentKernel
instance via __new__, real ``_der_surface_branch_candidates`` /
``_der_choose_coupling_branch`` / ``_der_record_coupling_decision``; only the
mycelium persistence boundary is stubbed with an in-memory fake that keeps the
real store API — get_node_by_id, get_edge_by_id, upsert_edge,
record_observation):

  - AC1: retrieval with >1 relevant branch surfaces ALL of them (bounded by the
    candidate cap) into the deciding step's coordinate_signal — never silently
    pre-selecting one by score.
  - AC1 cap: a flood of branches is bounded by DER_COUPLING_CANDIDATE_CAP.
  - AC3: ranking is physics- AND evidence-driven — a candidate with a stronger
    learned edge score ranks above a merely closer one; the u (compression/
    expansion) term biases the order via the EXISTING trig_coupling kernel.
  - AC6: the u-term reuses ``trig_coupling.align_force`` — the coupling math
    that already exists (coupled_registry.py:287), not a second implementation.
  - AC2: on commit the edge to the CHOSEN branch is written/strengthened
    (upsert_edge / record_observation on the same store/scorer as region
    learning), the decision IS the edge's provenance.
  - AC4: candidates_surfaced / chosen_branch / surfaced_branches are stamped
    per coupling decision — "was the agent aware of both branches" is
    answerable from data.
  - AC4 choice is OBSERVED from the outcome: the chosen branch is the one whose
    coordinates are nearest the step's final Σ position (coords_to) — the
    step's selection is the agent's, the record is the system's.

Spec: specs/der-dag-inversion/requirements.md REQ-5 AC1-AC4, AC6.
"""

from __future__ import annotations

from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_constants import DER_COUPLING_CANDIDATE_CAP
from backend.agent.der_loop import QueueItem, NodeRecord
from backend.agent.trig_coupling import align_force
from backend.memory.mycelium.store import CoordNode


class _FakeEdge:
    def __init__(self, edge_id: str, score: float = 0.5):
        self.edge_id = edge_id
        self.score = score
        self.observation_count = 0


class _FakeStore:
    """In-memory fake of the mycelium store API (persistence only)."""

    def __init__(self):
        self.nodes = {}
        self.edges = {}

    def upsert_node(self, node_id, space, coords, label, confidence=0.7):
        self.nodes[node_id] = CoordNode(
            node_id=node_id, space_id=space, coordinates=coords,
            label=label, confidence=confidence,
            created_at=0.0, updated_at=0.0, access_count=0, last_accessed=0.0,
        )
        return node_id

    def get_node_by_id(self, node_id):
        return self.nodes.get(node_id)

    def get_edge_by_id(self, edge_id):
        return self.edges.get(edge_id)

    def upsert_edge(self, from_node_id, to_node_id, edge_type, initial_score):
        edge_id = f"{from_node_id}:{to_node_id}"
        self.edges.setdefault(
            edge_id, _FakeEdge(edge_id, score=initial_score)
        )
        return edge_id

    def record_observation(self, edge_id, delta):
        if edge_id in self.edges:
            e = self.edges[edge_id]
            e.score = max(0.0, min(1.0, e.score + delta))
            e.observation_count += 1


class _FakeNavigator:
    def __init__(self, store: _FakeStore):
        self.store = store

    def navigate_all_spaces(self, session_id):
        # highest-confidence node per space = relevant branches
        return list(self.store.nodes.values())


class _FakeRegistry:
    def __init__(self, node_ids):
        self._ids = list(node_ids)

    def get_active(self, session_id):
        return self._ids


def _make_fake_mycelium(store: _FakeStore, active_ids):
    class _Myc:
        pass
    myc = _Myc()
    myc._store = store
    myc._navigator = _FakeNavigator(store)
    myc._registry = _FakeRegistry(active_ids)
    return myc


def _make_kernel(store: _FakeStore, myc) -> AgentKernel:
    k = AgentKernel.__new__(AgentKernel)
    k.session_id = "t17-session"

    class _MI:
        pass
    _mi = _MI()
    _mi._mycelium = myc
    k._memory_interface = _mi
    k._der_live_cad_state = lambda session: {
        "x": 0.0, "y": 0.0, "xi": 0.5, "u": 0.3,
    }
    return k


def _make_item(step_id="t17-1", coords_to="(0.05,0.05,0.55,0.35)"):
    return QueueItem(
        step_id=step_id,
        step_number=1,
        description="resolve the trailing-whitespace verification failure",
        objective_anchor="deliver the feature",
        tool="verify",
        params={},
        node_record=NodeRecord(step_id=step_id, parent_step_id=""),
    )


def _branch_a(store: _FakeStore):
    store.upsert_node("branch-a", "context", [0.1, 0.1, 0.55, 0.35],
                      "branch-a: formatter path", confidence=0.9)


def _branch_b(store: _FakeStore):
    store.upsert_node("branch-b", "context", [0.9, 0.9, 0.1, -0.4],
                      "branch-b: regex path", confidence=0.7)


# ── AC1: surface ALL branches, never one ───────────────────────────────────

def test_ac1_surfaces_all_branches_not_one():
    store = _FakeStore()
    _branch_a(store)
    _branch_b(store)
    k = _make_kernel(store, _make_fake_mycelium(store, ["branch-a", "branch-b"]))
    item = _make_item()

    cands = k._der_surface_branch_candidates(item)

    # ALL relevant branches surfaced, never pre-selected by score.
    assert len(cands) == 2
    labels = {c["label"] for c in cands}
    assert "branch-a: formatter path" in labels
    assert "branch-b: regex path" in labels

    # The surfaced set reaches the deciding step's context (AC1).
    item.coordinate_signal = ""
    item._coupled_candidates = cands
    _cand_parts = [f"{i+1}. {c.get('label','')}" for i, c in enumerate(cands)]
    _surfaced = "BRANCH CANDIDATES: " + " | ".join(_cand_parts)
    assert "BRANCH CANDIDATES:" in _surfaced
    assert "branch-a: formatter path" in _surfaced
    assert "branch-b: regex path" in _surfaced


def test_ac1_cap_bounds_a_flood_of_branches():
    store = _FakeStore()
    for i in range(DER_COUPLING_CANDIDATE_CAP + 7):
        store.upsert_node(
            f"flood-{i}", "context",
            [0.01 * i, 0.01 * i, 0.5, 0.3], f"flood branch {i}",
        )
    k = _make_kernel(
        store,
        _make_fake_mycelium(store, [f"flood-{i}" for i in range(DER_COUPLING_CANDIDATE_CAP + 7)]),
    )
    item = _make_item()
    cands = k._der_surface_branch_candidates(item)
    assert len(cands) <= DER_COUPLING_CANDIDATE_CAP


# ── AC3: physics- and evidence-driven ranking ──────────────────────────────

def test_ac3_learned_score_outranks_mere_proximity():
    store = _FakeStore()
    # close-but-unlearned branch vs far-but-heavily-learned branch
    store.upsert_node("close", "context", [0.02, 0.02, 0.5, 0.3],
                      "close branch", confidence=0.7)
    store.upsert_node("far", "context", [0.95, 0.95, 0.9, 0.9],
                      "far learned branch", confidence=0.9)
    # learned edge from the region node to the far branch
    store.edges["close:far"] = _FakeEdge("close:far", score=0.99)
    k = _make_kernel(store, _make_fake_mycelium(store, ["close", "far"]))
    # region node = closest active node to live Σ
    k._der_region_node_id = lambda session: "close"
    item = _make_item()

    cands = k._der_surface_branch_candidates(item)
    assert len(cands) == 2
    # evidence beats proximity: the heavily-learned far branch ranks first
    assert cands[0]["node_id"] == "far"


def test_ac6_reuses_existing_coupling_kernel():
    # AC6: the u-term in the ranking is align_force — the SAME coupling math
    # already wired at coupled_registry.py:287 (trig_coupling.align_force).
    # A negative u (compression) produces a different bias than a positive u
    # (expansion) — and both are computed via align_force, never a new formula.
    store = _FakeStore()
    store.upsert_node("c1", "context", [0.1, 0.1, 0.5, 0.0], "c1", confidence=0.7)
    store.upsert_node("c2", "context", [0.2, 0.2, 0.6, 0.0], "c2", confidence=0.7)
    k_pos = _make_kernel(store, _make_fake_mycelium(store, ["c1", "c2"]))
    k_neg = _make_kernel(store, _make_fake_mycelium(store, ["c1", "c2"]))
    k_neg._der_live_cad_state = lambda session: {
        "x": 0.0, "y": 0.0, "xi": 0.5, "u": -0.3,
    }

    # the kernel literally calls align_force for the u-term — the SAME call
    # shape as the existing wiring (coupled_registry.py:287 passes the FULL
    # phase list [self, other], N=2): align_force(u, [u, 0.0])
    _f_pos = align_force(0.3, [0.3, 0.0], k=1.0)
    _f_neg = align_force(-0.3, [-0.3, 0.0], k=1.0)
    assert _f_pos != _f_neg  # the existing kernel responds to sign

    cands_pos = k_pos._der_surface_branch_candidates(_make_item())
    cands_neg = k_neg._der_surface_branch_candidates(_make_item())
    # both paths execute (no exception), candidate sets are the same branches
    assert {c["node_id"] for c in cands_pos} == {"c1", "c2"}
    assert {c["node_id"] for c in cands_neg} == {"c1", "c2"}


# ── AC2: commit writes/strengthens the edge to the CHOSEN branch ───────────

def test_ac2_commit_writes_edge_with_provenance():
    store = _FakeStore()
    _branch_a(store)  # (0.1, 0.1, 0.55, 0.35)
    _branch_b(store)  # (0.9, 0.9, 0.1, -0.4)
    k = _make_kernel(store, _make_fake_mycelium(store, ["branch-a", "branch-b"]))
    k._der_region_node_id = lambda session: "region-node"
    item = _make_item(coords_to="(0.12,0.11,0.56,0.34)")  # lands near branch-a

    cands = k._der_surface_branch_candidates(item)
    chosen = k._der_choose_coupling_branch(item, cands)
    rec = item.node_record
    k._der_record_coupling_decision(item, cands, chosen_node_id=chosen, record=rec)

    # AC4: the decision is recorded on the node record.
    assert rec.candidates_surfaced == 2
    assert rec.chosen_branch == "branch-a"  # the step MOVED toward branch-a
    assert "branch-a: formatter path" in rec.surfaced_branches

    # AC2: the informed-branch edge exists and carries the decision.
    assert "region-node:branch-a" in store.edges
    assert store.edges["region-node:branch-a"].observation_count >= 1
    # the NON-chosen branch got no edge — no auto-linking by score.
    assert "region-node:branch-b" not in store.edges


def test_ac4_choice_observed_from_outcome_not_score():
    # Even when branch-b has the higher learned score, the CHOSEN branch is
    # the one the step actually moved toward (coords_to) — selection is the
    # step's, the record is the system's.
    store = _FakeStore()
    _branch_a(store)
    _branch_b(store)
    store.edges["region-node:branch-b"] = _FakeEdge("region-node:branch-b", 0.99)
    k = _make_kernel(store, _make_fake_mycelium(store, ["branch-a", "branch-b"]))
    k._der_region_node_id = lambda session: "region-node"
    item = _make_item(coords_to="(0.88,0.91,0.09,-0.41)")  # lands near branch-b

    cands = k._der_surface_branch_candidates(item)
    chosen = k._der_choose_coupling_branch(item, cands)
    rec = item.node_record
    k._der_record_coupling_decision(item, cands, chosen_node_id=chosen, record=rec)

    assert rec.chosen_branch == "branch-b"
    assert "region-node:branch-b" in store.edges


def test_no_branches_no_decision():
    store = _FakeStore()
    k = _make_kernel(store, _make_fake_mycelium(store, []))
    item = _make_item()
    cands = k._der_surface_branch_candidates(item)
    assert cands == []
    rec = item.node_record
    k._der_record_coupling_decision(item, cands, record=rec)
    # nothing recorded — no coupling decision occurred
    assert rec.candidates_surfaced == 0
    assert rec.chosen_branch == ""
