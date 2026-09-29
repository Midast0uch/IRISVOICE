"""Behavioural tests: the bench reports a per-stage breakdown (REQ-30 AC30.6, T38).

AC30.6 — `scripts/bench_decision_engine.py` SHALL report the latency breakdown
(tokenize / encode / session / post) so any change is attributable to a stage.

Before T38 the bench recorded only load+warm and end-to-end wall time, so a
regression could not be blamed on a stage — only on "the engine".
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

_REPO = Path(__file__).resolve().parents[3]
_BENCH = _REPO / "scripts" / "bench_decision_engine.py"

_STAGES = ("tokenize_ms", "encode_ms", "session_ms", "post_ms")


def _bench_src() -> str:
    return _BENCH.read_text(encoding="utf-8", errors="replace")


def _bench_module():
    spec = importlib.util.spec_from_file_location("bench_decision_engine", _BENCH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestPerStageBreakdown:
    def test_per_stage_breakdown_reported(self, onnx_backend):
        """AC30.6: the backend exposes the four stages for the last call."""
        assert onnx_backend.decide(
            "tool_choice", ["alpha", "beta"], {"goal": "pick one"}) is not None

        stages = onnx_backend.stage_ms

        assert stages, "the backend exposed no per-stage breakdown"
        assert set(stages) == set(_STAGES), (
            f"the breakdown is not the four documented stages: {sorted(stages)}"
        )
        assert all(v >= 0 for v in stages.values()), stages
        assert stages["session_ms"] > 0, (
            "the session stage recorded no time — the breakdown is not real"
        )
        assert stages["encode_ms"] > 0, stages

    def test_stages_account_for_the_measured_total(self, onnx_backend):
        """The stages must be a breakdown of the call, not unrelated numbers."""
        assert onnx_backend.decide(
            "tool_choice", ["alpha", "beta"], {"goal": "pick one"}) is not None
        stages = onnx_backend.stage_ms
        total = sum(stages.values())
        assert total > 0
        # session dominates on a real model; a breakdown where it does not is
        # measuring the wrong thing.
        assert stages["session_ms"] == max(stages.values()), (
            f"session_ms is not the dominant stage on a real ONNX call: {stages}"
        )

    def test_the_bench_prints_the_breakdown(self, onnx_backend):
        """AC30.6: the bench itself reports it, not just the backend."""
        src = _bench_src()
        assert "breakdown" in src, (
            "the bench does not report a latency breakdown (AC30.6)"
        )
        assert "_stage_breakdown" in src
        assert "session options" in src, (
            "the bench does not report the effective ORT session options"
        )

        # The bench reads the stages FROM the backend, so the four documented
        # names must be the keys it prints — verified against a real call.
        bench = _bench_module()
        assert onnx_backend.decide(
            "tool_choice", ["alpha", "beta"], {"goal": "pick one"}) is not None
        stages = bench._stage_breakdown(SimpleNamespace(_backend=onnx_backend))
        assert set(stages) == set(_STAGES), (
            f"the bench would print {sorted(stages)}, not the four documented "
            f"stages {sorted(_STAGES)}"
        )
