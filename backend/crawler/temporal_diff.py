"""T15 (REQ-14): TemporalDelta — semantic diff between a document's prior
snapshot and the current read, plain-English only.

Goal: never a raw JSON diff. Every field change becomes one sentence with
the old → new value, numeric changes (e.g. price) get a signed percent
overlay, purely additive.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class TemporalDelta:
    changed_fields: list[str] = field(default_factory=list)
    delta_statements: list[str] = field(default_factory=list)
    prior_revision: Optional[str] = None  # typographic slot for pinning into UI
    current_revision: Optional[str] = None


def _percent_change(old: float, new: float) -> str:
    if old == 0:
        return "+∞"
    pct = ((new - old) / old) * 100.0
    return f"{pct:+.1f}%"


def compute_temporal_delta(prior: Dict[str, Any], current: Dict[str, Any]) -> TemporalDelta:
    """Compute the field-level delta between two snapshots.

    - Pure function. No I/O, no network.
    - Only compares keys present in one or the other; shared key unchanged on
      both sides lands nowhere.
    - Numeric fields get the signed percent change in the statement.
    """
    delta = TemporalDelta()
    keys = set(prior) | set(current)
    for k in sorted(keys):
        old = prior.get(k)
        new = current.get(k)
        if old == new:
            continue
        delta.changed_fields.append(k)
        old_s = "—" if old is None else str(old)
        new_s = "—" if new is None else str(new)
        if isinstance(old, (int, float)) and isinstance(new, (int, float)):
            sentence = f"{k} moved from {old_s} to {new_s} ({_percent_change(old, new)})"
        else:
            sentence = f"{k} changed from {old_s} to {new_s}"
        delta.delta_statements.append(sentence)
    return delta
