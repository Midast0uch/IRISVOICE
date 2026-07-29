"""
DER Constants
File: IRISVOICE/backend/agent/der_constants.py

All DER loop constants in one place.
Source: specs/director_mode_system.md (Req 35) + bootstrap/GOALS.md Step 1.5

Gate 1 Step 1.5
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional


@dataclass(frozen=True)
class ResolvedWindow:
    """The resolved context window plus the source that produced it.

    ``source`` is one of ``override`` | ``authoritative`` | ``table`` |
    ``default``. Making the source explicit is what lets REQ-2 AC4 ("an unknown
    window SHALL be visible, not silent") and REQ-10 AC1 be checked — a boolean
    "was it a default" is the smallest thing that makes an unknown window visible.
    """

    tokens: int
    source: str  # "override" | "authoritative" | "table" | "default"


# ── Execution mode (Phase 3) ────────────────────────────────────────────────


class ExecutionMode(str, Enum):
    """Director execution modes — DISPLAY LABEL ONLY (Phase 2, D2.4).

    NOTE: ExecutionMode must NOT drive execution-tree *shape*. Shape is decided
    by the live Caducean state (u,xi) via _split_step / _growth_width (the
    System Invariant: one recursive operator, physics-driven). Mode here is a
    telemetry/label and (legacy) budget selector only. Do not add branching on
    mode that changes split width or verify strictness.

    The Director decides the mode dynamically (see _decide_mode in der_loop.py).
    Mode can escalate (QUICK → AGENTIC → FULL) or de-escalate mid-task.
    """

    QUICK = "quick"
    AGENTIC = "agentic"
    FULL = "full"

    @classmethod
    def from_string(cls, value: str) -> "ExecutionMode":
        """Safe parse — falls back to AGENTIC on unknown value."""
        try:
            return cls(value.lower())
        except (ValueError, AttributeError):
            return cls.AGENTIC

    def escalate(self) -> "ExecutionMode":
        """Return the next higher mode.  FULL stays FULL."""
        if self == ExecutionMode.QUICK:
            return ExecutionMode.AGENTIC
        elif self == ExecutionMode.AGENTIC:
            return ExecutionMode.FULL
        return ExecutionMode.FULL

    def de_escalate(self) -> "ExecutionMode":
        """Return the next lower mode.  QUICK stays QUICK."""
        if self == ExecutionMode.FULL:
            return ExecutionMode.AGENTIC
        elif self == ExecutionMode.AGENTIC:
            return ExecutionMode.QUICK
        return ExecutionMode.QUICK


MODE_ORDER = [ExecutionMode.QUICK, ExecutionMode.AGENTIC, ExecutionMode.FULL]


# ── Token budgets per mode ─────────────────────────────────────────────────

# New-style budgets keyed by ExecutionMode.value
DER_TOKEN_BUDGETS: Dict[str, int] = {
    "quick":    15_000,  # single tool call
    "agentic":  30_000,  # multi-step tool loop
    "full":     60_000,  # full exploration + research + synthesis
    # Legacy mode names (backward compat)
    "SPEC":       60_000,
    "RESEARCH":   80_000,
    "IMPLEMENT":  40_000,
    "DEBUG":      30_000,
    "TEST":       40_000,
    "REVIEW":     20_000,
    "DEFAULT":    40_000,
    "VOICE_FIRST": 15_000,
    # lowercase legacy aliases
    "spec":        60_000,
    "research":    80_000,
    "implement":   40_000,
    "debug":       30_000,
    "test":        40_000,
    "review":      20_000,
    "default":     40_000,
    "voice_first": 15_000,
}


# The smallest budget DER will ever run with, and itself capped by the real
# window (see resolve_der_token_budget). This is the ONLY floor. The per-mode
# values above are CEILINGS — how much of the window a task class is allowed to
# ask for — never floors.
#
# History: DER_TOKEN_BUDGETS was previously applied as `max(window*0.9, floor)`.
# Because every entry here is 15k-80k, the "floor" beat the derived value for
# any model under ~44k, so an 8k-window model was authorised 40,000 tokens — a
# ~5x overcommit that let the loop keep issuing steps while every call
# truncated. The floor must never exceed the window it is protecting.
DER_BUDGET_MIN_FLOOR = 4_000

# Fraction of the real context window DER may spend on step execution. The
# remainder is headroom for the system prompt, the final synthesis, and the
# response itself.
DER_WINDOW_UTILISATION = 0.9


def get_token_budget(mode: Optional[str]) -> int:
    """Get token budget for a mode string.  Falls back to AGENTIC budget."""
    if mode and mode in DER_TOKEN_BUDGETS:
        return DER_TOKEN_BUDGETS[mode]
    return DER_TOKEN_BUDGETS["agentic"]


# Per-class share of the model's usable window. This is the CEILING, expressed
# as a fraction so a large model is actually used: on a 256k window "full" gets
# ~207k instead of the flat 60k the absolute table allowed.
#
# DER_TOKEN_BUDGETS above stays in ABSOLUTE tokens and is NOT replaced — it is
# still read by DirectorQueue._decide_mode (der_loop.py:220) and _should_escalate
# (:283-289), which compare a remaining token count against a mode budget. Two
# structures because they answer two different questions: "how much of this
# window may this class use" (here) vs "does this mode have room left" (there).
DER_MODE_WINDOW_FRACTION: Dict[str, float] = {
    "quick":       0.10,   # single tool call — bounded on purpose
    "agentic":     0.40,
    "full":        0.90,
    "voice_first": 0.10,
    "spec":        0.90,
    "research":    0.90,
    "implement":   0.40,
    "debug":       0.40,
    "test":        0.40,
    "review":      0.25,
    "quick_edit":  0.10,
    "default":     0.40,
}
DER_DEFAULT_WINDOW_FRACTION = 0.40


def _mode_fraction(task_class: Optional[str]) -> float:
    if not task_class:
        return DER_DEFAULT_WINDOW_FRACTION
    return DER_MODE_WINDOW_FRACTION.get(
        task_class,
        DER_MODE_WINDOW_FRACTION.get(
            str(task_class).lower(), DER_DEFAULT_WINDOW_FRACTION
        ),
    )


def resolve_der_token_budget(context_window: int, task_class: Optional[str]) -> int:
    """Allocate DER's step budget from the model's REAL context window.

    The mode table is a per-class **ceiling** (a "quick" single-tool task should
    not be handed 230k just because the model is large); the window is the hard
    cap (no task class may exceed what the model can actually hold); and the
    floor is applied last and is itself clamped by the window, so it can never
    reintroduce an overcommit on a small model.

    Keeping this in one function is what makes `_token_budget` and
    `derive_work_units_0()` agree — both now derive from the same
    `context_window`, instead of one reading the window and the other reading a
    flat table.
    """
    _window_cap = max(int(context_window * DER_WINDOW_UTILISATION), 1)
    # Ceiling is a SHARE of the usable window, so capacity scales with the model
    # instead of being pinned to a constant tuned for an 8k-32k era.
    _mode_ceiling = int(_window_cap * _mode_fraction(task_class))
    _budget = min(_mode_ceiling, _window_cap)
    # Floor last, and never above the window.
    return max(_budget, min(DER_BUDGET_MIN_FLOOR, _window_cap))


# ── Safety limits ──────────────────────────────────────────────────────────

DER_EMERGENCY_STOP    = 200   # cycle count emergency brake (last resort only)
DER_MAX_VETO_PER_ITEM = 2     # max times Reviewer can veto one item before skip
DER_MAX_GRAFTS        = 3     # max LLM recovery-plan grafts after critical failures
DER_MAX_CONCURRENT_STEPS = 3  # max in-flight LLM calls per DER fan-out (semaphore)
DER_MAX_CYCLES        = 40    # hard cycle cap (secondary to token budget)
DER_WRITE_LOCK_TIMEOUT = 5.0  # seconds — Mycelium write lock timeout
TRAILING_GAP_MIN       = 2     # TrailingDirector gap-analysis cadence (steps)


# ── Mode selection thresholds ──────────────────────────────────────────────

# Confidence thresholds for TaskClassifier output
CLASSIFIER_CONFIDENCE_LOW = 0.4      # below this = unclear, escalate conservatively
CLASSIFIER_CONFIDENCE_HIGH = 0.85    # above this = trust the classification

# Message length heuristics (character counts)
MESSAGE_LENGTH_SHORT = 50            # "what's 2+2" → likely QUICK
MESSAGE_LENGTH_LONG = 200            # "research X, write a report, send to Y" → FULL

# Token budget thresholds for escalation
BUDGET_RATIO_ESCALATE = 0.3          # escalate if only < 30% of budget used (plenty left)
BUDGET_ABSOLUTE_MIN = 5_000          # never escalate if budget < 5k remaining


# ── Phase 2: Emergent Shape (growth-width split/execute) ───────────────────

# |u| band below which the step is unresolved/oscillating and should split wide.
# Start 0.5; tuned empirically by the Phase 4 outer loop.
U_SPLIT = 0.5

# Hard cap on recursion depth for growth-width splits (System Invariant: one
# recursive operator at bounded scale). Enforced in DirectorQueue + _split_step.
MAX_DEPTH = 3

# Average token cost of one step — used to derive the work-unit budget from the
# live context window (DER_WORK_UNITS_0). Phase-4-tunable.
AVG_STEP_COST = 1500

# High-|u| convergence threshold: at/above this the step is converged (atomic,
# deterministic verify only). Between U_SPLIT and this => mid-band (atomic +
# LLM rubric per D2.3).
U_CONVERGED = 0.85

# EML explore-pressure bands (REQ-17 / REQ-17 AC5)
# Shared source of truth for continuous explore-pressure function and
# cognitive-state phase label in agent_kernel.py. These match the old
# discrete thresholds: EXPLORE at >= 1.5, VERIFY at < 1.0, BALANCE in between.
EML_EXPLORE = 1.5
EML_VERIFY = 1.0


def derive_work_units_0(context_window: int) -> int:
    """DER_WORK_UNITS_0 (D-1): the unified termination resource.

    Derived from the live context window, NOT hardcoded. The work-unit count
    and the context window are the SAME resource (System Invariant): splitting
    prepays ``width`` units, completing/failing/vetoing consumes 1. This is what
    makes the Lyapunov potential Phi strictly decrease per cycle.

    Args:
        context_window: effective context window in tokens
                        (resolve_context_window() on the AgentKernel).

    Returns:
        int >= 1.
    """
    return max(1, int(context_window / AVG_STEP_COST))


def debit_work_units(current: int, measured_tokens: int) -> int:
    """REQ-3: consume work-units proportional to MEASURED token cost, not a flat
    child count.

    One work-unit ≈ AVG_STEP_COST tokens. A step always costs ≥1 unit (a step
    that did nothing still consumed a cycle). The result is clamped at 0 — the
    budget can never go negative.

    Args:
        current: work-units remaining before this step.
        measured_tokens: tokens this step actually spent.

    Returns:
        int >= 0 — remaining work-units.
    """
    _cost = max(1, measured_tokens // AVG_STEP_COST)
    return max(0, current - _cost)


def detect_physics_narration(
    prev_u_mag: Optional[float],
    u_mag: float,
    n_children: int,
    is_subloop: bool,
) -> Optional[str]:
    """REQ-7: agent-driven PHYSICS-EVENT narration trigger.

    Returns the spoken line to emit at a DER step boundary, or ``None`` when
    nothing physics-meaningful happened (so the agent stays SILENT on ordinary
    steps — no per-step heartbeat).

    Triggers (in precedence order):
      1. Split — step spawned Sub-Loop children -> "now moving into a sub-task".
      2. Sub-Loop collapse — a sub-loop item finalized with no children ->
         "folding back into the main thread".
      3. |u| transition oscillating -> converged -> "settling into the answer".
      4. |u| transition converged -> oscillating -> "re-opening the search".

    Thresholds reuse U_SPLIT (above = oscillating) and U_CONVERGED
    (at/above = converged). ``prev_u_mag is None`` (first step) yields no
    transition line.

    Invariant: spoken ⊆ visible — every returned line is a real transition,
    never filler.

    Args:
        prev_u_mag: |u| from the previous step (None on first step).
        u_mag: |u| at the current step (non-negative).
        n_children: number of Sub-Loop children spawned this finalize (0 = none).
        is_subloop: the finalized item is itself a Sub-Loop.

    Returns:
        str | None — the line to speak, or None to stay silent.
    """
    # Structural events take precedence.
    if n_children and n_children > 0:
        return (
            f"Now moving into a sub-task — splitting into {n_children} parts."
        )
    if is_subloop and not n_children:
        return "Sub-task done; folding back into the main thread."
    if prev_u_mag is None:
        return None
    # Bands: converged = |u| >= U_CONVERGED; oscillating = U_SPLIT < |u|
    # < U_CONVERGED; below U_SPLIT is the split/deep-oscillation zone.
    _was_conv = prev_u_mag >= U_CONVERGED
    _was_osc = (prev_u_mag > U_SPLIT) and (prev_u_mag < U_CONVERGED)
    _now_conv = u_mag >= U_CONVERGED
    _now_osc = (u_mag > U_SPLIT) and (u_mag < U_CONVERGED)
    if _was_osc and _now_conv:
        return "Settling into the answer now."
    if _was_conv and _now_osc:
        return "Re-opening the search."
    return None
