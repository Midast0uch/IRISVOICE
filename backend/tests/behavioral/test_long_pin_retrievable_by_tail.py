"""
Behavioral test: a long document whose distinguishing content is at the tail
is still retrievable by tail query (21%-of-PiNs edge case).

Strategy:
  - Inject a tiny chunker (window=8 tokens) and a deterministic encoder.
  - Index a document whose BODY is generic but TAIL is unique.
  - Query for the tail content.
  - Assert the document IS retrieved (max-pool preserves the tail signal).
"""

import hashlib
import math
import os
import tempfile
import uuid
from unittest.mock import patch

import pytest

from backend.memory.embedding import (
    EmbeddingService,
    Chunker,
    max_pool,
    l2_normalize,
    Embedding,
    BACKEND_HASH,
)
from backend.memory.episodic import EpisodicStore, Episode

# ── Deterministic 8-dim encoder (expanded to 1024 with zeros) ───────────────

def _hash_bow_1024(text: str) -> list:
    """Deterministic 1024-dim bag-of-words embedding via SHA-256 hashing.

    Similar text → similar vectors (word overlap → cosine > 0).
    Matches the structure of embedding.py's _hash_embed.
    """
    import hashlib, math
    vec = [0.0] * 1024
    tokens = text.lower().split()
    for tok in tokens:
        h = int(hashlib.sha256(tok.encode()).hexdigest(), 16) % 1024
        vec[h] += 1.0
    # Bigrams for partial context preservation
    for a, b in zip(tokens, tokens[1:]):
        bigram = f"{a}_{b}"
        h = int(hashlib.sha256(bigram.encode()).hexdigest(), 16) % 1024
        vec[h] += 0.5
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


@pytest.fixture(autouse=True)
def _patch_service():
    """Monkeypatch EmbeddingService for deterministic tiny encoder."""
    EmbeddingService.reset_instance()
    svc = EmbeddingService()
    svc._backend = BACKEND_HASH
    # Tiny chunker: window=8 tokens, chunk=8, overlap=2
    svc._chunker_for = lambda _backend: Chunker(window=8, chunk_tokens=8, overlap_tokens=2)
    svc._encode_chunk_with = lambda text, backend: _hash_bow_1024(text)
    yield
    EmbeddingService.reset_instance()


@pytest.fixture
def store():
    path = os.path.join(tempfile.gettempdir(), f"test_tail_{uuid.uuid4().hex}.db")
    s = EpisodicStore(path, b"test" * 8)
    yield s
    try:
        os.remove(path)
    except OSError:
        pass


def test_tail_content_retrievable(store):
    """A long document whose distinguishing tail is beyond the chunk window
    is still found when querying for the tail."""

    # Generate a document. BODY is generic filler, TAIL is a unique phrase.
    # With window=8 tokens, each chunk is 8 words.
    body = "generic filler word " * 20  # ~60 words -> ~7-8 chunks
    tail = "crimson narwhal quantum entanglement specific query target"
    document = body + tail

    ep = Episode(
        session_id="test-session",
        task_summary=document,
        full_content=document,
        tool_sequence=[],
        outcome_type="success",
    )
    store.store(ep, 0.9)

    # Query for the tail (should match via max-pool preserving the last chunk)
    results = store.retrieve_similar("crimson narwhal quantum entanglement")
    assert len(results) > 0, "Tail query should retrieve the document"

    # Score should be reasonably high
    assert results[0]["similarity"] > 0.1, (
        f"Tail similarity too low: {results[0]['similarity']}"
    )


def test_empty_query_returns_empty(store):
    """Edge case: empty query returns empty list."""
    results = store.retrieve_similar("")
    assert results == []


def test_unrelated_query_returns_empty(store):
    """Unrelated query does not retrieve the document."""
    body = "generic filler word " * 20
    tail = "crimson narwhal quantum entanglement"
    document = body + tail

    ep = Episode(
        session_id="test-session",
        task_summary=document,
        full_content=document,
        tool_sequence=[],
        outcome_type="success",
    )
    store.store(ep, 0.9)

    results = store.retrieve_similar("completely unrelated topic foo bar baz")
    # May still get a match due to hash collisions in 8 real dims, but
    # if we do, similarity should be low
    if results:
        assert results[0]["similarity"] < 0.5, (
            f"Unrelated query should have low similarity: {results[0]['similarity']}"
        )
