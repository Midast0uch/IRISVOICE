"""Behavioural tests: the `escalate_incomplete` consumer (REQ-29 AC29.3, T48).

AC29.3 — an `escalate_incomplete` bool consumer shadowing the keyword list,
with escalation and all budget safety behaviour UNCHANGED.

The site is `der_loop`'s incomplete-keyword trigger. The engine may never
PERMIT an escalation: the budget and veto-cap checks live inside
`self.escalate`, which this wave does not touch. The assertion that matters is
that a shadow verdict cannot ADD an escalation the keywords would not have
raised.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from backend.agent import surface_shadow as ss
from backend.agent.decision_engine import Noul

_REPO = Path(__file__).resolve().parents[3]
_DER_LOOP = _REPO / "backend" / "agent" / "der_loop.py"


class _Eng:
    def __init__(self, p):
        self._p = p
        self.seen: list = []

    def noul(self, consumer_id, statement, frame, *,
             true_label="yes", false_label="no"):
        self.seen.append(consumer_id)
        return Noul(consumer_id=consumer_id, probability=self._p,
                    engine_latency_ms=2)


@pytest.fixture
def rows():
    captured: list = []
    ss.set_row_sink(captured.append)
    yield captured
    ss.set_row_sink(None)


class TestEscalateIncomplete:
    def test_escalate_incomplete_safety_unchanged(self, rows):
        """AC29.3: the keyword list decides; the engine only records."""
        engine = _Eng(p=0.02)     # the engine is CONFIDENT there is NO issue
        value, row = ss.surface_bool(
            "escalate_incomplete", "Found several relevant pages",
            brain_bool_fn=lambda: True, engine=engine,
        )

        assert value is True, (
            "a confident NEGATIVE engine verdict suppressed the keyword "
            "escalation — the engine may never permit or suppress (AC29.3)"
        )
        assert row["brain_bool"] is True
        assert row["chosen"] is False    # the engine's own, opposite, opinion

    def test_a_confident_positive_engine_cannot_invent_an_escalation(
        self, rows,
    ):
        """Shadow: the engine's positive does NOT escalate by itself."""
        engine = _Eng(p=0.99)
        value, _row = ss.surface_bool(
            "escalate_incomplete", "The result looks complete",
            brain_bool_fn=lambda: False, engine=engine,
        )

        assert value is False, (
            "a shadow engine verdict escalated a step the keywords cleared"
        )

    def test_the_der_loop_site_is_wired(self):
        """The seam must be WIRED — an unimported module emits zero rows."""
        src = _DER_LOOP.read_text(encoding="utf-8", errors="replace")
        called = {
            node.func.attr
            for node in ast.walk(ast.parse(src))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "surface_bool" in called, (
            "der_loop never shadow-scores `escalate_incomplete` (AC29.3)"
        )
        assert '"escalate_incomplete"' in src
        assert "emit_row" in called

    def test_escalation_still_passes_through_the_safety_checks(self):
        """AC29.3: the escalate call (and its budget/veto checks) is intact."""
        src = _DER_LOOP.read_text(encoding="utf-8", errors="replace")
        assert "self.escalate(" in src, (
            "the escalate call was removed — budget safety is gone"
        )
        # the keyword list survives as the engine-unavailable fallback
        assert "incomplete_keywords" in src
