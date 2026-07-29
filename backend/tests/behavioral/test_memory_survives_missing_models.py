"""
Behavioral test: memory store/retrieve works when neural backends are unavailable.

With both BGE-M3 and LFM2.5 unavailable (simulated by making _ensure_backend
return False for both), the system falls back to hash-projection embedding.
Store and retrieve must still work and never raise.
"""

import os
import tempfile
import uuid
from unittest.mock import patch

import pytest

from backend.memory.embedding import (
    EmbeddingService,
    BACKEND_BGE,
    BACKEND_LFM,
    BACKEND_HASH,
)
from backend.memory.episodic import EpisodicStore, Episode
from backend.memory.reindex import reset_reindex_manager


class TestMemorySurvivesMissingModels:
    """Store and retrieve work with hash fallback when neural models are absent."""

    @pytest.fixture(autouse=True)
    def _patch_no_neural(self, monkeypatch):
        """Make _ensure_backend return False for neural backends."""
        # Reset singletons
        reset_reindex_manager()
        EmbeddingService.reset_instance()
        svc = EmbeddingService()

        # Make _ensure_backend return False for BGE and LFM
        original_ensure = svc._ensure_backend

        def no_neural_ensure(backend):
            if backend in (BACKEND_BGE, BACKEND_LFM):
                return False
            return original_ensure(backend)

        monkeypatch.setattr(svc, "_ensure_backend", no_neural_ensure)

        # Force backend to hash
        svc._backend = BACKEND_HASH
        svc._models = {BACKEND_HASH: "hash"}

        yield
        EmbeddingService.reset_instance()

    @pytest.fixture
    def store(self, tmp_path):
        """Create a temp EpisodicStore with biometric key."""
        db_path = os.path.join(tmp_path, "test_hash.db")
        return EpisodicStore(db_path, b"test" * 8)

    def test_store_success(self, store):
        """Episode can be stored with hash fallback."""
        ep = Episode(
            session_id="test-session",
            task_summary="store this with hash",
            full_content="test content",
            tool_sequence=[],
            outcome_type="success",
        )
        ep_id = store.store(ep, 0.9)
        assert ep_id is not None
        assert len(ep_id) > 0

    def test_retrieve_after_store(self, store):
        """Stored episode can be retrieved."""
        ep = Episode(
            session_id="test-session",
            task_summary="unique retrieval test phrase",
            full_content="test content",
            tool_sequence=[],
            outcome_type="success",
        )
        store.store(ep, 0.9)

        results = store.retrieve_similar("unique retrieval test phrase")
        assert len(results) >= 1
        assert results[0]["task_summary"] == "unique retrieval test phrase"

    def test_retrieve_failures(self, store):
        """Failure episodes can be stored and retrieved."""
        ep = Episode(
            session_id="test-session",
            task_summary="a failing task",
            full_content="it failed",
            tool_sequence=[],
            outcome_type="failure",
            failure_reason="something went wrong",
        )
        store.store(ep, 0.3)

        results = store.retrieve_failures("failing task")
        assert len(results) >= 1
        assert results[0]["failure_reason"] == "something went wrong"

    def test_fragment_and_store_chunks(self, store):
        """Context chunks can be stored with hash fallback."""
        chunk_ids = store.fragment_and_store(
            "This is some context content to fragment and store for testing.",
            "test-session",
        )
        assert len(chunk_ids) >= 1

    def test_retrieve_context_chunks(self, store):
        """Stored context chunks can be retrieved."""
        store.fragment_and_store(
            "The crimson narwhal quantum entanglement is a unique test phrase.",
            "test-session",
        )
        results = store.retrieve_context_chunks("crimson narwhal quantum")
        assert len(results) >= 1

    def test_multiple_episodes_no_cross_space_crash(self, store):
        """Multiple episodes can be stored and retrieved without cross-space crashes."""
        for i in range(3):
            ep = Episode(
                session_id="test-session",
                task_summary=f"episode number {i} with some content",
                full_content=f"content {i}",
                tool_sequence=[],
                outcome_type="success",
            )
            store.store(ep, 0.9)

        results = store.retrieve_similar("episode number")
        # At least some should be found (same space means no CrossSpaceComparisonError)
        assert len(results) >= 1

    def test_no_named_models_loaded(self):
        """Verify the test setup is correct: BGE/LFM are NOT available."""
        svc = EmbeddingService()
        assert BACKEND_BGE not in svc.available_backends()
        assert BACKEND_LFM not in svc.available_backends()
        assert BACKEND_HASH in svc.available_backends()

    def test_encode_with_backend_returns_none_for_missing(self):
        """encode_with_backend returns None for unavailable backends."""
        svc = EmbeddingService()
        result = svc.encode_with_backend("test", BACKEND_BGE)
        assert result is None

        result = svc.encode_with_backend("test", BACKEND_LFM)
        assert result is None

        # Hash always works
        result = svc.encode_with_backend("test", BACKEND_HASH)
        assert result is not None
        assert len(result) == 1024
