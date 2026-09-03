#!/usr/bin/env python3
"""Standalone test for W5: reformat by document_id (no client content, G1).

Run:  python backend/tests/test_document_reformat_by_id.py
NOT collected by pytest (no test_ prefix) to avoid the full-backend memory spike.

Covers:
  T6  (Integration): reformat via document_id retrieves canonical data + stored
      variants and reformats; DOCUMENT_RENDER preserves trust + document_id.
  T12 (Deterministic, G1): when target_format is a stored variant, reformat
      returns it with NO LLM call (assert _respond_direct not invoked).
  T13 (Retrieval scoping, G2): exact reformat by document_id returns the correct
      document's data; a different/non-existent id is never surfaced.
  Bonus: a genuinely new format falls back to the LLM and the result is cached
      as a new variant (so the next reformat is deterministic).
"""
import sys
import os
import json
import uuid
import sqlite3

REPO_ROOT = r"C:\dev\IRISVOICE"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import unittest.mock as mock
from backend.agent.agent_kernel import AgentKernel
from backend.agent.document_store import DocumentDataStore

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), name, ("- " + str(detail)) if detail else "")


class FakeEventBus:
    def __init__(self):
        self.events = []

    def emit(self, event, data=None, turn_id=None, conversation_id=None, **kw):
        self.events.append(
            {"event": event, "data": data, "turn_id": turn_id, "conversation_id": conversation_id}
        )


class FakeEpisodic:
    def __init__(self, conn):
        self.db = conn


class FakeMI:
    def __init__(self, conn):
        self.episodic = FakeEpisodic(conn)


class FakeRecorder:
    def __init__(self, coord):
        self._coord = coord

    def get_latest_coordinate(self, session_id):
        return self._coord


SAMPLE_COORD = {"x": 0.12, "y": 0.34, "xi": 0.5, "u": 0.7}


def make_kernel(conn):
    k = AgentKernel.__new__(AgentKernel)
    k._turn_touched_external = False
    k._memory_interface = FakeMI(conn)
    return k


def _renders(bus):
    return [e for e in bus.events if str(e["event"]).endswith("DOCUMENT_RENDER")]


def main():
    conn = sqlite3.connect(":memory:")
    k = make_kernel(conn)
    bus = FakeEventBus()
    immortus = []
    llm_calls = []

    canned = json.dumps(
        {"show": {"format": "diagram", "content": "graph TD; A-->B", "alternatives": []}}
    )

    with mock.patch("backend.agent.event_bus.get_event_bus", return_value=bus), \
         mock.patch(
             "backend.gateway.iris_ffi.ffi_immortus_chain_append",
             side_effect=lambda **kw: (immortus.append(kw) or 0),
         ), \
         mock.patch(
             "backend.agent.caducean_trajectory.get_trajectory_recorder",
             return_value=FakeRecorder(SAMPLE_COORD),
         ):
        k._respond_direct = lambda *a, **kw: (llm_calls.append(1) or canned)

        # ── Store a document with rendered variants (LLM emits in one response) ──
        doc_id = str(uuid.uuid4())
        show = {
            "format": "table",
            "content": "| Name | Val |\n|------|-----|\n| A | 1 |",
            "alternatives": ["markdown", "html"],
            "variants": {
                "markdown": "# Name\n- A: 1",
                "html": "<table><tr><td>A</td><td>1</td></tr></table>",
            },
        }
        k._store_document_data(
            document_id=doc_id, show=show, trust="trusted", turn_id="t1", conversation_id="c1"
        )

        # ── T6 + T12: reformat to a STORED variant -> deterministic, no LLM ──
        out = k.reformat_document(
            document_id=doc_id, target_format="markdown", conversation_id="c1", turn_id="t1"
        )
        renders = _renders(bus)
        check("T6 DOCUMENT_RENDER emitted on reformat", len(renders) >= 1)
        d = renders[-1]["data"]
        check("T6 reformat preserves document_id", d.get("document_id") == doc_id, str(d.get("document_id"))[:8])
        check("T6 reformat preserves trust", d.get("trust") == "trusted", str(d.get("trust")))
        check("T6 reformat returns stored markdown variant", d.get("content") == "# Name\n- A: 1", str(d.get("content"))[:20])
        check("T12 NO LLM call for stored variant", len(llm_calls) == 0, f"llm_calls={len(llm_calls)}")

        # ── T12 (same-format): reformat to original format -> also deterministic ──
        out2 = k.reformat_document(
            document_id=doc_id, target_format="table", conversation_id="c1", turn_id="t1"
        )
        check("T12b same-format reformat no LLM", len(llm_calls) == 0, f"llm_calls={len(llm_calls)}")
        check("T12b returns canonical table content", "A | 1" in (out2 or ""), str(out2)[:20])

        # ── LLM fallback: genuinely new format -> LLM called + variant cached ──
        out3 = k.reformat_document(
            document_id=doc_id, target_format="diagram", conversation_id="c1", turn_id="t1"
        )
        check("LLM fallback invoked for new format", len(llm_calls) == 1, f"llm_calls={len(llm_calls)}")
        check("LLM fallback returns diagram content", "graph TD" in (out3 or ""), str(out3)[:20])
        # cached variant now retrievable deterministically
        store = DocumentDataStore.get_for(k._memory_interface)
        check("new variant cached (G1)", store.get_variant(doc_id, "diagram") == "graph TD; A-->B")
        # second reformat to diagram -> now deterministic (no extra LLM)
        out4 = k.reformat_document(
            document_id=doc_id, target_format="diagram", conversation_id="c1", turn_id="t1"
        )
        check("cached variant reformat still no LLM", len(llm_calls) == 1, f"llm_calls={len(llm_calls)}")

        # ── T13: retrieval scoping by document_id (G2) ──────────────────────
        doc_id2 = str(uuid.uuid4())
        show2 = {
            "format": "markdown",
            "content": "completely different doc",
            "alternatives": ["html"],
            "variants": {"html": "<p>completely different doc</p>"},
        }
        k._store_document_data(
            document_id=doc_id2, show=show2, trust="untrusted", turn_id="t2", conversation_id="c1"
        )
        out_a = k.reformat_document(document_id=doc_id, target_format="html", conversation_id="c1")
        out_b = k.reformat_document(document_id=doc_id2, target_format="html", conversation_id="c1")
        check("T13 doc A returns A's html variant", "<table>" in (out_a or ""), str(out_a)[:20])
        check("T13 doc B returns B's html variant (no cross-leak)", "different" in (out_b or ""), str(out_b)[:20])
        check("T13 doc A != doc B content", out_a != out_b)
        # non-existent id -> not surfaced
        out_none = k.reformat_document(document_id="does-not-exist", target_format="markdown")
        check("T13 non-existent id returns None (no cross-context)", out_none is None)

    failed = [r for r in results if not r[1]]
    print("\n=== W5 REFORMAT-BY-ID SUMMARY ===")
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED:", [r[0] for r in failed])
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
