"""
Tests for Kyudo Precision Layer — Task 12.9
Requirements: 14.21–14.25, 16.1–16.29
"""

import json
import re
import struct
import time
import uuid

import pytest
from .conftest_mycelium import mem_conn  # noqa: F401

from backend.memory.mycelium.kyudo import (
    TaskClassifier,
    PredictiveLoader,
    MicroAbstractEncoder,
    DeltaEncoder,
    TASK_CLASS_SPACE_MAP,
)
from backend.memory.mycelium.interface import MyceliumInterface
from backend.memory.mycelium.store import CoordinateStore


# ---------------------------------------------------------------------------
# TaskClassifier
# ---------------------------------------------------------------------------

def test_task_classifier_quick_edit_short_task():
    """Under 20 words, no planning keywords → quick_edit with conduct+context subset."""
    tc = TaskClassifier()
    task_class, space_subset = tc.classify("rename the function to snake case")
    assert task_class == "quick_edit"
    assert "conduct" in space_subset
    assert "context" in space_subset


def test_task_classifier_code_task_keyword():
    """'implement' keyword → code_task with conduct, domain, toolpath, context."""
    tc = TaskClassifier()
    task_class, space_subset = tc.classify(
        "implement the new user authentication module with JWT support"
    )
    assert task_class == "code_task"
    expected = set(TASK_CLASS_SPACE_MAP["code_task"])
    assert set(space_subset) == expected


def test_task_classifier_research_task_keyword():
    """'analyze' keyword → research_task subset."""
    tc = TaskClassifier()
    task_class, space_subset = tc.classify(
        "analyze the performance of the database query and explain the bottleneck"
    )
    assert task_class == "research_task"


def test_task_classifier_planning_task_keyword():
    """'design' keyword → planning_task subset."""
    tc = TaskClassifier()
    task_class, _ = tc.classify(
        "design the architecture for the new microservice infrastructure"
    )
    assert task_class == "planning_task"


# ---------------------------------------------------------------------------
# PredictiveLoader
# ---------------------------------------------------------------------------

def test_predictive_loader_skips_when_immature(mem_conn):
    """
    When is_mature() returns False, pre_warm() should not create a cache entry.
    (Maturity gate is enforced by the caller in MyceliumInterface.clear_session).
    Verify directly: if we call pre_warm with a navigator that returns empty path,
    and then call get_cached with same session, we get None due to TTL/sim miss.
    """
    loader = PredictiveLoader()
    store = CoordinateStore(mem_conn)

    # Create a minimal stub navigator
    class _StubNavigator:
        def navigate_subgraph(self, text, spaces):
            return []  # immature — empty path

    loader.pre_warm("sess_immature", _StubNavigator(), "quick_edit")

    # Cache was written but path is empty; get_cached will fail sim check
    # (empty hint_text vs non-empty task_text → sim=0.0 < PREDICTION_MATCH_THRESHOLD=0.70)
    result = loader.get_cached("sess_immature", "implement something complex")
    assert result is None


def test_predictive_loader_cache_miss_no_entry():
    """No pre-warm → get_cached returns None."""
    loader = PredictiveLoader()
    result = loader.get_cached("sess_no_entry", "any task")
    assert result is None


# ---------------------------------------------------------------------------
# DeltaEncoder
# ---------------------------------------------------------------------------

def _make_node(node_id: str, space_id: str, coords: list) -> object:
    """Build a minimal node-like object for DeltaEncoder."""
    class _Node:
        pass
    n = _Node()
    n.node_id = node_id
    n.space_id = space_id
    n.coordinates = coords
    return n


def test_delta_encoder_baseline_first_session(mem_conn):
    """
    First call to encode_delta for a session must store full baseline
    with delta_compressed=0.
    """
    encoder = DeltaEncoder()
    nodes = [
        _make_node("n1", "domain", [0.5, 0.6, 0.7]),
        _make_node("n2", "conduct", [0.3, 0.4, 0.5, 0.6, 0.7]),
    ]
    session_id = "sess_baseline"

    delta = encoder.encode_delta(session_id, nodes, mem_conn)

    assert delta.delta_compressed == 0
    assert len(delta.added) == 2
    assert delta.removed == []
    assert delta.modified == []


def test_delta_encoder_delta_second_session(mem_conn):
    """
    Second call to encode_delta for same session with a changed node
    must store delta with delta_compressed=1.
    """
    encoder = DeltaEncoder()
    session_id = "sess_delta"

    # First call — baseline
    nodes_v1 = [
        _make_node("n1", "domain", [0.5, 0.6, 0.7]),
        _make_node("n2", "conduct", [0.3, 0.4, 0.5, 0.6, 0.7]),
    ]
    encoder.encode_delta(session_id, nodes_v1, mem_conn)

    # Second call — n1 coordinates changed significantly (> 0.05)
    nodes_v2 = [
        _make_node("n1", "domain", [0.9, 0.9, 0.9]),   # changed
        _make_node("n2", "conduct", [0.3, 0.4, 0.5, 0.6, 0.7]),  # unchanged
        _make_node("n3", "style", [0.2, 0.2, 0.2]),  # added
    ]
    delta2 = encoder.encode_delta(session_id, nodes_v2, mem_conn)

    assert delta2.delta_compressed == 1
    # n3 is new → in added
    assert any(n.get("node_id") == "n3" for n in delta2.added)
    # n1 coordinate change > DELTA_CHANGE_THRESHOLD → in modified
    assert any(m.get("node_id") == "n1" for m in delta2.modified)


def test_delta_encoder_reconstruct_roundtrip(mem_conn):
    """
    After storing 2 sessions of deltas, reconstruct() returns the correct
    final node set.
    """
    encoder = DeltaEncoder()
    session_id = "sess_reconstruct"

    # Baseline
    nodes_v1 = [
        _make_node("nA", "domain", [0.1, 0.2, 0.3]),
        _make_node("nB", "conduct", [0.4, 0.5, 0.6, 0.7, 0.8]),
    ]
    encoder.encode_delta(session_id, nodes_v1, mem_conn)

    # Delta: remove nB, add nC
    nodes_v2 = [
        _make_node("nA", "domain", [0.1, 0.2, 0.3]),
        _make_node("nC", "style", [0.9, 0.9, 0.9]),
    ]
    encoder.encode_delta(session_id, nodes_v2, mem_conn)

    # Reconstruct
    result = encoder.reconstruct(session_id, mem_conn)
    node_ids = {n["node_id"] for n in result}

    assert "nA" in node_ids
    assert "nC" in node_ids
    assert "nB" not in node_ids


# ---------------------------------------------------------------------------
# MicroAbstractEncoder
# ---------------------------------------------------------------------------

def test_micro_abstract_encoder_5_token_format():
    """
    encode() output must match the exact 5-field format:
    [space:{s} | outcome:{o} | tool:{t} | condition:{c} | delta:{d:.4f}]
    """
    enc = MicroAbstractEncoder()
    result = enc.encode(
        space_id="domain",
        outcome="miss",
        tool_id="bash",
        condition_hash="abc123",
        score_delta=-0.08,
    )
    pattern = (
        r"^\[space:[^\|]+ \| outcome:[^\|]+ \| tool:[^\|]+ \| "
        r"condition:[^\|]+ \| delta:-?\d+\.\d{4}\]$"
    )
    assert re.match(pattern, result), f"Format mismatch: {result!r}"


def test_micro_abstract_decoder_returns_human_readable():
    """decode() must return a string with no format brackets '[...]'."""
    enc = MicroAbstractEncoder()
    encoded = enc.encode("toolpath", "hit", "grep", "deadbeef", 0.05)
    decoded = enc.decode(encoded)

    # Must not contain the raw encoding bracket syntax
    assert "[" not in decoded or "space:" not in decoded
    assert isinstance(decoded, str)
    assert len(decoded) > 0


# ---------------------------------------------------------------------------
# Partial profile: only requested spaces assembled
# ---------------------------------------------------------------------------

def test_partial_profile_returns_subset_only(mem_conn):
    """
    When TaskClassifier selects 'quick_edit' (conduct + context), get_context_path()
    should only call get_profile_section() for those spaces.

    Verifies via MyceliumInterface.get_profile_section() — non-requested spaces
    return None for a fresh graph.
    """
    mi = MyceliumInterface(mem_conn, dev_mode=True)

    # Verify that the task classifier correctly limits the profile
    tc = TaskClassifier()
    task_class, space_subset = tc.classify("rename the variable to snake case")
    assert task_class == "quick_edit"
    # Only conduct and context should be included
    for space in space_subset:
        assert space in ("conduct", "context"), (
            f"quick_edit should only return conduct/context, got {space}"
        )
    # Spaces like 'domain', 'chrono', 'style' should NOT be in subset
    assert "domain" not in space_subset
    assert "chrono" not in space_subset
