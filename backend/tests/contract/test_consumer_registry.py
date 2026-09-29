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

from backend.agent import surface_shadow as ss
from backend.agent.decision_engine import CONSUMERS

_REPO = Path(__file__).resolve().parents[3]

_SURFACE = ("has_gaps", "use_thinking", "escalate_incomplete", "needs_action")
_NON_FIT = "tier0_classify"


class TestConsumerRegistry:
    def test_tier0_not_scored(self):
        """AC29.5: the recorded non-fit is absent from the consumer set."""
        assert _NON_FIT not in CONSUMERS, (
            "tier0_classify was added to CONSUMERS — it is a recorded NON-FIT "
            "(pure, <1ms, no I/O); a model there is a regression (AC29.5)"
        )
        for mod in ("decision_engine.py", "decision_backend_onnx.py",
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

    def test_the_four_surface_consumers_are_registered(self):
        """All four are enumerated AND have their own criteria (REQ-19)."""
        for cid in _SURFACE:
            assert cid in CONSUMERS, f"{cid} is not a registered consumer"

        # The first call registers whatever is missing; a SECOND must be a
        # no-op, or every scoring call would re-register (and the registry is
        # process-wide).
        ss.register_surface_consumers()
        assert ss.register_surface_consumers() == 0, (
            "registration was not idempotent — a second call re-registered"
        )

        from backend.agent.decision_backend_onnx import get_consumer_spec

        for cid in _SURFACE:
            spec = get_consumer_spec(cid)
            assert spec is not None, (
                f"{cid} has no criteria — the engine would REFUSE to score it "
                "(REQ-19)"
            )
            assert spec.instruction == ss.SURFACE_CONSUMERS[cid], (
                f"{cid} was registered under another consumer's head"
            )
            assert set(spec.labels) == {"yes", "no"}

    def test_each_surface_consumer_has_its_own_instruction(self):
        """No two consumers share a head — the REQ-19 binding rule."""
        instructions = list(ss.SURFACE_CONSUMERS.values())
        assert len(set(instructions)) == len(instructions), (
            "two surface consumers share an instruction — they would be scored "
            "under the same head"
        )
