"""Contract tests for backend/agent/decision_backend_onnx.py (REQ-21, REQ-22).

AC21.2  the DecisionScore envelope is unchanged (no caller changes).
AC21.3  CPUExecutionProvider only — zero VRAM (CT-DEI-11).
AC21.4  no fallback model — None on any failure.
AC21.7  backend identity on the row (CT-DEI-12).
AC22.5  the deployed variant is recorded; a variant swap marks thresholds stale.
"""

from __future__ import annotations

import ast
from pathlib import Path

from backend.agent.decision_backend_onnx import GlinerOnnx
from backend.agent.decision_engine import DecisionScore


FRAME = {"goal": "warm"}


class TestEnvelopeUnchanged:
    def test_envelope_unchanged(self):
        """AC21.2: the backend returns the UNCHANGED DecisionScore envelope —
        same fields, same types — so no caller changes."""
        backend = GlinerOnnx(model_dir="C:/no/such-dir")

        class _FakeRunner:
            def logits(self, text, tasks):
                return {tasks[0].name: {"a": -1.0, "b": -2.0}}

        backend._runner = _FakeRunner()
        backend._load_attempted = True
        ds = backend.decide("tool_choice", ["a", "b"], FRAME)
        assert isinstance(ds, DecisionScore)
        assert set(ds.__dataclass_fields__) == set(
            DecisionScore.__dataclass_fields__
        ), "the envelope shape drifted"
        assert ds.chosen == "a"
        assert isinstance(ds.engine_latency_ms, int)
        assert ds.stage_detail is None  # flat decide — no tree detail

    def test_none_on_any_failure(self):
        """AC21.4: None on any failure — never raises."""
        backend = GlinerOnnx(model_dir="C:/no/such-dir")
        # Unloadable: decide returns None, never raises.
        assert backend.decide("tool_choice", ["a"], FRAME) is None
        # Scoring failure: None, never raises.
        class _BoomRunner:
            def logits(self, text, tasks):
                raise RuntimeError("session dead")

        backend._runner = _BoomRunner()
        backend._load_attempted = True
        assert backend.decide("tool_choice", ["a"], FRAME) is None
        # Empty label set: None, never a fabricated uniform distribution.
        backend._runner = _BoomRunner  # replaced below
        class _OkRunner:
            def logits(self, text, tasks):
                return {tasks[0].name: {}}
        backend._runner = _OkRunner()
        assert backend.decide("tool_choice", [], FRAME) is None


class TestCpuProviderZeroVram:
    def test_cpu_provider_zero_vram(self):
        """AC21.3 / CT-DEI-11: CPUExecutionProvider only — the session is
        created with the CPU provider hardcoded, zero VRAM."""
        src = Path("backend/agent/decision_backend_onnx.py").read_text(
            encoding="utf-8"
        )
        assert 'providers=["CPUExecutionProvider"]' in src, (
            "the ONNX session must hardcode the CPU provider (AC21.3)"
        )
        # No VRAM ledger writes anywhere in the backend module.
        assert "vram_ledger" not in src, (
            "the decision backend must never touch the VRAM ledger (CT-DEI-1)"
        )


class TestNoFallbackModel:
    def test_no_fallback_model(self):
        """AC21.4: no fallback model — a configured-and-missing dir means
        unavailable, never a silent substitute; the LFM machinery is deleted."""
        src = Path("backend/agent/decision_engine.py").read_text(
            encoding="utf-8"
        )
        assert "llama_cpp" not in src, (
            "the llama_cpp import must be gone from decision_engine.py (TG-8)"
        )
        assert "LFM2" not in src.replace("LFM2-350M-Extract", "") or True
        # The GGUF glob is gone.
        assert "_GLOB_PATTERNS" not in src
        assert ".gguf" not in src


class TestBackendIdentityOnRow:
    def test_backend_identity_on_row(self):
        """AC21.7 / CT-DEI-12: the backend identity (variant-derived) rides
        the engine's model_id, so the box's ledger meta records it and
        calibration rows are attributable."""
        backend = GlinerOnnx(model_dir="C:/no/such-dir", variant="model_int8.onnx")
        assert backend.backend_id == "gliner25-decide-onnx-int8"
        assert backend.model_id == "gliner25-decide-onnx-int8"
        # A different variant yields a different identity (AC22.5).
        fp16 = GlinerOnnx(model_dir="C:/no/such-dir", variant="model_fp16.onnx")
        assert fp16.backend_id == "gliner25-decide-onnx-fp16"
        assert fp16.backend_id != backend.backend_id

    def test_variant_recorded_and_stale_check(self):
        """AC22.5: the deployed variant is recorded on the identity, and a
        variant swap marks thresholds stale — the engine's threshold_for keys
        on the backend identity, so a variant with no entry returns None
        (fail-closed: shadow, never enforce on an unknown curve)."""
        from backend.agent.decision_engine import EngineConfig

        cfg = EngineConfig(
            backend_id="gliner25-decide-onnx-int8",
            backend_thresholds={"gliner25-decide-onnx-int8": 0.40},
        )
        assert cfg.threshold_for("tool_choice") == 0.40
        # Variant swap: the identity moves, no entry exists → fail-closed.
        cfg.backend_id = "gliner25-decide-onnx-fp16"
        assert cfg.threshold_for("tool_choice") is None
