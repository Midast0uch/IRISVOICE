"""Unit test: config fallback (REQ-25 AC25.3).

A missing or malformed oracle key falls back to the code default and
logs the fallback ONCE — never crashes, never silently accepts a partial
config.
"""

from __future__ import annotations

import logging

import pytest

from backend.agent import decision_engine as de_mod
from backend.agent.decision_engine import EngineConfig, load_engine_config


class TestMissingKeyFallsBackAndLogsOnce:
    def test_missing_file_falls_back_and_logs_once(self, tmp_path, caplog, monkeypatch):
        """AC25.3: a missing config file falls back to the code default and
        logs ONCE — never crashes."""
        monkeypatch.setattr(de_mod, "_config_fallback_logged", False)
        with caplog.at_level("WARNING"):
            cfg = load_engine_config(str(tmp_path / "no-such.yaml"))
            cfg2 = load_engine_config(str(tmp_path / "no-such.yaml"))
        assert isinstance(cfg, EngineConfig)
        assert cfg.candidate_cap == 6  # the code default
        fallbacks = [
            r for r in caplog.records if "config fallback" in r.message
        ]
        assert len(fallbacks) == 1, "the fallback must log ONCE (AC25.3)"

    def test_missing_block_falls_back(self, tmp_path, monkeypatch):
        """AC25.3: a config file without an oracle block falls back."""
        monkeypatch.setattr(de_mod, "_config_fallback_logged", False)
        p = tmp_path / "cfg.yaml"
        p.write_text("models:\n  - id: other\n", encoding="utf-8")
        cfg = load_engine_config(str(p))
        assert isinstance(cfg, EngineConfig)
        assert cfg.candidate_cap == 6

    def test_malformed_key_falls_back(self, tmp_path, monkeypatch):
        """AC25.3: a malformed key falls back to the code default — never
        crashes, never silently accepts a partial config."""
        monkeypatch.setattr(de_mod, "_config_fallback_logged", False)
        p = tmp_path / "cfg.yaml"
        p.write_text(
            "models:\n"
            "  - id: oracle\n"
            "    constraints:\n"
            "      candidate_cap: not-a-number\n"
            "      backend_thresholds: broken\n",
            encoding="utf-8",
        )
        cfg = load_engine_config(str(p))
        assert cfg.candidate_cap == 6  # the code default
        assert cfg.backend_thresholds == {}  # the code default
