"""REQ-26 contract — the Bayesian update is a real posterior, region-scoped.

Pins the (coordinate-region, mediator) edge contract at the REAL
``EdgeScorer`` boundary (real CoordinateStore, real instance, real
BehavioralPredictor — no mocks on the update path):

  - AC3 (read-after-write): a miss write changes the edge score, and the NEXT
    ranking of that region reflects it (the decision reads the updated score
    as its prior — this is what closes the loop).
  - AC5 (unseen-pair prior): a brand-new (region, mediator) pair starts at the
    recorded ``_UNSEEN_PAIR_PRIOR`` (0.5), never at an accident of
    initialization — first-encounter behavior is a decision.
  - AC4 (no hardcoded retry): repeated failure changes ONLY the score; the
    next mediator choice comes from the ranking, and the scoring method
    itself contains no "retry the failed tool" branch.
  - AC7 (decay is forgetting, not observation): apply_decay lowers the score
    but NEVER increments observation_count and never counts as a miss.

Spec: specs/der-dag-inversion/requirements.md REQ-26 (amendment, Wave 1.2).
"""

from __future__ import annotations

import sqlite3
import struct
import time
import uuid

import pytest

from backend.memory.mycelium.interpreter import BehavioralPredictor
from backend.memory.mycelium.scorer import EdgeScorer, _UNSEEN_PAIR_PRIOR
from backend.memory.mycelium.store import CoordinateStore


def _make_mem_conn() -> sqlite3.Connection:
    """In-memory Mycelium store with the REQ-26 observation_count column."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE mycelium_nodes (
            node_id TEXT PRIMARY KEY, space_id TEXT, coordinates BLOB,
            label TEXT, confidence REAL, access_count INTEGER DEFAULT 0,
            created_at REAL, updated_at REAL, last_accessed REAL
        );
        CREATE TABLE mycelium_edges (
            edge_id TEXT PRIMARY KEY, from_node_id TEXT, to_node_id TEXT,
            score REAL DEFAULT 0.5, edge_type TEXT DEFAULT 'traversal',
            traversal_count INTEGER DEFAULT 0, hit_count INTEGER DEFAULT 0,
            miss_count INTEGER DEFAULT 0, decay_rate REAL DEFAULT 0.01,
            created_at REAL, last_traversed REAL,
            observation_count INTEGER DEFAULT 0
        );
        """
    )
    conn.commit()
    return conn


def _insert_node(
    conn: sqlite3.Connection,
    space_id: str,
    label: str,
    coords: list,
) -> str:
    nid = str(uuid.uuid4())
    blob = struct.pack(f">{len(coords)}f", *coords)
    now = time.time()
    conn.execute(
        "INSERT INTO mycelium_nodes VALUES (?,?,?,?,?,1,?,?,?)",
        (nid, space_id, blob, label, 0.7, now, now, now),
    )
    conn.commit()
    return nid


def _insert_edge(
    conn: sqlite3.Connection,
    from_id: str,
    to_id: str,
    score: float = 0.5,
    edge_type: str = "tool_choice",
) -> str:
    edge_id = str(uuid.uuid4())
    now = time.time()
    conn.execute(
        "INSERT INTO mycelium_edges "
        "(edge_id, from_node_id, to_node_id, score, edge_type, decay_rate, "
        " created_at, last_traversed) "
        "VALUES (?,?,?,?,?,0.01,?,?)",
        (edge_id, from_id, to_id, score, edge_type, now, now),
    )
    conn.commit()
    return edge_id


def _edge(conn: sqlite3.Connection, edge_id: str) -> tuple:
    row = conn.execute(
        "SELECT score, observation_count, hit_count FROM mycelium_edges "
        "WHERE edge_id = ?",
        (edge_id,),
    ).fetchone()
    assert row is not None, f"edge {edge_id} missing"
    return row


def _region_mediator_edge(
    conn: sqlite3.Connection, from_id: str, mediator: str
) -> str:
    row = conn.execute(
        """SELECT e.edge_id FROM mycelium_edges e
           JOIN mycelium_nodes m ON m.node_id = e.to_node_id
           WHERE e.from_node_id = ? AND m.label = ? AND m.space_id = 'toolpath'""",
        (from_id, mediator),
    ).fetchone()
    assert row is not None, f"no (region, mediator) edge for {from_id} -> {mediator}"
    return row[0]


class TestReadAfterWriteAcrossDecisionBoundary:
    """REQ-26 AC3 — the contract test that proves the loop CLOSES: a score
    write is readable by the next decision in that region."""

    def test_miss_changes_score_and_next_ranking_reflects_it(self):
        conn = _make_mem_conn()
        store = CoordinateStore(conn)
        region_a = _insert_node(conn, "context", "A", [0.1, 0.2, 0.3, 0.4])
        m = _insert_node(conn, "toolpath", "run_command", [0.1, 0.2, 0.3, 0.4])
        x = _insert_node(conn, "toolpath", "other_tool", [0.1, 0.2, 0.3, 0.4])
        edge_a_m = _insert_edge(conn, region_a, m, score=0.5)
        edge_a_x = _insert_edge(conn, region_a, x, score=0.45)

        # Baseline: M is the top-ranked mediator in region A (0.5 > 0.45).
        ranked = [e.to_node_id for e in store.get_outbound_edges(region_a)]
        assert ranked[0] == m, f"baseline: M must lead region A, got {ranked}"

        # WRITE: 5 repeated misses for M in region A.
        scorer = EdgeScorer(store)
        for _ in range(5):
            scorer.record_region_mediator_outcome(region_a, "run_command", "miss")

        # READ: the score changed...
        score, obs, _ = _edge(conn, edge_a_m)
        assert score < 0.4, f"score must drop below 0.4 after 5 misses, got {score}"
        assert obs == 5, f"observation_count must be 5, got {obs}"

        # ...and the NEXT ranking of region A reflects it: X now leads, M
        # fell to second place.
        ranked_after = [e.to_node_id for e in store.get_outbound_edges(region_a)]
        assert ranked_after[0] == x, (
            f"read-after-write: the next ranking in region A must reflect the "
            f"misses (X leads, M dropped), got {ranked_after}"
        )
        assert ranked_after.index(m) > ranked_after.index(x)

        # The DECISION (BehavioralPredictor) reads the updated score as its
        # prior: M is no longer the top predicted tool for region A.
        preds = BehavioralPredictor().predict(
            session_id="sess-ct", current_node_ids=[region_a],
            task_class="code", completed_tools=[], conn=conn,
        )
        assert preds and preds[0] == "other_tool", (
            f"the next decision must read the updated score: top prediction "
            f"for region A is {preds} (expected other_tool first)"
        )

    def test_observation_count_is_region_scoped(self):
        """The same mediator in a DIFFERENT region keeps its own count — the
        edge, not a global per-tool tally, carries the evidence."""
        conn = _make_mem_conn()
        store = CoordinateStore(conn)
        region_a = _insert_node(conn, "context", "A", [0.1, 0.2, 0.3, 0.4])
        region_b = _insert_node(conn, "context", "B", [0.8, 0.7, 0.6, 0.5])
        m = _insert_node(conn, "toolpath", "run_command", [0.5, 0.5, 0.5, 0.5])
        edge_b_m = _insert_edge(conn, region_b, m, score=0.5)

        scorer = EdgeScorer(store)
        for _ in range(5):
            scorer.record_region_mediator_outcome(region_a, "run_command", "miss")

        _, obs_b, _ = _edge(conn, edge_b_m)
        assert obs_b == 0, (
            f"region B's edge for the SAME mediator must carry 0 observations "
            f"(the update site selects the (A, M) edge, never a global tally), "
            f"got {obs_b}"
        )


class TestUnseenPairPrior:
    """REQ-26 AC5 — the prior for an unseen (region, mediator) pair is
    explicit and recorded, so first-encounter behavior is a decision."""

    def test_fresh_pair_starts_at_recorded_prior(self):
        assert _UNSEEN_PAIR_PRIOR == 0.5, (
            "the unseen-pair prior is a recorded decision; changing it must "
            "change this test"
        )
        conn = _make_mem_conn()
        store = CoordinateStore(conn)
        region = _insert_node(conn, "context", "A", [0.1, 0.2, 0.3, 0.4])

        # First encounter: one hit on the fresh pair. The edge did not exist
        # before this call — it is created at the prior 0.5, then the first
        # observation lands at full strength (+0.05).
        EdgeScorer(store).record_region_mediator_outcome(
            region, "fresh_tool", "hit"
        )
        edge_id = _region_mediator_edge(conn, region, "fresh_tool")
        score, obs, _ = _edge(conn, edge_id)
        assert score == pytest.approx(0.5 + 0.05, abs=1e-6), (
            f"first hit on an unseen pair must start from the prior 0.5 and "
            f"apply the full first observation: got {score}"
        )
        assert obs == 1


class TestNoHardcodedRetry:
    """REQ-26 AC4 — failure changes the score, never a retry branch."""

    def test_scoring_method_has_no_retry_branch(self):
        import inspect

        from backend.agent.agent_kernel import AgentKernel

        src = inspect.getsource(AgentKernel._der_score_step_outcome)
        lowered = src.lower()
        for banned in ("retry", "re-queue", "requeue", "_split_step", "same_tool"):
            assert banned not in lowered, (
                f"REQ-26 AC4: {banned} found in _der_score_step_outcome — the "
                f"scoring path must ONLY update the score; recovery is a "
                f"separate decision (REQ-24), never an inline retry branch"
            )


class TestDecayIsNotAnObservation:
    """REQ-26 AC7 — decay is forgetting, not a miss; it never inflates the
    evidence count."""

    def test_decay_moves_score_but_not_observation_count(self):
        conn = _make_mem_conn()
        store = CoordinateStore(conn)
        region = _insert_node(conn, "context", "A", [0.1, 0.2, 0.3, 0.4])
        m = _insert_node(conn, "toolpath", "run_command", [0.1, 0.2, 0.3, 0.4])
        edge_id = _insert_edge(conn, region, m, score=0.5)

        EdgeScorer(store).record_outcome([edge_id], "hit")
        score_before, obs_before, hits_before = _edge(conn, edge_id)
        assert score_before == pytest.approx(0.55, abs=1e-6)
        assert obs_before == 1
        assert hits_before == 0  # region-scored path never bumps hit_count

        # Backdate last_traversed so decay actually moves the score.
        old = time.time() - 20 * 86400
        conn.execute(
            "UPDATE mycelium_edges SET last_traversed = ? WHERE edge_id = ?",
            (old, edge_id),
        )
        conn.commit()

        pruned = EdgeScorer(store).apply_decay()
        score_after, obs_after, _ = _edge(conn, edge_id)

        assert pruned == 0, "edge must survive decay (score well above PRUNE_THRESHOLD)"
        assert score_after < score_before, (
            f"decay must lower the score ({score_before} -> {score_after})"
        )
        assert obs_after == obs_before, (
            f"REQ-26 AC7: decay must never inflate observation_count "
            f"({obs_before} -> {obs_after})"
        )
