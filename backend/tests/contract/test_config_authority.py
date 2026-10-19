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
        # STALE-BY-SPEC update (2026-10-18): the cap is 32 (CANDIDATE_CAP_
        # DEFAULT; up to 30 real tools plus DELEGATE and NONE - oracle.md
        # 3.8). The 6 here was the pre-32 era's calibrated width.
        assert cfg.candidate_cap == 32, (
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
        width the current threshold curve was derived at. STALE-BY-SPEC
        update (2026-10-18): that width is 32 (CANDIDATE_CAP_DEFAULT,
        oracle.md 3.8); the 6 here was the pre-32 era."""
        cfg = load_engine_config()
        assert cfg.candidate_cap == 32, (
            "the shipped cap must equal the calibrated width (Decision C)"
        )

    def test_threshold_keyed_by_active_backend_fail_closed(self):
        """AC25.8: thresholds are keyed by the FULL BACKEND IDENTITY
        (model|readout|criteria_hash, since Wave 3) and enforcement is
        REFUSED when the active identity has no entry (fail-closed).
        STALE-BY-SPEC update (2026-10-18): the yaml's BARE model-id entries
        are historical (retired backends) and never resolve - the live
        thresholds come from the fitted calibration file (oracle.md 3.6)."""
        import backend.agent.decision_engine as de

        cfg = load_engine_config()
        # The deployed block has entries.
        assert cfg.backend_thresholds, "no backend_thresholds entries"
        # An unknown active backend -> None -> fail-closed (shadow).
        unknown = EngineConfig(
            backend_id="no-such-backend",
            backend_thresholds=cfg.backend_thresholds,
        )
        assert unknown.threshold_for("tool_choice") is None
        # The yaml's BARE model-id keys are historical and do NOT resolve
        # (a bare model id is no longer a key - fail-closed by design).
        bare = EngineConfig(
            backend_id="gliner25-decide-onnx-int8",
            backend_thresholds=cfg.backend_thresholds,
        )
        assert bare.threshold_for("tool_choice") is None
        # An entry keyed by the COMPOSED identity resolves.
        gliner = de.decision_identity(
            "gliner25-decide-onnx-int8", de.CURRENT_READOUT_MODE, "tool_choice")
        known = EngineConfig(
            backend_id="gliner25-decide-onnx-int8",
            backend_thresholds={gliner: 0.40},
        )
        assert known.threshold_for("tool_choice") == 0.40

