"""GROUND TRUTH — the write-path fixes actually write, proven WITHOUT traffic.

specs/der-ground-truth/ T24 (REQ-16). Headless: no app, no dev server, no
developer-mode session.

WHY THIS EXISTS
---------------
Every fix in Part 1 targets a store that is empty in production, so the obvious
way to check them is "run the app and look". That is exactly the manual gate this
spec exists to remove. These tests drive each fixed writer against a temp store
and assert the row appears.

What still needs traffic is the production RATE, not the mechanism: whether the
guard passes often enough, how the failure rate reconciles. The fixes themselves
are provable now, and are proven here.
"""
import os
import sqlite3
import tempfile

import pytest

from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder
from backend.agent.termination import TerminationCause, TerminationRecord
from backend.agent import write_counters as wc


@pytest.fixture()
def rec():
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(tmp, check_same_thread=False)
    wc.reset()
    yield CaduceanTrajectoryRecorder(conn), conn, tmp
    conn.close()
    wc.reset()


class TestT4FanTraces:
    """The execution trace was emitted only by a DCP the DER loop never builds."""

    def test_traces_are_written_and_a_failure_is_recorded_faithfully(self, rec):
        r, conn, _ = rec
        for i in range(3):
            r.record_fan_trace(session_id="s1", step_id=f"st{i}", tool="crawler_query",
                               args_hash="abc",
                               outcome="VERIFIED" if i else "FAILED", u=0.1, xi=0.2)
        assert conn.execute("SELECT COUNT(*) FROM der_fan_traces").fetchone()[0] == 3
        # REQ-1 AC6: a missing row and a failed row must never look alike.
        assert conn.execute(
            "SELECT COUNT(*) FROM der_fan_traces WHERE outcome='FAILED'").fetchone()[0] == 1


class TestT5FailuresReachPhysics:
    """Live store: 26.9% episode failure rate vs 0.5% at the physics layer."""

    def test_failed_commits_persist(self, rec):
        r, conn, _ = rec
        for lbl in ("VERIFIED", "FAILED", "UNVERIFIED", "FAILED"):
            r.record_commit(session_id="s1", step_id="x", commit_hash="", message="m",
                            u=0.0, xi=0.0, verified_label=lbl)
        assert conn.execute(
            "SELECT COUNT(*) FROM der_commits WHERE verified_label='FAILED'"
        ).fetchone()[0] == 2

    def test_failure_trajectories_persist(self, rec):
        r, conn, _ = rec
        for i, out in enumerate(("success", "failure", "failure")):
            r.record(session_id="s1", step_num=i, x=0.0, y=0.0, xi=0.0, u=0.0,
                     action="a", outcome=out, eml_after=0.0, recommendation="r")
        assert conn.execute(
            "SELECT COUNT(*) FROM caducean_trajectories WHERE outcome='failure'"
        ).fetchone()[0] == 2


class TestT19AndFinding10:
    """A run must record WHY it stopped, on a row that joins to something."""

    def test_exit_carries_cause_headroom_and_a_joinable_identity(self, rec):
        r, conn, _ = rec
        r.record_session_exit(
            session_id="kernel-proc", domain="d", natural_exit=False,
            conversation_id="conv-42",
            termination=TerminationRecord(TerminationCause.TOKEN_BUDGET,
                                          configured=120000, measured=119873),
        )
        row = conn.execute(
            "SELECT conversation_id, termination_cause, bound_configured, bound_measured "
            "FROM caducean_session_exits").fetchone()
        # Finding 10: exits spanned 2 session ids while episodes spanned 47.
        assert row[0] == "conv-42"
        assert row[1] == "token_budget"
        # REQ-9 AC3: "how close was it" answerable without a reproduction.
        assert int(row[2] - row[3]) == 127


class TestT10SilentFailurePolicy:
    """A swallowed write must leave a number behind."""

    def test_skips_and_successes_are_both_counted(self):
        wc.reset()
        wc.bump("edge_scoring.skipped_no_region", 5)
        wc.bump("edge_scoring.written")
        assert wc.get("edge_scoring.skipped_no_region") == 5
        # The POSITIVE is what makes the negative interpretable: without it,
        # zero writes and zero attempts are indistinguishable.
        assert wc.get("edge_scoring.written") == 1


class TestInvariantsOverAFixedStore:
    """The closer: a store written ONLY by the fixed paths passes the invariants
    that the live (pre-fix) store fails."""

    def test_fan_trace_and_failure_invariants_flip_to_PASS(self, rec):
        import importlib.util
        r, conn, tmp = rec
        # Build a store the way the fixed writers do.
        for i in range(4):
            r.record_fan_trace(session_id="s", step_id=f"st{i}", tool="t",
                               args_hash="h", outcome="VERIFIED", u=0.0, xi=0.0)
            r.record_commit(session_id="s", step_id=f"st{i}", commit_hash="",
                            message="m", u=0.0, xi=0.0,
                            verified_label="FAILED" if i < 1 else "VERIFIED")
            r.record(session_id="s", step_num=i, x=0.0, y=0.0, xi=0.0, u=0.0,
                     action="a", outcome="failure" if i < 1 else "success",
                     eml_after=0.0, recommendation="r")
        conn.commit()

        spec = importlib.util.spec_from_file_location(
            "vsi", os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                "scripts", "validate_store_invariants.py"))
        vsi = importlib.util.module_from_spec(spec)
        # Register BEFORE exec: the module defines dataclasses, and dataclasses
        # resolves annotations via sys.modules[cls.__module__].
        import sys as _sys
        _sys.modules["vsi"] = vsi
        spec.loader.exec_module(vsi)
        results = {x.name: x.status for x in vsi.run(tmp)}

        # These FAIL against the live pre-fix store; they PASS here because the
        # fixed writers produced the rows.
        assert results["every_step_has_fan_trace"] == "PASS", results
        assert results["commits_carry_verified_label"] == "PASS", results
