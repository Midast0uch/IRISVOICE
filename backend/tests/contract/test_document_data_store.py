"""Pytest tests for W4 document data store (T1, T9, W4 coordinate contract).

Converted from a standalone check()-based script to proper pytest test functions.

Covers:
  T1  — DOCUMENT_RENDER payload includes document_id + trust.
  T9  — Mycelium stores canonical data keyed by document_id
        (fragment_and_store, chunk_type=document_data, zone by trust).
        Immortus chain append carries document_id, thread_id, and the
        canonical coordinate string (coords_from) from format_coords.
  W4  — Coordinate round-trip through format_coords/parse_coords and
        the document-store coordinate thread (coords_from on chain).
"""
import json
import uuid
from unittest import mock

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.caducean_trajectory import format_coords, parse_coords


# ── Sample data ────────────────────────────────────────────────────────

SAMPLE_COORD = {"x": 0.12, "y": 0.34, "xi": 0.5, "u": 0.7}
EXPECTED_COORD_STR = format_coords(0.12, 0.34, 0.5, 0.7)
# "0.12,0.34,0.50,0.70"


# ── Fixtures ───────────────────────────────────────────────────────────

class FakeRecorder:
    def __init__(self, coord):
        self._coord = coord
    def get_latest_coordinate(self, session_id):
        return self._coord


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


def _is_uuid(s):
    try:
        uuid.UUID(str(s))
        return True
    except Exception:
        return False


def _renders(bus):
    return [e for e in bus.events if str(e["event"]).endswith("DOCUMENT_RENDER")]


# ── Shared helpers ─────────────────────────────────────────────────────

def _run_process(response_json, trusted=True, coord=SAMPLE_COORD):
    """Process a structured response and return (bus, immortus_appends, kernel).

    Mocks the event bus, Immortus chain append, and trajectory recorder so
    the document path runs without external dependencies.
    """
    bus = FakeEventBus()
    immortus = []
    with mock.patch("backend.agent.event_bus.get_event_bus", return_value=bus), \
         mock.patch("backend.gateway.iris_ffi.ffi_immortus_chain_append",
                    side_effect=lambda **kw: (immortus.append(kw) or 0)), \
         mock.patch("backend.agent.caducean_trajectory.get_trajectory_recorder",
                    return_value=FakeRecorder(coord)):
        k = AgentKernel.__new__(AgentKernel)
        k._turn_touched_external = not trusted
        k._memory_interface = FakeMI()
        k._process_structured_response(response_json, turn_id="t1", conversation_id="c1")
    return bus, immortus, k


# ── T1: DOCUMENT_RENDER contract ───────────────────────────────────────

TRUSTED_RESPONSE = json.dumps({
    "show": {"format": "table", "content": "Name,Age\nA,1", "alternatives": ["markdown", "html"]}
})
UNTRUSTED_RESPONSE = json.dumps({
    "show": {"format": "html", "content": "<p>web</p>", "alternatives": ["markdown"]}
})


def test_t1_document_render_emitted():
    """DOCUMENT_RENDER is emitted with document_id, trust, content."""
    bus, _, _ = _run_process(TRUSTED_RESPONSE)
    renders = _renders(bus)
    assert len(renders) == 1, "DOCUMENT_RENDER must be emitted"
    data = renders[0]["data"]
    assert data.get("document_id"), "payload must have document_id"
    assert _is_uuid(data["document_id"]), "document_id must be a UUID"
    assert data.get("trust") == "trusted", "trusted turn -> trust='trusted'"
    assert data.get("content") == "Name,Age\nA,1"


def test_t1_untrusted_document_render():
    """Untrusted turn produces trust='untrusted'."""
    bus, _, _ = _run_process(UNTRUSTED_RESPONSE, trusted=False)
    renders = _renders(bus)
    assert len(renders) == 1
    assert renders[0]["data"]["trust"] == "untrusted"


# ── T9: Mycelium storage ───────────────────────────────────────────────

def test_t9_mycelium_fragment_and_store():
    """Mycelium stores canonical data (document_data, zone=trusted)."""
    bus, _, k = _run_process(TRUSTED_RESPONSE)
    renders = _renders(bus)
    data = renders[0]["data"]
    mc = k._memory_interface.episodic.calls
    assert len(mc) == 1, "mycelium storage called"
    assert mc[0]["chunk_type"] == "document_data"
    assert mc[0]["zone"] == "trusted"
    stored = json.loads(mc[0]["content"])
    assert stored["document_id"] == data["document_id"]
    assert stored["trust"] == "trusted"
    assert stored["content"] == "Name,Age\nA,1"
    assert stored["alternatives"] == ["markdown", "html"]


def test_t9_untrusted_mycelium_zone():
    """Untrusted turn -> zone='reference'."""
    bus, _, k = _run_process(UNTRUSTED_RESPONSE, trusted=False)
    assert len(k._memory_interface.episodic.calls) == 1
    assert k._memory_interface.episodic.calls[0]["zone"] == "reference"


# ── T9: Immortus chain append ──────────────────────────────────────────

def test_t9_immortus_chain_append():
    """Immortus chain append carries document_id, thread_id, coords_from."""
    bus, immortus, _ = _run_process(TRUSTED_RESPONSE)
    renders = _renders(bus)
    data = renders[0]["data"]
    assert len(immortus) == 1, "Immortus chain_append called"
    ic = immortus[0]
    # T1: file_path is the document_id.
    assert ic.get("file_path") == data["document_id"], "file_path must be document_id"
    ic_data = json.loads(ic.get("result", "{}"))
    assert ic_data["document_id"] == data["document_id"], "result carries document_id"
    assert ic.get("thread_id") == "c1", "thread_id == conversation_id"
    # W4: coords_from is the canonical 2-decimal coordinate string.
    assert ic.get("coords_from") == EXPECTED_COORD_STR, (
        f"coords_from={ic.get('coords_from')!r} != {EXPECTED_COORD_STR!r}"
    )
    assert bool(ic.get("coords_from")), "coords_from must be non-empty"


def test_t9_untrusted_immortus_coords_from():
    """Untrusted turn still threads coords_from."""
    _, immortus, _ = _run_process(UNTRUSTED_RESPONSE, trusted=False)
    assert len(immortus) == 1
    assert immortus[0]["coords_from"] == EXPECTED_COORD_STR, (
        f"untrusted coords_from={immortus[0]['coords_from']!r}"
    )


# ── W4: Coordinate round-trip & format contract ────────────────────────

class TestW4CoordinateContract:
    """W4: canonical 4D coordinate round-trips and contract stability."""

    PARAMETRIZED_COORDS = [
        (0.12, 0.34, 0.5, 0.7),
        (0.0, 0.0, 0.0, 0.0),
        (-1.5, 2.3, -0.5, 1.2),
        (99.99, -88.88, 77.77, -66.66),
    ]

    def test_w4_round_trip(self):
        """parse_coords(format_coords(x,y,xi,u)) ≈ (x,y,xi,u) within 2dp."""
        for x, y, xi, u in self.PARAMETRIZED_COORDS:
            s = format_coords(x, y, xi, u)
            rx, ry, rxi, ru = parse_coords(s)
            assert round(rx - x, 2) == 0, f"x mismatch: {rx} != {x} (from repr {s!r})"
            assert round(ry - y, 2) == 0
            assert round(rxi - xi, 2) == 0
            assert round(ru - u, 2) == 0

    def test_w4_legacy_4_decimal_interop(self):
        """Legacy 4-decimal strings (pre-REQ-5) still parse to the same tuple.

        Before REQ-5 coordinates were serialised as 4 decimal places.  After
        the change to 2 dp the format changed but parse_coords must accept
        both so old stored data remains reachable.
        """
        legacy = "0.1200,0.3400,0.5000,0.7000"
        x, y, xi, u = parse_coords(legacy)
        assert round(x, 2) == 0.12
        assert round(y, 2) == 0.34
        assert round(xi, 2) == 0.50
        assert round(u, 2) == 0.70

    def test_w4_format_immutability(self):
        """2-decimal format is a stable contract (CU-7)."""
        import re
        s = format_coords(0.12, 0.34, 0.5, 0.7)
        assert re.match(
            r"^-?\d+\.\d{2},-?\d+\.\d{2},-?\d+\.\d{2},-?\d+\.\d{2}$",
            s,
        ), f"format {s!r} does not match canonical pattern"
