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
    from backend.tests._kernel_source import kernel_tree
    tree = kernel_tree()
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
    # `on_track` had one site, the FULL-mode progress check, REMOVED 2026-10-01
    # (owner: its Brain call's answer was ignored). Any monitor that comes back
    # - on_track or another - must defer too.
    inline = sorted(k for k, deferred in consumers.items() if not deferred)
    assert not inline, f"shadow score(s) back on the reply path: {inline}"


# ── review_verdict, depth_route, and the monitor input size (2026-10-01) ──
# Same coding eval: review_verdict 98 inline scores (p50 586 ms, 59 s/run),
# depth_route 69 (33 s/run); done/on_track scored the Brain's whole prompt cut
# at 512 ids (done p50 2.3 s, max 4.3 s) instead of a ~200-token statement.


# test_review_verdict_scores_off_the_step_path REMOVED 2026-11-10 (owner):
# review_verdict is retired; the Reviewer scores nothing.


def test_kernel_wires_off_path_shadows():
    from backend.tests._kernel_source import kernel_tree
    tree = kernel_tree()
    attrs = {
        n.func.attr: n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    # (2026-11-10: the review_verdict and depth_route halves went with the
    # retired consumers - neither is consulted at all now; see
    # test_six_consumers_retired_contract.)
    assert "set_shadow_sink" not in attrs and "depth_route" not in attrs
    for c in ast.walk(tree):
        if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                and c.func.attr == "monitor_bool"):
            first = c.args[1] if len(c.args) > 1 else None
            assert not (isinstance(first, ast.Name) and first.id == "prompt"), (
                "a monitor scores the Brain's whole prompt again (512-id input)")


def test_monitor_statement_is_bounded():
    from types import SimpleNamespace

    from backend.agent.agent_kernel import _MONITOR_STATEMENT_CHARS, _monitor_statement

    items = [SimpleNamespace(step_number=i, description="x" * 500,
                             result="y" * 5000, envelope=None) for i in range(20)]
    s = _monitor_statement("o" * 2000, items)
    assert len(s) <= _MONITOR_STATEMENT_CHARS
    assert s.startswith("OBJECTIVE:")
