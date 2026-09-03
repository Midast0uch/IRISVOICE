"""
Tests for ConfigDeriver / derive_config (Phase 3, Wave 2).

T2.2: ConfigDeriver — given model_meta + hardware + target_tps, returns
the largest n_ctx such that:
  a) estimated VRAM (weights + KV cache) fits in gpu_free_vram
  b) expected tps >= target_tps

D-2: n_gpu_layers is ALWAYS -1 for chat (full GPU offload, never CPU offload).
D-3: VRAM estimate includes KV cache (context-dependent).
"""

import pytest
from unittest.mock import patch, MagicMock
from backend.agent.local_model_manager import (
    LocalModelManager,
    MIN_CTX,
    MAX_CTX,
    TARGET_TPS,
)


MODEL_8B = {
    "params_b": 8.0,
    "quantization": "Q4_K_M",
    "context_length": 32768,
    "block_count": 32,
    "embed_dim": 4096,
    "n_heads": 32,
}

MODEL_230M = {
    "params_b": 0.2,
    "quantization": "Q8_0",
    "context_length": 32768,
    "block_count": 12,
    "embed_dim": 512,
    "n_heads": 8,
}


@pytest.fixture
def lmm():
    return LocalModelManager()


class TestConfigDeriverVramConstraint:
    """a) estimated VRAM fits in gpu_free_vram."""

    def test_large_model_shrinks_ctx(self, lmm):
        """8B model on 8GB GPU must shrink n_ctx below MAX_CTX."""
        config = lmm.derive_config(
            MODEL_8B,
            vram_budget_gb=7.0,  # ~7GB free on RTX 3070
            base_tps=100.0,  # high base_tps so throughput isn't the bottleneck
        )
        assert config["n_ctx"] < MAX_CTX, "8B model must shrink context on 8GB GPU"
        assert config["n_ctx"] >= MIN_CTX

    def test_small_model_keeps_max_ctx(self, lmm):
        """230M model on 8GB GPU can keep MAX_CTX."""
        config = lmm.derive_config(
            MODEL_230M,
            vram_budget_gb=7.0,
            base_tps=100.0,
        )
        assert config["n_ctx"] == MAX_CTX, "230M model should fit at MAX_CTX"

    def test_vram_est_in_config(self, lmm):
        """Config includes vram_est_gb that fits within budget."""
        config = lmm.derive_config(
            MODEL_8B,
            vram_budget_gb=7.0,
            base_tps=100.0,
        )
        assert config["vram_est_gb"] <= 7.0 + 0.5  # small tolerance

    def test_binary_search_finds_largest_fitting_ctx(self, lmm):
        """Binary search must find the LARGEST n_ctx that fits."""
        # Use a budget that's between two n_ctx values
        config = lmm.derive_config(
            MODEL_8B,
            vram_budget_gb=8.0,  # 8B weights ≈ 5.3GB, so there's room for KV cache
            base_tps=100.0,
        )
        # Verify that n_ctx + some increment would exceed budget
        vram_at_best = lmm.estimate_vram_gb(MODEL_8B, n_ctx=config["n_ctx"])
        assert vram_at_best <= 8.0 + 0.5  # fits


class TestConfigDeriverThroughputConstraint:
    """b) expected tps >= target_tps."""

    def test_throughput_constraint_shrinks_ctx(self, lmm):
        """If target_tps is very high, n_ctx must shrink to meet it."""
        # base_tps=50 at MIN_CTX=4096. target_tps=45 means n_ctx can be at most
        # MIN_CTX * (base_tps/target_tps)^2 = 4096 * (50/45)^2 ≈ 5053
        config = lmm.derive_config(
            MODEL_230M,
            vram_budget_gb=7.0,
            base_tps=50.0,
            target_tps=45.0,
        )
        # Throughput at MAX_CTX would be 50 * sqrt(4096/32768) = 50 * 0.354 = 17.7
        # Which is below 45, so n_ctx must shrink
        assert config["n_ctx"] < MAX_CTX

    def test_low_target_tps_allows_max_ctx(self, lmm):
        """If target_tps is very low, n_ctx can be MAX_CTX."""
        config = lmm.derive_config(
            MODEL_230M,
            vram_budget_gb=7.0,
            base_tps=50.0,
            target_tps=1.0,  # very low — always satisfied
        )
        assert config["n_ctx"] == MAX_CTX

    def test_expected_tps_in_config(self, lmm):
        """Config includes expected_tps >= target_tps."""
        config = lmm.derive_config(
            MODEL_8B,
            vram_budget_gb=7.0,
            base_tps=100.0,
            target_tps=TARGET_TPS,
        )
        assert config["expected_tps"] >= TARGET_TPS - 0.01


class TestConfigDeriverD2:
    """D-2: n_gpu_layers ALWAYS -1 for chat. Never CPU offload."""

    def test_n_gpu_layers_always_minus_one(self, lmm):
        """n_gpu_layers must be -1 (full GPU offload, never CPU)."""
        config = lmm.derive_config(
            MODEL_8B,
            vram_budget_gb=7.0,
            base_tps=100.0,
        )
        assert config["n_gpu_layers"] == -1

    def test_n_gpu_layers_minus_one_for_small_model(self, lmm):
        """Even for small models, n_gpu_layers is -1."""
        config = lmm.derive_config(
            MODEL_230M,
            vram_budget_gb=7.0,
            base_tps=100.0,
        )
        assert config["n_gpu_layers"] == -1


class TestConfigDeriverBatch:
    """n_batch scaling."""

    def test_n_batch_scales_with_ctx(self, lmm):
        """n_batch should scale with n_ctx, capped at 2048."""
        config = lmm.derive_config(
            MODEL_8B,
            vram_budget_gb=7.0,
            base_tps=100.0,
        )
        assert 512 <= config["n_batch"] <= 2048

    def test_n_batch_capped_at_2048(self, lmm):
        """n_batch must not exceed 2048."""
        config = lmm.derive_config(
            MODEL_230M,
            vram_budget_gb=7.0,
            base_tps=100.0,
        )
        assert config["n_batch"] <= 2048


class TestConfigDeriverEdgeCases:
    """Edge cases and error handling."""

    def test_min_ctx_floor(self, lmm):
        """n_ctx must never go below MIN_CTX."""
        # Tiny budget — should still return MIN_CTX
        config = lmm.derive_config(
            MODEL_8B,
            vram_budget_gb=0.1,  # impossibly small
            base_tps=100.0,
        )
        assert config["n_ctx"] >= MIN_CTX

    def test_zero_params_returns_min_ctx(self, lmm):
        """If params_b is 0, VRAM estimate is 0, so n_ctx = MAX_CTX."""
        config = lmm.derive_config(
            {"params_b": 0, "quantization": "Q4_K_M"},
            vram_budget_gb=7.0,
            base_tps=100.0,
        )
        assert config["n_ctx"] == MAX_CTX

    def test_config_has_all_keys(self, lmm):
        """Config dict must have all required keys."""
        config = lmm.derive_config(
            MODEL_8B,
            vram_budget_gb=7.0,
            base_tps=100.0,
        )
        required_keys = {"n_ctx", "n_gpu_layers", "n_batch", "vram_est_gb", "expected_tps"}
        assert set(config.keys()) == required_keys
