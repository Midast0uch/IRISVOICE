"""Turn-end shadow monitors never hold the reply (2026-10-01).

Measured (eval c04, backend log): at the end of a DER turn the `done` shadow
score took 4.3 s and `on_track` 1.3 s, inline, before synthesis - for rows
nothing on the answer path reads (both consumers are shadow; the Brain's bool
decides). With ``defer=True`` the Brain answers first and the Noul is scored
on the ``oracle_shadow`` lane, which emits the row (paired with the Brain's
answer) when it lands.
"""
from __future__ import annotations

import ast
import threading
from pathlib import Path

from backend.agent import monitor_shadow as ms

_KERNEL = Path(__file__).resolve().parents[2] / "agent" / "agent_kernel.py"


class _Noul:
    def __init__(self, p):
        self.probability = p
        self.engine_latency_ms = 1

    def true(self, t):
        return self.probability >= t


class _SlowEngine:
    """noul() blocks until released - a stand-in for a 4 s Oracle score."""

    def __init__(self):
        self.release = threading.Event()
        self.called = threading.Event()

    def noul(self, consumer_id, statement, frame, true_label, false_label):
        self.called.set()
        assert self.release.wait(5), "test engine never released"
        return _Noul(0.9)


def test_deferred_monitor_returns_before_the_score(monkeypatch):
    monkeypatch.setattr(ms, "register_monitor_consumers", lambda: 0)
    rows = []
    landed = threading.Event()

    def _sink(row):
        rows.append(row)
        landed.set()

    ms.set_row_sink(_sink)
    eng = _SlowEngine()
    try:
        value, text, row = ms.monitor_bool(
            "done", "is it done?", brain_bool_fn=lambda: True,
            brain_text_fn=lambda: "", engine=eng, defer=True,
        )
        # The reply has its answer while the score is still blocked.
        assert (value, text, row) == (True, "", None)
        assert not rows
        eng.release.set()
        assert landed.wait(5), "the deferred row never reached the sink"
    finally:
        ms.set_row_sink(None)
    assert rows[0]["consumer_id"] == "done"
    assert rows[0]["brain_bool"] is True, "the row keeps its Brain reference"
    assert rows[0]["shadow"] is True


def test_kernel_turn_end_monitors_defer():
    tree = ast.parse(_KERNEL.read_text(encoding="utf-8", errors="replace"))
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "monitor_bool"
    ]
    consumers = {}
    for c in calls:
        if c.args and isinstance(c.args[0], ast.Constant):
            kw = {k.arg: k.value for k in c.keywords}
            consumers[c.args[0].value] = (
                isinstance(kw.get("defer"), ast.Constant) and kw["defer"].value is True)
    assert consumers.get("done") is True, "`done` shadow score is back on the reply path"
    assert consumers.get("on_track") is True, "`on_track` shadow score is back on the reply path"
