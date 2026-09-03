"""
Closed-loop tuning test (Phase 3, Wave 4, T4.2/T4.3 / REQ-4 AC2,AC4).

Injects sustained sub-target throughput, then asserts:
  - the RUNNING model was NOT reconfigured (REQ-4 AC4)
  - the NEXT load uses a reduced context (the correction landed in ConfigCache
    and is consulted on load — REQ-5 known-good start)
"""

import asyncio
import pytest
from unittest.mock import patch, AsyncMock

from backend.agent.local_model_manager import (
    LocalModelManager,
    ConfigCache,
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

SYNTH_HW = {
    "cuda_available": True,
    "gpu_name": "NVIDIA GeForce RTX 3070",
    "vram_total_gb": 8.0,
    "vram_free_gb": 7.0,
}


@pytest.fixture
def lmm(tmp_path):
    mgr = LocalModelManager()
    mgr._config_cache = ConfigCache(tmp_path / "local_model_configs.json")
    return mgr


def _make_model_file(tmp_path, name="model.gguf", size=2000):
    p = tmp_path / name
    p.write_bytes(b"x" * size)
    import os
    os.utime(p, (1000.0, 1000.0))
    return p


class TestClosedLoopTuning:
    def test_running_model_not_reconfigured(self, lmm, tmp_path):
        """REQ-4 AC4: record_tps must never mutate the running model's params."""
        p = _make_model_file(tmp_path)
        lmm._current_model_path = str(p)
        lmm._current_model_meta = dict(MODEL_8B)
        lmm._current_params = {"n_ctx": 32768, "n_gpu_layers": -1, "n_batch": 2048}
        lmm._current_purpose = "chat"
        before = dict(lmm._current_params)
        with patch.object(lmm, "get_hardware_info", return_value=SYNTH_HW):
            lmm.record_tps(5.0, gpu_active=True)
            lmm.record_tps(5.0, gpu_active=True)
            lmm.record_tps(5.0, gpu_active=True)
        # The running model's params must be byte-for-byte unchanged.
        assert lmm._current_params == before, (
            "record_tps must not reconfigure the running model"
        )

    def test_next_load_uses_reduced_context(self, lmm, tmp_path):
        """REQ-4 AC2 + REQ-5: a sub-target run shrinks the NEXT load's n_ctx."""
        p = _make_model_file(tmp_path)
        # Simulate a model already loaded at a large context.
        lmm._current_model_path = str(p)
        lmm._current_model_meta = dict(MODEL_8B)
        lmm._current_params = {"n_ctx": 32768, "n_gpu_layers": -1, "n_batch": 2048}
        lmm._current_purpose = "chat"

        captured = {}

        async def fake_load_inprocess(model_path, params, progress_cb=None):
            captured["params"] = dict(params)
            lmm._current_model_path = model_path
            lmm._current_params = dict(params)
            return True

        with patch.object(lmm, "get_hardware_info", return_value=SYNTH_HW), \
             patch.object(lmm, "parse_gguf_metadata", return_value=dict(MODEL_8B)), \
             patch.object(lmm, "_load_inprocess", side_effect=fake_load_inprocess), \
             patch("backend.agent.local_model_manager.kill_orphan_servers"), \
             patch.object(lmm, "unload_model", new=AsyncMock()):
            # 1) Inject sustained sub-target throughput → writes correction.
            lmm.record_tps(5.0, gpu_active=True)
            lmm.record_tps(5.0, gpu_active=True)
            lmm.record_tps(5.0, gpu_active=True)
            # 2) Next load consults the cache.
            asyncio.run(
                lmm.load_model(str(p), profile="balanced", purpose="chat")
            )

        assert "params" in captured, "load_model should have invoked the loader"
        used_n_ctx = captured["params"]["n_ctx"]
        assert used_n_ctx < 32768, (
            f"next load must use the reduced context from cache, got {used_n_ctx}"
        )
        assert captured["params"]["n_gpu_layers"] == -1
