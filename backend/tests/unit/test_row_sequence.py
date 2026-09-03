"""GROUND TRUTH REQ-17 / REQ-13 — the backend-owned row ordering key.

specs/der-ground-truth/ T28/T29. Pure unit tests: no app, no DB, no network.

The property that matters is MEMOIZATION. Allocation order must equal emit order
(so a row created between planner steps sorts between them), while re-emitting an
existing row must return the key it already owns (so a revision, graft, or split
cannot renumber a card that is already on screen). Get one of those two wrong and
the card either loses chronology or reshuffles under the user mid-run.
"""
import pytest

from backend.agent import row_sequence as rs
from backend.agent import write_counters as wc


@pytest.fixture(autouse=True)
def _clean():
    rs.reset_all()
    wc.reset()
    yield
    rs.reset_all()
    wc.reset()


class TestAllocation:
    def test_allocates_monotonically_in_emit_order(self):
        assert rs.seq_for("c", "a") == 1
        assert rs.seq_for("c", "b") == 2
        assert rs.seq_for("c", "d") == 3

    def test_memoized_per_row_identity(self):
        first = rs.seq_for("c", "a")
        rs.seq_for("c", "b")
        # re-emitting "a" (revision / graft / split) returns its ORIGINAL key
        assert rs.seq_for("c", "a") == first

    def test_a_revision_cannot_renumber_existing_rows(self):
        p1 = rs.seq_for("c", "p1")
        p2 = rs.seq_for("c", "p2")
        # graft re-emits p1 alongside a new child
        assert rs.seq_for("c", "p1") == p1
        child = rs.seq_for("c", "p1_child")
        assert child > p2
        assert len({p1, p2, child}) == 3, "distinct rows must never collide"

    def test_a_phase_row_interleaves_with_planner_rows(self):
        p1 = rs.seq_for("c", "p1")
        phase = rs.seq_for("c", "phase-searching")
        p2 = rs.seq_for("c", "p2")
        # the phase opened between the two planner rows and sorts between them
        assert p1 < phase < p2

    def test_a_revisited_phase_keeps_its_key(self):
        first = rs.seq_for("c", "phase-searching")
        rs.seq_for("c", "phase-extracting")
        # a re-query returns to the same phase; the reducer flips that existing
        # node back to working rather than appending a second one
        assert rs.seq_for("c", "phase-searching") == first

    def test_conversations_are_isolated(self):
        assert rs.seq_for("c1", "a") == 1
        assert rs.seq_for("c2", "a") == 1
        assert rs.seq_for("c1", "b") == 2


class TestDegradedPaths:
    def test_missing_inputs_return_zero_not_a_fabricated_key(self):
        # 0 means "no key" and the emitter contract (rule E1) surfaces it.
        # Inventing a key would hide a real defect.
        assert rs.seq_for(None, "a") == 0
        assert rs.seq_for("c", None) == 0
        assert rs.seq_for("", "") == 0

    def test_peek_never_allocates(self):
        assert rs.peek("c", "a") == 0
        assert rs.peek("c", "a") == 0
        assert rs.seq_for("c", "a") == 1, "peek must not have consumed a value"
        assert rs.peek("c", "a") == 1

    def test_reset_conversation_is_scoped(self):
        rs.seq_for("c1", "a")
        rs.seq_for("c2", "a")
        rs.reset_conversation("c1")
        assert rs.seq_for("c1", "a") == 1, "c1 restarts"
        assert rs.peek("c2", "a") == 1, "c2 untouched"

    def test_conversation_cap_evicts_oldest_and_stays_bounded(self):
        for i in range(rs.MAX_CONVERSATIONS + 10):
            rs.seq_for("conv%d" % i, "row")
        assert len(rs._ROWS) <= rs.MAX_CONVERSATIONS

    def test_row_cap_still_yields_unique_ascending_keys_and_counts_it(self):
        cid = "big"
        for i in range(rs.MAX_ROWS_PER_CONVERSATION + 5):
            rs.seq_for(cid, "r%d" % i)
        # past the cap, memoization is lost but ORDER is not: keys stay unique
        # and ascending. And the degradation is COUNTED, never silent.
        a = rs.seq_for(cid, "beyond-1")
        b = rs.seq_for(cid, "beyond-2")
        assert b > a
        assert wc.get("row_sequence.unmemoized_allocation") > 0


class TestWriteCounters:
    def test_counts_and_totals(self):
        wc.bump("x")
        wc.bump("x", 4)
        wc.bump("y")
        assert wc.get("x") == 5
        assert wc.total() == 6

    def test_empty_name_is_ignored(self):
        wc.bump("")
        assert wc.total() == 0

    def test_distinct_name_cap_records_the_overflow(self):
        for i in range(wc.MAX_DISTINCT_NAMES + 20):
            wc.bump("n%d" % i)
        snap = wc.snapshot()
        assert len(snap) <= wc.MAX_DISTINCT_NAMES + 1
        # REQ-13: a silent cap reads as full coverage when it is not.
        assert snap.get("_counter_names_overflow", 0) > 0

    def test_never_raises_on_bad_input(self):
        wc.bump(None)  # type: ignore[arg-type]
        wc.bump("ok", None)  # type: ignore[arg-type]
        assert isinstance(wc.total(), int)
