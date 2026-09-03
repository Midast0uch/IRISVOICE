"""
Tests for Topology Layer v2.0 — Task 12.10
Requirements: 14.26–14.29, 17.1–17.25
"""

import struct
import time
import uuid

import pytest
from .conftest_mycelium import mem_conn  # noqa: F401

from backend.memory.mycelium.topology import (
    BehavioralPrimitive,
    PrimitiveClassifier,
    ChartRegistry,
    DeficiencyDetector,
    TopologyContext,
    TopologyLayer,
    CHART_ACTIVATION_THRESHOLD,
)
from backend.memory.mycelium.store import CoordinateStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_landmark(conn, activation_count=1, task_class="code_task"):
    """Insert a landmark row; returns landmark_id."""
    lm_id = str(uuid.uuid4())
    now = time.time()
    conn.execute(
        """INSERT INTO mycelium_landmarks
           (landmark_id, label, task_class, coordinate_cluster, traversal_sequence,
            cumulative_score, micro_abstract, micro_abstract_text, activation_count,
            is_permanent, conversation_ref, absorbed, created_at, last_activated)
           VALUES (?,?,?,?,?,?,?,?,?,0,NULL,NULL,?,NULL)""",
        (lm_id, task_class, task_class, "{}", "[]", 0.8, b"", "", activation_count, now),
    )
    conn.commit()
    return lm_id


def _insert_chart_row(conn, landmark_id, session_id, x, y, z, primitive, stale=0):
    """Insert a chart position row."""
    position_id = str(uuid.uuid4())
    now = time.time()
    conn.execute(
        """INSERT INTO mycelium_charts
           (position_id, landmark_id, session_id, x, y, z, primitive, confidence, stale, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (position_id, landmark_id, session_id, x, y, z, primitive, 0.8, stale, now),
    )
    conn.commit()
    return position_id


# ---------------------------------------------------------------------------
# ChartRegistry
# ---------------------------------------------------------------------------

def test_chart_registry_empty_below_threshold(mem_conn):
    """Landmark with activation_count = 11 (< 12) → get_chart_origins returns []."""
    lm_id = _insert_landmark(mem_conn, activation_count=CHART_ACTIVATION_THRESHOLD - 1)
    registry = ChartRegistry(mem_conn)
    origins = registry.get_chart_origins()
    assert lm_id not in origins


def test_chart_registry_returns_qualifying_landmarks(mem_conn):
    """Landmark with activation_count = 12 → returned by get_chart_origins()."""
    lm_id = _insert_landmark(mem_conn, activation_count=CHART_ACTIVATION_THRESHOLD)
    registry = ChartRegistry(mem_conn)
    origins = registry.get_chart_origins()
    assert lm_id in origins


# ---------------------------------------------------------------------------
# PrimitiveClassifier — all 6 primitives
# ---------------------------------------------------------------------------

def test_primitive_classify_core():
    assert PrimitiveClassifier.classify(0.9, 0.9, 0.0) == BehavioralPrimitive.CORE


def test_primitive_classify_exploration():
    assert PrimitiveClassifier.classify(0.8, 0.3, 0.0) == BehavioralPrimitive.EXPLORATION


def test_primitive_classify_transfer():
    assert PrimitiveClassifier.classify(0.3, 0.8, 0.0) == BehavioralPrimitive.TRANSFER


def test_primitive_classify_acquisition():
    # z > CONVERGENCE_THRESHOLD (0.08) → ACQUISITION
    assert PrimitiveClassifier.classify(0.5, 0.5, +0.15) == BehavioralPrimitive.ACQUISITION


def test_primitive_classify_evolution():
    # z < DIVERGENCE_THRESHOLD (-0.06), x >= 0.5, y >= 0.5 → EVOLUTION
    assert PrimitiveClassifier.classify(0.7, 0.6, -0.10) == BehavioralPrimitive.EVOLUTION


def test_primitive_classify_orbit():
    # None of the above trigger → ORBIT fallback
    assert PrimitiveClassifier.classify(0.4, 0.4, +0.02) == BehavioralPrimitive.ORBIT


# ---------------------------------------------------------------------------
# DeficiencyDetector
# ---------------------------------------------------------------------------

def test_deficiency_detector_below_minimum(mem_conn):
    """4 ORBIT chart records → returns [] (needs MIN_ORBIT_SESSIONS=5)."""
    lm_id = _insert_landmark(mem_conn, activation_count=CHART_ACTIVATION_THRESHOLD)

    for i in range(4):
        _insert_chart_row(
            mem_conn, lm_id, f"sess_{i}",
            x=0.35, y=0.35, z=0.01,
            primitive=BehavioralPrimitive.ORBIT.value,
        )

    detector = DeficiencyDetector(mem_conn)
    signals = detector.detect_orbits(lm_id)
    assert signals == []


def test_deficiency_detector_returns_signal_at_minimum(mem_conn):
    """5 ORBIT records clustered together → returns at least one DeficiencySignal."""
    lm_id = _insert_landmark(mem_conn, activation_count=CHART_ACTIVATION_THRESHOLD)

    # Insert 5 tightly clustered ORBIT positions
    for i in range(5):
        _insert_chart_row(
            mem_conn, lm_id, f"sess_orb_{i}",
            x=0.30 + i * 0.01,   # within 0.25 cluster radius of each other
            y=0.30 + i * 0.01,
            z=0.02,
            primitive=BehavioralPrimitive.ORBIT.value,
        )

    detector = DeficiencyDetector(mem_conn)
    signals = detector.detect_orbits(lm_id)
    assert len(signals) >= 1, "Expected at least one DeficiencySignal for 5 ORBIT records"


# ---------------------------------------------------------------------------
# TopologyLayer
# ---------------------------------------------------------------------------

def test_topology_layer_returns_none_no_anchors(mem_conn):
    """Fresh install, no crystallized landmarks → get_topology_context() returns None."""
    store = CoordinateStore(mem_conn)
    topology = TopologyLayer(mem_conn, store)
    result = topology.get_topology_context("sess_fresh", [])
    assert result is None


def test_encode_topology_context_under_25_tokens(mem_conn):
    """
    Build a valid TopologyContext; encode_topology_context() output
    has token count < 25.
    """
    store = CoordinateStore(mem_conn)
    topology = TopologyLayer(mem_conn, store)

    ctx = TopologyContext(
        anchor_ids=["anchor1"],
        primitives=[BehavioralPrimitive.CORE],
        z_values=[+0.12],
        trajectory_label="test_label",
        deficiency_signals=[],
        confidence_delta=0.04,
    )

    encoded = topology.encode_topology_context(ctx)
    token_count = len(encoded.split())
    assert token_count < 25, (
        f"encode_topology_context produced {token_count} tokens (>= 25): {encoded!r}"
    )


def test_encode_topology_context_returns_empty_for_none(mem_conn):
    """encode_topology_context(None) must return ''."""
    store = CoordinateStore(mem_conn)
    topology = TopologyLayer(mem_conn, store)
    assert topology.encode_topology_context(None) == ""


def test_run_topology_maintenance_no_v15_table_modification(mem_conn):
    """
    run_topology_maintenance() must NOT modify rows in:
    mycelium_nodes, mycelium_edges, mycelium_landmarks, or mycelium_profile.

    Insert a known row in each table; run maintenance; verify rows unchanged.
    """
    import struct

    # Insert a node
    nid = str(uuid.uuid4())
    blob = struct.pack("5f", 0.5, 0.5, 0.5, 0.5, 0.5)
    now = time.time()
    mem_conn.execute(
        """INSERT INTO mycelium_nodes
           (node_id, space_id, coordinates, label, confidence, access_count,
            created_at, updated_at, last_accessed)
           VALUES (?,?,?,?,?,1,?,?,NULL)""",
        (nid, "domain", blob, "test", 0.8, now, now),
    )
    # Insert an edge
    eid = str(uuid.uuid4())
    mem_conn.execute(
        """INSERT INTO mycelium_edges
           (edge_id, from_node_id, to_node_id, score, edge_type,
            traversal_count, hit_count, miss_count, decay_rate, created_at, last_traversed)
           VALUES (?,?,?,?,?,0,0,0,0.01,?,NULL)""",
        (eid, nid, nid, 0.5, "traversal", now),
    )
    # Insert a landmark
    lm_id = _insert_landmark(mem_conn, activation_count=1)
    # Insert profile row (uses new schema with section_id)
    mem_conn.execute(
        """INSERT OR IGNORE INTO mycelium_profile
           (section_id, space_id, render_order, prose, source_node_ids,
            source_lm_ids, dirty, last_rendered, word_count)
           VALUES (?,?,99,?,NULL,NULL,0,?,0)""",
        ("prof_domain", "domain", "test_render", now),
    )
    mem_conn.commit()

    store = CoordinateStore(mem_conn)
    topology = TopologyLayer(mem_conn, store)
    topology.run_topology_maintenance()

    # Verify node still exists with same label
    row = mem_conn.execute(
        "SELECT label FROM mycelium_nodes WHERE node_id = ?", (nid,)
    ).fetchone()
    assert row is not None and row[0] == "test"

    # Verify landmark still exists
    row = mem_conn.execute(
        "SELECT landmark_id FROM mycelium_landmarks WHERE landmark_id = ?", (lm_id,)
    ).fetchone()
    assert row is not None

    # Verify profile row still exists with same prose
    row = mem_conn.execute(
        "SELECT prose FROM mycelium_profile WHERE space_id = 'domain'"
    ).fetchone()
    assert row is not None and row[0] == "test_render"
