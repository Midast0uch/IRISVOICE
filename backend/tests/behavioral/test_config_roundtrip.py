"""Behavioral test: the config round-trip (REQ-25 AC25.4/AC25.5, BT-DEI-16).

AC25.4  a non-default cap is effective in the menu width.
AC25.5  a cap change marks the calibrated threshold STALE.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.agent.decision_engine import (
    CandidateScore,
    DecisionScore,
    EngineConfig,
    EngineCounters,
)
from backend.agent.tool_decision import ToolDecisionBox

# Oracle Stage B (2026-10-05): the stand-in engine decides only through the real
# enforcement chokepoint; see conftest.oracle_decides_module.
ORACLE_DECIDES = ("tool_choice",)


class _WidthEngine:
    """Records the menu width it was handed."""

    def __init__(self, cap):
        self.model_id = "width-stub"
        self.counters = EngineCounters()
        self._cfg = SimpleNamespace(candidate_cap=cap)
        self.widths = []

    def decide(self, consumer_id, options, frame):
        self.widths.append(len(options))
        return DecisionScore(
            consumer_id=consumer_id, chosen="NONE", confidence=0.9,
            distribution=tuple(CandidateScore(o, -0.1, 0.9) for o in options),
            engine_latency_ms=1,
        )


REGISTRY = [
    {"name": n, "description": f"{n} d", "category": "misc"}
    for n in (
        "read_file", "list_directory", "get_system_info", "recall_memory",
        "speak", "ask_user_question", "create_skill", "improve_self",
        "combine_documents", "transcribe_media",
    )
]


def _resolve(engine):
    box = ToolDecisionBox(
        router=SimpleNamespace(),
        tool_bridge=SimpleNamespace(),
        get_available_tools=lambda: REGISTRY,
        validate_tool_call=lambda t, p: (True, None),
        decision_engine=engine,
    )
    box.resolve(
        {"description": "do a thing", "task_class": "full"},
        session_id="s1", conversation_id="c1",
    )
    return engine.widths[0] if engine.widths else None


@pytest.mark.usefixtures("oracle_decides_module")
class TestCapEffectiveInMenuWidth:
    def test_cap_effective_in_menu_width(self):
        """AC25.4 / BT-DEI-16: a non-default cap is EFFECTIVE in the menu
        width — the config round-trips into the composed menu."""
        assert _resolve(_WidthEngine(cap=4)) == 4, (
            "a non-default cap did not round-trip into the menu width"
        )
        assert _resolve(_WidthEngine(cap=9)) == 9

    def test_shipped_cap_six(self):
        """The shipped cap (6) is effective: the menu is 6 wide, both control
        labels included (AC21.8 shape)."""
        assert _resolve(_WidthEngine(cap=6)) == 6


class TestCapChangeMarksThresholdStale:
    def test_cap_change_marks_threshold_stale(self):
        """AC25.5 / BT-DEI-16: a cap change marks the calibrated threshold
        STALE — threshold_for returns None (fail-closed) and enforcement is
        refused until the curve is re-derived."""
        from backend.agent.decision_engine import EngineConfig

        # The calibrated configuration: cap 6 = the calibrated width.
        calibrated = EngineConfig(
            backend_id="gliner25-decide-onnx-int8",
            backend_thresholds={"gliner25-decide-onnx-int8": 0.40},
            candidate_cap=6,
            calibrated_cap=6,
        )
        assert calibrated.threshold_stale() is False
        assert calibrated.threshold_for("tool_choice") == 0.40
        # The cap MOVED: the threshold is STALE — fail-closed, no enforcement
        # on a curve measured at a different width.
        moved = EngineConfig(
            backend_id="gliner25-decide-onnx-int8",
            backend_thresholds={"gliner25-decide-onnx-int8": 0.40},
            candidate_cap=32,
            calibrated_cap=6,
        )
        assert moved.threshold_stale() is True
        assert moved.threshold_for("tool_choice") is None
        assert moved.threshold_for("presentation") is None


# ── REQ-31 AC31.4 (T50) ────────────────────────────────────────────────────


class TestStaleRefusesEnforcement:
    def test_stale_refuses_enforcement(self, monkeypatch, tmp_path):
        """AC31.4: a deployed configuration that differs from the calibrated
        one marks thresholds STALE and refuses enforcement at the SOURCE.

        Stage B (2026-10-05) setup change, assertions unchanged: enforcement now
        needs ALL FOUR keys, so the owner switch, the earned bar and a fitted
        threshold are provided through tmp files, and the ONLY thing that varies
        between (a) and (b) is the configuration's staleness (the real check, not
        a patched one). `has_gaps` (a removed consumer) became `depth_met`."""
        import json

        import backend.agent.decision_engine as de_mod
        from backend.agent import consumer_bar, oracle_calibration
        from backend.agent.decision_engine import (
            EngineConfig,
            enforced_consumers,
        )

        engine_id = "gliner25-decide-onnx-int8"
        _cons = ("tool_choice", "depth_met")
        (tmp_path / "bar.json").write_text(json.dumps({
            c: {"consumer_id": c, "rows": 120, "precision": 0.95, "ece": 0.01,
                "status": "enforced", "gap": "", "config": {"backend_id": engine_id}}
            for c in _cons}), encoding="utf-8")
        (tmp_path / "cal.json").write_text(json.dumps({engine_id: {
            c: {"knots": [[0.5, 0.5], [1.0, 1.0]], "threshold": 0.85}
            for c in _cons}}), encoding="utf-8")
        monkeypatch.setattr(consumer_bar, "BAR_PATH", tmp_path / "bar.json")
        monkeypatch.setattr(oracle_calibration, "CALIBRATION_PATH", tmp_path / "cal.json")
        oracle_calibration._CACHE.clear()
        monkeypatch.setattr(de_mod, "_current_backend_identity", lambda: engine_id)
        monkeypatch.setenv("IRIS_DECISION_ENFORCE", "tool_choice,depth_met")

        # (a) calibrated configuration → enforcement proceeds.
        fresh = EngineConfig()
        fresh.backend_id = "gliner25-decide-onnx-int8"
        monkeypatch.setattr(
            de_mod, "get_decision_engine",
            lambda: SimpleNamespace(_cfg=fresh),
        )
        assert enforced_consumers() == frozenset({"tool_choice", "depth_met"})

        # (b) the cap MOVED → no consumer may be enforced on the old curve.
        stale = EngineConfig(candidate_cap=10)     # calibrated width is 6
        stale.backend_id = "gliner25-decide-onnx-int8"
        monkeypatch.setattr(
            de_mod, "get_decision_engine",
            lambda: SimpleNamespace(_cfg=stale),
        )
        assert enforced_consumers() == frozenset(), (
            "a stale configuration still enforced consumers — a flip measured "
            "at a superseded curve can stand (AC31.4/AC31.6)"
        )
