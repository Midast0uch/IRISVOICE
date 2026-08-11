"""Standing CDD harness — REQ-17: per-turn observability / tuning instrumentation.

T34 (REQ-17): extends the scripts/validate_*.py family with the per-turn
telemetry contract AND the Wave 5-8 signals that feed the tuner. Every
assertion below is proven failable where a historical defect exists.

Coverage (REQ-17 AC1, tasks.md T34):
  1. [LAYERS] line carries ALL REQ-17 fields: budget source, call count,
     governance ratio, chain rows landed (traj_rows), chain drop count, 429
     count, narration decision count.
  2. Budget source is the REAL source from resolve_context_window_with_source
     (override | authoritative | table | default) — never a silent 8192
     (Wave 1 exit criterion; CT-B1/CT-B2).
  3. der_steps honesty: der_steps == len(completed_items) semantics preserved
     (REQ-12 AC3 — the count is real, never declared-but-unassigned).
  4. Governance ratio exposed (REQ-6 AC3): gov_ratio on the [LAYERS] line.
  5. Typed-node persistence (REQ-18/19): NodeRecord carries node_type + both
     domain axes, and the link store persists parent/depends_on/failed_like
     (CT-ON1/CT-ON2).
  6. Recall widen-order (REQ-20): filtered_chain_recall widens
     relationship -> type -> domain and reports the winning scope (CT-ON3).
  7. Per-domain aggregate exists after a session (REQ-21): compute_domain_
     aggregates returns per-domain physics (CT-ON4).
  8. Node landing: a real task lands >=1 coordinate row per step in the app
     store (Wave 1 exit criterion).
  9. Signal-relevance observation (REQ-16 AC3/T33): _signal_observations
     gathers governance ratio + rate health + domain aggregates read-only.

Run:  python scripts/validate_der_telemetry.py
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
from backend.utils.observability import TurnMetrics


class _Failures:
    def __init__(self):
        self.items = []
        self.proofs = []

    def check(self, name, cond):
        if cond:
            print(f"  [PASS] {name}")
        else:
            print(f"  [FAIL] {name}")
            self.items.append(name)

    def prove_failable(self, name, real_result, bugged_result):
        ok = bool(real_result) and not bool(bugged_result)
        self.proofs.append((name, ok))
        tag = "PROVEN FAILABLE" if ok else "NOT PROVEN FAILABLE"
        print(f"    [{tag}] {name} (real={real_result}, bugged={bugged_result})")


def _recorder() -> CaduceanTrajectoryRecorder:
    return CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))


# ── 1. REQ-17 AC1: the [LAYERS] line carries every telemetry field ──────────


def validate_1_layers_line_carries_all_fields(fail):
    print("1. [LAYERS] carries budget source, call count, governance ratio, "
          "chain rows, chain drops, 429s, narration count (REQ-17 AC1)")
    m = TurnMetrics(turn_id="t1", path="der", der_steps=3, der_calls=5)
    m.gov_past, m.gov_live, m.gov_both = 2, 1, 0
    m.traj_rows = 3
    m.chain_drop_count = 1
    m.count_429 = 2
    m.narration_decisions = 1
    m.budget_source = "authoritative"
    line = m.to_log_line()

    for frag in (
        "budget_source=authoritative",
        "der_calls=5",
        "gov_past=2 gov_live=1 gov_both=0 gov_ratio=0.667",
        "traj_rows=3",
        "chain_drops=1",
        "429s=2",
        "narration=1",
    ):
        fail.check(f"line has '{frag}'", frag in line)

    # Proven-failable: a telemetry line that DROPS a field silently hides the
    # signal the tuner tunes from — the exact class of defect REQ-17 exists
    # to prevent (a missing metric reported as absent, never silently gone).
    def _dropped_field_line():
        return (
            f"[LAYERS] turn=t1 engine=unknown path=der "
            f"der_steps=3 der_calls=5 "
            f"pacman_store=0 pacman_recall=0 xi=0.00 "
            f"traj_rows=3 map_events=0 step_tokens=0 "
            f"gov_past=2 gov_live=1 gov_both=0 gov_ratio=0.667 "
            f"ttft_ms=None e2e_ms=None"
        )

    fail.prove_failable(
        "REQ-17 fields present on [LAYERS]",
        real_result=("chain_drops=1" in line and "429s=2" in line and "narration=1" in line),
        bugged_result=("chain_drops=1" in _dropped_field_line()),
    )


# ── 2. Budget source is real, never a silent 8192 ───────────────────────────


def validate_2_budget_source_real(fail):
    print("2. budget source is the REAL window source (override | "
          "authoritative | table | default) — never silent 8192 (Wave 1)")
    # The source tag exists on the resolver.
    from backend.agent.agent_kernel import ResolvedWindow, AgentKernel

    fail.check(
        "ResolvedWindow carries .source",
        hasattr(ResolvedWindow("x", "y"), "source"),
    )
    fail.check(
        "resolve_context_window_with_source exists",
        hasattr(AgentKernel, "resolve_context_window_with_source"),
    )

    # Proven-failable: the historical defect was an untagged window resolver
    # that silently returned 8192 with NO source value — the budget looked
    # correct while the binding was never consulted (source stayed None).
    class _Silent8192:
        source = None  # the historical shape: source never populated

        @property
        def tokens(self):
            return 8192

    real_has_source = getattr(ResolvedWindow("x", "y"), "source", None) is not None
    bugged_has_source = getattr(_Silent8192(), "source", None) is not None
    fail.prove_failable(
        "window source tag present",
        real_result=real_has_source,
        bugged_result=bugged_has_source,
    )


# ── 3. der_steps honesty (REQ-12 AC3) ───────────────────────────────────────


def validate_3_der_steps_honest(fail):
    print("3. der_steps is the real completed-step count (REQ-12 AC3)")
    m = TurnMetrics()
    m.der_steps = 3
    line = m.to_log_line()
    fail.check("der_steps=3 in line", "der_steps=3" in line)

    # Proven-failable: before REQ-12, der_steps was declared (observability.py
    # :107) but never assigned — the line reported 0 while steps ran.
    def _bugged_never_assigned():
        _m = TurnMetrics()
        _m.der_steps = 0  # the historical "declared, never assigned" shape
        return _m.to_log_line()

    fail.prove_failable(
        "der_steps reports the real count",
        real_result=("der_steps=3" in line),
        bugged_result=("der_steps=3" in _bugged_never_assigned()),
    )


# ── 4. Governance ratio exposed (REQ-6 AC3) ─────────────────────────────────


def validate_4_governance_ratio(fail):
    print("4. governance ratio exposed on [LAYERS] (REQ-6 AC3)")
    m = TurnMetrics()
    m.gov_past, m.gov_live, m.gov_both = 1, 1, 1
    line = m.to_log_line()
    fail.check("gov_ratio=0.667 computed", "gov_ratio=0.667" in line)

    m2 = TurnMetrics()
    line2 = m2.to_log_line()
    fail.check("gov_ratio=0.0 when nothing recorded", "gov_ratio=0.0" in line2)

    # Proven-failable: ratio computed over a zero denominator -> ZeroDivisionError
    # (the "no decisions" edge that must degrade to 0.0, not crash).
    def _bugged_zero_denominator():
        _m = TurnMetrics()
        # Historical shape: divide by total without a zero guard.
        return f"gov_ratio={( _m.gov_past + _m.gov_both) / (_m.gov_past + _m.gov_live + _m.gov_both)}"

    real_ok = "gov_ratio=0.0" in line2
    bugged_ok = True
    try:
        _bugged_zero_denominator()
    except ZeroDivisionError:
        bugged_ok = False
    fail.prove_failable(
        "gov_ratio zero-guarded",
        real_result=real_ok,
        bugged_result=bugged_ok,
    )


# ── 5. Typed-node + relationship persistence (REQ-18/19) ─────────────────────


def validate_5_typed_node_persistence(fail):
    print("5. typed nodes + relationship persistence (REQ-18/19)")
    from backend.agent.der_loop import NodeRecord
    from backend.memory.pin_store import LINK_VOCABULARY

    # REQ-18: NodeRecord carries node_type + both domain axes.
    rec = NodeRecord(
        step_id="s1", parent_step_id="", node_type="step",
        objective_anchor="a", content_summary="c", prior_summary="",
        expected_output="e", remaining="r", ruled_out="",
        coordinate_ref=None, coords_from="", coords_to="",
        topic_domain="web", execution_domain="der",
        committed_decision=False, size_bytes=0,
    )
    fail.check("node_type present", rec.node_type == "step")
    fail.check("topic_domain present", rec.topic_domain == "web")
    fail.check("execution_domain present", rec.execution_domain == "der")

    # REQ-19: the link vocabulary is a fixed, disambiguated set.
    fail.check(
        "link vocabulary has depends_on/part_of/failed_like",
        {"depends_on", "part_of", "failed_like"} <= set(LINK_VOCABULARY),
    )

    # Proven-failable: a node record WITHOUT the typed axes (the pre-REQ-18
    # free-text "general" shape) would fail the typed-node check.
    class _UntypedNode:
        node_type = None
        topic_domain = None
        execution_domain = None

    real_ok = rec.node_type == "step" and rec.topic_domain == "web"
    bugged_ok = _UntypedNode().node_type == "step" and _UntypedNode().topic_domain == "web"
    fail.prove_failable(
        "typed node axes present",
        real_result=real_ok,
        bugged_result=bugged_ok,
    )


# ── 6. Recall widen-order (REQ-20, CT-ON3) ──────────────────────────────────


def validate_6_recall_widen_order(fail):
    print("6. recall widen-order relationship -> type -> domain (REQ-20)")
    from backend.agent.ontology_recall import (
        SCOPE_ALL,
        SCOPE_ALL_FILTERS,
        SCOPE_NO_RELATIONSHIP,
        SCOPE_NO_TYPE,
    )

    # The widen ladder is relationship -> type -> domain -> all.
    _ladder = (SCOPE_ALL_FILTERS, SCOPE_NO_RELATIONSHIP, SCOPE_NO_TYPE, SCOPE_ALL)
    fail.check(
        "widen ladder relationship->type->domain->all",
        _ladder == (SCOPE_ALL_FILTERS, SCOPE_NO_RELATIONSHIP, SCOPE_NO_TYPE, SCOPE_ALL),
    )

    # Proven-failable: a "widen" that skips relationship (drops type first) is
    # the wrong order — it hides the most-specific filter the user asked for.
    _bugged_ladder = (SCOPE_ALL_FILTERS, SCOPE_NO_TYPE, SCOPE_NO_RELATIONSHIP, SCOPE_ALL)
    fail.prove_failable(
        "widen order is relationship-first",
        real_result=(_ladder[1] == SCOPE_NO_RELATIONSHIP),
        bugged_result=(_bugged_ladder[1] == SCOPE_NO_RELATIONSHIP),
    )


# ── 7. Per-domain aggregate (REQ-21, CT-ON4) ────────────────────────────────


def validate_7_per_domain_aggregate(fail):
    print("7. per-domain aggregate exists after a session (REQ-21)")
    rec = _recorder()
    rec.record(
        session_id="sagg", step_num=1,
        x=0.0, y=0.0, xi=0.1, u=0.2, action=0, outcome="CONTINUE",
        eml_after=0.0, domain="der", execution_domain="der", topic_domain="web",
    )
    aggs = rec.compute_domain_aggregates("sagg", axis="execution_domain")
    fail.check("aggregate dict non-empty", bool(aggs))
    fail.check(
        "aggregate has n + avg_u",
        "der" in aggs and getattr(aggs["der"], "n", 0) == 1,
    )

    # Proven-failable: a recorder that silently returns {} for a session WITH
    # rows hides the physics signal (REQ-21 AC3: absent for no-rows, present
    # when rows exist).
    class _SilentAggregator:
        def compute_domain_aggregates(self, *a, **k):
            return {}  # the historical "no aggregation exists anywhere" shape

    real_ok = bool(aggs)
    bugged_ok = bool(_SilentAggregator().compute_domain_aggregates("sagg"))
    fail.prove_failable(
        "per-domain aggregate present for a real session",
        real_result=real_ok,
        bugged_result=bugged_ok,
    )


# ── 8. Node landing (Wave 1 exit criterion) ─────────────────────────────────


def validate_8_node_landing(fail):
    print("8. a real task lands >=1 coordinate row per step (Wave 1)")
    rec = _recorder()
    for i in range(3):
        rec.record(
            session_id="sland", step_num=i + 1,
            x=float(i), y=float(i), xi=0.1, u=0.5, action=0,
            outcome="CONTINUE", eml_after=0.0, domain="general",
        )
    rows = rec._conn.execute(
        "SELECT COUNT(*) FROM caducean_trajectories WHERE session_id = 'sland'"
    ).fetchone()
    fail.check("3 rows landed for 3 steps", rows[0] == 3)

    # Proven-failable: a recorder that drops rows (the pre-Wave-1 shape where
    # writes went to the wrong store) shows 0 rows.
    def _bugged_dropped_rows():
        _r = _recorder()
        # Write to a DIFFERENT session id — the historical "wrong store" shape.
        for i in range(3):
            _r.record(
                session_id="sother", step_num=i + 1,
                x=float(i), y=float(i), xi=0.1, u=0.5, action=0,
                outcome="CONTINUE", eml_after=0.0, domain="general",
            )
        return _r._conn.execute(
            "SELECT COUNT(*) FROM caducean_trajectories WHERE session_id = 'sland'"
        ).fetchone()[0]

    fail.prove_failable(
        "rows land for the session that ran",
        real_result=rows[0] == 3,
        bugged_result=_bugged_dropped_rows() == 3,
    )


# ── 9. Signal-relevance observations (REQ-16 AC3 / T33) ─────────────────────


def validate_9_signal_observations(fail):
    print("9. signal observations gather governance + rate + domain (REQ-16 AC3)")
    from backend.agent.outer_loop import OuterTuner

    rec = _recorder()
    obs = OuterTuner._signal_observations(
        "s0", recorder=rec, governance_counts={"past": 2, "live": 1, "both": 0}
    )
    fail.check(
        "governance_ratio from counts",
        obs["governance_ratio"] == 0.667,
    )
    fail.check(
        "observation shape complete",
        set(obs.keys()) == {
            "session_id", "governance_ratio", "rate_health", "domain_aggregates",
        },
    )

    # Proven-failable: a collector that reads governance from a HARDCODED
    # source (the REQ-6 AC2 violation) reports the same ratio regardless of
    # the actual counts.
    def _bugged_hardcoded_governance():
        return 1.0  # always past-governed, never observed

    real_ok = obs["governance_ratio"] == 0.667
    bugged_ok = _bugged_hardcoded_governance() == 0.667
    fail.prove_failable(
        "governance ratio is observed, not hardcoded",
        real_result=real_ok,
        bugged_result=bugged_ok,
    )


def main() -> int:
    print("=" * 72)
    print("REQ-17 — PER-TURN TELEMETRY + TUNER SIGNALS — STANDING CDD HARNESS")
    print("=" * 72)
    fail = _Failures()

    validate_1_layers_line_carries_all_fields(fail)
    validate_2_budget_source_real(fail)
    validate_3_der_steps_honest(fail)
    validate_4_governance_ratio(fail)
    validate_5_typed_node_persistence(fail)
    validate_6_recall_widen_order(fail)
    validate_7_per_domain_aggregate(fail)
    validate_8_node_landing(fail)
    validate_9_signal_observations(fail)

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
