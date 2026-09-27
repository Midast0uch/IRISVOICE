"""Contract tests: config authority (REQ-25, CT-DEI-16) — the oracle
block parsed into EngineConfig, the effective configuration observable, and
backend-keyed thresholds fail-closed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import yaml

from backend.agent.decision_engine import (
    EngineConfig,
    load_engine_config,
)


class TestYamlParsedIntoEngineConfig:
    def test_yaml_parsed_into_engineconfig(self):
        """AC25.1 / CT-DEI-16: the oracle block is parsed into
        EngineConfig — the block is LIVE, not decorative."""
        cfg = load_engine_config()
        assert isinstance(cfg, EngineConfig)
        # The block's values actually landed (a non-default round-trip).
        assert cfg.candidate_cap == 6, (
            f"candidate_cap did not round-trip: {cfg.candidate_cap}"
        )
        assert cfg.acquire_timeout_s == 2.0
        assert cfg.backend_thresholds.get("gliner25-decide-onnx-int8") == 0.40

    def test_effective_config_observable(self):
        """AC25.2: the effective configuration is observable — the engine
        exposes the resolved config, backend identity included."""
        from backend.agent.decision_engine import DecisionEngine

        e = DecisionEngine(config=EngineConfig(candidate_cap=9))
        eff = e.effective_config()
        assert eff["candidate_cap"] == 9, "a non-default cap is not observable"
        assert "backend_id" in eff and "backend_thresholds" in eff

    def test_no_unread_keys_in_block(self):
        """AC25.6: every key in the oracle block is parsed or
        removed — a documented value that does not change behaviour is a
        defect. The parser reads: path, candidate_cap, acquire_timeout_s,
        backend_thresholds, thresholds. Nothing else may remain in
        constraints."""
        src = Path("backend/agent/agent_config.yaml").read_text(encoding="utf-8")
        data = yaml.safe_load(src) or {}
        block = None
        for m in data.get("models", []) or []:
            if isinstance(m, dict) and m.get("id") == "oracle":
                block = m
                break
        assert block is not None, "oracle block not found"
        constraints = block.get("constraints") or {}
        parsed_keys = {
            "candidate_cap", "acquire_timeout_s", "backend_thresholds",
            "thresholds",
        }
        extra = set(constraints) - parsed_keys
        assert not extra, (
            f"documented-but-unread keys remain in the block: {extra}"
        )
        # The deprecated default_threshold is GONE (T31).
        assert "default_threshold" not in constraints

    def test_shipped_cap_equals_calibrated_width(self):
        """AC25.7 (Decision C): the SHIPPED candidate_cap equals the menu
        width the current threshold curve was derived at (6)."""
        cfg = load_engine_config()
        assert cfg.candidate_cap == 6, (
            "the shipped cap must equal the calibrated width (Decision C)"
        )

    def test_threshold_keyed_by_active_backend_fail_closed(self):
        """AC25.8: thresholds are keyed by BACKEND IDENTITY and enforcement
        is REFUSED when the active backend has no entry (fail-closed)."""
        cfg = load_engine_config()
        # The deployed backend has an entry.
        assert cfg.backend_thresholds, "no backend_thresholds entries"
        # An unknown active backend → None → fail-closed (shadow).
        unknown = EngineConfig(
            backend_id="no-such-backend",
            backend_thresholds=cfg.backend_thresholds,
        )
        assert unknown.threshold_for("tool_choice") is None
        # The known backend resolves.
        known = EngineConfig(
            backend_id="gliner25-decide-onnx-int8",
            backend_thresholds=cfg.backend_thresholds,
        )
        assert known.threshold_for("tool_choice") == 0.40
