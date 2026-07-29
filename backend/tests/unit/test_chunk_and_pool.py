"""
Unit tests for chunking + pooling (REQ-2).

Verifies:
  - Sub-window text (fits in window) is returned as a single chunk,
    byte-identical to unchunked path.
  - Exact-window text is also a single chunk.
  - Multi-chunk text triggers chunking, max-pool, then L2 normalisation.
  - Pooling is element-wise MAX (not mean) — verified against mean-pool.
"""

import hashlib
import math
from unittest.mock import patch

import pytest

from backend.memory.embedding import (
    EmbeddingService,
    Chunker,
    max_pool,
    l2_normalize,
    DEFAULT_CHUNK_TOKENS,
    DEFAULT_OVERLAP_TOKENS,
    MAX_CHUNKS_PER_DOC,
)


# ── Tiny deterministic per-chunk encoder ─────────────────────────────────────

def _chunk_hash_to_dim(text: str, dim: int = 8) -> list:
    """Map a chunk's SHA-256 into an 8-dim vector (deterministic)."""
    h = hashlib.sha256(text.encode()).digest()
    vec = [(h[i % len(h)] / 255.0) * 2 - 1 for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


# Pad to 1024 with zeros (as EmbeddingService expects 1024-dim output)
def _hash_1024_vec(text: str) -> list:
    small = _chunk_hash_to_dim(text, dim=8)
    return small + [0.0] * (1024 - 8)


class TestChunker:
    """Chunker unit tests — window, overlap, truncation."""

    def test_sub_window_single_chunk(self):
        """Text shorter than window returns a single chunk."""
        chunker = Chunker(window=8, chunk_tokens=8, overlap_tokens=2)
        chunks, truncated = chunker.chunk("hello world")
        assert len(chunks) == 1
        assert chunks[0] == "hello world"
        assert truncated is False

    def test_exact_window_single_chunk(self):
        """Text exactly as long as window returns a single chunk."""
        chunker = Chunker(window=4, chunk_tokens=4, overlap_tokens=1)
        text = "one two three four"
        chunks, truncated = chunker.chunk(text)
        assert len(chunks) == 1
        assert chunks[0] == text
        assert truncated is False

    def test_multi_chunk(self):
        """Text exceeding window produces multiple chunks."""
        # Window=2 tokens, chunk=2, overlap=0 -> each pair of words is a chunk
        chunker = Chunker(window=2, chunk_tokens=2, overlap_tokens=0)
        text = "a b c d e f"
        chunks, truncated = chunker.chunk(text)
        assert len(chunks) >= 2
        assert truncated is False

    def test_truncation(self):
        """Text exceeding max_chunks is truncated."""
        chunker = Chunker(
            window=2, chunk_tokens=2, overlap_tokens=0, max_chunks=2
        )
        text = "a b c d e f g h"
        chunks, truncated = chunker.chunk(text)
        assert len(chunks) == 2
        assert truncated is True

    def test_empty_text_single_chunk(self):
        """Empty string returns a single empty chunk."""
        chunker = Chunker(window=8)
        chunks, truncated = chunker.chunk("")
        assert len(chunks) == 1
        assert truncated is False

    def test_whitespace_text_single_chunk(self):
        """Whitespace-only returns a single empty-like chunk."""
        chunker = Chunker(window=8)
        chunks, truncated = chunker.chunk("   ")
        assert len(chunks) == 1
        assert truncated is False


class TestEncodingWithChunking:
    """REQ-2: encode path with injected tiny chunker + deterministic encoder."""

    @pytest.fixture(autouse=True)
    def _patch_service(self):
        """Monkeypatch EmbeddingService to use tiny chunker + deterministic encoder."""
        svc = EmbeddingService()
        # Force backend to hash so _ensure_backend doesn't try to load neural models
        svc._backend = "hash"
        self._svc = svc
        # Override chunker for test: window=8 tokens, chunk=8, overlap=2
        self._chunker = Chunker(window=8, chunk_tokens=8, overlap_tokens=2)
        svc._chunker_for = lambda _backend: self._chunker
        # Override per-chunk encoder
        svc._encode_chunk_with = lambda text, backend: _hash_1024_vec(text)
        yield
        # Clean up singleton for other tests
        EmbeddingService.reset_instance()

    def test_short_text_byte_identical_to_unchunked(self):
        """Sub-window text produces same result as if chunking were bypassed.

        Single-chunk path goes through _encode_chunk_with directly (no max-pool),
        so for short text the result is byte-identical to calling encode_chunk_with.
        """
        text = "hello world"
        # Force single chunk by using a big window
        self._chunker = Chunker(window=1000)
        self._svc._chunker_for = lambda _backend: self._chunker

        vec = self._svc.encode(text)
        expected = _hash_1024_vec(text)
        assert vec == expected

    def test_long_text_differs_from_chunk0(self):
        """Multi-chunk text yields a max-pooled result (different from chunk 0 alone)."""
        # 32 tokens with window=8 -> 4 chunks
        text = "word " * 32
        vec = self._svc.encode(text)

        # Just the first 8 tokens
        first_chunk = " ".join(text.split()[:8])
        first_vec = _hash_1024_vec(first_chunk)

        # The pooled result should be different from the first chunk alone
        assert vec != first_vec, "max-pooled result should differ from single chunk"

    def test_long_text_is_1024_dim(self):
        """Multi-chunk text still produces 1024-dim output."""
        text = "word " * 32
        vec = self._svc.encode(text)
        assert len(vec) == 1024

    def test_chunk_count_metadata(self):
        """encode_with_meta reports the correct chunk count."""
        text = "word " * 32
        meta = self._svc.encode_with_meta(text)
        assert meta.chunk_count > 1
        assert meta.truncated is False

    def test_max_pool_not_mean_pool(self):
        """Verify max-pool produces different result than mean-pool for multi-chunk.

        This is a basic sanity — the dedicated test_pooling_is_max_not_mean.py
        has the distinguishing case.
        """
        text = "word " * 32
        vec = self._svc.encode(text)

        # Compute mean-pool manually
        self._chunker = Chunker(window=8, chunk_tokens=8, overlap_tokens=2)
        chunks, _ = self._chunker.chunk(text)
        chunk_vecs = [_hash_1024_vec(c) for c in chunks]
        mean_pooled = [sum(col) / len(col) for col in zip(*chunk_vecs)]
        mean_l2 = l2_normalize(mean_pooled)

        assert vec != mean_l2, "max-pool should differ from mean-pool for multi-chunk text"
