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
            "use_thinking": {"rows": 200, "precision": 0.88, "ece": 0.02},
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
        assert "precision" in record["use_thinking"].gap
        assert "ECE" in record["needs_action"].gap
        for cid in ("has_gaps", "use_thinking", "needs_action"):
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
