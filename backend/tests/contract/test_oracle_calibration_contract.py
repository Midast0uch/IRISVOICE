"""Contract: Oracle Stage A - honest measurement and calibration (2026-10-05).

Each test pins one seam that let a wrong VALUE through while the code ran green:

  * a yes/no row wrote P(true) as its confidence, so a sure "no" read as 0.1 and
    the error-detection AUROC came out inverted (web_intent 0.218,
    escalate_incomplete 0.003);
  * the same input rescored many times counted as many rows (web_intent 654
    distinct of 2690; presentation 2 of 918);
  * the bar passed on in-sample numbers, one-class references and rank-less
    confidence;
  * a calibration map that nothing could read.

Nothing here touches a model or the live ledger: rows are synthetic, the ledger a
tmp sqlite file.
"""

from __future__ import annotations

import json
import random
import sqlite3

import pytest

from backend.agent.consumer_bar import derive_status
from backend.agent.explorer import (
    WEB_INTENT_CONSUMER,
    _engine_web_intent,
    set_row_sink,
)
from backend.agent.monitor_shadow import shadow_row as monitor_row
from backend.agent.oracle_calibration import (
    apply_knots,
    binary_consumers,
    calibrated,
    threshold,
)
from backend.agent.surface_shadow import shadow_row as surface_row
from backend.agent.tool_bridge import _DECISION_META_KEYS
from scripts.calibrate_decision_threshold import _ece_brier
from scripts.consumer_enforcement_report import (
    build_report,
    load_rows,
    measure,
    thresholds_by_consumer,
)
from scripts.fit_oracle_calibration import (
    fit_consumer,
    fit_isotonic,
    oof_calibrated,
    pick_threshold,
    wilson_lb,
)


# -- 1. The emit paths: confidence in the CHOSEN answer, P(true) beside it ----

class _Noul:
    def __init__(self, p):
        self.probability = p
        self.engine_latency_ms = 3

    def true(self, threshold=0.5):
        return self.probability >= threshold

    def confident(self, threshold):
        return self.probability >= threshold or self.probability <= 1.0 - threshold


class _Engine:
    model_id = "fake-engine"

    def __init__(self, p):
        self._p = p

    def noul(self, consumer_id, statement, frame, true_label, false_label):
        return _Noul(self._p)


def _web_intent_row(p, keyword):
    from backend.utils.durability_queue import lane

    seen = []
    set_row_sink(seen.append)
    try:
        _engine_web_intent("find the price online", _Engine(p), keyword=keyword)
        # Stage B (2026-10-05): a web_intent that does not decide (the default)
        # writes its calibration row from the oracle_shadow lane, so the row is
        # observable after the lane drains. The row's shape is unchanged.
        assert lane("oracle_shadow").flush(10.0)
    finally:
        set_row_sink(None)
    assert len(seen) == 1
    return seen[0]


@pytest.mark.parametrize("make_row", [
    pytest.param(lambda p: monitor_row("sufficient", _Noul(p), brain_bool=False),
                 id="monitor_shadow"),
    pytest.param(lambda p: surface_row("use_thinking", _Noul(p), brain_bool=False),
                 id="surface_shadow"),
    pytest.param(lambda p: _web_intent_row(p, keyword=False), id="explorer_web_intent"),
])
class TestBinaryRowEmit:
    def test_a_no_carries_its_confidence_in_no_not_p_true(self, make_row):
        """p(true)=0.1 is a 0.9-sure NO. Old code wrote 0.1 - the inverted value
        that turned every rank metric over."""
        row = make_row(0.1)
        assert row["confidence"] == 0.9
        assert row["probability"] == 0.1

    def test_a_yes_keeps_p_true_as_its_confidence(self, make_row):
        row = make_row(0.8)
        assert row["confidence"] == 0.8
        assert row["probability"] == 0.8

    def test_confidence_is_never_below_a_coin_flip(self, make_row):
        for p in (0.0, 0.2, 0.4999, 0.5, 0.7, 1.0):
            assert make_row(p)["confidence"] >= 0.5


def test_the_ledger_whitelist_keeps_the_raw_probability():
    """shadow_row already emitted `probability`; the whitelist dropped it, so no
    ledger row ever carried it (checked on the live ledger 2026-10-05)."""
    assert "probability" in _DECISION_META_KEYS


# -- 2. The loader: normalise old rows, count each input once -----------------

def _db(tmp_path, decisions):
    p = tmp_path / "memory.db"
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE system_events (outcome TEXT, event_type TEXT, "
              "interaction_payload TEXT)")
    for d in decisions:
        c.execute("INSERT INTO system_events VALUES (NULL, 'tool_execution', ?)",
                  (json.dumps({"tool": "no_tool", "decision": d}),))
    c.commit()
    c.close()
    return str(p)


def _row(cid, chosen, conf, **ref):
    return {"consumer_id": cid, "chosen": chosen, "confidence": conf,
            "route": "shadow", "shadow": True, "engine": "e", **ref}


class TestLoadRows:
    def test_an_old_binary_row_is_normalised_to_confidence_in_the_chosen_answer(
        self, tmp_path,
    ):
        """Old rows hold P(true) in `confidence` whatever they chose, so a "no"
        stored as 0.1 is a 0.9-confident no. The binary set comes from the
        engine's own specs (no `binary=` passed)."""
        db = _db(tmp_path, [
            _row("sufficient", False, 0.1, brain_bool=False),
            _row("sufficient", True, 0.7, brain_bool=True),
        ])
        rows, _ = load_rows(db)
        by_chosen = {r["chosen"]: r for r in rows}
        assert by_chosen[False]["confidence"] == 0.9
        assert by_chosen[False]["probability"] == 0.1
        assert by_chosen[True]["confidence"] == 0.7
        assert by_chosen[True]["probability"] == 0.7

    def test_a_choice_consumer_confidence_is_left_alone(self, tmp_path):
        db = _db(tmp_path, [_row("mode", "coding", 0.3, brain_choice="coding")])
        rows, _ = load_rows(db)
        assert rows[0]["confidence"] == 0.3 and rows[0]["probability"] is None

    def test_the_binary_set_is_read_from_the_engine_specs(self):
        b = binary_consumers()
        # `on_track` and `has_gaps` were removed 2026-10-05 (Stage B, owner-approved).
        assert {"sufficient", "done", "use_thinking",
                "escalate_incomplete", "needs_action", "depth_met",
                WEB_INTENT_CONSUMER} <= b
        assert not ({"on_track", "has_gaps"} & b)
        assert not ({"mode", "tool_choice", "presentation", "narration",
                     "review_verdict", "recovery_strategy"} & b)

    def test_repeats_of_one_input_count_once(self, tmp_path):
        """The same input rescored 5 times is ONE row carrying repeats=5."""
        same = _row("web_intent", "yes", 0.6, brain_choice="no")
        db = _db(tmp_path, [same] * 5 + [_row("web_intent", "yes", 0.7,
                                              brain_choice="yes")])
        rows, skipped = load_rows(db)
        assert len(rows) == 2
        assert sorted(r["repeats"] for r in rows) == [1, 5]
        assert skipped["duplicates"] == 4

    def test_same_score_different_label_stays_two_rows(self, tmp_path):
        """Same confidence and chosen, but one agrees with the incumbent and one
        does not: two different outcomes are two pieces of evidence."""
        db = _db(tmp_path, [
            _row("web_intent", "yes", 0.6, brain_choice="yes"),
            _row("web_intent", "yes", 0.6, brain_choice="no"),
        ])
        rows, _ = load_rows(db)
        assert sorted(r["correct"] for r in rows) == [False, True]


# -- 3. The fit ---------------------------------------------------------------

def _mis_scaled(n=600, seed=1):
    """Raw confidence x in [0.5, 1) ranks outcomes well, but P(correct) = x**4,
    so a raw 0.8 is right 41% of the time: well ranked, badly scaled."""
    rng = random.Random(seed)
    xs = [0.5 + 0.5 * rng.random() for _ in range(n)]
    return xs, [rng.random() < x ** 4 for x in xs]


class TestIsotonic:
    def test_the_map_is_monotone(self):
        xs, ok = _mis_scaled()
        knots = fit_isotonic(xs, [1.0 if v else 0.0 for v in ok])
        assert len(knots) >= 2
        assert all(a[0] < b[0] for a, b in zip(knots, knots[1:]))
        assert all(a[1] <= b[1] for a, b in zip(knots, knots[1:]))

    def test_a_block_under_the_minimum_is_pooled(self):
        """30 points alternating right/wrong cannot support a step: with
        min_block=20 the map is one constant (the base rate)."""
        xs = [0.5 + i / 100 for i in range(30)]
        ys = [float(i % 2) for i in range(30)]
        knots = fit_isotonic(xs, ys, min_block=20)
        assert len(knots) == 1 and knots[0][1] == pytest.approx(0.5)

    def test_out_of_fold_calibration_cuts_the_ece_of_a_mis_scaled_set(self):
        xs, ok = _mis_scaled()
        raw_ece, _ = _ece_brier([{"confidence": x, "correct": c}
                                 for x, c in zip(xs, ok)])
        cal = oof_calibrated(xs, ok)
        cal_ece, _ = _ece_brier([{"confidence": x, "correct": c}
                                 for x, c in zip(cal, ok)])
        assert raw_ece > 0.2, "the synthetic set must start mis-scaled"
        assert cal_ece < 0.05, f"out-of-fold ECE {cal_ece} (raw {raw_ece})"

    def test_apply_knots_interpolates_and_clips(self):
        knots = [[0.5, 0.2], [1.0, 1.0]]
        assert apply_knots(knots, 0.75) == pytest.approx(0.6)
        assert apply_knots(knots, 0.1) == 0.2
        assert apply_knots(knots, 2.0) == 1.0


class TestThresholdRule:
    def test_a_qualifying_point_returns_the_smallest_t(self):
        # 100 rows at 0.9 (97 right) and 100 at 0.5 (50 right).
        cal = [0.9] * 100 + [0.5] * 100
        ok = [True] * 97 + [False] * 3 + [True] * 50 + [False] * 50
        t, n_above, k = pick_threshold(cal, ok)
        assert (t, n_above, k) == (0.9, 100, 97)

    def test_none_when_precision_is_short_everywhere(self):
        cal = [0.8] * 200
        ok = [True] * 160 + [False] * 40  # 0.80
        assert pick_threshold(cal, ok) is None

    def test_none_when_too_few_rows_reach_the_precision(self):
        cal = [0.95] * 49 + [0.4] * 151
        ok = [True] * 49 + [True] * 75 + [False] * 76
        assert pick_threshold(cal, ok) is None

    def test_none_when_the_wilson_bound_is_short_though_the_point_estimate_passes(self):
        """50 rows, 46 right: precision 0.92 passes, its 95% lower bound (about
        0.81) does not - 50 rows cannot show 0.90."""
        cal = [0.9] * 50
        ok = [True] * 46 + [False] * 4
        assert 46 / 50 >= 0.90 and wilson_lb(46, 50) < 0.85
        assert pick_threshold(cal, ok) is None


# -- 4. The hardened bar ------------------------------------------------------

def _honest(**over):
    h = {"rows_distinct": 150, "classes": {"correct": 110, "wrong": 40},
         "threshold": 0.8, "rows_above": 80,
         "oof": {"ece": 0.03, "brier": 0.1, "auroc": 0.80,
                 "precision_at_t": 0.95, "wilson_lb": 0.88}}
    oof = over.pop("oof", {})
    h.update(over)
    h["oof"] = {**h["oof"], **oof}
    return h


class TestHardenedBar:
    def test_all_clauses_met_enforces(self):
        assert derive_status(0, 0.0, None, honest=_honest()) == ("enforced", "")

    @pytest.mark.parametrize("over,needle", [
        (dict(rows_distinct=99), "distinct rows 99"),
        (dict(classes={"correct": 150, "wrong": 0}), "one class"),
        (dict(classes={"correct": 150, "wrong": 0}, oof={"auroc": None}), "one class"),
        (dict(classes={"correct": 144, "wrong": 6}), "minority"),
        (dict(oof={"auroc": 0.60}), "AUROC"),
        (dict(oof={"auroc": None}), "AUROC"),
        (dict(threshold=None), "no calibrated threshold"),
        (dict(rows_above=30), "rows above threshold 30"),
        (dict(oof={"precision_at_t": 0.85}), "precision"),
        (dict(oof={"wilson_lb": 0.80}), "Wilson"),
        (dict(oof={"ece": 0.06}), "ECE"),
    ])
    def test_each_failing_clause_keeps_it_in_shadow_and_is_named(self, over, needle):
        status, gap = derive_status(0, 0.0, None, honest=_honest(**over))
        assert status == "shadow"
        assert needle in gap, gap

    def test_the_legacy_numbers_cannot_override_the_honest_ones(self):
        """200 rows, precision 0.99, ECE 0.01 flip the legacy bar; with a one-
        class reference the hardened bar refuses them."""
        assert derive_status(200, 0.99, 0.01)[0] == "enforced"
        h = _honest(classes={"correct": 200, "wrong": 0})
        assert derive_status(200, 0.99, 0.01, honest=h)[0] == "shadow"


class TestReport:
    def test_a_one_class_consumer_with_perfect_raw_numbers_is_not_flipped(self):
        """200 rows, every one right at confidence 1.0: raw precision 1.0, raw ECE
        0.0, and nothing to learn from (no wrong row). The old report flipped it."""
        rows = [{"consumer_id": "c", "confidence": 1.0, "correct": True,
                 "shadow": True, "engine": "e"} for _ in range(200)]
        thresholds = {"c": 0.4}
        rep = build_report(measure(rows, thresholds), {},
                           {"backend_id": "b", "candidate_cap": 6})
        assert rep["flipped"] == []
        assert "one class" in rep["consumers"]["c"]["gap"]

    def test_a_threshold_lookup_exists_for_every_declared_consumer(self):
        from backend.agent.decision_engine import CONSUMERS

        thresholds, _config = thresholds_by_consumer()
        assert set(CONSUMERS) <= set(thresholds), (
            "a hard-coded list omitted depth_met, which then read as 'no threshold'"
        )

    def test_a_declared_consumer_with_no_rows_still_gets_a_line(self):
        measured = measure([], {"depth_met": 0.4})
        assert measured["depth_met"]["rows"] == 0


def test_fit_consumer_refuses_to_fit_what_it_cannot_score():
    """Under two blocks of evidence the entry carries no knots and no oof numbers."""
    rows = [{"confidence": 0.5 + i / 100, "correct": i % 2 == 0} for i in range(30)]
    e = fit_consumer(rows)
    assert e["knots"] == [] and e["threshold"] is None and e["oof"]["auroc"] is None


# -- 5. The runtime loader ----------------------------------------------------

class TestRuntimeLoader:
    def test_a_missing_file_is_none_never_an_error(self, tmp_path):
        missing = tmp_path / "nope.json"
        assert calibrated("b", "mode", 0.7, path=missing) is None
        assert threshold("b", "mode", path=missing) is None

    def test_a_malformed_file_is_none(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        assert calibrated("b", "mode", 0.7, path=bad) is None
        assert threshold("b", "mode", path=bad) is None

    def test_a_fixture_file_returns_the_calibrated_value_and_threshold(self, tmp_path):
        f = tmp_path / "cal.json"
        f.write_text(json.dumps({"backend-x": {
            "mode": {"method": "isotonic", "knots": [[0.5, 0.2], [1.0, 1.0]],
                     "threshold": 0.8},
            "no_fit": {"method": "isotonic", "knots": [], "threshold": None},
        }}), encoding="utf-8")
        assert calibrated("backend-x", "mode", 0.75, path=f) == pytest.approx(0.6)
        assert threshold("backend-x", "mode", path=f) == 0.8
        # unknown backend / consumer / empty fit: None, not a guess
        assert calibrated("other", "mode", 0.75, path=f) is None
        assert calibrated("backend-x", "missing", 0.75, path=f) is None
        assert calibrated("backend-x", "no_fit", 0.75, path=f) is None
        assert threshold("backend-x", "no_fit", path=f) is None
