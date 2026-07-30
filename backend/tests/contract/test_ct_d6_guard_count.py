"""CT-D6: guard count.

Spec: specs/phase-6-der-integrity/design.md Testing Strategy > Contract table,
row CT-D6. "The debug endpoint reports live_guards == 3 with an empty
dead-guard list."

Drives the REAL `/api/debug/caducean` `_outer_loop()` section (not a
reimplementation of it) by monkeypatching the `OuterTuner` name it imports
at call time to a factory bound to an in-memory, fully-seeded recorder — the
same technique the endpoint itself would see in production once real
session-exit rows with `tokens_total` and `executed_steps` populated exist.
"""

from __future__ import annotations

import sqlite3

import backend.agent.outer_loop as _ol_module
from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder
from backend.agent.outer_loop import OuterTuner


def _seeded_tuner() -> OuterTuner:
    rec = CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))
    for i in range(4):
        rec.record_session_exit(
            f"s{i}", "general", natural_exit=True, verified_count=8,
            tokens_total=5000.0, executed_steps=10,
        )
    return OuterTuner(recorder=rec, held_out_count=3)


class TestCTD6GuardCount:
    def test_all_three_inputs_computable_yields_three_live_guards(self, monkeypatch):
        from backend.api import caducean_debug

        monkeypatch.setattr(_ol_module, "OuterTuner", _seeded_tuner)
        result = caducean_debug._outer_loop()
        assert result["live_guards"] == 3, result
        assert result["dead_guards"] == [], result

    def test_missing_tokens_total_input_reduces_live_count_and_names_it(self, monkeypatch):
        """Contrast case: with executed_steps populated but NO tokens spent
        anywhere (every session had 0 verified steps so tokens_per_verified
        has no denominator), live_guards must drop below 3 and name the
        dead guard — proving the endpoint reports REAL liveness, not a
        hardcoded 3."""
        from backend.api import caducean_debug

        def _degenerate_tuner():
            rec = CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))
            for i in range(4):
                rec.record_session_exit(
                    f"s{i}", "general", natural_exit=True, verified_count=0,
                    tokens_total=5000.0, executed_steps=10,
                )
            return OuterTuner(recorder=rec, held_out_count=3)

        monkeypatch.setattr(_ol_module, "OuterTuner", _degenerate_tuner)
        result = caducean_debug._outer_loop()
        assert result["live_guards"] < 3, result
        assert "tokens_per_verified" in result["dead_guards"], result

    def test_no_session_exit_rows_reports_zero_live_not_a_fake_three(self, monkeypatch):
        def _empty_tuner():
            rec = CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))
            return OuterTuner(recorder=rec, held_out_count=3)

        from backend.api import caducean_debug

        monkeypatch.setattr(_ol_module, "OuterTuner", _empty_tuner)
        result = caducean_debug._outer_loop()
        assert result["live_guards"] == 0
        assert set(result["dead_guards"]) == {
            "natural_exit_rate", "verified_fraction", "tokens_per_verified",
        }
