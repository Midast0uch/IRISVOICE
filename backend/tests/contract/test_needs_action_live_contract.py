"""needs_action has a live home (2026-10-13): the DIRECT/REACT question is measured and enforced.

Pins three seams: the outcome row the shadow lane writes (surface_shadow._submit_shadow), the label
rule and the enforced DIRECT branch inside AgentKernel._der_run_node (structural: read from source,
because the method is too large to drive in a unit), and the wording the engine scores.
Reason: needs_action had no live caller. Outcome labels gave 216 distinct rows, OOF AUROC 0.8043,
threshold 0.80 and precision 0.9174, so it was switched on.
"""
from __future__ import annotations

import inspect
import re

import pytest

from backend.agent import decision_engine as de
from backend.agent import surface_shadow as ss
from backend.agent.agent_kernel import AgentKernel


class _FakeNoul:
    """Minimal Noul: the probability and latency that shadow_row reads, plus true(cut)."""

    def __init__(self, probability: float):
        self.probability = probability
        self.engine_latency_ms = 5

    def true(self, cut: float) -> bool:
        return self.probability >= cut


class _InlineLane:
    """Runs the shadow job at once, so the row is ready when _submit_shadow returns."""

    def submit(self, name, job):
        job()
        return True


@pytest.fixture
def captured(monkeypatch):
    rows: list = []
    monkeypatch.setattr(ss, "score_surface_bool",
                        lambda cid, statement, **kw: _FakeNoul(0.2))
    monkeypatch.setattr(ss, "emit_row", lambda row: rows.append(row))
    import backend.utils.durability_queue as dq
    monkeypatch.setattr(dq, "lane", lambda name: _InlineLane())
    return rows


# ── (b) the outcome row ─────────────────────────────────────────────────────

def test_outcome_row_carries_the_outside_label(captured):
    ss._submit_shadow("needs_action", "Open the forms page", ss.AUTO_ENGINE, True, None,
                      "needs_action/v1", outside_label=True)
    assert len(captured) == 1
    row = captured[0]
    assert row["consumer_id"] == "needs_action"
    assert row["outside_label"] is True
    assert row["label_source"] == "outcome"
    assert row["criteria_version"] == "needs_action/v1"
    assert row["brain_bool"] is True

    captured.clear()
    ss._submit_shadow("needs_action", "Open the forms page", ss.AUTO_ENGINE, True, None,
                      "needs_action/v1", outside_label=False)
    assert len(captured) == 1
    row = captured[0]
    assert row["outside_label"] is False
    assert row["label_source"] == "outcome"
    assert row["criteria_version"] == "needs_action/v1"
    assert row["brain_bool"] is True


def test_outcome_row_without_a_label_has_no_outside_label_key(captured):
    ss._submit_shadow("needs_action", "Open the forms page", ss.AUTO_ENGINE, True, None,
                      "needs_action/v1")
    assert len(captured) == 1
    assert "outside_label" not in captured[0]
    assert "label_source" not in captured[0]


# ── (b) the label rule, read from the kernel source ─────────────────────────

def test_the_label_rule():
    """Structural guard: the outcome label expressions are inline in _der_run_node.

    Reads the source of AgentKernel._der_run_node. A call that worked labels True. No call and a
    successful step labels False. Anything else gets no row. The row is keyed to needs_action/v1.
    """
    src = inspect.getsource(AgentKernel._der_run_node)
    assert 'any(c.get("ok") for c in _calls)' in src
    assert "not _calls and result.success" in src
    assert '"needs_action/v1"' in src
    assert "outside_label=_label" in src


# ── (a) the enforced branch, read from the kernel source ────────────────────

def test_enforced_branch_moves_react_to_direct_only_when_the_oracle_acts():
    """Structural guard: the needs_action gate sits between the mode rule and the DIRECT return.

    The gate asks decides("needs_action"), then oracle_acts("needs_action", ...), and only a
    'no tool' answer (not _na.true(0.5)) sets item.mode = DIRECT. The order must be:
    mode_for_goal( < decides("needs_action") < item.mode = DIRECT < if item.mode == DIRECT:.
    """
    src = inspect.getsource(AgentKernel._der_run_node)
    assert 'decides("needs_action")' in src
    assert re.search(r'oracle_acts\(\s*"needs_action"', src)
    assert "not _na.true(0.5)" in src
    assert "item.mode = _xr_mode.DIRECT" in src

    mode_at = src.index("mode_for_goal(")
    gate_at = src.index('decides("needs_action")')
    set_at = src.index("item.mode = _xr_mode.DIRECT")
    direct_return_at = src.index("if item.mode == _xr_mode.DIRECT:")
    assert mode_at < gate_at < set_at < direct_return_at


# ── (c) the question wording and the consumer set ───────────────────────────

def test_the_question_names_the_tools():
    text = ss.SURFACE_CONSUMERS["needs_action"].lower()
    for word in ("browser", "file", "search", "command"):
        assert word in text

    decl = de.CONSUMER_DECLARATIONS["needs_action"]
    assert decl.criteria["true"].startswith("Yes:")
    assert decl.criteria["false"].startswith("No:")

    assert "needs_action" in de.CONSUMERS
    assert "use_thinking" not in de.CONSUMERS
    assert "use_thinking" not in de.CONSUMER_DECLARATIONS
    assert "use_thinking" not in ss.SURFACE_CONSUMERS
