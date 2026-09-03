"""
Contract tests for cross-space refusal (CT-E6).

Verifies:
  - compare_embeddings raises CrossSpaceComparisonError for different backends.
  - Same backend returns a float.
  - EpisodicStore with cross-space rows silently skips (no crash, no match).
"""

import json
import os
import struct
import tempfile
import uuid
from unittest.mock import patch

import pytest

from backend.memory.embedding import (
    compare_embeddings,
    CrossSpaceComparisonError,
    BACKEND_BGE,
    BACKEND_LFM,
    BACKEND_HASH,
    Embedding,
    EmbeddingService,
)
from backend.memory.episodic import EpisodicStore, Episode


# ── Deterministic "embedding" helpers ────────────────────────────────────────

def _fake_bge(text: str) -> list:
    """Deterministic 1024-dim BGE vector (hash-based)."""
    import hashlib, math
    vec = [0.0] * 1024
    for i, c in enumerate(text):
        h = int(hashlib.md5(f"{c}{i}".encode()).hexdigest(), 16) % 1024
        vec[h] += 1.0
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


def _fake_lfm(text: str) -> list:
    """Deterministic 1024-dim LFM vector (different distribution)."""
    import hashlib, math
    vec = [0.0] * 1024
    for i, c in enumerate(text):
        h = int(hashlib.sha256(f"lfm_{c}{i}".encode()).hexdigest(), 16) % 1024
        vec[h] += 2.0
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


class TestCompareEmbeddingsContract:
    """CT-E6 — cross-space refusal."""

    def test_same_backend_returns_float(self):
        a = _fake_bge("hello")
        b = _fake_bge("world")
        sim = compare_embeddings(a, BACKEND_BGE, b, BACKEND_BGE)
        assert isinstance(sim, float)
        assert -1.0 <= sim <= 1.0

    def test_different_backend_raises(self):
        a = _fake_bge("hello")
        b = _fake_lfm("world")
        with pytest.raises(CrossSpaceComparisonError):
            compare_embeddings(a, BACKEND_BGE, b, BACKEND_LFM)

    def test_hash_and_bge_different(self):
        a = _fake_bge("hello")
        b = _fake_bge("world")
        with pytest.raises(CrossSpaceComparisonError):
            compare_embeddings(a, BACKEND_BGE, b, BACKEND_HASH)

    def test_empty_backend_skips_check(self):
        a = _fake_bge("hello")
        b = _fake_lfm("world")
        sim = compare_embeddings(a, "", b, "")
        assert isinstance(sim, float)
        sim = compare_embeddings(a, BACKEND_BGE, b, "")
        assert isinstance(sim, float)


class TestEpisodicCrossSpace:
    """EpisodicStore cross-space behavior (no crash, no match)."""

    @pytest.fixture(autouse=True)
    def _patch_service(self, monkeypatch):
        """Force EmbeddingService to use BGE backend with deterministic encoding."""
        EmbeddingService.reset_instance()
        svc = EmbeddingService()
        # Patch the internal encoding to return deterministic BGE vectors
        svc._backend = BACKEND_BGE
        svc._models = {BACKEND_HASH: "hash", BACKEND_BGE: "mock-bge"}
        svc._encode_chunk_with = lambda text, backend: _fake_bge(text)
        yield
        EmbeddingService.reset_instance()

    @pytest.fixture
    def store(self, tmp_path):
        db_path = os.path.join(tmp_path, "test_cross_space.db")
        return EpisodicStore(db_path, b"test" * 8)

    def _force_backend(self, store, backend):
        """Change the store's active backend and encoder."""
        svc = store._embed
        svc._backend = backend
        svc._enc_cache.clear()  # clear cache so fresh encodes use new backend
        if backend == BACKEND_LFM:
            svc._models[BACKEND_LFM] = "mock-lfm"
            svc._encode_chunk_with = lambda text, _b: _fake_lfm(text)
        elif backend == BACKEND_BGE:
            svc._models[BACKEND_BGE] = "mock-bge"
            svc._encode_chunk_with = lambda text, _b: _fake_bge(text)

    def test_retrieve_similar_cross_space_skipped(self, store):
        """retrieve_similar does not return cross-space rows (no crash)."""
        # Store one row with BGE backend
        ep = Episode(
            session_id="test-session",
            task_summary="bge test task",
            full_content="test",
            tool_sequence=[],
            outcome_type="success",
        )
        store.store(ep, 0.9)

        # Verify it was stored with BGE
        row = store.db.execute(
            "SELECT embedding_backend FROM episodes"
        ).fetchone()
        assert row[0] == BACKEND_BGE

        # Now force LFM for querying
        self._force_backend(store, BACKEND_LFM)

        # Query with DIFFERENT text (avoid cache collision) from LFM space
        results = store.retrieve_similar("completely unrelated query from lfm")
        assert len(results) == 0, (
            f"Expected 0 cross-space results, got {len(results)}"
        )

    def test_retrieve_failures_cross_space_skipped(self, store):
        """retrieve_failures does not crash on cross-space rows."""
        ep = Episode(
            session_id="test-session",
            task_summary="failed task",
            full_content="fail",
            tool_sequence=[],
            outcome_type="failure",
            failure_reason="test failure",
        )
        store.store(ep, 0.3)

        self._force_backend(store, BACKEND_LFM)
        results = store.retrieve_failures("completely unrelated lfm failure query")
        assert len(results) == 0

    def test_retrieve_similar_same_space_works(self, store):
        """Same-space retrieval works normally."""
        ep = Episode(
            session_id="test-session",
            task_summary="hello world",
            full_content="test",
            tool_sequence=[],
            outcome_type="success",
        )
        store.store(ep, 0.9)

        # Query with same backend
        results = store.retrieve_similar("hello world")
        assert len(results) >= 1
        assert results[0]["similarity"] > 0.0

    def test_compare_embeddings_with_hash_backend(self):
        """Hash vs LFM raises CrossSpaceComparisonError."""
        a = _fake_bge("hello")
        b = _fake_bge("world")
        with pytest.raises(CrossSpaceComparisonError):
            compare_embeddings(a, BACKEND_HASH, b, BACKEND_LFM)
