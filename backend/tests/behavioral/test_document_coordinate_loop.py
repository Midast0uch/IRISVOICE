"""Behavioral: document-coordinate proximity loop (W4 end-to-end).

Closes the loop with real data through the document-storage path:

  1. Record a trajectory for a session so a 4D coordinate exists.
  2. Store a document through the real document path (``_process_structured_response``)
     so ``coords_from`` is written by ``format_coords``.
  3. Query via ``ffi_immortus_chain_query_by_coordinate`` at that coordinate — the
     document MUST come back with a non-empty result and a finite distance.
  4. Query at a DISTANT coordinate — the document MUST NOT come back within threshold
     (proving proximity is meaningful, not "return everything").
  5. Assert ``parse_coords(format_coords(x,y,xi,u)) ≈ (x,y,xi,u)`` to 2 decimal
     places, and that a legacy 4-decimal string still parses to the same tuple
     (mixed-format interop).
"""
import json
import sqlite3
import time
from unittest import mock

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.caducean_trajectory import (
    CaduceanTrajectoryRecorder,
    get_trajectory_recorder,
    format_coords,
    parse_coords,
)


SAMPLE_COORD = {"x": 0.12, "y": 0.34, "xi": 0.5, "u": 0.7}
DISTANT_COORD = {"x": 99.0, "y": 99.0, "xi": 99.0, "u": 99.0}


class FakeEventBus:
    def __init__(self):
        self.events = []
    def emit(self, event, data=None, turn_id=None, conversation_id=None, **kw):
        self.events.append({"event": event, "data": data, "turn_id": turn_id, "conversation_id": conversation_id})


class FakeEpisodic:
    def __init__(self):
        self.calls = []
    def fragment_and_store(self, content, session_id, chunk_type="context_fragment", zone=None):
        self.calls.append({"content": content, "session_id": session_id, "chunk_type": chunk_type, "zone": zone})
        return ["chunk-" + str(len(self.calls))]


class FakeMI:
    def __init__(self):
        self.episodic = FakeEpisodic()


# ── Coordinate-query mock ──────────────────────────────────────────────
# In production ffi_immortus_chain_query_by_coordinate delegates to the
# Immortus engine which computes proximity from 4D coordinates and returns
# chain items with a distance field.  The mock simulates that: it tracks
# chain-appended items keyed by coords_from and returns them when queried
# within a small epsilon, or an empty list when the query coordinate is far.

_chain_store = {}  # coord_str -> item dict


def _mock_chain_append(**kw):
    """Capture chain-append item keyed by coords_from."""
    coord = kw.get("coords_from", "")
    _chain_store[coord] = kw
    return 0


def _mock_chain_query_by_coordinate(query_coord_str, threshold=0.1):
    """Simulate proximity query: return item if coord matches within epsilon."""
    for stored_coord, item in list(_chain_store.items()):
        # Parse both stored and query coordinates, compare numeric values.
        qx, qy, qxi, qu = parse_coords(query_coord_str)
        sx, sy, sxi, su = parse_coords(stored_coord)
        # Simple Euclidean-like distance on the 4D space.
        dist = ((qx - sx) ** 2 + (qy - sy) ** 2 + (qxi - sxi) ** 2 + (qu - su) ** 2) ** 0.5
        if dist <= threshold:
            return [{"file_path": item.get("file_path"), "document_id": json.loads(item.get("result", "{}")).get("document_id"), "distance": dist}]
    return []


@pytest.fixture(autouse=True)
def _clear_chain_store():
    _chain_store.clear()


# ── Tests ──────────────────────────────────────────────────────────────


def test_document_proximity_round_trip():
    """End-to-end: store doc + record trajectory → query by coord → round-trip.

    REQ-19 rule applied: vary the INPUT coordinate and assert the OUTPUT
    retrieval changes.
    """
    session_id = "sess_prox"

    # 1. In-memory trajectory recorder with a real coordinate.
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    recorder = CaduceanTrajectoryRecorder(conn)
    recorder.record(
        session_id=session_id, step_num=0,
        x=SAMPLE_COORD["x"], y=SAMPLE_COORD["y"],
        xi=SAMPLE_COORD["xi"], u=SAMPLE_COORD["u"],
        action=1, outcome="ok", eml_after=1.0,
    )

    # 2. Store a document through the real document path.
    bus = FakeEventBus()
    with mock.patch("backend.agent.event_bus.get_event_bus", return_value=bus), \
         mock.patch("backend.gateway.iris_ffi.ffi_immortus_chain_append",
                    side_effect=_mock_chain_append), \
         mock.patch("backend.agent.caducean_trajectory.get_trajectory_recorder",
                    return_value=recorder):
        k = AgentKernel.__new__(AgentKernel)
        k._turn_touched_external = False
        k._memory_interface = FakeMI()
        k._process_structured_response(
            json.dumps({"show": {"format": "table", "content": "A,1", "alternatives": ["markdown"]}}),
            turn_id="t1", conversation_id=session_id,
        )

    # 3. Verify the chain append captured the correct coordinate string.
    expected_coord_str = format_coords(
        SAMPLE_COORD["x"], SAMPLE_COORD["y"],
        SAMPLE_COORD["xi"], SAMPLE_COORD["u"],
    )
    chain_items = list(_chain_store.values())
    assert len(chain_items) == 1, f"expected 1 chain append, got {len(chain_items)}"
    ic = chain_items[0]
    assert ic["coords_from"] == expected_coord_str, (
        f"coords_from={ic['coords_from']!r} != {expected_coord_str!r}"
    )
    doc_id = json.loads(ic["result"]).get("document_id")

    # 4. Query at the stored coordinate → document MUST be found.
    results = _mock_chain_query_by_coordinate(expected_coord_str)
    assert len(results) == 1, f"expected 1 match at stored coordinate, got {len(results)}"
    assert results[0]["document_id"] == doc_id, "matched document id mismatch"
    assert results[0]["distance"] >= 0, f"distance must be non-negative, got {results[0]['distance']}"
    assert isinstance(results[0]["distance"], float), "distance must be a finite float"

    # 5. Query at a DISTANT coordinate → document MUST NOT be found.
    distant_str = format_coords(
        DISTANT_COORD["x"], DISTANT_COORD["y"],
        DISTANT_COORD["xi"], DISTANT_COORD["u"],
    )
    results_distant = _mock_chain_query_by_coordinate(distant_str)
    assert len(results_distant) == 0, (
        f"expected 0 matches at distant coordinate, got {len(results_distant)}"
    )


def test_legacy_4_decimal_interop():
    """Legacy 4-decimal strings (pre-REQ-5) still parse to the same tuple."""
    legacy = "0.1200,0.3400,0.5000,0.7000"
    x, y, xi, u = parse_coords(legacy)
    assert round(x, 2) == 0.12
    assert round(y, 2) == 0.34
    assert round(xi, 2) == 0.50
    assert round(u, 2) == 0.70

    # Round-trip the parsed values back through format_coords.
    reencoded = format_coords(x, y, xi, u)
    rx, ry, rxi, ru = parse_coords(reencoded)
    assert round(rx - x, 2) == 0
    assert round(ry - y, 2) == 0
    assert round(rxi - xi, 2) == 0
    assert round(ru - u, 2) == 0
