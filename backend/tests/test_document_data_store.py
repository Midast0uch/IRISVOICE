#!/usr/bin/env python3
"""Standalone test for W4: store canonical DATA keyed by document_id.

Run:  python backend/tests/test_document_data_store.py
NOT collected by pytest (no test_ prefix) to avoid the full-backend memory spike.

Covers:
  T1 (contract): DOCUMENT_RENDER payload includes `document_id` + `trust`.
  T9 (data-centric): canonical data stored in Mycelium (fragment_and_store,
    chunk_type=document_data, zone by trust) and Immortus (immortus_chain_append,
    file_path=document_id) keyed by document_id. The stored record carries the
    same document_id as the emitted render (source-of-truth linkage, G4).
"""
import sys
import os
import json
import uuid

REPO_ROOT = r"C:\dev\IRISVOICE"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import unittest.mock as mock
from backend.agent.agent_kernel import AgentKernel

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), name, ("- " + str(detail)) if detail else "")


def _is_uuid(s):
    try:
        uuid.UUID(str(s))
        return True
    except Exception:
        return False


# ── Fakes ────────────────────────────────────────────────────────────────
class FakeEventBus:
    def __init__(self):
        self.events = []

    def emit(self, event, data=None, turn_id=None, conversation_id=None, **kw):
        self.events.append(
            {"event": event, "data": data, "turn_id": turn_id, "conversation_id": conversation_id}
        )


class FakeEpisodic:
    def __init__(self):
        self.calls = []

    def fragment_and_store(self, content, session_id, chunk_type="context_fragment", zone=None):
        self.calls.append(
            {"content": content, "session_id": session_id, "chunk_type": chunk_type, "zone": zone}
        )
        return ["chunk-" + str(len(self.calls))]


class FakeMI:
    def __init__(self):
        self.episodic = FakeEpisodic()


class FakeRecorder:
    def __init__(self, coord):
        self._coord = coord  # dict x,y,xi,u or None

    def get_latest_coordinate(self, session_id):
        return self._coord


SAMPLE_COORD = {"x": 0.12, "y": 0.34, "xi": 0.5, "u": 0.7}
EXPECTED_COORD_STR = "0.1200,0.3400,0.5000,0.7000"


def make_kernel():
    k = AgentKernel.__new__(AgentKernel)
    k._turn_touched_external = False
    k._memory_interface = FakeMI()
    return k


def _renders(bus):
    return [e for e in bus.events if str(e["event"]).endswith("DOCUMENT_RENDER")]


def main():
    # ── Trusted turn ───────────────────────────────────────────────────────
    bus = FakeEventBus()
    immortus = []
    with mock.patch("backend.agent.event_bus.get_event_bus", return_value=bus), \
         mock.patch(
             "backend.gateway.iris_ffi.ffi_immortus_chain_append",
             side_effect=lambda **kw: (immortus.append(kw) or 0),
         ), \
         mock.patch(
             "backend.agent.caducean_trajectory.get_trajectory_recorder",
             return_value=FakeRecorder(SAMPLE_COORD),
         ):
        k = make_kernel()
        response = json.dumps(
            {
                "show": {
                    "format": "table",
                    "content": "Name,Age\nA,1",
                    "alternatives": ["markdown", "html"],
                }
            }
        )
        k._process_structured_response(response, turn_id="t1", conversation_id="c1")

        # ── T1: DOCUMENT_RENDER includes document_id + trust ──────────────
        renders = _renders(bus)
        check("T1a DOCUMENT_RENDER emitted", len(renders) == 1)
        data = renders[0]["data"] if renders else {}
        check("T1b payload has document_id", bool(data.get("document_id")), str(data.get("document_id"))[:8])
        check("T1b document_id is a uuid", _is_uuid(data.get("document_id")))
        check("T1b payload has trust='trusted'", data.get("trust") == "trusted", str(data.get("trust")))
        check("T1b payload has content", data.get("content") == "Name,Age\nA,1")

        # ── T9: Mycelium stores canonical data keyed by document_id ───────
        mc_calls = k._memory_interface.episodic.calls
        check("T9a Mycelium fragment_and_store called", len(mc_calls) == 1)
        if mc_calls:
            mc = mc_calls[0]
            check("T9a chunk_type=document_data", mc["chunk_type"] == "document_data", mc["chunk_type"])
            check("T9a zone=trusted (trusted turn)", mc["zone"] == "trusted", str(mc["zone"]))
            stored = json.loads(mc["content"])
            check("T9a stored document_id matches render", stored.get("document_id") == data.get("document_id"))
            check("T9a stored content matches", stored.get("content") == "Name,Age\nA,1")
            check("T9a stored alternatives match", stored.get("alternatives") == ["markdown", "html"])
            check("T9a stored trust matches", stored.get("trust") == "trusted")

        # ── T9: Immortus stores canonical data keyed by document_id ───────
        check("T9b Immortus chain_append called", len(immortus) == 1)
        if immortus:
            ic = immortus[0]
            check("T9b file_path == document_id", ic.get("file_path") == data.get("document_id"), str(ic.get("file_path")))
            ic_data = json.loads(ic.get("result", "{}"))
            check("T9b result carries document_id", ic_data.get("document_id") == data.get("document_id"))
            check("T9b thread_id == conversation_id", ic.get("thread_id") == "c1")
            # ── W4 coordinate thread: coords_from = reasoning-state coord ─
            check("T9d Immortus coords_from is the trajectory coord", ic.get("coords_from") == EXPECTED_COORD_STR, str(ic.get("coords_from")))
            check("T9d coords_from non-empty (not orphaned)", bool(ic.get("coords_from")))

    # ── Untrusted turn: zone should be 'reference' ─────────────────────────
    bus2 = FakeEventBus()
    immortus2 = []
    with mock.patch("backend.agent.event_bus.get_event_bus", return_value=bus2), \
         mock.patch(
             "backend.gateway.iris_ffi.ffi_immortus_chain_append",
             side_effect=lambda **kw: (immortus2.append(kw) or 0),
         ), \
         mock.patch(
             "backend.agent.caducean_trajectory.get_trajectory_recorder",
             return_value=FakeRecorder(SAMPLE_COORD),
         ):
        k2 = make_kernel()
        k2._turn_touched_external = True
        response2 = json.dumps(
            {"show": {"format": "html", "content": "<p>web</p>", "alternatives": ["markdown"]}}
        )
        k2._process_structured_response(response2, turn_id="t2", conversation_id="c2")
        renders2 = _renders(bus2)
        check("T1c untrusted turn -> trust='untrusted'", renders2[0]["data"].get("trust") == "untrusted")
        check(
            "T9c untrusted -> Mycelium zone='reference'",
            k2._memory_interface.episodic.calls[0]["zone"] == "reference",
            k2._memory_interface.episodic.calls[0]["zone"],
        )
        check(
            "T9d untrusted turn still threads coords_from",
            immortus2 and immortus2[0].get("coords_from") == EXPECTED_COORD_STR,
            str(immortus2[0].get("coords_from")) if immortus2 else "no-call",
        )

    failed = [r for r in results if not r[1]]
    print("\n=== W4 DOCUMENT DATA STORE SUMMARY ===")
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED:", [r[0] for r in failed])
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
