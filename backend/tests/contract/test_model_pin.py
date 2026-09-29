"""Contract tests: the model pin on calibration rows (REQ-6 AC6.5, T27).

AC6.5 — record `model_id` + file hash on calibration rows and assert identity at
load, so a model swap is DETECTABLE instead of silently invalidating every
threshold measured on the previous model.

This is the guard behind REQ-22 AC22.1 (thresholds are distribution-specific)
and REQ-31 AC31.4 (a moved configuration marks thresholds stale).
"""

from __future__ import annotations

import re

import pytest

from backend.agent.decision_backend_onnx import GlinerOnnx
from backend.agent.decision_engine import (
    DecisionEngine,
    EngineConfig,
    load_engine_config,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class TestModelIdentity:
    def test_model_identity_matches_calibration_rows(self, onnx_backend):
        """AC6.5: the hash on the loaded backend is a real file digest, and the
        ENGINE reports the SAME identity a calibration row would record."""
        digest = onnx_backend.model_hash

        assert digest, "the backend exposed no model hash"
        assert _HEX64.match(digest), (
            f"the model hash is not a sha256 hex digest: {digest!r}"
        )

        # The engine's identity is only real AFTER a decision — the backend
        # load is lazy, and a hash before load is None by design.
        eng = DecisionEngine(load_engine_config())
        if eng.decide("tool_choice", ["alpha", "beta"], {"goal": "pin"}) is None:
            pytest.skip("engine could not score — identity unavailable")
        assert eng.model_hash == digest, (
            "the engine's model identity differs from the deployed backend's — "
            "a calibration row could not be attributed to the right model"
        )
        eng.shutdown()

    def test_the_backend_identity_is_variant_derived(self, onnx_backend):
        """The backend id names the deployed VARIANT, so an int8/fp16 swap is
        distinguishable (AC21.7/AC22.5)."""
        assert onnx_backend.backend_id
        assert "onnx" in onnx_backend.backend_id, onnx_backend.backend_id
        # the variant is part of the identity, not a separate field nobody reads
        assert (
            "int8" in onnx_backend.backend_id
            or "fp16" in onnx_backend.backend_id
            or "fp32" in onnx_backend.backend_id
        ), onnx_backend.backend_id

    def test_no_hash_before_load(self):
        """A hash before load must be None, never a placeholder — a fabricated
        identity would make a swap undetectable."""
        assert GlinerOnnx().model_hash is None

    def test_the_threshold_is_keyed_by_the_backend_identity(self):
        """AC6.5 + AC25.8: the calibration row's identity is the SAME key the
        threshold resolves against, or the pin would not protect anything."""
        cfg = load_engine_config()
        assert cfg.backend_thresholds, "no backend-keyed thresholds parsed"

        cfg.backend_id = "gliner25-decide-onnx-int8"
        assert cfg.threshold_for("tool_choice") == 0.40

        # An UNKNOWN backend refuses (fail-closed) rather than reusing a curve.
        cfg.backend_id = "some-future-model"
        assert cfg.threshold_for("tool_choice") is None, (
            "an unregistered backend inherited another model's threshold"
        )

    def test_a_config_with_no_backend_id_refuses(self):
        """No active identity → no threshold. Fail-closed by construction."""
        cfg = EngineConfig()
        cfg.backend_id = None
        assert cfg.threshold_for("tool_choice") is None

    def test_engine_exposes_the_effective_backend_id(self, onnx_backend):
        """The effective configuration reports the active backend so a
        calibration run can attribute its rows (AC25.2/AC6.5)."""
        eng = DecisionEngine(load_engine_config())
        if eng.decide("tool_choice", ["alpha", "beta"], {"goal": "pin"}) is None:
            pytest.skip("engine could not score — identity unavailable")

        effective = eng.effective_config()
        assert "backend_id" in effective
        assert effective["backend_id"] is not None
        assert effective["backend_id"] == onnx_backend.backend_id, (
            "the effective configuration names a different backend than the "
            "one actually loaded"
        )
        eng.shutdown()
