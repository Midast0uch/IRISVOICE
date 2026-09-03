"""
Tests for estimate_vram_gb including KV cache (Phase 3, Wave 2).

D-3: VRAM estimate must include KV cache (context-dependent, not weights-only).

REQ-2 AC1: THE SYSTEM SHALL estimate VRAM as weights + KV cache, where
KV cache = 2 × n_layers × n_ctx × hidden_size × 2 bytes (fp16).
"""

import pytest
from backend.agent.local_model_manager import LocalModelManager, MIN_CTX


@pytest.fixture
def lmm():
    return LocalModelManager()


# ── Test model metadata fixtures ──

MODEL_8B = {
    "params_b": 8.0,
    "quantization": "Q4_K_M",
    "context_length": 32768,
    "block_count": 32,
    "embed_dim": 4096,
    "n_heads": 32,
}

MODEL_1B = {
    "params_b": 1.0,
    "quantization": "Q4_K_M",
    "context_length": 4096,
    "block_count": 16,
    "embed_dim": 1024,
    "n_heads": 16,
}

MODEL_NO_ARCH = {
    "params_b": 4.0,
    "quantization": "Q4_K_M",
    "context_length": 8192,
    # No block_count, embed_dim — should fall back to params-based estimate
}


class TestVramIncludesKvCache:
    """D-3: VRAM estimate must include KV cache (context-dependent)."""

    def test_vram_increases_with_ctx(self, lmm):
        """Larger n_ctx → larger VRAM estimate (KV cache grows)."""
        small = lmm.estimate_vram_gb(MODEL_8B, n_ctx=4096)
        large = lmm.estimate_vram_gb(MODEL_8B, n_ctx=32768)
        assert large > small, "VRAM must increase with context length (KV cache)"

    def test_vram_at_min_ctx_is_not_zero(self, lmm):
        """Even at MIN_CTX, VRAM should be non-zero (weights + minimal KV)."""
        vram = lmm.estimate_vram_gb(MODEL_8B, n_ctx=MIN_CTX)
        assert vram > 0

    def test_vram_includes_kv_cache_component(self, lmm):
        """The KV cache component must be non-trivial (not just weights)."""
        vram_min = lmm.estimate_vram_gb(MODEL_8B, n_ctx=4096)
        vram_max = lmm.estimate_vram_gb(MODEL_8B, n_ctx=32768)
        delta = vram_max - vram_min
        # KV cache for 8x32x32768x4096x2 bytes ≈ 10.9 GB
        # So the delta should be substantial (at least 1 GB)
        assert delta > 1.0, f"KV cache delta should be >1GB, got {delta:.2f}GB"

    def test_weights_only_estimate_is_lower(self, lmm):
        """The old weights-only estimate should be lower than the new one."""
        # Old formula: params_b * bpw / 8.0 * 1.1
        old_estimate = MODEL_8B["params_b"] * 4.85 / 8.0 * 1.1  # ≈ 5.34 GB
        new_estimate = lmm.estimate_vram_gb(MODEL_8B, n_ctx=32768)
        assert new_estimate > old_estimate, "New estimate must include KV cache on top of weights"

    def test_kv_cache_grows_linearly_with_ctx(self, lmm):
        """KV cache should grow linearly with n_ctx (holding architecture constant)."""
        vram_8k = lmm.estimate_vram_gb(MODEL_8B, n_ctx=8192)
        vram_12k = lmm.estimate_vram_gb(MODEL_8B, n_ctx=12288)
        vram_16k = lmm.estimate_vram_gb(MODEL_8B, n_ctx=16384)

        delta_8k_12k = vram_12k - vram_8k
        delta_12k_16k = vram_16k - vram_12k
        # KV cache is linear in n_ctx, so equal steps should give equal deltas
        ratio = delta_8k_12k / delta_12k_16k if delta_12k_16k > 0 else 0
        assert 0.8 < ratio < 1.2, f"KV cache should be linear in n_ctx, ratio={ratio:.2f}"

    def test_fallback_when_arch_missing(self, lmm):
        """When architecture metadata is missing, fall back to params-based estimate."""
        vram = lmm.estimate_vram_gb(MODEL_NO_ARCH, n_ctx=8192)
        assert vram > 0
        # Should still include some KV cache component
        vram_min = lmm.estimate_vram_gb(MODEL_NO_ARCH, n_ctx=MIN_CTX)
        vram_max = lmm.estimate_vram_gb(MODEL_NO_ARCH, n_ctx=8192)
        assert vram_max > vram_min

    def test_zero_params_returns_zero(self, lmm):
        """If params_b is 0 or missing, return 0."""
        assert lmm.estimate_vram_gb({"params_b": 0}) == 0.0
        assert lmm.estimate_vram_gb({}) == 0.0

    def test_uses_native_context_when_n_ctx_none(self, lmm):
        """When n_ctx is None, use model's native context_length."""
        vram_default = lmm.estimate_vram_gb(MODEL_8B)
        vram_32k = lmm.estimate_vram_gb(MODEL_8B, n_ctx=32768)
        assert vram_default == pytest.approx(vram_32k)
