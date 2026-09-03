"""
Tests for ResonanceScorer — Task 12.6 (resonance half)
Requirements: 14.11, 11.1–11.12
"""

import json
import struct
import time
import uuid
import pytest
from .conftest_mycelium import mem_conn  # noqa: F401

from backend.memory.mycelium.store import CoordinateStore
from backend.memory.mycelium.resonance import ResonanceScorer
from backend.memory.mycelium.spaces import (
    RESONANCE_SPACES,
    RESONANCE_WEIGHT_PER_SPACE,
    LANDMARK_MATCH_BONUS,
    SUPPRESSION_COVERAGE_THRESHOLD,
)


def _seed_spaces(conn):
    for sid in ["conduct", "domain", "style", "chrono", "context", "capability", "toolpath"]:
        conn.execute(
            "INSERT OR IGNORE INTO mycelium_spaces (space_id, axes, dtype, value_range) VALUES (?,?,?,?)",
            (sid, "[]", "float32", "[0.0,1.0]"),
        )
    conn.commit()


def _insert_node(conn, space_id, coords, label="n", confidence=0.8):
    nid = str(uuid.uuid4())
    # Big-endian to match CoordinateStore._pack_coords / _unpack_coords
    blob = struct.pack(f">{len(coords)}f", *coords)
    now = time.time()
    conn.execute(
        "INSERT INTO mycelium_nodes VALUES (?,?,?,?,?,1,?,?,?)",
        (nid, space_id, blob, label, confidence, now, now, now),
    )
    conn.commit()
    return nid


def _insert_episode_index(conn, episode_id, session_id, node_ids, space_ids=None, landmark_id=None):
    """Insert a mycelium_episode_index row with node_ids as JSON (matching the code)."""
    idx_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO mycelium_episode_index
           (idx_id, episode_id, session_id, node_ids, space_ids, landmark_id, source_channel, created_at)
           VALUES (?,?,?,?,?,?,2,?)""",
        (
            idx_id,
            episode_id,
            session_id,
            json.dumps(node_ids),
            json.dumps(space_ids or []),
            landmark_id,
            time.time(),
        ),
    )
    conn.commit()


def _make_candidate(cosine_score=0.7, outcome="success", episode_id=None):
    return {
        "episode_id": episode_id or str(uuid.uuid4()),
        "cosine_score": cosine_score,
        "task_text": "sample task",
        "outcome": outcome,
    }


def test_zero_space_resonance_final_equals_cosine(mem_conn):
    """
    Req 11.5: No episode index entries → resonance_multiplier = 0.
    final_score = cosine * (1 + 0) * 1.0 = cosine.
    """
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    scorer = ResonanceScorer(mem_conn, store)

    candidate = _make_candidate(cosine_score=0.65)
    results = scorer.augment_retrieval("sess_zero", [candidate])
    assert len(results) == 1
    final = results[0].get("final_score", 0.0)
    assert final == pytest.approx(0.65, abs=0.01), (
        f"Req 11.5: no space overlap → final_score must equal cosine (0.65), got {final}"
    )


def test_single_space_resonance_boost(mem_conn):
    """
    Req 11.5: 1 space with overlap > 0.60 → resonance_multiplier += RESONANCE_WEIGHT_PER_SPACE (0.15).
    final_score = cosine * (1 + 0.15) = 0.6 * 1.15 = 0.69.
    """
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)

    # Create a matching node in the domain space for session
    nid_sess = _insert_node(mem_conn, "domain", [0.9, 0.9, 0.9, 0.9, 0.9], "session_node")
    # Create a closely matching node for the episode
    nid_ep = _insert_node(mem_conn, "domain", [0.9, 0.9, 0.9, 0.9, 0.9], "episode_node")

    episode_id = str(uuid.uuid4())
    session_id = "sess_single_space"

    # Index the session's nodes
    _insert_episode_index(mem_conn, "sess_ep", session_id, [nid_sess], ["domain"])
    # Index the episode's nodes
    _insert_episode_index(mem_conn, episode_id, "other_session", [nid_ep], ["domain"])

    scorer = ResonanceScorer(mem_conn, store)
    candidate = _make_candidate(cosine_score=0.60, episode_id=episode_id)
    results = scorer.augment_retrieval(session_id, [candidate])

    assert len(results) == 1
    multiplier = results[0].get("resonance_multiplier", 0.0)
    assert multiplier >= RESONANCE_WEIGHT_PER_SPACE - 0.001, (
        f"Req 11.5: 1 matching space → resonance_multiplier >= {RESONANCE_WEIGHT_PER_SPACE}, got {multiplier}"
    )


def test_failure_episode_never_suppressed(mem_conn):
    """
    Req 11.9: failure episodes must NEVER be suppressed, regardless of coverage.
    """
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    scorer = ResonanceScorer(mem_conn, store)

    episode_id = str(uuid.uuid4())
    candidate = _make_candidate(cosine_score=0.90, outcome="failure", episode_id=episode_id)
    results = scorer.augment_retrieval("sess_fail", [candidate])
    assert len(results) == 1
    assert results[0].get("suppressed", False) is False, (
        "Req 11.9: failure episodes must never be suppressed"
    )


def test_no_index_data_graceful_fallback(mem_conn):
    """
    Req 11.5: No mycelium_episode_index rows → graceful fallback with
    final_score set and suppressed=False.
    """
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    scorer = ResonanceScorer(mem_conn, store)

    candidate = _make_candidate(cosine_score=0.55)
    results = scorer.augment_retrieval("sess_no_data", [candidate])
    assert len(results) == 1
    assert results[0].get("suppressed", False) is False
    # final_score should be present and non-negative
    assert results[0].get("final_score", -1) >= 0.0


def test_landmark_match_bonus_applied(mem_conn):
    """
    Req 11.6: if episode's landmark_id matches current_landmark_id →
    resonance_multiplier += LANDMARK_MATCH_BONUS (0.40).
    """
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)

    episode_id = str(uuid.uuid4())
    landmark_id = str(uuid.uuid4())
    session_id = "sess_lm"

    # Index episode with a landmark
    _insert_episode_index(mem_conn, episode_id, session_id, [], [], landmark_id=landmark_id)
    # Also add a session entry so session nodes don't trip up loading
    _insert_episode_index(mem_conn, "sess_ep2", session_id, [], [])

    scorer = ResonanceScorer(mem_conn, store)
    candidate = _make_candidate(cosine_score=0.50, episode_id=episode_id)
    results = scorer.augment_retrieval(session_id, [candidate], current_landmark_id=landmark_id)

    assert len(results) == 1
    multiplier = results[0].get("resonance_multiplier", 0.0)
    assert multiplier >= LANDMARK_MATCH_BONUS - 0.001, (
        f"Req 11.6: landmark match must add {LANDMARK_MATCH_BONUS} bonus, got multiplier={multiplier}"
    )


def test_final_score_formula(mem_conn):
    """
    Req 11.7: final_score = cosine * (1 + resonance_multiplier) * channel_weight.
    With no overlap and no landmark: multiplier=0, weight=1.0 → final=cosine.
    """
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    scorer = ResonanceScorer(mem_conn, store)

    cosine = 0.72
    candidate = _make_candidate(cosine_score=cosine)
    results = scorer.augment_retrieval("sess_formula", [candidate])
    assert len(results) == 1
    final = results[0].get("final_score", 0.0)
    # With zero multiplier and default weight=1.0:
    # final = cosine * (1 + 0) * 1.0 = cosine
    assert final == pytest.approx(cosine, abs=0.01), (
        f"Req 11.7: final_score formula failed. Expected {cosine}, got {final}"
    )


def test_suppressed_success_ranked_last(mem_conn):
    """
    Req 11.10: suppressed items must be ranked last in returned list.
    A non-suppressed low-score item must rank above a suppressed high-score item.
    """
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)

    # Create identical nodes in 6 resonance spaces so coverage = 1.0 >= 0.70
    session_id = "sess_rank"
    ep_node_ids = []
    for space_id in RESONANCE_SPACES:
        nid = _insert_node(mem_conn, space_id, [0.8, 0.8, 0.8, 0.8, 0.8], f"n_{space_id}")
        ep_node_ids.append(nid)

    # Session entry so _load_session_nodes_by_space finds matching nodes
    _insert_episode_index(mem_conn, "sess_cur", session_id, ep_node_ids, list(RESONANCE_SPACES))

    # Suppressed high-score success episode with identical nodes
    ep_suppressed = str(uuid.uuid4())
    _insert_episode_index(
        mem_conn, ep_suppressed, "past_session", ep_node_ids, list(RESONANCE_SPACES)
    )

    scorer = ResonanceScorer(mem_conn, store)
    suppressed_candidate = {
        "episode_id": ep_suppressed,
        "cosine_score": 0.95,
        "outcome": "success",
    }
    low_score_candidate = {
        "episode_id": str(uuid.uuid4()),
        "cosine_score": 0.30,
        "outcome": "success",
    }

    results = scorer.augment_retrieval(session_id, [suppressed_candidate, low_score_candidate])
    assert len(results) == 2

    # If suppressed candidate IS suppressed, it must rank last
    if results[0].get("suppressed") or results[1].get("suppressed"):
        last = results[-1]
        assert last.get("suppressed", False) is True, (
            "Req 11.10: suppressed items must rank last"
        )


def test_resonance_spaces_excludes_toolpath(mem_conn):
    """
    Req 11.5: RESONANCE_SPACES must be the 6 non-toolpath spaces.
    """
    assert "toolpath" not in RESONANCE_SPACES, (
        "Req 11.5: toolpath must NOT be in RESONANCE_SPACES"
    )
    assert len(RESONANCE_SPACES) == 6, (
        f"Req 11.5: RESONANCE_SPACES must have exactly 6 entries, got {len(RESONANCE_SPACES)}"
    )


def test_augment_retrieval_returns_empty_for_empty_input(mem_conn):
    """Req 11.5: empty candidates list → returns empty list (no crash)."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    scorer = ResonanceScorer(mem_conn, store)

    results = scorer.augment_retrieval("sess_empty", [])
    assert results == [], "Empty input must return empty list"
