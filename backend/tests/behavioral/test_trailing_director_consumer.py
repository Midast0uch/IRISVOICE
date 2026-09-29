"""Behavioural tests: the `has_gaps` consumer (REQ-29 AC29.1, T46).

AC29.1 — a `has_gaps` consumer shadowing the (former) `trailing_director`, with
the Brain writing gap items only when the engine scores positive.

SESSION 364 — TWO TESTS REMOVED, deliberately, and the reason matters:
`trailing_director.py` was DELETED. It had been unreachable since 2026-08-06
(the gap-fill was removed for causing unbounded same-turn re-queuing — see the
note in agent_kernel._der_finalize_step), and this file's own docstring already
named the failure mode it could not prevent: "a module that is never imported
emits zero rows (the T14/T21 failure mode)".

The two removed tests asserted on that module's SOURCE:
  * test_the_trailing_director_site_is_wired        — required
    `score_surface_bool` / `"has_gaps"` / `emit_row` in trailing_director.py
  * test_the_brain_call_is_unchanged_in_shadow      — required `max_tokens=800`
    in trailing_director.py
Both are unsatisfiable once the module is gone. They were REMOVED, not
weakened: nothing about the `has_gaps` shadow MECHANISM is asserted here any
less strictly than before — the mechanism tests below are untouched.

WHAT THIS MEANS FOR AC29.1, STATED PLAINLY: `has_gaps` now has NO live scoring
site, exactly like `narration` (oracle.md 14.3). It can produce no row until a
site is wired again. That is a REQUIREMENTS state, not a test failure — it needs
a decision (wire it, e.g. onto the goal-contract open-facts path, or remove it
from CONSUMERS atomically with its pinned enumerations).
"""

from __future__ import annotations

import pytest

from backend.agent import surface_shadow as ss
from backend.agent.decision_engine import Noul


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


class TestHasGapsShadowRow:
    def test_has_gaps_shadow_row(self, rows):
        """AC29.1: a well-formed shadow row while the legacy decider decides."""
        engine = _Eng(p=0.91)
        calls = {"n": 0}

        def _brain_bool():
            calls["n"] += 1
            return True     # the Brain found gaps

        value, row = ss.surface_bool(
            "has_gaps", "step 3: summarise the findings",
            brain_bool_fn=_brain_bool, engine=engine,
        )

        assert value is True and calls["n"] == 1, (
            "the Brain's answer was not the decider — AC29.1 is shadow-only"
        )
        assert row is not None
        assert row["consumer_id"] == "has_gaps"
        assert row["shadow"] is True
        assert 0.0 <= row["probability"] <= 1.0
        assert row["brain_bool"] is True
        assert engine.seen == ["has_gaps"]

        ss.emit_row(row)
        assert rows and rows[0]["consumer_id"] == "has_gaps"

    def test_the_engine_never_writes_prose(self):
        """AC29.1: the engine supplies a bool only — the Brain writes items."""
        engine = _Eng(p=0.99)
        _value, row = ss.surface_bool(
            "has_gaps", "step 1", brain_bool_fn=lambda: True, engine=engine,
            enforced=True,     # even ENFORCED, the engine adds no prose
        )
        assert set(row) >= {"consumer_id", "chosen", "brain_bool", "shadow"}
        assert "text" not in row and "items" not in row and "prose" not in row
