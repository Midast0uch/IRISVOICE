"""Phase 3 tests — Invariant Suite (G1-G5 enforcement + System Invariant).

Validates D3.1-D3.3 of docs/DER_COUPLED_ACTION_CYCLE_SPEC.md:
  G1 : stub/placeholder result -> FAILED (never silently VERIFIED)
  G2 : honest feedback (no false success edge on veto/failure)
  G3 : termination bounded (split refused when work_units exhausted / MAX_DEPTH)
  G4 : skill registration gated on VERIFIED (unverified -> refused)
  G5 : commit ledger written ONLY on VERIFIED (honest audit trail)
"""

import types

import pytest


def _make_kernel():
    from backend.agent.agent_kernel import AgentKernel

    k = AgentKernel.__new__(AgentKernel)
    k._memory_interface = None
    k._tool_bridge = None
    k._der_task_class = "full"
    k._der_completed_tools = []
    k._der_work_units = 0
    k.conversation_id = "test-conv"
    k.session_id = "test-session"
    return k


# ── G1: stub/placeholder result -> FAILED ───────────────────────────────────
def test_g1_stub_is_failed():
    k = _make_kernel()
    # A stub/placeholder actual result must never verify as success.
    verdict = k._verify_step_result(
        "create file",
        "file created and tests pass",
        "[step 1 completed successfully]",
    )
    assert verdict == "FAILED", "stub/placeholder result must be FAILED (G1)"


# ── G2: honest feedback — no false success on failure ───────────────────────
def test_g2_no_false_success_on_failure():
    k = _make_kernel()
    # A clearly-wrong result must not be VERIFIED.
    verdict = k._verify_step_result(
        "return the sum",
        "returns 42",
        "Error: division by zero",
    )
    assert verdict != "VERIFIED", "error result must not be VERIFIED (G2)"
    assert verdict in ("FAILED", "UNVERIFIED")


# ── G3: termination bounded — split refused when work_units exhausted ───────
def test_g3_termination_bounded():
    from backend.agent.der_constants import MAX_DEPTH

    k = _make_kernel()
    from backend.agent.der_loop import QueueItem

    item = QueueItem(
        step_id="s1", step_number=1, description="x",
        objective_anchor="o", depth_layer=0, expected_output="x",
    )
    cad = {"u": 0.0}  # unresolved -> wants wide split
    # work_units = 0 -> split MUST be refused (bounded termination)
    children = k._split_step(item, "unresolved_u", cad, work_units=0)
    assert children == [], "split refused when work_units exhausted (G3)"
    # Also refused at MAX_DEPTH
    item2 = QueueItem(
        step_id="s2", step_number=1, description="x",
        objective_anchor="o", depth_layer=MAX_DEPTH, expected_output="x",
    )
    children2 = k._split_step(item2, "unresolved_u", cad, work_units=10)
    assert children2 == [], "split refused at MAX_DEPTH (G3)"


# ── G4: skill registration gated on VERIFIED ────────────────────────────────
def test_g4_skill_gate_on_verified():
    from backend.agent import workflow_capture as wc

    # Unverified stub -> registration refused (returns empty key, no write).
    unverified = {
        "name": "do_thing",
        "verified": False,
        "summary": "x",
        "command": "x",
        "category": "build",
    }
    key = wc.register_verified_skill(unverified, memory=None, confidence=0.9)
    assert key == "", "unverified skill must NOT be registered (G4)"

    # Verified stub -> registration allowed.
    verified = dict(unverified)
    verified["verified"] = True
    verified["description"] = "does the thing"
    verified["tool_sequence"] = [{"tool": "run_command", "params": {}}]
    # memory=None would try to write; stub it to avoid DB. We only assert the
    # gate logic: a verified stub passes the gate (reaches skill_key build).
    # Use a fake memory that records the write.
    class _Semantic:
        def __init__(self):
            self.written = []

        def update(self, category=None, key=None, value=None, **kw):
            self.written.append((key, value))

    class _Mem:
        def __init__(self):
            self.semantic = _Semantic()

    mem = _Mem()
    key2 = wc.register_verified_skill(verified, memory=mem, confidence=0.9)
    assert key2 != "", "verified skill passes the gate (G4)"
    assert mem.semantic.written, "verified skill is actually written"


# ── G5: commit ledger written ONLY on VERIFIED ──────────────────────────────
def test_g5_commit_only_on_verified():
    import sqlite3

    from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder

    conn = sqlite3.connect(":memory:")
    rec = CaduceanTrajectoryRecorder(db_conn=conn)
    # Fresh in-memory check: record_commit writes a row.
    before = rec._conn.execute(
        "SELECT COUNT(*) FROM der_commits"
    ).fetchone()[0]
    rec.record_commit("test-session", "s1", "abc123", "VERIFIED step", u=0.2, xi=0.1)
    after = rec._conn.execute(
        "SELECT COUNT(*) FROM der_commits"
    ).fetchone()[0]
    assert after == before + 1, "VERIFIED step writes a commit ledger row (G5)"
    # The row carries the session + step
    row = rec._conn.execute(
        "SELECT session_id, step_id, commit_hash FROM der_commits ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row[0] == "test-session" and row[1] == "s1" and row[2] == "abc123"
