"""The offline replay measures the question and the label the BAR measures.

scripts/replay_consumer.py is the method instrument for re-earning a consumer's
bar (docs/architecture/oracle.md section 12). Found 2026-11-09, for the yes/no
consumers (needs_action, depth_met, escalate_incomplete, tool_approval):
  * the label was brain_bool only - for needs_action the incumbent's constant
    True on 1233 of 1233 rows, so an acting "no" could never score right;
  * --variants / --options changed nothing: the d1 backend reads the yes/no
    criteria from the declaration, so every "variant" asked the live text;
  * "live" asked NO question (live_instruction returned "" for them);
  * the printed "oof_auroc" was in-sample, and no bar clause was checked.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import replay_consumer as rc  # noqa: E402


def test_the_label_is_the_outside_label_first():
    assert rc.bool_reference({"outside_label": False, "brain_bool": True}) is False
    assert rc.bool_reference({"outside_label": None, "brain_bool": True}) is True
    assert rc.bool_reference({"outside_label": True}) is True
    assert rc.bool_reference({}) is None


def test_a_variant_really_changes_the_yes_no_criteria():
    import backend.agent.decision_backend_d1 as d1mod

    live = rc.declaration_text("needs_action")
    assert live, "needs_action declares its criteria"
    orig = d1mod.declared_criteria
    with rc.bool_criteria("needs_action", "bare", live, {}):
        assert d1mod.declared_criteria("needs_action") is None
    with rc.bool_criteria("needs_action", "custom", live, {"false": "No: X"}):
        assert d1mod.declared_criteria("needs_action")["false"] == "No: X"
        assert d1mod.declared_criteria("needs_action")["true"] == live["true"]
        assert d1mod.declared_criteria("depth_met") == orig("depth_met")
    assert d1mod.declared_criteria is orig, "restored after the run"


def test_live_asks_the_live_question():
    from backend.agent.surface_shadow import SURFACE_CONSUMERS
    from backend.agent.tool_approval_shadow import TOOL_APPROVAL_INSTRUCTION

    assert rc.live_instruction("needs_action") == SURFACE_CONSUMERS["needs_action"]
    assert rc.live_instruction("tool_approval") == TOOL_APPROVAL_INSTRUCTION


def test_each_variant_gets_the_bars_verdict(capsys):
    res = [(0.6 + (i % 40) / 100.0, i % 7 != 0, "yes", "yes") for i in range(300)]
    rc.bar_verdict("needs_action", res)
    out = capsys.readouterr().out
    assert "BAR: status=" in out and "oof_auroc=" in out
