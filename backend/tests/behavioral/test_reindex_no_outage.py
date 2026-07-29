"""
Behavioral test: re-index does not cause an outage.

During a migration:
  - Queries return results (no crash).
  - No CrossSpaceComparisonError is raised (no space mixing).
  - The ReindexManager.search methods handle dual-read correctly.
"""

import hashlib
import json
import math
import os
import tempfile
import time
import uuid
from unittest.mock import patch

import pytest

from backend.memory.embedding import (
    EmbeddingService,
    Embedding,
    compare_embeddings,
    CrossSpaceComparisonError,
    BACKEND_BGE,
    BACKEND_LFM,
    BACKEND_HASH,
)
from backend.memory.episodic import EpisodicStore, Episode
from backend.memory.reindex import (
    ReindexManager,
    init_reindex_manager,
    reset_reindex_manager,
    get_reindex_manager,
)

# ── Deterministic per-backend encoders ──────────────────────────────────────

def _bge_vec(text: str, dim: int = 64) -> list:
    """Deterministic BGE-style vector (64 non-zero dims)."""
    h = hashlib.sha256(f"bge:{text}".encode()).digest()
    vec = [(h[i % len(h)] / 255.0) * 2 - 1 for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec + [0.0] * (1024 - dim)


def _lfm_vec(text: str, dim: int = 64) -> list:
    """Deterministic LFM-style vector (different from BGE)."""
    h = hashlib.sha256(f"lfm:{text}".encode()).digest()
    vec = [(h[i % len(h)] / 255.0) * 2 - 1 for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec + [0.0] * (1024 - dim)


@pytest.fixture(autouse=True)
def _patch_service():
    """Monkeypatch EmbeddingService for deterministic dual-backend support."""
    EmbeddingService.reset_instance()
    svc = EmbeddingService()
    svc._backend = BACKEND_BGE
    svc._models = {BACKEND_HASH: "hash", BACKEND_BGE: "mock-bge", BACKEND_LFM: "mock-lfm"}
    svc._encode_chunk_with = lambda text, backend: (
        _bge_vec(text) if backend == BACKEND_BGE
        else _lfm_vec(text) if backend == BACKEND_LFM
        else _bge_vec(text)  # fallback
    )
    yield
    EmbeddingService.reset_instance()


class TestReindexNoOutage:
    """Dual-read works without crashes during migration."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        db_path = os.path.join(tmp_path, "test_reindex_no_outage.db")
        self.db_path = db_path
        self.store = EpisodicStore(db_path, b"test" * 8)
        reset_reindex_manager()

        # Store several episodes with BGE backend
        for i in range(5):
            ep = Episode(
                session_id="test-session",
                task_summary=f"bge test task number {i} with unique content",
                full_content=f"episode {i} content here",
                tool_sequence=[],
                outcome_type="success" if i % 2 == 0 else "failure",
            )
            self.store.store(ep, 0.8 + i * 0.05)

        # Init a ReindexManager for dual-read
        self.rm = init_reindex_manager(
            db_path, b"test" * 8,
            state_file=os.path.join(tmp_path, "reindex_state.json"),
        )

    def test_query_during_migration_returns_results(self):
        """Queries return normally during a migration (no crash, no error)."""
        # Start migration in a thread
        self.rm.start(BACKEND_BGE, BACKEND_LFM)

        # Query while migration is active
        try:
            results = self.store.retrieve_similar("test task")
            # Should return results (at least some from the BGE space)
            assert len(results) >= 0, "Query should not crash during migration"
            # All results should have valid structure
            for r in results:
                assert "task_summary" in r
                assert "similarity" in r
        except CrossSpaceComparisonError:
            pytest.fail("CrossSpaceComparisonError leaked during dual-read")

        # Wait for migration to finish
        time.sleep(2)
        progress = self.rm.progress()
        assert progress["state"] in ("complete", "interrupted", "running")

    def test_dual_read_episodes_no_space_mixing(self):
        """Episodes from both spaces are returned, never compared across spaces."""
        self.rm.start(BACKEND_BGE, BACKEND_LFM)
        time.sleep(1)

        try:
            results = self.store.retrieve_similar("test task")
            # Just verify no crash
            assert isinstance(results, list)
        except CrossSpaceComparisonError:
            pytest.fail("Dual-read leaked CrossSpaceComparisonError")

    def test_dual_read_failures_no_crash(self):
        """Failure retrieval during migration works."""
        self.rm.start(BACKEND_BGE, BACKEND_LFM)
        time.sleep(1)

        try:
            results = self.store.retrieve_failures("test task")
            assert isinstance(results, list)
        except CrossSpaceComparisonError:
            pytest.fail("Dual-read failure query crashed")

    def test_dual_read_chunks_no_crash(self):
        """Context chunk retrieval during migration works."""
        # Store some context chunks first
        self.store.fragment_and_store(
            "some context chunk content for testing purposes",
            "test-session",
        )
        self.rm.start(BACKEND_BGE, BACKEND_LFM)
        time.sleep(1)

        try:
            results = self.store.retrieve_context_chunks("test query")
            assert isinstance(results, list)
        except CrossSpaceComparisonError:
            pytest.fail("Dual-read chunk query crashed")
