"""The bar's out-of-fold split is GROUPED, and the model must beat a trivial rule.

Found 2026-11-09 (docs/architecture/oracle.md 12.8), replaying tool_approval/v6
(6482 rows) on d1-2B:
  * every row came from 92 eval tasks run again and again, and the folds were
    split by row, so near-identical runs of one task were fitted on and scored
    in the same fit: the OOF numbers were optimistic;
  * a rule that knew only the tool's failure rate - no model - passed the bar
    by itself and beat d1 on every number. It measured which tools were broken
    on this machine, not decision quality.
Pinned here: no group straddles a fold (the ungrouped split is unchanged row
for row), runs of one eval task are one group, the fit measures the model
against a rule that decides WITHOUT it (the proposed tool alone, or the most
common answer), and the bar demotes a model that does not beat that rule.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.agent.consumer_bar import derive_status  # noqa: E402
from scripts import fit_oracle_calibration as fit  # noqa: E402
from scripts.consumer_enforcement_report import fold_group  # noqa: E402


def _old_stratified(correct, folds=fit.FOLDS, seed=0):
    """The split as it was before 2026-11-09, for the no-group parity check."""
    rng = random.Random(seed)
    fold_of = [0] * len(correct)
    for label in (True, False):
        idx = [i for i in range(len(correct)) if bool(correct[i]) is label]
        rng.shuffle(idx)
        for pos, i in enumerate(idx):
            fold_of[i] = pos % folds
    return fold_of


def test_runs_of_one_eval_task_are_one_group():
    assert fold_group("eval-c10_create_module-924185") == "eval-c10_create_module"
    assert fold_group("eval-c10_create_module-1a2b3c") == "eval-c10_create_module"
    assert fold_group("eval-m01_recall_taught_name-seed-4889a0") == "eval-m01_recall_taught_name-seed"
    assert fold_group("de-shadow-battery") == "de-shadow-battery"
    assert fold_group("") is None and fold_group(None) is None


def test_no_group_straddles_a_fold():
    rng = random.Random(7)
    groups, correct = [], []
    for g in range(60):
        for _ in range(rng.randint(3, 25)):
            groups.append(f"task{g}")
            correct.append(rng.random() < 0.8)
    fold_of, info = fit.assign_folds(correct, groups)
    assert info["grouped"] is True and info["groups"] == 60
    seen = {}
    for g, f in zip(groups, fold_of):
        assert seen.setdefault(g, f) == f, f"group {g} is on both sides of a fold"
    sizes = [fold_of.count(f) for f in range(fit.FOLDS)]
    assert max(sizes) - min(sizes) <= 25, f"folds are uneven: {sizes}"
    rare = [sum(1 for i, v in enumerate(correct) if fold_of[i] == f and not v)
            for f in range(fit.FOLDS)]
    assert min(rare) > 0, f"a fold holds none of the rarer label: {rare}"


def test_a_group_larger_than_a_fold_is_split_not_held_out_whole():
    groups = ["battery"] * 400 + [f"t{i}" for i in range(100)]
    correct = [i % 5 != 0 for i in range(500)]
    fold_of, info = fit.assign_folds(correct, groups)
    assert info["split_rows"] == 400
    assert len({fold_of[i] for i in range(400)}) == fit.FOLDS


def test_without_groups_the_split_is_unchanged_row_for_row():
    correct = [i % 7 != 0 for i in range(333)]
    assert fit.assign_folds(correct, None)[0] == _old_stratified(correct)
    assert fit.assign_folds(correct, [None] * 333)[0] == _old_stratified(correct)


def _yes_no_rows(n=600, seed=3):
    """The 12.8 case: P(yes) is noise, the proposed tool alone predicts success."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        tool = ("search", "read_file", "list_directory", "edit_file")[i % 4]
        succeeds = rng.random() < (0.05 if tool == "search" else 0.95)
        p_yes = rng.uniform(0.0, 1.0)
        said_yes = p_yes >= 0.5
        out.append({"confidence": max(p_yes, 1 - p_yes), "probability": p_yes,
                    "chosen": said_yes, "correct": said_yes == succeeds,
                    "group": f"task{i % 40}", "rule_key": tool})
    return out


def test_a_yes_no_model_is_measured_against_a_rule_from_the_input_alone():
    e = fit.fit_consumer(_yes_no_rows())
    assert e["folds"]["grouped"] is True and e["folds"]["groups"] == 40
    bl = e["baseline"]
    assert bl["metric"] == "truth_auroc" and bl["keys"] == 4
    assert bl["rule"] > 0.85 and bl["model"] < 0.6, bl


def test_a_choice_model_is_measured_against_the_most_common_answer():
    rows = [{"confidence": 0.9, "chosen": "silent", "reference": "silent", "correct": True,
             "probability": None, "group": f"t{i % 30}"} for i in range(80)]
    rows += [{"confidence": 0.9, "chosen": "silent", "reference": "speak", "correct": False,
              "probability": None, "group": f"t{i % 30}"} for i in range(20)]
    bl = fit.fit_consumer(rows)["baseline"]
    # the model always says "silent", exactly what "the most common answer" says
    assert bl == {"metric": "accuracy", "model": 0.8, "rule": 0.8, "keys": 1}


def _honest(model, rule):
    return {"rows_distinct": 600, "classes": {"correct": 500, "wrong": 100},
            "threshold": 0.9, "rows_above": 300,
            "baseline": {"metric": "accuracy", "model": model, "rule": rule},
            "oof": {"auroc": 0.75, "precision_at_t": 0.95, "wilson_lb": 0.92, "ece": 0.02}}


def test_the_bar_demotes_a_model_a_trivial_rule_matches():
    status, gap = derive_status(0, 0.0, None, honest=_honest(0.80, 0.85))
    assert status == "shadow" and "trivial rule" in gap
    assert derive_status(0, 0.0, None, honest=_honest(0.80, 0.80))[0] == "shadow"
    assert derive_status(0, 0.0, None, honest=_honest(0.90, 0.80)) == ("enforced", "")
    # not measurable (one truth class): nothing to beat
    assert derive_status(0, 0.0, None, honest=_honest(None, None)) == ("enforced", "")
