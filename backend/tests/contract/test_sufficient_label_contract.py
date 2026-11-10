"""The `sufficient` consumer runs again and is labelled by the turn verdict
(2026-11-10).

Its gate tested `item.tool`, which a node step never has (since 2026-09-29),
so the gate and its consumer never ran again (last row 2026-09-29). And its
rows were parity rows against the Brain. Now: the gate reads what the step
DID (`_step_calls`); a row is held for the turn verdict only when the Brain
said "enough" (the loop then went straight to synthesis, so the verdict tests
that judgment); after "not enough" the loop grafted, so the row keeps no
reference.

Each guard FAILS on the old code: the gate tested item.tool, and the row
was emitted at once with the Brain's answer as its reference.
"""
from __future__ import annotations

from pathlib import Path

from backend.agent import monitor_shadow as ms
from backend.agent import turn_verdict_label as tvl

_KERNEL = Path(__file__).resolve().parents[2] / "agent" / "agent_kernel.py"


class _Noul:
    probability = 0.8
    engine_latency_ms = 5

    def true(self, cut: float = 0.5) -> bool:
        return self.probability >= cut


class _Lane:
    def submit(self, name, job):
        job()
        return True


def _run(monkeypatch, brain: bool):
    import backend.utils.durability_queue as dq

    monkeypatch.setattr(dq, "lane", lambda _n: _Lane())
    monkeypatch.setattr(ms, "score_monitor_bool", lambda *a, **k: _Noul())
    monkeypatch.setattr(ms, "_scope_now", lambda: {"turn_id": "tS"})
    written: list = []
    monkeypatch.setattr(ms, "emit_row", lambda r: written.append(r) if r else None)
    tvl.reset()
    value, _text = ms.sufficiency_gate(
        "the gathered findings", brain_bool_fn=lambda: brain,
        brain_text_fn=lambda: "", engine=object(), defer=True)
    assert value is brain
    return written


def test_the_gate_reads_what_the_step_did_not_item_tool():
    src = _KERNEL.read_text(encoding="utf-8", errors="replace")
    assert 'if (getattr(item, "tool", None) or "").lower() in self._DER_GATHER_TOOLS:' not in src
    assert "for c in _step_calls(item)):" in src


def test_enough_is_held_for_the_turn_verdict(monkeypatch):
    written = _run(monkeypatch, brain=True)
    assert written == [], "the row waits for the verdict - never parity"
    assert tvl.report_verdict("tS", passed=False) == 1
    (row,) = written
    assert row["outside_label"] is False and row["brain_bool"] is None
    assert row["brain_said"] is True
    assert row["criteria_version"] == "sufficient/verdict-v1"
    tvl.reset()


def test_not_enough_keeps_no_reference(monkeypatch):
    written = _run(monkeypatch, brain=False)
    (row,) = written
    assert row["brain_bool"] is None and row.get("outside_label") is None
    assert row["brain_said"] is False
    tvl.reset()
