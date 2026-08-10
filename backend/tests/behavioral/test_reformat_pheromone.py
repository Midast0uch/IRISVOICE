#!/usr/bin/env python3
"""Standalone test for W10: pheromone-reinforced reformat + cross-modal synergy (O4).

Run:  python backend/tests/test_reformat_pheromone.py
NOT collected by pytest (no test_ prefix) to avoid the full-backend memory spike.

Covers T16 (behavioral): reformat usage reinforces a pheromone edge; the
most-reinforced target format is predicted; reformat_document records the edge;
suggest_reformat surfaces the prediction; vocalize_document speaks the
reformatted content via SpeakTool; diagram_document returns a diagram view.
"""
import sys
import os
import sqlite3
import tempfile

REPO_ROOT = r"C:\dev\IRISVOICE"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import uuid
from backend.agent.agent_kernel import AgentKernel
from backend.agent.document_store import DocumentDataStore
from backend.agent.tools import speak_tool as speak_mod
from backend.agent.tools.speak_tool import SpeakTool

results = []


def check(name, cond, detail=""):
    results.append((name, cond, detail))
    print(("PASS" if cond else "FAIL"), name, ("- " + detail) if detail else "")


def make_kernel():
    k = AgentKernel.__new__(AgentKernel)
    k._turn_touched_external = False
    k._memory_interface = None
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    k._doc_store = DocumentDataStore(sqlite3.connect(path))
    k._doc_store_path = path

    def _get_document_store():
        return k._doc_store

    k._get_document_store = _get_document_store
    return k


def main():
    k = make_kernel()
    cid = "conv_w10"
    store = k._doc_store

    # ── T16a: reformat pheromone edge reinforces + predicts ─────────────────
    store.record_reformat("table", "markdown")
    store.record_reformat("table", "markdown")  # compound
    store.record_reformat("table", "html")
    edges = store.get_reformat_edges("table")
    check("T16a edges recorded (2)", len(edges) == 2, str(edges))
    check("T16a table->markdown is top (compounded to 2.0)",
          edges[0] == {"from_format": "table", "to_format": "markdown", "weight": 2.0}, str(edges[0]))
    check("T16a predict_next_format returns markdown", store.predict_next_format("table") == "markdown")
    check("T16a unknown from_format -> None", store.predict_next_format("xyz") is None)

    # ── T16b: reformat_document records the edge (hook fires) ──────────────
    doc_id = str(uuid.uuid4())
    store.store(document_id=doc_id, conversation_id=cid, fmt="table",
                content="| a | b |\n|---|---|\n| 1 | 2 |", variants={"table": "| a | b |"},
                alternatives=[], trust="trusted")
    store.add_variant(doc_id, "markdown", "| a | b |\n|---|---|\n| 1 | 2 |")
    out = k.reformat_document(document_id=doc_id, target_format="markdown", conversation_id=cid)
    check("T16b reformat returns markdown variant", out is not None)
    edges2 = store.get_reformat_edges("table")
    top = edges2[0]
    check("T16b hook recorded table->markdown edge (weight >= 1.0)",
          top["to_format"] == "markdown" and top["weight"] >= 1.0, str(top))

    # ── T16c: suggest_reformat surfaces the prediction ─────────────────────
    sug = k.suggest_reformat(doc_id, conversation_id=cid)
    check("T16c suggest_reformat returns markdown", sug == "markdown", str(sug))
    check("T16c suggest_reformat unknown doc -> None", k.suggest_reformat("nope") is None)

    # ── T16d: vocalize_document speaks the reformatted content ─────────────
    spoken = {}

    class FakeSpeak(SpeakTool):
        def speak(self, text, priority="normal", interrupt=False):
            spoken["text"] = text
            return {"status": "ok", "utterance_id": "x"}

    speak_mod.get_speak_tool = lambda: FakeSpeak()
    status = k.vocalize_document(doc_id, target_format="markdown", conversation_id=cid)
    check("T16d vocalize returns ok", status.get("status") == "ok", str(status))
    check("T16d SpeakTool received reformatted content",
          "a" in spoken.get("text", ""), str(spoken.get("text", ""))[:40])

    # ── T16e: diagram_document returns a diagram view ──────────────────────
    store.add_variant(doc_id, "diagram", "graph TD; A-->B")
    diag = k.diagram_document(doc_id, conversation_id=cid)
    check("T16e diagram_document returns mermaid content",
          diag is not None and "graph TD" in diag, str(diag)[:40])

    # cleanup
    try:
        os.remove(k._doc_store_path)
    except Exception:
        pass

    failed = [r for r in results if not r[1]]
    print("\n=== W10 REFORMAT PHEROMONE SUMMARY ===")
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED:", [r[0] for r in failed])
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
