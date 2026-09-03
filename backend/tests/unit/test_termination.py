"""GROUND TRUTH REQ-9 / REQ-10 — every run records WHY it stopped.

specs/der-ground-truth/ T18/T19/T21/T22. Headless: no network, no TTS, no model,
no GUI, no developer-mode session (REQ-10 AC5).

The property under test is not "the loop stops" — it already does, via eight-plus
bounds across four modules. It is that **a run that stopped because it ran OUT of
something is distinguishable, afterwards, from one that finished**. Today those
are identical in the record, which is why every loop pathology needs a live
reproduction to diagnose.
"""
import sqlite3
import tempfile
import os

import pytest

from backend.agent.termination import (
    BOUNDED_EXITS,
    CAUSE_BOUNDS,
    TerminationCause,
    TerminationRecord,
    classify,
)
from backend.agent import write_counters as wc


@pytest.fixture(autouse=True)
def _clean():
    wc.reset()
    yield
    wc.reset()


class TestVocabulary:
    """REQ-9 AC1/AC6 — closed set, reserved member, nothing discarded."""

    def test_covers_every_existing_exit_path(self):
        # The eight-plus bounds that already exist, each with a name.
        for expected in ("natural", "sufficiency", "cycle_cap", "token_budget",
                         "turn_wallclock", "veto_cap", "graft_cap", "depth_cap",
                         "zero_yield", "permission_refused", "user_abort",
                         "unexpected"):
            assert TerminationCause(expected).value == expected

    def test_classify_is_forgiving_about_form_but_not_about_meaning(self):
        assert classify("cycle_cap") is TerminationCause.CYCLE_CAP
        assert classify("CYCLE-CAP") is TerminationCause.CYCLE_CAP
        assert classify(" Cycle Cap ") is TerminationCause.CYCLE_CAP

    def test_an_unrecognised_cause_is_counted_never_discarded(self):
        assert classify("gremlins") is TerminationCause.UNEXPECTED
        assert classify(None) is TerminationCause.UNEXPECTED
        # REQ-9 AC6: the Layer-3 discipline. Unknown is kept and tallied.
        assert wc.get("termination.unexpected_cause") == 2

    def test_every_bounded_cause_names_the_constant_that_defines_it(self):
        # REQ-9 AC5 forbids this module from CHANGING any bound, so the mapping
        # is documentation that cannot drift from what it documents.
        for cause in BOUNDED_EXITS:
            if cause is not TerminationCause.ZERO_YIELD:
                assert cause in CAUSE_BOUNDS, f"{cause} has no named bound"


class TestRecord:
    """REQ-9 AC3 — how close was it, answerable without a reproduction."""

    def test_headroom_from_configured_and_measured(self):
        r = TerminationRecord(TerminationCause.CYCLE_CAP, configured=40, measured=40)
        assert r.headroom == 0.0
        assert TerminationRecord(TerminationCause.CYCLE_CAP, 40, 12).headroom == 28.0

    def test_headroom_is_none_when_not_measurable_not_zero(self):
        # None means "unknown". Zero would mean "exactly at the bound" — a
        # completely different fact, and the confusion this spec exists to stop.
        assert TerminationRecord(TerminationCause.NATURAL).headroom is None
        assert TerminationRecord(TerminationCause.CYCLE_CAP, 40, None).headroom is None

    def test_a_bounded_exit_is_not_a_success(self):
        # REQ-10 AC2: a run stopped by a bound must never report as finished.
        for c in (TerminationCause.CYCLE_CAP, TerminationCause.TOKEN_BUDGET,
                  TerminationCause.TURN_WALLCLOCK, TerminationCause.ZERO_YIELD):
            assert TerminationRecord(c).is_bounded_exit is True
        for c in (TerminationCause.NATURAL, TerminationCause.SUFFICIENCY):
            assert TerminationRecord(c).is_bounded_exit is False

    def test_co_occurring_near_miss_stays_visible(self):
        # REQ-9 edge case: two bounds trip in the same cycle. The one that
        # stopped dispatch is the cause; the other is recorded, not dropped.
        r = TerminationRecord(TerminationCause.TOKEN_BUDGET,
                              co_occurring=TerminationCause.CYCLE_CAP)
        assert r.to_dict()["co_occurring_cause"] == "cycle_cap"

    def test_a_disabled_bound_is_recorded_as_disabled(self):
        # So a distribution is never read against the wrong configuration.
        assert TerminationRecord(TerminationCause.NATURAL, disabled=True).to_dict()[
            "bound_disabled"] == 1


class TestPersistence:
    """T19/T22 — the cause reaches the ledger, and absence stays honest."""

    def _recorder(self):
        from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(tmp, check_same_thread=False)
        return CaduceanTrajectoryRecorder(conn), tmp, conn

    def test_each_cause_round_trips_to_the_exit_ledger(self):
        rec, tmp, conn = self._recorder()
        try:
            for i, cause in enumerate(TerminationCause):
                rec.record_session_exit(
                    session_id=f"s{i}", domain="d", natural_exit=(cause is TerminationCause.NATURAL),
                    termination=TerminationRecord(cause, configured=40, measured=i),
                )
            rows = dict(conn.execute(
                "SELECT session_id, termination_cause FROM caducean_session_exits"))
            assert len(rows) == len(list(TerminationCause))
            assert set(rows.values()) == {c.value for c in TerminationCause}
        finally:
            conn.close()

    def test_a_caller_that_supplies_no_cause_leaves_it_NULL_not_invented(self):
        # REQ-9: absence is recorded as absence. The REQ-6 invariant then reports
        # it honestly rather than a fabricated "natural".
        rec, tmp, conn = self._recorder()
        try:
            rec.record_session_exit(session_id="x", domain="d", natural_exit=True)
            row = conn.execute(
                "SELECT termination_cause FROM caducean_session_exits").fetchone()
            assert row[0] is None
        finally:
            conn.close()

    def test_a_malformed_record_does_not_take_the_exit_row_down_with_it(self):
        rec, tmp, conn = self._recorder()

        class Broken:
            def to_dict(self):
                raise RuntimeError("boom")

        try:
            rec.record_session_exit(session_id="b", domain="d", natural_exit=False,
                                    termination=Broken())
            row = conn.execute(
                "SELECT session_id, termination_cause FROM caducean_session_exits"
            ).fetchone()
            # the row survives, and the cause degrades to the reserved member
            assert row[0] == "b"
            assert row[1] == "unexpected"
        finally:
            conn.close()

    def test_configured_and_measured_survive_the_round_trip(self):
        rec, tmp, conn = self._recorder()
        try:
            rec.record_session_exit(
                session_id="m", domain="d", natural_exit=False,
                termination=TerminationRecord(TerminationCause.TOKEN_BUDGET,
                                              configured=120000, measured=119873),
            )
            row = conn.execute(
                "SELECT bound_configured, bound_measured FROM caducean_session_exits"
            ).fetchone()
            assert row[0] == 120000.0
            # "how close was it" — 127 tokens of headroom, answerable from the row
            assert row[1] == 119873.0
        finally:
            conn.close()
