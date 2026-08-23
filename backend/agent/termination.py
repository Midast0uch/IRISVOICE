"""Why did this run stop? — the closed termination-cause vocabulary.

specs/der-ground-truth/ REQ-9 (T18/T19/T20).

THE PROBLEM
-----------
The bounds are not missing. `DER_MAX_CYCLES=40`, `DER_MAX_VETO_PER_ITEM=2`,
`DER_MAX_GRAFTS=3`, `DER_TOKEN_BUDGETS`, `MAX_DEPTH=3`
(`backend/agent/der_constants.py:196-237`), `_DER_TURN_BUDGET_S=600`
(`agent_kernel.py:125`), plus session 247's wall ledger, sufficiency gate and
zero-yield cutoff. Eight-plus termination controls across four modules, each
added reactively after an incident.

What is missing is the ability to answer **"why did this run stop?"** from stored
data. A run that hit its token budget, a run that converged naturally, and a run
killed by the turn wall-clock are indistinguishable afterwards. That is what
makes the loop feel brittle: not an absence of limits, but that its stopping
behaviour is unobservable, so every incident needs a live reproduction.

**This module adds no bounds** (REQ-9 AC5). It records the ones that exist.

THE DISCIPLINE
--------------
Closed vocabulary with a reserved member for the unrecognised, exactly like
`NodeOutcome.Reason` (`backend/agent/nodes/outcome.py:40`). An unrecognised cause
maps to `unexpected` and is COUNTED — never discarded (REQ-9 AC6).

Each record carries the bound's CONFIGURED value and its MEASURED value at exit
(REQ-9 AC3), so "how close was it" is answerable without a reproduction.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

__all__ = ["TerminationCause", "TerminationRecord", "classify", "CAUSE_BOUNDS"]


class TerminationCause(str, Enum):
    """Closed set. Every run ends in exactly one of these (REQ-9 AC1/AC2)."""

    NATURAL = "natural"                      # queue drained, all items complete
    SUFFICIENCY = "sufficiency"              # findings judged sufficient pre-graft
    CYCLE_CAP = "cycle_cap"                  # DER_MAX_CYCLES
    TOKEN_BUDGET = "token_budget"            # DER_TOKEN_BUDGETS exhausted
    TURN_WALLCLOCK = "turn_wallclock"        # _DER_TURN_BUDGET_S
    VETO_CAP = "veto_cap"                    # DER_MAX_VETO_PER_ITEM
    GRAFT_CAP = "graft_cap"                  # DER_MAX_GRAFTS
    DEPTH_CAP = "depth_cap"                  # MAX_DEPTH
    ZERO_YIELD = "zero_yield"                # consecutive zero-usable-page jobs
    PERMISSION_REFUSED = "permission_refused"  # terminal permission outcome
    USER_ABORT = "user_abort"                # user cancelled
    UNEXPECTED = "unexpected"                # RESERVED - counted, never discarded


#: Which constant defines each bound, for the report. Documentation that cannot
#: drift, because REQ-9 AC5 forbids this module from changing any of them.
CAUSE_BOUNDS = {
    TerminationCause.CYCLE_CAP: "DER_MAX_CYCLES (der_constants.py:199)",
    TerminationCause.TOKEN_BUDGET: "DER_TOKEN_BUDGETS (der_constants.py:83)",
    TerminationCause.TURN_WALLCLOCK: "IRIS_DER_TURN_BUDGET_S (agent_kernel.py:125)",
    TerminationCause.VETO_CAP: "DER_MAX_VETO_PER_ITEM (der_constants.py:196)",
    TerminationCause.GRAFT_CAP: "DER_MAX_GRAFTS (der_constants.py:197)",
    TerminationCause.DEPTH_CAP: "MAX_DEPTH (der_constants.py:237)",
    TerminationCause.ZERO_YIELD: "orchestrator.research() zero-yield cutoff",
}

#: Causes that mean the loop stopped because it ran OUT of something, rather than
#: because it finished. A run ending on one of these has NOT succeeded, and
#: REQ-10 AC2 forbids reporting it as though it had.
BOUNDED_EXITS = frozenset({
    TerminationCause.CYCLE_CAP,
    TerminationCause.TOKEN_BUDGET,
    TerminationCause.TURN_WALLCLOCK,
    TerminationCause.VETO_CAP,
    TerminationCause.GRAFT_CAP,
    TerminationCause.DEPTH_CAP,
    TerminationCause.ZERO_YIELD,
})


@dataclass(frozen=True)
class TerminationRecord:
    """One run's ending, with the evidence to judge how close it was."""

    cause: TerminationCause
    #: The bound's configured value (e.g. 40 cycles), when the cause has one.
    configured: Optional[float] = None
    #: What was actually measured at exit (e.g. 40 cycles used, or 12).
    measured: Optional[float] = None
    #: A bound that ALSO tripped in the same cycle but did not stop dispatch.
    #: REQ-9 edge case: both stay visible; the near-miss is not discarded.
    co_occurring: Optional[TerminationCause] = None
    #: True when the bound was switched off, so a distribution is never read
    #: against the wrong configuration (REQ-9 edge case).
    disabled: bool = False

    @property
    def is_bounded_exit(self) -> bool:
        return self.cause in BOUNDED_EXITS

    @property
    def headroom(self) -> Optional[float]:
        """How much of the bound was left. None when not measurable."""
        if self.configured in (None, 0) or self.measured is None:
            return None
        return float(self.configured) - float(self.measured)

    def to_dict(self) -> dict:
        return {
            "termination_cause": self.cause.value,
            "bound_configured": self.configured,
            "bound_measured": self.measured,
            "co_occurring_cause": self.co_occurring.value if self.co_occurring else None,
            "bound_disabled": int(self.disabled),
        }


def classify(raw: Optional[str]) -> TerminationCause:
    """Map a free-form cause to the closed vocabulary.

    An unrecognised value becomes ``UNEXPECTED`` and is counted, never dropped
    (REQ-9 AC6) — the same Layer-3 discipline FAULTLINE applies to error labels.
    """
    if raw is None:
        _count_unexpected("none")
        return TerminationCause.UNEXPECTED
    key = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    for c in TerminationCause:
        if c.value == key:
            return c
    _count_unexpected(key)
    return TerminationCause.UNEXPECTED


def _count_unexpected(key: str) -> None:
    try:
        from backend.agent import write_counters as _wc
        _wc.bump("termination.unexpected_cause")
    except Exception:
        pass
