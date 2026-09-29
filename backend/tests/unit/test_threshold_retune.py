"""Unit test: the tool_choice threshold retune (REQ-22 AC22.1).

Three threshold sources reconciled: the box's constructor default (hardcoded
0.85, never passed), EngineConfig.default_threshold (DELETED), and the
backend-keyed backend_thresholds. The deployed operating point is 0.40.
"""

from __future__ import annotations

from backend.agent.decision_engine import EngineConfig, load_engine_config


class TestDefaultThreshold040:
    def test_default_threshold_040(self):
        """AC22.1: the deployed operating point is 0.40, keyed by the active
        backend identity — not a global 0.85."""
        cfg = load_engine_config()
        assert cfg.backend_thresholds.get("gliner25-decide-onnx-int8") == 0.40, (
            "the deployed operating point must be 0.40 for the GLiNER backend"
        )
        # The deprecated global default is GONE (T31).
        assert not hasattr(cfg, "default_threshold"), (
            "EngineConfig.default_threshold must be deleted (T31/AC22.1)"
        )

    def test_backend_keyed_resolution(self):
        """AC25.8: the threshold resolves by ACTIVE BACKEND IDENTITY."""
        cfg = EngineConfig(
            backend_id="gliner25-decide-onnx-int8",
            backend_thresholds={
                "lfm2-350m-extract": 0.85,
                "gliner25-decide-onnx-int8": 0.40,
            },
        )
        assert cfg.threshold_for("tool_choice") == 0.40
        # The retiring backend's entry is historical only.
        cfg.backend_id = "lfm2-350m-extract"
        assert cfg.threshold_for("tool_choice") == 0.85

    def test_per_consumer_override_sits_on_top(self):
        """REQ-13: explicit per-consumer overrides sit ON TOP of the backend
        threshold."""
        cfg = EngineConfig(
            backend_id="gliner25-decide-onnx-int8",
            backend_thresholds={"gliner25-decide-onnx-int8": 0.40},
            thresholds={"presentation": 0.90},
        )
        assert cfg.threshold_for("presentation") == 0.90
        assert cfg.threshold_for("tool_choice") == 0.40
