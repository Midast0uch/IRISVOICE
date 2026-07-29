"""
Tests for TPS correction loop (Phase 3, Wave 4).

T4.1: threshold is TARGET_TPS (not hardcoded 8).
T4.2: sustained sub-target throughput writes a reduced-context config to ConfigCache.
T4.4: embedding/rerank purposes are NOT measured against TARGET_TPS.
T4.5: ConfigCache persists corrections.
"""

import pytest
from unittest.mock import patch, MagicMock
from backend.agent.local_model_manager import (
    LocalModelManager,
    ConfigCache,
    TARGET_TPS,
    TPS_DEADBAND,
    MIN_CTX,
    MAX_CTX,
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

SYNTH_HW = {
    "cuda_available": True,
    "gpu_name": "NVIDIA GeForce RTX 3070",
    "vram_total_gb": 8.0,
    "vram_free_gb": 7.0,
}


@pytest.fixture
def lmm(tmp_path):
    mgr = LocalModelManager()
    # Isolate the cache to a temp file so we don't touch the real one.
    mgr._config_cache = ConfigCache(tmp_path / "local_model_configs.json")
    return mgr


def _load_state(mgr, n_ctx=32768, purpose="chat"):
    """Simulate a successfully-loaded model (record_tps reads this state)."""
    mgr._current_model_path = "/fake/model.gguf"
    mgr._current_model_meta = dict(MODEL_8B)
    mgr._current_params = {
        "n_ctx": n_ctx,
        "n_gpu_layers": -1,
        "n_batch": 2048,
    }
    mgr._current_purpose = purpose


def _feed(mgr, values):
    for v in values:
        mgr.record_tps(v, gpu_active=True)


class TestTpsCorrectionShrink:
    """Sustained below target → reduced-context next-load config (T4.2)."""

    def test_sub_target_writes_smaller_ctx(self, lmm):
        _load_state(lmm, n_ctx=32768)
        with patch.object(lmm, "get_hardware_info", return_value=SYNTH_HW):
            # 5 tok/s avg, well below TARGET_TPS (25) and outside deadband.
            _feed(lmm, [5.0, 5.0, 5.0])
        assert len(lmm._config_cache._data) == 1, "correction should be written to cache"
        entry = next(iter(lmm._config_cache._data.values()))
        cached_n_ctx = entry["config"]["n_ctx"]
        assert cached_n_ctx < 32768, (
            f"sub-target should shrink n_ctx, got {cached_n_ctx}"
        )
        assert entry["config"]["n_gpu_layers"] == -1
        assert entry["measured_tps"] == 5.0


class TestTpsCorrectionGrow:
    """Comfortably above target with headroom → increased next-load config."""

    def test_above_target_writes_larger_ctx(self, lmm):
        # Use a small model so VRAM is not the binding constraint and TPS can
        # drive the context upward. Start below MAX_CTX so there is room to grow.
        lmm._current_model_path = "/fake/small.gguf"
        lmm._current_model_meta = dict(MODEL_230M)
        lmm._current_params = {"n_ctx": 16384, "n_gpu_layers": -1, "n_batch": 2048}
        lmm._current_purpose = "chat"
        with patch.object(lmm, "get_hardware_info", return_value=SYNTH_HW):
            # 40 tok/s avg, above TARGET_TPS (25) and outside deadband.
            _feed(lmm, [40.0, 40.0, 40.0])
        assert len(lmm._config_cache._data) == 1, "correction should be written to cache"
        entry = next(iter(lmm._config_cache._data.values()))
        cached_n_ctx = entry["config"]["n_ctx"]
        assert cached_n_ctx > 16384, (
            f"above-target should grow n_ctx, got {cached_n_ctx}"
        )


class TestTpsCorrectionDeadband:
    """Within TPS_DEADBAND → records nothing (REQ-4 AC5)."""

    def test_within_deadband_writes_nothing(self, lmm):
        _load_state(lmm, n_ctx=32768)
        with patch.object(lmm, "get_hardware_info", return_value=SYNTH_HW):
            # 26 tok/s is within 25 * (1 +/- 0.15) = [21.25, 28.75].
            _feed(lmm, [26.0, 26.0, 26.0])
        assert lmm._config_cache._data == {}, (
            "within deadband must not write a correction"
        )


class TestCpuPurposeNotMeasured:
    """embedding/rerank purposes are never measured against TARGET_TPS (T4.4)."""

    def test_embedding_records_no_correction(self, lmm):
        _load_state(lmm, n_ctx=4096, purpose="embedding")
        with patch.object(lmm, "get_hardware_info", return_value=SYNTH_HW):
            # Even a very slow embedding model must not record a correction.
            _feed(lmm, [2.0, 2.0, 2.0])
        assert lmm._config_cache._data == {}, (
            "embedding purpose must not be measured against TARGET_TPS"
        )

    def test_rerank_records_no_correction(self, lmm):
        _load_state(lmm, n_ctx=4096, purpose="rerank")
        with patch.object(lmm, "get_hardware_info", return_value=SYNTH_HW):
            _feed(lmm, [1.0, 1.0, 1.0])
        assert lmm._config_cache._data == {}, (
            "rerank purpose must not be measured against TARGET_TPS"
        )


class TestThresholdIsTargetTps:
    """T4.1: the threshold used is TARGET_TPS, not the old hardcoded 8."""

    def test_threshold_uses_target_tps(self, lmm):
        # A chat model at 15 tok/s is below TARGET_TPS (25) but above the old 8.
        _load_state(lmm, n_ctx=32768)
        with patch.object(lmm, "get_hardware_info", return_value=SYNTH_HW):
            _feed(lmm, [15.0, 15.0, 15.0])
        assert len(lmm._config_cache._data) == 1, (
            "15 tok/s is below TARGET_TPS(25) and must trigger a correction; "
            "the old hardcoded 8 tok/s threshold would have missed this"
        )
