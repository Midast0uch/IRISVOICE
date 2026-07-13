"""
DER Constants
File: IRISVOICE/backend/agent/der_constants.py

All DER loop constants in one place.
Source: specs/director_mode_system.md (Req 35) + bootstrap/GOALS.md Step 1.5

Gate 1 Step 1.5
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Optional


# ── Execution mode (Phase 3) ────────────────────────────────────────────────


class ExecutionMode(str, Enum):
    """Director execution modes for the DER loop.

    QUICK:    Single tool call, fast response.  For simple Q&A, single-step
              tool use, voice-first when the task is straightforward.
    AGENTIC:  Multi-step tool loop with review.  The Director can emit
              multiple tool calls, review results, and decide to continue
              or stop.  Default for most tasks.
    FULL:     Full exploration + research + synthesis.  Multi-cycle with
              re-planning, web search, deep research, and comprehensive
              final response.  For complex multi-step tasks.

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


def get_token_budget(mode: Optional[str]) -> int:
    """Get token budget for a mode string.  Falls back to AGENTIC budget."""
    if mode and mode in DER_TOKEN_BUDGETS:
        return DER_TOKEN_BUDGETS[mode]
    return DER_TOKEN_BUDGETS["agentic"]


# ── Safety limits ──────────────────────────────────────────────────────────

DER_EMERGENCY_STOP    = 200   # cycle count emergency brake (last resort only)
DER_MAX_VETO_PER_ITEM = 2     # max times Reviewer can veto one item before skip
DER_MAX_GRAFTS        = 3     # max LLM recovery-plan grafts after critical failures
DER_MAX_CYCLES        = 40    # hard cycle cap (secondary to token budget)
DER_WRITE_LOCK_TIMEOUT = 5.0  # seconds — Mycelium write lock timeout


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
