#!/usr/bin/env python3
"""Standalone test for W7/O1: trajectory-conditioned document retrieval.

Run:  python backend/tests/test_trajectory_retrieval.py
NOT collected by pytest (no test_ prefix) to avoid the full-backend memory spike.

T10 (Trajectory retrieval, O1): a coordinate-proximity query over the Immortus
4D chain returns document data produced in a *similar reasoning state*
(coordinate proximity), distinct from embedding cosine similarity. We prove the
distinction by giving two documents IDENTICAL content at very different
coordinates: a query near one returns it first, never the other, despite the
content match. Also verifies ordering by proximity, threshold scoping, and the
agent_kernel.retrieve_documents_by_trajectory O1 primitive.
"""
import sys
import os
import json
import tempfile

REPO_ROOT = r"C:\dev\IRISVOICE"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.gateway.iris_ffi import _PythonFallbackEngine
from backend.agent.agent_kernel import AgentKernel

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), name, ("- " + str(detail)) if detail else "")


def main():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp.name
    tmp.close()

    engine = _PythonFallbackEngine(db_path, "00" * 16)

    def append_doc(doc_id, coords, content, thread="c1", outcome="document_render"):
        canonical = json.dumps(
            {"document_id": doc_id, "format": "table", "content": content, "trust": "trusted"}
        )
        engine.immortus_chain_append(
            thread_id=thread,
            result=canonical,
            coords_from=",".join(f"{c:.4f}" for c in coords),
            coords_to="table",
            nbl_outcome=outcome,
            file_path=doc_id,
        )

    # Two docs with IDENTICAL content at very different coordinates.
    append_doc("docA", (0.10, 0.10, 0.10, 0.10), "IDENTICAL CONTENT")
    append_doc("docB", (0.90, 0.90, 0.90, 0.90), "IDENTICAL CONTENT")
    # A near-A doc (different content) to test ordering.
    append_doc("docC", (0.20, 0.20, 0.20, 0.20), "near A content")
    # A far doc.
    append_doc("docD", (0.50, 0.50, 0.50, 0.50), "far content")
    # A non-document chain entry (should be excluded by nbl_outcome filter).
    append_doc("notdoc", (0.10, 0.10, 0.10, 0.10), "should be ignored", outcome="other")

    query = (0.10, 0.10, 0.10, 0.10)

    # ── T10a: proximity ordering + threshold scoping ───────────────────────
    near = engine.immortus_chain_query_by_coordinate(
        query, threshold=0.3, limit=10, nbl_outcome="document_render"
    )
    ids = [e["file_path"] for e in near]
    check("T10a docA returned (dist 0)", "docA" in ids, str(ids))
    check("T10a docC returned (dist 0.2)", "docC" in ids, str(ids))
    check("T10a docD excluded (dist 0.8)", "docD" not in ids, str(ids))
    check("T10a docB excluded (dist 1.6)", "docB" not in ids, str(ids))
    check("T10a non-doc excluded by outcome", "notdoc" not in ids, str(ids))
    check("T10a ordered by proximity (A before C)", ids.index("docA") < ids.index("docC"), str(ids))
    check("T10a docA distance ~0", abs(near[ids.index("docA")]["distance"]) < 1e-6)
    check("T10a docC distance ~0.2", abs(near[ids.index("docC")]["distance"] - 0.2) < 1e-6,
          str(near[ids.index("docC")]["distance"]))

    # ── T10b: tighter threshold excludes docC ──────────────────────────────
    tight = engine.immortus_chain_query_by_coordinate(
        query, threshold=0.15, limit=10, nbl_outcome="document_render"
    )
    tight_ids = [e["file_path"] for e in tight]
    check("T10b only docA within 0.15", tight_ids == ["docA"], str(tight_ids))

    # ── T10c: DISTINCT from semantic — identical content, coordinate orders ─
    # Query near docA must return docA first, never docB, despite identical text.
    check("T10c identical-content docB NOT returned near A", "docB" not in ids, str(ids))
    check("T10c docA (identical content) IS returned near A", "docA" in ids)

    # ── T10d: agent_kernel O1 primitive ────────────────────────────────────
    import backend.gateway.iris_ffi as iris_ffi_mod
    iris_ffi_mod._engine = engine  # point the FFI global at our engine
    k = AgentKernel.__new__(AgentKernel)
    docs = k.retrieve_documents_by_trajectory(query, threshold=0.3, conversation_id="c1")
    dids = [d.get("document_id") for d in docs]
    check("T10d O1 returns docA", "docA" in dids, str(dids))
    check("T10d O1 returns docC", "docC" in dids, str(dids))
    check("T10d O1 excludes docB", "docB" not in dids, str(dids))
    check("T10d O1 carries _distance", any(isinstance(d.get("_distance"), float) for d in docs))
    iris_ffi_mod._engine = None  # restore

    try:
        os.unlink(db_path)
    except Exception:
        pass

    failed = [r for r in results if not r[1]]
    print("\n=== W7 TRAJECTORY RETRIEVAL SUMMARY ===")
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED:", [r[0] for r in failed])
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
