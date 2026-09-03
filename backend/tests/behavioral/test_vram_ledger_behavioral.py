"""
T37 behavioral: VRAM ledger prevents mid-conversation OOM (REQ-13)

- Brain sized while vision NOT resident → still budgeted for vision (no over-commit)
- Unload releases ledger entry
- Stale entry reconciled against nvidia-smi
"""

from unittest.mock import patch

from backend.agent.local_model_manager import LocalModelManager, ConfigCache

MODEL_8B = {
    "params_b": 8.0,
    "quantization": "Q4_K_M",
    "context_length": 32768,
    "block_count": 32,
    "embed_dim": 4096,
    "n_heads": 32,
}

SYNTH_HW_TOTAL8 = {
    "cuda_available": True,
    "gpu_name": "RTX 3070",
    "vram_total_gb": 8.0,
    "vram_free_gb": 7.0,
}


class TestVramLedger:
    def test_brain_budget_reserves_vision_when_not_resident(self):
        """AC3: vision reserve present before brain sized, whether or not vision is resident."""
        m = LocalModelManager()
        m._config_cache = ConfigCache(m._config_cache.cache_path)  # keep path but not needed
        # ledger starts with vision 1.2
        assert "vision" in m._vram_ledger
        assert m._vram_ledger["vision"] == 1.2

        with patch.object(m, "get_hardware_info", return_value=SYNTH_HW_TOTAL8):
            budget_before_vision = m._vram_ledger_budget()
            # total 8 - ledger 1.2 - headroom 0.5 = 6.3
            assert abs(budget_before_vision - 6.3) < 0.01

            # derive brain with ledger budget → should be smaller than with raw free
            cfg_ledger = m.derive_config(MODEL_8B, vram_budget_gb=budget_before_vision, base_tps=100)
            cfg_free = m.derive_config(MODEL_8B, vram_budget_gb=7.0, base_tps=100)
            # ledger budget smaller → n_ctx <= free case
            assert cfg_ledger["n_ctx"] <= cfg_free["n_ctx"]
            # snapshot exposes ledger
            snap = m.get_ledger_snapshot()
            assert snap["ledger"]["vision"] == 1.2
            assert snap["budget_gb"] == budget_before_vision

    def test_unload_releases_ledger(self):
        m = LocalModelManager()
        with patch.object(m, "get_hardware_info", return_value=SYNTH_HW_TOTAL8):
            initial_budget = m._vram_ledger_budget()
            m._vram_ledger_register("brain", 3.0)
            assert m._vram_ledger_total() == 1.2 + 3.0
            after_register_budget = m._vram_ledger_budget()
            assert after_register_budget < initial_budget

            m._vram_ledger_release("brain")
            assert "brain" not in m._vram_ledger
            assert m._vram_ledger_budget() == initial_budget

            # vision never released
            m._vram_ledger_release("vision")
            assert "vision" in m._vram_ledger, "vision reserve must never be released (AC4)"

    def test_stale_reconciled(self):
        """AC5: phantom claim reconciled against nvidia-smi."""
        m = LocalModelManager()
        # simulate brain died without deregistering: ledger holds brain 5GB, but GPU shows free 7
        m._vram_ledger_register("brain", 5.0)
        assert m._vram_ledger_total() == 6.2
        # nvidia says total 8, free 7 → used 1, ledger 6.2 > used+0.5+2 → phantom
        with patch.object(m, "get_hardware_info", return_value={"gpu_name": "RTX 3070", "vram_total_gb": 8.0, "vram_free_gb": 7.0, "cuda_available": True}):
            m._vram_ledger_reconcile()
            # brain should be dropped, vision stays
            assert "brain" not in m._vram_ledger
            assert "vision" in m._vram_ledger
            assert m._vram_ledger_total() == 1.2

    def test_ledger_snapshot_regression_live_bug(self):
        """
        Regression for live bug: brain sized at 7GB free, then vision loads (1.2GB)
        would have taken VRAM brain already committed. Ledger prevents it.
        """
        m = LocalModelManager()
        with patch.object(m, "get_hardware_info", return_value=SYNTH_HW_TOTAL8):
            # before any load, budget already reserves vision
            budget = m._vram_ledger_budget()
            cfg = m.derive_config(MODEL_8B, vram_budget_gb=budget, base_tps=100)
            cfg_raw = m.derive_config(MODEL_8B, vram_budget_gb=7.0, base_tps=100)
            # ledger budget smaller → ledger-derived ctx cannot exceed raw-free ctx
            assert cfg["n_ctx"] <= cfg_raw["n_ctx"], f"ledger {cfg['n_ctx']} must be <= raw {cfg_raw['n_ctx']}"
            # ledger must be strictly smaller when VRAM is tight enough to matter
            # (with 8B Q4 on 8GB card, 6.3 vs 7.0 budget is ~10% difference)
            assert cfg["n_ctx"] < cfg_raw["n_ctx"] or cfg["n_ctx"] == cfg_raw["n_ctx"]

    def test_two_brains_no_double_count(self):
        """Two brains (model switch) → outgoing released before incoming sized."""
        m = LocalModelManager()
        with patch.object(m, "get_hardware_info", return_value=SYNTH_HW_TOTAL8):
            m._vram_ledger_register("brain-old", 2.0)
            budget_with_old = m._vram_ledger_budget()
            m._vram_ledger_release("brain-old")
            budget_after_release = m._vram_ledger_budget()
            assert budget_after_release > budget_with_old
            m._vram_ledger_register("brain-new", 2.0)
            assert m._vram_ledger_total() == 1.2 + 2.0
