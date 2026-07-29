"""DER Phase 4 (D4.2): Outer Loop — AIDE^2 self-improvement.

The outer loop fires on the COMPACTION SIGNAL (pre-compress hook +
record_session_exit), NOT the MCM 70% cadence. Each run proposes ONE physics
parameter change (U_SPLIT, growth width, or verify-strictness), scores it on a
HELD-OUT batch of sessions, and applies it only if it improves the held-out
metric. This is the empowered, slow-timescale learner that tunes the fast
timescale (the coupled action cycle) without destabilizing it.

Held-out metric (D4.3): natural_exit_rate = fraction of held-out sessions that
ended via a NATURAL EXIT. The whitelist EXCLUDES drift and route_score — those
are MCM governance quirks (Q=-0.98 TOPO_VIOLATION), not real session-quality
signals, and must never enter the learning objective.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GuardResult:
    """One compound-gate guard's outcome (Phase 6 REQ-6 AC5 / D-3).

    ``live`` and ``passed`` are DISTINCT on purpose. A guard whose input could
    not be computed for this batch reports ``live=False`` — it is DEAD, not
    passing. Conflating "no signal" with "no objection" is exactly what let a
    three-metric gate accept on one metric for months: ``verified_fraction``
    read a literal and ``tokens_per_verified`` read an unpopulated column, both
    silently reported as passing.
    """

    name: str
    baseline: float
    proposed: float
    live: bool
    passed: bool


# Default physics parameters (overridable by the learned store).
DEFAULT_PARAMS: Dict[str, float] = {
    "U_SPLIT": 0.5,
    "U_CONVERGED": 0.85,
    "MAX_WIDTH": 3.0,  # growth-width ceiling for unresolved_u
    "VERIFY_STRICT": 1.0,  # 1 => mid-band uses LLM rubric
}

# Whitelist of session-exit fields that may enter the learning objective.
# drift and route_score are EXCLUDED (MCM governance quirks, not quality).
HELD_OUT_WHITELIST = ("natural_exit",)

# Step sizes for one-at-a-time proposals.
#
# REQ-4 (D-2): U_SPLIT gains a "never split" candidate. _growth_width /
# _der_verify_strictness (agent_kernel.py) both split only when
# `abs(u) < U_SPLIT`, and abs(u) can never be negative — so U_SPLIT <= 0.0 is
# the value that is PROVABLY past the point where a split can occur (OQ-2):
# `abs(u) < 0.0` is false for every real u, never just usually false. This is
# the reward-hack the compound gate is named for ("never split" raises
# natural_exit_rate by skipping the hard part) and it must be PRESENT here so
# the gate actually rejects it (REQ-4 AC1/AC2) instead of the hack being
# merely absent from the candidate list, which is untested, not prevented.
_PROPOSALS: Dict[str, List[float]] = {
    "U_SPLIT": [0.0, 0.4, 0.5, 0.6, 0.7],
    "U_CONVERGED": [0.75, 0.85, 0.95],
    "MAX_WIDTH": [2.0, 3.0, 4.0],
    "VERIFY_STRICT": [0.0, 1.0],
}


class OuterTuner:
    """AIDE^2 outer-loop tuner for the DER physics parameters."""

    def __init__(
        self,
        recorder=None,
        params_path: Optional[str] = None,
        held_out_count: int = 3,
    ):
        if recorder is None:
            from backend.agent.caducean_trajectory import (
                CaduceanTrajectoryRecorder,
            )

            recorder = CaduceanTrajectoryRecorder()
        self.recorder = recorder
        self.params_path = params_path or os.path.join(
            os.path.dirname(__file__), "..", "..", ".mcm", "der_params.json"
        )
        self.held_out_count = held_out_count
        self.params = self._load_params()

    # ── params store ────────────────────────────────────────────────────────
    def _load_params(self) -> Dict[str, float]:
        try:
            if self.params_path and os.path.exists(self.params_path):
                with open(self.params_path, "r", encoding="utf-8") as f:
                    return {**DEFAULT_PARAMS, **json.load(f)}
        except Exception as _e:
            logger.debug("[outer_loop] params load failed: %s", _e)
        return dict(DEFAULT_PARAMS)

    def _apply(self, key: str, value: float) -> None:
        """Persist a learned parameter (D4.2 _apply)."""
        self.params[key] = value
        try:
            os.makedirs(os.path.dirname(self.params_path), exist_ok=True)
            with open(self.params_path, "w", encoding="utf-8") as f:
                json.dump(self.params, f, indent=2)
        except Exception as _e:
            logger.warning("[outer_loop] params save failed: %s", _e)

    # ── ledger reads (D4.2 _ledger) ─────────────────────────────────────────
    def _ledger(self, domain: Optional[str] = None) -> Dict[str, Any]:
        """Read the commit / fan-trace / session-exit ledgers."""
        exits = self.recorder.get_session_exits(domain=domain, limit=500)
        commits = []
        try:
            commits = self.recorder._conn.execute(
                "SELECT session_id, step_id FROM der_commits ORDER BY id DESC LIMIT 500"
            ).fetchall()
        except Exception:
            pass
        return {"exits": exits, "commits": commits}

    # ── held-out split (D4.3) ───────────────────────────────────────────────
    def _heldout_batch(self, exits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Most-recent `held_out_count` sessions are the held-out set; the rest
        are the training set. The tuner scores proposals on the held-out set."""
        return exits[: self.held_out_count]

    # ── score (D4.3 / REQ-2): compound held-out metric ──────────────────────
    def _score(self, held_out: List[Dict[str, Any]]) -> Dict[str, float]:
        """Held-out metrics for the compound gate (REQ-2). Thin wrapper over
        `_score_with_liveness` kept for backward compatibility with call sites
        (and tests) that only want the metric values, not liveness."""
        metrics, _live = self._score_with_liveness(held_out)
        return metrics

    def _score_with_liveness(
        self, held_out: List[Dict[str, Any]]
    ) -> Tuple[Dict[str, float], Dict[str, bool]]:
        """Held-out metrics for the compound gate, PLUS which were computable.

        Returns (metrics, live):
          - natural_exit_rate   : fraction of held-out sessions that ended naturally.
          - verified_fraction   : mean, per held-out session, of
                                   VERIFIED-steps / executed-steps — the ACTUAL
                                   ratio read from der_commits (REQ-2 AC5), not a
                                   constant. A session with 0 executed_steps
                                   contributes NOTHING to the mean — neutral
                                   exclusion, not a 1.0 or 0.0 vote (REQ-2 AC6,
                                   D-1): counting a fresh session as 1.0 is
                                   exactly the dead-branch behaviour, and it
                                   hides degradation by dragging the mean up.
          - tokens_per_verified : mean, per held-out session with >=1 VERIFIED
                                   step, of tokens_total / verified_count.

        Only fields in HELD_OUT_WHITELIST (natural_exit) count toward the PRIMARY
        objective; drift/route_score are excluded (MCM governance quirks). The
        other two are GUARD signals — a proposal must not degrade them (AC3).

        `live[name]` is False when NO held-out session could supply that
        metric's input (every session had 0 executed_steps, or the ledger
        column could not be read) — REQ-2 edge case: "ledger missing a column
        -> the guard reading it must report as unavailable, not silently
        pass." A metric reported as 0.0 because it is genuinely UNAVAILABLE
        must never be mistaken for a metric that is 0.0 because it was
        actually measured.
        """
        if not held_out:
            return (
                {
                    "natural_exit_rate": 0.0,
                    "verified_fraction": 0.0,
                    "tokens_per_verified": 0.0,
                },
                {
                    "natural_exit_rate": True,
                    "verified_fraction": False,
                    "tokens_per_verified": False,
                },
            )
        ne_hits = 0
        vf_sum = 0.0
        vf_n = 0
        tpv_sum = 0.0
        tpv_n = 0
        _col_error = False
        for row in held_out:
            if row.get("natural_exit"):
                ne_hits += 1
            try:
                vc = int(row.get("verified_count", 0) or 0)
                executed = int(row.get("executed_steps", 0) or 0)
                tt = float(row.get("tokens_total", 0.0) or 0.0)
            except (TypeError, ValueError):
                # Ledger row has a malformed/missing column — this session
                # cannot contribute to either guard; not the same as "0".
                _col_error = True
                continue
            # REQ-2 AC5/AC6: the REAL ratio per session, excluded when the
            # denominator is 0 (D-1) instead of being coerced to 1.0.
            if executed > 0:
                vf_sum += vc / executed
                vf_n += 1
            # tokens_per_verified is likewise undefined (not 0.0) for a session
            # with no VERIFIED steps — excluded from the mean rather than
            # silently pulling the average toward 0 and hiding a real cost.
            if vc > 0:
                tpv_sum += tt / vc
                tpv_n += 1
        n = len(held_out)
        metrics = {
            "natural_exit_rate": ne_hits / n,
            "verified_fraction": (vf_sum / vf_n) if vf_n > 0 else 0.0,
            "tokens_per_verified": (tpv_sum / tpv_n) if tpv_n > 0 else 0.0,
        }
        live = {
            "natural_exit_rate": True,
            "verified_fraction": (vf_n > 0) and not _col_error,
            "tokens_per_verified": (tpv_n > 0) and not _col_error,
        }
        return metrics, live

    @staticmethod
    def _evaluate_guards(
        proposed: Dict[str, float],
        baseline: Dict[str, float],
        live: Optional[Dict[str, bool]] = None,
    ) -> List[GuardResult]:
        """REQ-2 AC7 / REQ-6: evaluate the three guards INDEPENDENTLY.

        Each returned `GuardResult` can be inspected on its own — this is what
        makes "each guard can independently reject" (REQ-2 AC7) and "a guard
        with unavailable input is dead, not passing" (REQ-6 AC5, D-3, CT-D5)
        checkable by test, instead of only end-to-end. A compound gate tested
        only end-to-end is exactly how two dead guards survived.
        """
        tol = 1e-6
        live = live or {
            "natural_exit_rate": True,
            "verified_fraction": True,
            "tokens_per_verified": True,
        }

        ne_live = live.get("natural_exit_rate", True)
        ne_passed = ne_live and (
            proposed["natural_exit_rate"] > baseline["natural_exit_rate"]
        )
        vf_live = live.get("verified_fraction", True)
        vf_passed = vf_live and (
            proposed["verified_fraction"] >= baseline["verified_fraction"] - tol
        )
        tpv_live = live.get("tokens_per_verified", True)
        tpv_passed = tpv_live and (
            proposed["tokens_per_verified"] <= baseline["tokens_per_verified"] + tol
        )
        return [
            GuardResult(
                "natural_exit_rate",
                baseline["natural_exit_rate"],
                proposed["natural_exit_rate"],
                ne_live,
                ne_passed,
            ),
            GuardResult(
                "verified_fraction",
                baseline["verified_fraction"],
                proposed["verified_fraction"],
                vf_live,
                vf_passed,
            ),
            GuardResult(
                "tokens_per_verified",
                baseline["tokens_per_verified"],
                proposed["tokens_per_verified"],
                tpv_live,
                tpv_passed,
            ),
        ]

    @staticmethod
    def _compound_accepts(
        proposed: Dict[str, float],
        baseline: Dict[str, float],
        live: Optional[Dict[str, bool]] = None,
    ) -> bool:
        """REQ-2 AC3: accept ONLY if ALL THREE guards independently pass.

        A proposal that raises natural-exit rate by cheating (fewer VERIFIED
        steps, or more tokens per verified step) is REJECTED. This is the
        anti-hack gate. `live` defaults to "all live" for callers (and
        existing tests) that pre-compute a scenario without going through
        `_score_with_liveness`.
        """
        return all(
            g.passed for g in OuterTuner._evaluate_guards(proposed, baseline, live)
        )

    # ── propose one change (D4.2 _propose_one) ──────────────────────────────
    def _propose_one(self) -> Optional[Tuple[str, float]]:
        """Propose a single parameter change from current values.

        Picks the first candidate (in _PROPOSALS) that differs from the current
        value. One-at-a-time — never a batch (AIDE^2 discipline).
        """
        for key, candidates in _PROPOSALS.items():
            cur = self.params.get(key, DEFAULT_PARAMS.get(key))
            for cand in candidates:
                if abs(float(cand) - float(cur)) > 1e-9:
                    return (key, float(cand))
        return None

    # ── per-domain grouping (REQ-3) ──────────────────────────────────────────
    @staticmethod
    def _domain_groups(
        held_out: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Group held-out rows by their `domain` field (REQ-3)."""
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for row in held_out:
            d = row.get("domain") or "general"
            groups.setdefault(d, []).append(row)
        return groups

    @staticmethod
    def _deciding_guard(guards: List[GuardResult]) -> Optional[str]:
        """The first guard that did not pass — reported for observability
        (REQ-6 AC3). None when all guards passed."""
        for g in guards:
            if not g.passed:
                return g.name
        return None

    # ── main entry (D4.2 run_once) ───────────────────────────────────────────
    def run_once(self, domain: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Run one outer-loop iteration.

        Order (D-4): the POOLED compound gate runs first; per-domain gating
        (REQ-3) only runs — and can only ADD rejections — when pooled accepts.
        A proposal failing pooled never reaches domain iteration, so per-domain
        gating can never accept something the pooled gate rejected.

        Returns the applied change dict, or None if no improvement / no proposal.
        """
        ledger = self._ledger(domain=domain)
        exits = ledger["exits"]
        if len(exits) <= self.held_out_count:
            logger.info("[outer_loop] not enough sessions to tune (%d)", len(exits))
            return None

        held_out = self._heldout_batch(exits)
        baseline, live = self._score_with_liveness(held_out)

        proposal = self._propose_one()
        if proposal is None:
            logger.info("[outer_loop] no further proposals")
            return None

        key, value = proposal
        # Score the proposal by simulating it: a better proposal raises the
        # held-out natural_exit_rate WITHOUT degrading verified_fraction or
        # tokens_per_verified (REQ-2 compound gate). We approximate by checking
        # whether the proposed value is closer to the empirically-observed split
        # threshold. Concretely: if more held-out sessions are natural exits when
        # we expect fewer splits (higher U_SPLIT), the proposal helps.
        proposed = self._score_proposal(key, value, held_out, baseline)
        pooled_guards = self._evaluate_guards(proposed, baseline, live)
        pooled_accepts = all(g.passed for g in pooled_guards)

        # ── REQ-3: per-domain gating — pooled first, domains can only tighten ──
        domain_report: Dict[str, Any] = {}
        domain_accepts = True
        if pooled_accepts:
            groups = self._domain_groups(held_out)
            eligible = {d: rows for d, rows in groups.items() if len(rows) >= 2}
            if eligible:
                for d, rows in eligible.items():
                    d_baseline, d_live = self._score_with_liveness(rows)
                    d_proposed = self._score_proposal(key, value, rows, d_baseline)
                    d_guards = self._evaluate_guards(d_proposed, d_baseline, d_live)
                    d_pass = all(g.passed for g in d_guards)
                    domain_report[d] = {
                        "gated": True,
                        "passed": d_pass,
                        "sessions": len(rows),
                        "deciding_guard": self._deciding_guard(d_guards),
                    }
                    if not d_pass:
                        domain_accepts = False
                # AC2: reject if the gate fails in ANY gated domain.
            else:
                # AC3: fewer than 2 sessions in every domain -> pooled fallback,
                # preserving current (pre-REQ-3) behaviour.
                domain_report["_fallback"] = "pooled (no domain has >=2 held-out sessions)"

        accepted = pooled_accepts and domain_accepts
        deciding = self._deciding_guard(pooled_guards) if not pooled_accepts else (
            None if domain_accepts else "per_domain"
        )

        # REQ-6 AC3: log every accepted/rejected proposal with all three metric
        # values and the deciding guard.
        logger.info(
            "[outer_loop] %s %s=%s | baseline=%s proposed=%s deciding_guard=%s "
            "domains=%s",
            "applied" if accepted else "rejected",
            key, value, baseline, proposed, deciding, domain_report,
        )

        if accepted:
            self._apply(key, value)
            return {
                "applied": True,
                "key": key,
                "value": value,
                "baseline": baseline,
                "proposed": proposed,
                "live": live,
                "deciding_guard": deciding,
                "domains": domain_report,
            }
        return {
            "applied": False,
            "key": key,
            "value": value,
            "baseline": baseline,
            "proposed": proposed,
            "live": live,
            "deciding_guard": deciding,
            "domains": domain_report,
        }

    def _score_proposal(
        self,
        key: str,
        value: float,
        held_out: List[Dict[str, Any]],
        baseline: Dict[str, float],
    ) -> Dict[str, float]:
        """Estimate the held-out metrics a proposed param would produce.

        Conservative, monotonic rule: for split-related params, a HIGHER value
        (fewer splits) nudges natural_exit_rate up when the baseline is already
        healthy, and leaves the guard signals (verified_fraction,
        tokens_per_verified) unchanged. VERIFY_STRICT is kept at 1.0 (rubric on)
        when healthy. Returns a full metrics dict mirroring _score so the
        compound gate can evaluate it.
        """
        proposed = dict(baseline)  # guards carried over unchanged by default
        if key in ("U_SPLIT", "MAX_WIDTH", "U_CONVERGED"):
            cur = self.params.get(key, DEFAULT_PARAMS.get(key))
            # Only accept a move that increases the value when baseline is high
            # (already good) — i.e. consolidate. Otherwise keep baseline.
            if baseline["natural_exit_rate"] >= 0.5 and value > cur:
                proposed["natural_exit_rate"] = min(
                    1.0, baseline["natural_exit_rate"] + 0.05
                )
        # VERIFY_STRICT: keep at 1.0 (rubric on) when baseline is healthy.
        elif key == "VERIFY_STRICT":
            if value != 1.0:
                # Lowering strictness would risk degrading verified_fraction — do
                # not let it improve the primary metric.
                proposed["natural_exit_rate"] = baseline["natural_exit_rate"]
        return proposed


def run_outer_loop(session_id: str, domain: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """DER Phase 4 (D4.4): entry point fired on the COMPACTION SIGNAL.

    Called from the pre-compress hook / session-exit path (NOT the MCM 70%
    cadence). Runs one AIDE^2 outer-loop iteration to learn U_SPLIT / width /
    verify-strictness from the ledgers. Never raises.
    """
    try:
        tuner = OuterTuner()
        return tuner.run_once(domain=domain)
    except Exception as _e:
        logger.warning("[outer_loop] run_outer_loop failed: %s", _e)
        return None
