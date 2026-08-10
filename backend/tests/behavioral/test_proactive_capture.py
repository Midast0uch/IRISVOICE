#!/usr/bin/env python3
"""Standalone test for W9: proactive structured-data capture from tool results (O3).

Run:  python backend/tests/test_proactive_capture.py
NOT collected by pytest (no test_ prefix) to avoid the full-backend memory spike.

Covers T15 (behavioral): structured data from a non-show tool result
(web_search / read_file) is captured into DocumentDataStore and becomes
reformat-able via reformat_document (W5). Trivial / error / low-relevance
results are skipped by the capture-worthiness gate.
"""
import sys
import os
import sqlite3
import tempfile

REPO_ROOT = r"C:\dev\IRISVOICE"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.agent.agent_kernel import AgentKernel
from backend.agent.document_store import DocumentDataStore

results = []


def check(name, cond, detail=""):
    results.append((name, cond, detail))
    print(("PASS" if cond else "FAIL"), name, ("- " + detail) if detail else "")


def make_kernel():
    """Build an AgentKernel without running __init__ (avoids heavy setup)."""
    k = AgentKernel.__new__(AgentKernel)
    k._turn_touched_external = False
    k._memory_interface = None
    # Real, isolated DocumentDataStore backed by a temp SQLite DB.
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
    cid = "conv_w9"

    # ── T15a: web_search result is captured as untrusted + reformat-able ────
    web_result = {
        "query": "iris voice architecture",
        "results": [
            {"title": "IRIS Voice", "url": "https://x.com", "snippet": "voice assistant"},
        ],
    }
    doc_id = k._capture_tool_result("web_search", web_result, cid, turn_id="t1")
    check("T15a web_search captured -> document_id returned", doc_id is not None, str(doc_id))
    rec = k._doc_store.get(doc_id)
    check("T15a stored record present", rec is not None)
    check("T15a trust == untrusted (external tool)", rec["trust"] == "untrusted", rec["trust"])
    check("T15a format == json", rec["format"] == "json", rec["format"])
    # reformat to its own stored variant -> deterministic, no LLM
    reformatted = k.reformat_document(document_id=doc_id, target_format="json", conversation_id=cid)
    check("T15a reformat_document returns stored variant",
          reformatted is not None and "IRIS Voice" in reformatted, str(reformatted)[:60])

    # ── T15b: read_file result is captured as trusted + reformat-able ──────
    file_result = (
        "def main():\n"
        "    print('hello iris')\n"
        "    # a longer comment so the payload exceeds the triviality threshold\n"
        "    return 0\n"
    )
    doc_id2 = k._capture_tool_result("read_file", file_result, cid, turn_id="t2")
    check("T15b read_file captured", doc_id2 is not None)
    rec2 = k._doc_store.get(doc_id2)
    check("T15b trust == trusted (local tool)", rec2["trust"] == "trusted", rec2["trust"])
    check("T15b format == text", rec2["format"] == "text", rec2["format"])
    reformatted2 = k.reformat_document(document_id=doc_id2, target_format="text", conversation_id=cid)
    check("T15b reformat_document returns stored variant",
          reformatted2 is not None and "hello iris" in reformatted2, str(reformatted2)[:60])

    # ── T15c: trivial short result is NOT captured ─────────────────────────
    doc_id3 = k._capture_tool_result("read_file", "ok", cid, turn_id="t3")
    check("T15c trivial result skipped (None)", doc_id3 is None, str(doc_id3))

    # ── T15d: error payload is NOT captured ────────────────────────────────
    doc_id4 = k._capture_tool_result("web_search", {"error": "rate limited"}, cid, turn_id="t4")
    check("T15d error payload skipped (None)", doc_id4 is None, str(doc_id4))

    # ── T15e: low-relevance scored result is skipped; high is captured ─────
    low = {"data": "some content here that is long enough to pass length", "relevance": 0.1}
    doc_id5 = k._capture_tool_result("web_search", low, cid, turn_id="t5")
    check("T15e low-relevance skipped (None)", doc_id5 is None, str(doc_id5))
    high = {"data": "some content here that is long enough to pass length", "relevance": 0.9}
    doc_id6 = k._capture_tool_result("web_search", high, cid, turn_id="t6")
    check("T15e high-relevance captured", doc_id6 is not None)

    # ── T15f: capture-worthiness gate is deterministic ────────────────────
    check("T15f None skipped", k._is_capture_worthy("web_search", None) is False)
    check("T15f dict with error skipped",
          k._is_capture_worthy("web_search", {"error": "x"}) is False)
    check("T15f long string captured", k._is_capture_worthy("read_file", "x" * 60) is True)

    # cleanup
    try:
        os.remove(k._doc_store_path)
    except Exception:
        pass

    failed = [r for r in results if not r[1]]
    print("\n=== W9 PROACTIVE CAPTURE SUMMARY ===")
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED:", [r[0] for r in failed])
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
