"""
Contract tests for EmbeddingService (CT-E1, CT-E2).

Verifies:
  - get_embedding_service() returns the same singleton every call.
  - encode / encode_batch signatures unchanged (1024-dim output).
  - Every persisted vector is 1024-dim AND carries a non-empty backend
    (tested via encode_with_meta).
"""

import pytest
from unittest.mock import patch

from backend.memory.embedding import (
    get_embedding_service,
    Embedding,
    BACKEND_HASH,
)


class TestEmbeddingContract:
    """CT-E1, CT-E2 — EmbeddingService contract."""

    def test_singleton(self):
        """CT-E1: get_embedding_service() returns the same instance."""
        svc1 = get_embedding_service()
        svc2 = get_embedding_service()
        assert svc1 is svc2

    def test_encode_returns_1024_dim(self):
        """CT-E1: encode() returns a 1024-dim vector."""
        svc = get_embedding_service()
        vec = svc.encode("test query")
        assert isinstance(vec, list)
        assert len(vec) == 1024
        # All floats
        assert all(isinstance(v, float) for v in vec)

    def test_encode_empty_returns_zero_vector(self):
        """Empty input yields a zero vector (never raises)."""
        svc = get_embedding_service()
        vec = svc.encode("")
        assert len(vec) == 1024
        assert all(v == 0.0 for v in vec)

    def test_encode_whitespace_returns_zero_vector(self):
        """Whitespace-only input yields zero vector."""
        svc = get_embedding_service()
        vec = svc.encode("   ")
        assert len(vec) == 1024
        assert all(v == 0.0 for v in vec)

    def test_encode_batch_signature(self):
        """CT-E1: encode_batch returns list of 1024-dim vectors."""
        svc = get_embedding_service()
        texts = ["hello", "world", "test"]
        results = svc.encode_batch(texts)
        assert isinstance(results, list)
        assert len(results) == 3
        for vec in results:
            assert len(vec) == 1024
            assert all(isinstance(v, float) for v in vec)

    def test_encode_batch_empty(self):
        """Empty batch returns empty list."""
        svc = get_embedding_service()
        assert svc.encode_batch([]) == []

    def test_encode_with_meta_returns_full_embedding(self):
        """CT-E1: encode_with_meta returns Embedding with vector, backend, chunk_count."""
        svc = get_embedding_service()
        meta = svc.encode_with_meta("test query")
        assert isinstance(meta, Embedding)
        assert isinstance(meta.vector, list)
        assert len(meta.vector) == 1024
        assert isinstance(meta.backend, str)
        assert meta.backend != ""  # non-empty backend
        assert meta.chunk_count >= 1
        assert isinstance(meta.truncated, bool)

    def test_encode_with_meta_backend_is_hash(self):
        """In test env with no neural models, backend is 'hash'."""
        svc = get_embedding_service()
        meta = svc.encode_with_meta("test")
        assert meta.backend == BACKEND_HASH

    def test_encode_repeatable(self):
        """Same input yields same vector (deterministic via hash)."""
        svc = get_embedding_service()
        v1 = svc.encode("repeatable test")
        v2 = svc.encode("repeatable test")
        assert v1 == v2

    def test_available_backends_includes_hash(self):
        """hash backend is always available."""
        svc = get_embedding_service()
        avail = svc.available_backends()
        assert BACKEND_HASH in avail

    def test_encode_with_backend_hash(self):
        """encode_with_backend with explicit hash backend works."""
        svc = get_embedding_service()
        vec = svc.encode_with_backend("test", BACKEND_HASH)
        assert vec is not None
        assert len(vec) == 1024
