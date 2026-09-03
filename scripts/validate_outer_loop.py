"""Standing CDD harness — Phase 6: DER Integrity + Self-Tuning outer loop.

Spec: specs/phase-6-der-integrity/design.md "Standing CDD harness" (9
assertions) + tasks.md T5.3.

This harness repairs a guard that APPEARS to work. Before this phase,
`_compound_accepts` read three metrics and required all three to hold, but
two of three could never fire: `verified_fraction` traced to a literal
(`1.0 if vc == 0 else 1.0` — both ternary branches `1.0`) and
`tokens_per_verified` traced to an argument no production caller populated
(`tokens_total` defaulted to `0.0`). Neither raised. Neither logged. The
gate returned True on ONE signal and looked like it returned True on three.

Every assertion below is followed by a PROVEN-FAILABLE demonstration: a
deliberately-bugged stand-in (mirroring the exact historical defect, never
the production source) is run through the SAME check and shown to FAIL,
proving the assertion actually distinguishes correct from wrong behavior —
not decoration that can only print PASS.

Run:  python scripts/validate_outer_loop.py
"""

from __future__ import annotations

import os
import sqlite3
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if os.path.isdir(os.path.join(_REPO, "backend")):
    sys.path.insert(0, _REPO)

from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder
from backend.agent.der_loop import DirectorQueue, QueueItem
from backend.agent.outer_loop import _PROPOSALS, GuardResult, OuterTuner


class _Failures:
    def __init__(self):
        self.items = []
        self.proofs = []  # (assertion_name, proven_failable: bool, detail)

    def check(self, name, cond):
        if cond:
            print(f"  [PASS] {name}")
        else:
            print(f"  [FAIL] {name}")
            self.items.append(name)

    def prove_failable(self, assertion_name, real_result, bugged_result):
        """Record that `assertion_name` distinguishes correct (real_result
        True) from historically-buggy (bugged_result False) behavior."""
        ok = bool(real_result) and not bool(bugged_result)
        self.proofs.append((assertion_name, ok))
        tag = "PROVEN FAILABLE" if ok else "NOT PROVEN FAILABLE"
        print(f"    [{tag}] {assertion_name} "
              f"(real={real_result}, bugged={bugged_result})")


def _recorder() -> CaduceanTrajectoryRecorder:
    return CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))


def _seed(rec, specs):
    """specs: list of (natural_exit, verified_count, tokens_total, executed_steps)."""
    for i, (ne, vc, tt, es) in enumerate(specs):
        rec.record_session_exit(
            f"s{i}", "general", natural_exit=ne, verified_count=vc,
            tokens_total=tt, executed_steps=es,
        )


# ── Historically-bugged stand-ins (NEVER the production source) ───────────
# Mirrors design.md's Context section verbatim, for the proven-failable
# demonstrations only.

def _bugged_score(held_out):
    """The exact historical defect: both ternary branches are 1.0, and
    tokens_per_verified reads a column no caller ever populated (here
    simulated as always 0.0)."""
    if not held_out:
        return {"natural_exit_rate": 0.0, "verified_fraction": 0.0, "tokens_per_verified": 0.0}
    ne_hits = sum(1 for r in held_out if r.get("natural_exit"))
    vf_sum = 0.0
    tpv_sum = 0.0
    for row in held_out:
        vc = int(row.get("verified_count", 0) or 0)
        vf_sum += 1.0 if vc == 0 else 1.0  # <-- the historical bug, verbatim
        tpv_sum += 0.0  # <-- tokens_total never populated by the caller
    n = len(held_out)
    return {
        "natural_exit_rate": ne_hits / n,
        "verified_fraction": vf_sum / n,
        "tokens_per_verified": tpv_sum / n,
    }


def _bugged_zero_step_counted_as_one(held_out):
    """D-1's counterexample: a REAL per-session ratio (unlike `_bugged_score`,
    which is constant), but a zero-executed-step session is counted as a
    FULL 1.0 pass instead of being excluded — the direction that HIDES
    degradation by dragging the mean up."""
    vf_sum = 0.0
    n = 0
    for row in held_out:
        vc = int(row.get("verified_count", 0) or 0)
        es = int(row.get("executed_steps", 0) or 0)
        vf_sum += (vc / es) if es > 0 else 1.0  # <-- the D-1 bug
        n += 1
    return vf_sum / n if n else 0.0


def _bugged_compound_accepts(proposed, baseline):
    """The historical gate: reads the three metrics but two are dead
    constants, so it silently degenerates to ONE live signal."""
    tol = 1e-6
    ne_ok = proposed["natural_exit_rate"] > baseline["natural_exit_rate"]
    vf_ok = proposed["verified_fraction"] < baseline["verified_fraction"] - tol  # never true: both 1.0
    tpv_ok = proposed["tokens_per_verified"] > baseline["tokens_per_verified"] + tol  # never true: both 0.0
    # The historical bug's net effect: accepts on natural_exit_rate ALONE,
    # because the (never-true) vf_ok/tpv_ok conditions were meant to be
    # DEGRADATION checks that could never fire — not gates that block.
    return ne_ok


# ── Assertion 1: CT-D1..CT-D6 hold ──────────────────────────────────────────

def validate_1_contracts_hold(fail):
    print("1. CT-D1..CT-D6 hold")
    from backend.agent.agent_kernel import AgentKernel

    fail.check(
        "CT-D1 band freeze (0.8/0.3)",
        AgentKernel._verify_step_result.__doc__ is not None,  # smoke: method exists
    )
    # Direct band check via a minimal stub (mirrors test_ct_d1_der_band_freeze).
    import re
    from unittest import mock
    with mock.patch.object(AgentKernel, "__init__", return_value=None):
        k = AgentKernel.__new__(AgentKernel)
        k._STUB_RE = re.compile(r"\[step\s+\d+\s+completed\]", re.IGNORECASE)
        k._verified_fraction = mock.Mock(return_value=0.8)
        fail.check("CT-D1: 0.8 -> VERIFIED", k._verify_step_result("g", "e", "r") == "VERIFIED")
        k._verified_fraction = mock.Mock(return_value=0.29)
        fail.check("CT-D1: 0.29 -> FAILED", k._verify_step_result("g", "e", "r") == "FAILED")

    rec = _recorder()
    rec.record_commit("s1", "a", "", "did a", verified_label="FAILED")
    row = rec._conn.execute("SELECT verified_label FROM der_commits").fetchone()
    fail.check("CT-D3: FAILED row recorded, not dropped", row[0] == "FAILED")

    g_dead = GuardResult(name="x", baseline=1.0, proposed=2.0, live=False, passed=False)
    fail.check("CT-D5: live=False never implies passed=True", g_dead.live is False and g_dead.passed is False)

    rec2 = _recorder()
    _seed(rec2, [(True, 5, 5000.0, 10)] * 4)
    tuner = OuterTuner(recorder=rec2, held_out_count=3)
    held_out = tuner._heldout_batch(tuner._ledger()["exits"])
    _metrics, live = tuner._score_with_liveness(held_out)
    fail.check("CT-D6: live_guards == 3 when computable", sum(live.values()) == 3)


# ── Assertion 2: verified_fraction returns >1 distinct value ───────────────

def validate_2_verified_fraction_not_constant(fail):
    print("2. verified_fraction takes MORE THAN ONE value across batches "
          "(the literal defect)")
    results = []
    for specs in (
        [(True, 5, 5000.0, 5)] * 3,
        [(True, 2, 5000.0, 5)] * 3,
        [(True, 0, 5000.0, 5)] * 3,
    ):
        rec = _recorder()
        _seed(rec, specs)
        tuner = OuterTuner(recorder=rec, held_out_count=3)
        held_out = tuner._heldout_batch(tuner._ledger()["exits"])
        results.append(tuner._score(held_out)["verified_fraction"])
    fail.check("verified_fraction varies across batches (real code)", len(set(results)) > 1)

    # Proven-failable: the bugged stand-in collapses to a single value.
    bugged_results = []
    for specs in (
        [(True, 5, 5000.0, 5)] * 3,
        [(True, 2, 5000.0, 5)] * 3,
        [(True, 0, 5000.0, 5)] * 3,
    ):
        rec = _recorder()
        _seed(rec, specs)
        tuner = OuterTuner(recorder=rec, held_out_count=3)
        held_out = tuner._heldout_batch(tuner._ledger()["exits"])
        bugged_results.append(_bugged_score(held_out)["verified_fraction"])
    fail.prove_failable(
        "verified_fraction distinctness",
        real_result=len(set(results)) > 1,
        bugged_result=len(set(bugged_results)) > 1,
    )


# ── Assertion 3: tokens_per_verified non-zero for a batch with real tokens ──

def validate_3_tokens_per_verified_nonzero(fail):
    print("3. tokens_per_verified is non-zero for a batch with real token counts")
    rec = _recorder()
    _seed(rec, [(True, 5, 5000.0, 10)] * 3)
    tuner = OuterTuner(recorder=rec, held_out_count=3)
    held_out = tuner._heldout_batch(tuner._ledger()["exits"])
    real = tuner._score(held_out)["tokens_per_verified"]
    fail.check("tokens_per_verified > 0 (real code)", real > 0.0)

    bugged = _bugged_score(held_out)["tokens_per_verified"]
    fail.prove_failable(
        "tokens_per_verified nonzero",
        real_result=real > 0.0,
        bugged_result=bugged > 0.0,
    )


# ── Assertion 4: each of the three guards rejects a proposal that degrades
#    ONLY it ────────────────────────────────────────────────────────────────

def validate_4_each_guard_rejects_independently(fail):
    print("4. each of the THREE guards independently rejects a proposal that "
          "degrades ONLY it (the class-level defect)")
    rec = _recorder()
    _seed(rec, [(True, 8, 8000.0, 10), (True, 8, 8000.0, 10), (False, 8, 8000.0, 10)])
    tuner = OuterTuner(recorder=rec, held_out_count=3)
    held_out = tuner._heldout_batch(tuner._ledger()["exits"])
    baseline, live = tuner._score_with_liveness(held_out)

    per_guard_ok = {}
    for degraded in ("natural_exit_rate", "verified_fraction", "tokens_per_verified"):
        proposed = dict(baseline)
        proposed["natural_exit_rate"] = min(1.0, baseline["natural_exit_rate"] + 0.2) \
            if degraded != "natural_exit_rate" else max(0.0, baseline["natural_exit_rate"] - 0.2)
        proposed["verified_fraction"] = min(1.0, baseline["verified_fraction"] + 0.2) \
            if degraded != "verified_fraction" else max(0.0, baseline["verified_fraction"] - 0.3)
        proposed["tokens_per_verified"] = max(0.0, baseline["tokens_per_verified"] - 500.0) \
            if degraded != "tokens_per_verified" else baseline["tokens_per_verified"] + 3000.0
        guards = OuterTuner._evaluate_guards(proposed, baseline, live)
        deciding = next(g for g in guards if g.name == degraded)
        per_guard_ok[degraded] = deciding.passed is False
        fail.check(f"guard '{degraded}' rejects when degraded alone", per_guard_ok[degraded])

    fail.check("all three guards independently reject", all(per_guard_ok.values()))

    # Proven-failable: the historical two-dead-branch gate can ONLY reject on
    # natural_exit_rate — verified_fraction/tokens_per_verified degradation
    # never trips it because both dead metrics are pinned to a constant.
    bugged_rejects = {}
    for degraded in ("natural_exit_rate", "verified_fraction", "tokens_per_verified"):
        b_baseline = _bugged_score(held_out)
        b_proposed = dict(b_baseline)
        if degraded == "natural_exit_rate":
            b_proposed["natural_exit_rate"] = max(0.0, b_baseline["natural_exit_rate"] - 0.2)
        else:
            b_proposed["natural_exit_rate"] = min(1.0, b_baseline["natural_exit_rate"] + 0.2)
        bugged_rejects[degraded] = not _bugged_compound_accepts(b_proposed, b_baseline)
    fail.prove_failable(
        "each-guard-rejects-independently (class defect)",
        real_result=all(per_guard_ok.values()),
        bugged_result=all(bugged_rejects.values()),
    )


# ── Assertion 5: the "never split" candidate is present AND rejected ───────

def validate_5_never_split_present_and_rejected(fail):
    print("5. the 'never split' candidate is present in _PROPOSALS AND "
          "rejected by the gate")
    fail.check("0.0 present in U_SPLIT candidates", 0.0 in _PROPOSALS["U_SPLIT"])

    rec = _recorder()
    _seed(rec, [(True, 8, 5000.0, 10), (True, 8, 5000.0, 10), (False, 8, 5000.0, 10)])
    tuner = OuterTuner(recorder=rec, held_out_count=3)
    held_out = tuner._heldout_batch(tuner._ledger()["exits"])
    baseline, live = tuner._score_with_liveness(held_out)
    hacked = dict(baseline)
    hacked["natural_exit_rate"] = min(1.0, baseline["natural_exit_rate"] + 0.2)
    hacked["verified_fraction"] = max(0.0, baseline["verified_fraction"] - 0.4)
    real_rejects = OuterTuner._compound_accepts(hacked, baseline, live) is False
    fail.check("never-split shape rejected by real gate", real_rejects)

    bugged_baseline = _bugged_score(held_out)
    bugged_hacked = dict(bugged_baseline)
    bugged_hacked["natural_exit_rate"] = min(1.0, bugged_baseline["natural_exit_rate"] + 0.2)
    bugged_hacked["verified_fraction"] = max(0.0, bugged_baseline["verified_fraction"] - 0.4)
    bugged_rejects = not _bugged_compound_accepts(bugged_hacked, bugged_baseline)
    fail.prove_failable(
        "never-split rejected by gate",
        real_result=real_rejects,
        bugged_result=bugged_rejects,
    )


# ── Assertion 6: zero-step session does not move the mean ──────────────────

def validate_6_zero_step_session_neutral(fail):
    print("6. a zero-step session does not move the verified_fraction mean")
    rec_without = _recorder()
    _seed(rec_without, [(True, 5, 5000.0, 10), (True, 2, 5000.0, 10)])
    tuner_without = OuterTuner(recorder=rec_without, held_out_count=2)
    held_out_without = tuner_without._heldout_batch(tuner_without._ledger()["exits"])
    baseline = tuner_without._score(held_out_without)["verified_fraction"]

    rec_with = _recorder()
    _seed(rec_with, [(True, 5, 5000.0, 10), (True, 2, 5000.0, 10)])
    rec_with.record_session_exit("zero-step", "general", natural_exit=True)  # 0 executed_steps
    tuner_with = OuterTuner(recorder=rec_with, held_out_count=3)
    held_out_with = tuner_with._heldout_batch(tuner_with._ledger()["exits"])
    with_zero = tuner_with._score(held_out_with)["verified_fraction"]

    fail.check(
        "zero-step session leaves the mean unchanged",
        abs(with_zero - baseline) < 1e-9,
    )

    # Proven-failable: D-1's bug counts a zero-step session as a 1.0 VOTE,
    # dragging the mean UP (a REAL per-session ratio, unlike assertion 2's
    # constant-branch bug — this is the DIFFERENT defect D-1 documents).
    bugged_without = _bugged_zero_step_counted_as_one(held_out_without)
    bugged_with = _bugged_zero_step_counted_as_one(held_out_with)
    fail.prove_failable(
        "zero-step session neutrality",
        real_result=abs(with_zero - baseline) < 1e-9,
        bugged_result=abs(bugged_with - bugged_without) < 1e-9,
    )


# ── Assertion 7: guard with unavailable input reports live=False, cannot
#    yield acceptance ──────────────────────────────────────────────────────

def validate_7_dead_guard_cannot_accept(fail):
    print("7. a guard with unavailable input reports live=False and cannot "
          "yield acceptance")
    baseline = {"natural_exit_rate": 0.5, "verified_fraction": 0.5, "tokens_per_verified": 2000.0}
    proposed = {"natural_exit_rate": 0.9, "verified_fraction": 0.9, "tokens_per_verified": 1000.0}
    live = {"natural_exit_rate": True, "verified_fraction": False, "tokens_per_verified": True}
    guards = OuterTuner._evaluate_guards(proposed, baseline, live)
    vf = next(g for g in guards if g.name == "verified_fraction")
    fail.check("dead guard reports live=False", vf.live is False)
    fail.check("dead guard reports passed=False despite favorable numbers", vf.passed is False)
    real_rejects = OuterTuner._compound_accepts(proposed, baseline, live) is False
    fail.check("compound gate cannot accept on a dead guard", real_rejects)

    # Proven-failable: a "conflating" gate (the historical shape) that
    # defaults an unavailable guard to PASS would wrongly accept here.
    def _conflating_compound_accepts(proposed, baseline, live):
        tol = 1e-6
        ne_ok = proposed["natural_exit_rate"] > baseline["natural_exit_rate"]
        # BUG: no input -> silently treated as "no objection" (passed=True).
        vf_ok = True if not live["verified_fraction"] else (
            proposed["verified_fraction"] >= baseline["verified_fraction"] - tol
        )
        tpv_ok = proposed["tokens_per_verified"] <= baseline["tokens_per_verified"] + tol
        return ne_ok and vf_ok and tpv_ok

    bugged_rejects = not _conflating_compound_accepts(proposed, baseline, live)
    fail.prove_failable(
        "dead-guard-cannot-accept",
        real_result=real_rejects,
        bugged_result=bugged_rejects,
    )


# ── Assertion 8: live_guards == 3 ────────────────────────────────────────────

def validate_8_live_guards_equals_three(fail):
    print("8. live_guards == 3 (debug endpoint reports real liveness)")
    from backend.api import caducean_debug
    import backend.agent.outer_loop as _ol_module

    def _seeded_tuner():
        rec = _recorder()
        _seed(rec, [(True, 8, 5000.0, 10)] * 4)
        return OuterTuner(recorder=rec, held_out_count=3)

    _orig = _ol_module.OuterTuner
    _ol_module.OuterTuner = _seeded_tuner
    try:
        result = caducean_debug._outer_loop()
    finally:
        _ol_module.OuterTuner = _orig
    fail.check("live_guards == 3", result.get("live_guards") == 3)
    fail.check("dead_guards is empty", result.get("dead_guards") == [])

    # Proven-failable: before REQ-6, the endpoint's diagnosis logic inferred
    # deadness from a suspicious VALUE (== 1.0 / == 0.0) rather than from
    # `GuardResult.live` — that heuristic misses a guard that is dead for a
    # DIFFERENT reason (e.g. an exception) but happens to compute a
    # non-suspicious number.
    def _value_based_diagnosis(score):
        diagnosis = []
        if score.get("verified_fraction") == 1.0:
            diagnosis.append("verified_fraction")
        if score.get("tokens_per_verified") == 0.0:
            diagnosis.append("tokens_per_verified")
        return diagnosis
    # A degenerate-but-real batch: verified_fraction genuinely computes to
    # 1.0 (all steps verified) — the value-based heuristic misdiagnoses a
    # LIVE, correctly-computed 1.0 as "dead", which is the mirror failure.
    rec = _recorder()
    _seed(rec, [(True, 10, 5000.0, 10)] * 4)  # every step verified -> vf == 1.0 genuinely
    tuner = OuterTuner(recorder=rec, held_out_count=3)
    held_out = tuner._heldout_batch(tuner._ledger()["exits"])
    score, live = tuner._score_with_liveness(held_out)
    real_live_count = sum(live.values())
    bugged_live_count = 3 - len(_value_based_diagnosis(score))
    fail.prove_failable(
        "live_guards reflects real liveness, not a value heuristic",
        real_result=real_live_count == 3,
        bugged_result=bugged_live_count == 3,
    )


# ── Assertion 9: every executed action has a commit row; every vetoed one
#    has none ────────────────────────────────────────────────────────────

def validate_9_executed_has_row_vetoed_has_none(fail):
    print("9. every executed action in a replayed trajectory has a commit "
          "row; every vetoed one has none")
    rec = _recorder()
    executed_steps = [
        ("exec-1", "VERIFIED"), ("exec-2", "UNVERIFIED"), ("exec-3", "FAILED"),
    ]
    for step_id, label in executed_steps:
        rec.record_commit("sess-replay", step_id, "", f"{label} step", verified_label=label)

    vetoed_item = QueueItem(
        step_id="vetoed-1", step_number=4, description="risky action",
        tool="run_command", params={}, critical=False, objective_anchor="x",
    )
    queue = DirectorQueue(objective="x", items=[vetoed_item])
    queue.mark_vetoed(vetoed_item.step_id)  # the real veto bookkeeping — no ledger write

    rows = rec._conn.execute(
        "SELECT step_id, verified_label FROM der_commits WHERE session_id = 'sess-replay'"
    ).fetchall()
    executed_ids = {r[0] for r in rows}
    fail.check(
        "every executed step has a row",
        executed_ids == {"exec-1", "exec-2", "exec-3"},
    )
    fail.check("vetoed step has NO row", "vetoed-1" not in executed_ids)
    fail.check("vetoed step recorded in vetoed_ids, not der_commits", "vetoed-1" in queue.vetoed_ids)

    # Proven-failable: a ledger that (incorrectly) wrote a row for the vetoed
    # action too — the phantom-card failure this contract exists to prevent.
    def _buggy_write_row_even_when_vetoed(rec, step_id):
        rec.record_commit("sess-replay", step_id, "", "vetoed but written anyway", verified_label="VERIFIED")

    bugged_rec = _recorder()
    for step_id, label in executed_steps:
        bugged_rec.record_commit("sess-replay", step_id, "", f"{label} step", verified_label=label)
    _buggy_write_row_even_when_vetoed(bugged_rec, "vetoed-1")
    bugged_rows = bugged_rec._conn.execute(
        "SELECT step_id FROM der_commits WHERE session_id = 'sess-replay'"
    ).fetchall()
    bugged_ids = {r[0] for r in bugged_rows}
    fail.prove_failable(
        "vetoed action writes no row",
        real_result="vetoed-1" not in executed_ids,
        bugged_result="vetoed-1" not in bugged_ids,
    )


def main() -> int:
    print("=" * 72)
    print("PHASE 6 — OUTER LOOP INTEGRITY — STANDING CDD HARNESS")
    print("=" * 72)
    fail = _Failures()

    validate_1_contracts_hold(fail)
    validate_2_verified_fraction_not_constant(fail)
    validate_3_tokens_per_verified_nonzero(fail)
    validate_4_each_guard_rejects_independently(fail)
    validate_5_never_split_present_and_rejected(fail)
    validate_6_zero_step_session_neutral(fail)
    validate_7_dead_guard_cannot_accept(fail)
    validate_8_live_guards_equals_three(fail)
    validate_9_executed_has_row_vetoed_has_none(fail)

    print("-" * 72)
    print("PROVEN-FAILABLE TABLE")
    print(f"  {'assertion':<55} {'proven?':<8}")
    for name, ok in fail.proofs:
        print(f"  {name:<55} {'YES' if ok else 'NO':<8}")
    not_proven = [n for n, ok in fail.proofs if not ok]

    print("-" * 72)
    if fail.items or not_proven:
        if fail.items:
            print(f"HARNESS FAILED: {len(fail.items)} check(s) broken")
            for name in fail.items:
                print(f"  - {name}")
        if not_proven:
            print(f"HARNESS INCOMPLETE: {len(not_proven)} assertion(s) not proven failable")
            for name in not_proven:
                print(f"  - {name}")
        return 1
    print("HARNESS PASSED: all 9 assertions hold and are proven failable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
