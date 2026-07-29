"""
Tests for ConfigCache (Phase 3, Wave 4, T4.5 / REQ-5).

- fingerprint changes on mtime/size (REQ-5 AC2)
- hw_fingerprint mismatch invalidates (REQ-5 AC4)
- corrupt file falls back to derivation (REQ-5 AC5)
"""

import json
from pathlib import Path

import pytest

from backend.agent.local_model_manager import ConfigCache


MODEL_META = {
    "params_b": 8.0,
    "quantization": "Q4_K_M",
    "context_length": 32768,
}

HW_A = {
    "cuda_available": True,
    "gpu_name": "NVIDIA GeForce RTX 3070",
    "vram_total_gb": 8.0,
    "vram_free_gb": 7.0,
}

HW_B = {
    "cuda_available": True,
    "gpu_name": "NVIDIA GeForce RTX 4090",
    "vram_total_gb": 24.0,
    "vram_free_gb": 22.0,
}


@pytest.fixture
def cache(tmp_path):
    return ConfigCache(tmp_path / "local_model_configs.json")


def _write_real_file(tmp_path, name="model.gguf", size=12345, mtime=1000.0):
    p = tmp_path / name
    p.write_bytes(b"x" * size)
    # Set mtime explicitly so the fingerprint is deterministic.
    atime = mtime
    Path(p).touch()
    import os
    os.utime(p, (atime, mtime))
    return p


class TestFingerprintStability:
    """REQ-5 AC2: fingerprint changes when the file changes."""

    def test_fingerprint_changes_on_size(self, tmp_path):
        p = _write_real_file(tmp_path, size=1000, mtime=1000.0)
        fp1 = ConfigCache._model_fingerprint(str(p), MODEL_META)
        p.write_bytes(b"x" * 2000)
        import os
        os.utime(p, (1000.0, 1000.0))
        fp2 = ConfigCache._model_fingerprint(str(p), MODEL_META)
        assert fp1 != fp2, "size change must change the fingerprint"

    def test_fingerprint_changes_on_mtime(self, tmp_path):
        p = _write_real_file(tmp_path, size=1000, mtime=1000.0)
        fp1 = ConfigCache._model_fingerprint(str(p), MODEL_META)
        import os
        os.utime(p, (2000.0, 2000.0))
        fp2 = ConfigCache._model_fingerprint(str(p), MODEL_META)
        assert fp1 != fp2, "mtime change must change the fingerprint"

    def test_fingerprint_stable_when_unchanged(self, tmp_path):
        p = _write_real_file(tmp_path, size=1000, mtime=1000.0)
        fp1 = ConfigCache._model_fingerprint(str(p), MODEL_META)
        fp2 = ConfigCache._model_fingerprint(str(p), MODEL_META)
        assert fp1 == fp2, "fingerprint must be stable for an unchanged file"


class TestHwFingerprint:
    """REQ-5 AC4: hardware change invalidates the cached entry."""

    def test_hw_mismatch_invalidates(self, cache, tmp_path):
        p = _write_real_file(tmp_path)
        cfg = {"n_ctx": 8192, "n_gpu_layers": -1, "n_batch": 1024}
        cache.put(str(p), MODEL_META, HW_A, cfg, measured_tps=30.0)
        # Same model, different hardware → cache miss.
        got = cache.get(str(p), MODEL_META, HW_B)
        assert got is None, "hw fingerprint mismatch must invalidate the entry"

    def test_hw_match_returns_entry(self, cache, tmp_path):
        p = _write_real_file(tmp_path)
        cfg = {"n_ctx": 8192, "n_gpu_layers": -1, "n_batch": 1024}
        cache.put(str(p), MODEL_META, HW_A, cfg, measured_tps=30.0)
        got = cache.get(str(p), MODEL_META, HW_A)
        assert got is not None
        assert got.config["n_ctx"] == 8192
        assert got.measured_tps == 30.0


class TestCorruptCache:
    """REQ-5 AC5: a corrupt cache file is discarded, derivation falls back."""

    def test_corrupt_file_tolerated(self, tmp_path):
        cache_path = tmp_path / "local_model_configs.json"
        cache_path.write_text("{ this is not valid json ")
        cache = ConfigCache(cache_path)
        # Must not raise; get() returns None so caller re-derives.
        p = _write_real_file(tmp_path)
        got = cache.get(str(p), MODEL_META, HW_A)
        assert got is None
        # And put() must still work after the corrupt load.
        cache.put(str(p), MODEL_META, HW_A, {"n_ctx": 4096})
        assert cache.get(str(p), MODEL_META, HW_A) is not None


class TestPersistence:
    """The cache survives a fresh ConfigCache instance (file-backed)."""

    def test_survives_reload(self, tmp_path):
        p = _write_real_file(tmp_path)
        cfg = {"n_ctx": 8192, "n_gpu_layers": -1, "n_batch": 1024}
        c1 = ConfigCache(tmp_path / "local_model_configs.json")
        c1.put(str(p), MODEL_META, HW_A, cfg)
        # New instance reads the same file.
        c2 = ConfigCache(tmp_path / "local_model_configs.json")
        got = c2.get(str(p), MODEL_META, HW_A)
        assert got is not None
        assert got.config["n_ctx"] == 8192
