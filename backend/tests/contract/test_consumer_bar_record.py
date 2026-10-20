"""Contract tests: the per-consumer enforcement bar record (REQ-31 AC31.5, T52).

AC31.5 — THE SYSTEM SHALL record, per consumer, the measured bar (rows,
precision, ECE) that justified its enforcement flip or its continued shadow
status.

Without this the question "why is this consumer enforced?" is unanswerable, and
a flip measured at a superseded configuration cannot be detected (AC31.6).
"""

from __future__ import annotations

from pathlib import Path

from backend.agent.consumer_bar import (
    BAR_PATH,
    MAX_ECE,
    MIN_PRECISION,
    MIN_ROWS,
    build_bar,
    derive_status,
    load_bar_record,
    record_bars,
    save_bar_record,
)

_REPO = Path(__file__).resolve().parents[3]


class TestBarRecordedPerConsumer:
    def test_bar_recorded_per_consumer(self, tmp_path, monkeypatch):
        """AC31.5: every measured consumer gets a record with its numbers, its
        status, and — when shadow — the clause it missed."""
        import backend.agent.consumer_bar as cb

        target = tmp_path / "consumer_bar_record.json"
        monkeypatch.setattr(cb, "BAR_PATH", target)

        measured = {
            "tool_choice": {"rows": 500, "precision": 0.96, "ece": 0.01},
            "has_gaps": {"rows": 40, "precision": 0.93, "ece": 0.02},
            # The precision-gap case (was use_thinking, removed 2026-10-13).
            "depth_met": {"rows": 200, "precision": 0.88, "ece": 0.02},
            "needs_action": {"rows": 200, "precision": 0.95, "ece": 0.11},
        }
        record = record_bars(
            measured,
            config={"candidate_cap": 6, "backend_id": "gliner25-decide-onnx-int8"},
        )

        assert set(record) == set(measured), (
            "a measured consumer has no bar record (AC31.5)"
        )

        # The flipped one.
        tc = record["tool_choice"]
        assert tc.flipped and tc.gap == ""
        assert (tc.rows, tc.precision, tc.ece) == (500, 0.96, 0.01)
        assert tc.config["candidate_cap"] == 6, (
            "the record must store the configuration it was measured at, or "
            "AC31.6's superseded-flip check is impossible"
        )

        # Each shadow one names the clause it missed — no silent shadow.
        assert "rows 40" in record["has_gaps"].gap
        assert "precision" in record["depth_met"].gap
        assert "ECE" in record["needs_action"].gap
        for cid in ("has_gaps", "depth_met", "needs_action"):
            assert record[cid].status == "shadow"

        # And it is PERSISTED where the next run will read it.
        assert target.is_file(), "the bar record was not written"
        reloaded = load_bar_record(target)
        assert set(reloaded) == set(measured)
        assert reloaded["tool_choice"].flipped

    def test_the_bar_is_the_documented_one(self):
        """The recorded bar is TG-7's: rows, precision AND an ECE bound."""
        assert MIN_ROWS == 100
        assert MIN_PRECISION == 0.90
        assert MAX_ECE > 0.0

        # Boundaries are inclusive on the passing side.
        assert derive_status(MIN_ROWS, MIN_PRECISION, MAX_ECE)[0] == "enforced"
        assert derive_status(MIN_ROWS - 1, MIN_PRECISION, MAX_ECE)[0] == "shadow"
        assert derive_status(MIN_ROWS, MIN_PRECISION - 1e-9, MAX_ECE)[0] == "shadow"
        assert derive_status(MIN_ROWS, MIN_PRECISION, MAX_ECE + 1e-9)[0] == "shadow"

    def test_the_record_lives_in_the_repo(self):
        """A temp path would be invisible to the next run."""
        assert "benchmarks" in str(BAR_PATH)
        assert _REPO in BAR_PATH.parents

    def test_the_acting_clause_grades_the_side_that_acts(self):
        """An asymmetric consumer is graded on the answer that changes behaviour.

        Measured 2026-10-19 (needs_action/v5, 111 rows): the aggregate bar passed
        (precision 0.9492) while the acting answer, the only one that moves a
        step to DIRECT, stood at 13 rows / low precision. The clause makes that
        state "shadow" with the acting gap, and only a clean acting side passes.
        """
        good = {
            "rows_distinct": 120,
            "classes": {"correct": 96, "wrong": 24},
            "threshold": 0.9,
            "rows_above": 60,
            "oof": {
                "auroc": 0.8, "ece": 0.02,
                "precision_at_t": 0.95, "wilson_lb": 0.9,
                # the aggregate passes; the acting side does not
                "acting_answer": "no", "acting_rows_above": 13,
                "acting_precision": 0.77, "acting_wilson_lb": 0.5,
            },
            "acting_required": True,
        }
        status, gap = derive_status(120, 0.95, 0.0, honest=good)
        assert status == "shadow"
        assert "acting answer 'no'" in gap and "13 rows" in gap

        good["oof"].update(acting_rows_above=60, acting_precision=0.95,
                           acting_wilson_lb=0.9)
        assert derive_status(120, 0.95, 0.0, honest=good)[0] == "enforced"

        # The same numbers WITHOUT the clause still pass: adoption is explicit,
        # so a report run cannot demote a consumer that already decides.
        del good["acting_required"]
        good["oof"].update(acting_rows_above=13, acting_precision=0.5)
        assert derive_status(120, 0.95, 0.0, honest=good)[0] == "enforced"

    def test_an_absent_or_broken_record_is_empty_not_fatal(self, tmp_path):
        """A missing/garbled record is EMPTY — never an exception."""
        missing = tmp_path / "nope.json"
        assert load_bar_record(missing) == {}

        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        assert load_bar_record(broken) == {}

        partial = tmp_path / "partial.json"
        partial.write_text(
            '{"ok": {"consumer_id": "ok", "rows": 1, "precision": 0.1,'
            ' "ece": null, "status": "shadow", "gap": "g", "config": {}},'
            ' "bad": {"nonsense": true}}',
            encoding="utf-8",
        )
        out = load_bar_record(partial)
        assert set(out) == {"ok"}, (
            "a malformed row must be skipped, not lose the whole record"
        )

    def test_an_empty_record_round_trips(self, tmp_path):
        target = tmp_path / "empty.json"
        save_bar_record({}, target)
        assert load_bar_record(target) == {}

    def test_build_bar_defaults_are_conservative(self):
        """Missing numbers must NOT read as a pass."""
        bar = build_bar("x", {})
        assert bar.status == "shadow"
        assert bar.rows == 0
        assert bar.precision == 0.0
        assert bar.ece is None
