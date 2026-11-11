"""Contract tests: the surface-consumer registry (REQ-29 AC29.5, T49).

AC29.5 — THE SYSTEM SHALL NOT score `tier0_classify`'s deterministic branch;
the non-fit SHALL be recorded so it is not re-proposed.

`semantic_gate.tier0_classify` is pure, deterministic, no-I/O, and resolves
most traffic at <1ms. Replacing it with a ~150ms model would be a REGRESSION.
This suite is the guard that keeps it out of the consumer set.
"""

from __future__ import annotations

import ast
from pathlib import Path

from backend.agent.decision_engine import CONSUMERS

_REPO = Path(__file__).resolve().parents[3]

# The surface consumers are all retired: `has_gaps` 2026-10-05,
# `escalate_incomplete` 2026-11-09, `needs_action` and `depth_met` 2026-11-10
# (owner). Their registry tests went with them; the non-fit guard stays.
_NON_FIT = "tier0_classify"


class TestConsumerRegistry:
    def test_tier0_not_scored(self):
        """AC29.5: the recorded non-fit is absent from the consumer set."""
        assert _NON_FIT not in CONSUMERS, (
            "tier0_classify was added to CONSUMERS — it is a recorded NON-FIT "
            "(pure, <1ms, no I/O); a model there is a regression (AC29.5)"
        )
        for mod in ("decision_engine.py", "decision_backend_d1.py",
                    "surface_shadow.py"):
            src = (_REPO / "backend" / "agent" / mod).read_text(
                encoding="utf-8", errors="replace")
            tree = ast.parse(src)
            scored = {
                node.value
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            }
            assert _NON_FIT not in scored, (
                f"{mod} names {_NON_FIT} as a scored consumer string"
            )
