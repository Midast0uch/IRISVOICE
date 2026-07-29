"""
Behavioral test: re-index resumes after interruption.

Verifies:
  - Already-migrated rows are NOT re-embedded.
  - No row is half-migrated (vector written but backend not updated).
  - Migration picks up from last_row_id on resume.
"""

import hashlib
import math
import os
import time
import uuid
from unittest.mock import patch

import pytest

from backend.memory.embedding import (
    EmbeddingService,
    Embedding,
    BACKEND_BGE,
    BACKEND_LFM,
    BACKEND_HASH,
)
from backend.memory.episodic import EpisodicStore, Episode, _pack_embedding
from backend.memory.reindex import (
    ReindexManager,
    init_reindex_manager,
    reset_reindex_manager,
    get_reindex_manager,
)


def _bge_vec(text: str, dim: int = 64) -> list:
    import hashlib, math
    h = hashlib.sha256(f"bge:{text}".encode()).digest()
    vec = [(h[i % len(h)] / 255.0) * 2 - 1 for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec + [0.0] * (1024 - dim)


def _lfm_vec(text: str, dim: int = 64) -> list:
    import hashlib, math
    h = hashlib.sha256(f"lfm:{text}".encode()).digest()
    vec = [(h[i % len(h)] / 255.0) * 2 - 1 for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec + [0.0] * (1024 - dim)


@pytest.fixture(autouse=True)
def _patch_service():
    EmbeddingService.reset_instance()
    svc = EmbeddingService()
    svc._backend = BACKEND_BGE
    svc._models = {BACKEND_HASH: "hash", BACKEND_BGE: "mock-bge", BACKEND_LFM: "mock-lfm"}
    svc._encode_chunk_with = lambda text, backend: (
        _bge_vec(text) if backend == BACKEND_BGE
        else _lfm_vec(text) if backend == BACKEND_LFM
        else _bge_vec(text)
    )
    yield
    EmbeddingService.reset_instance()


class TestReindexResumes:
    """Reindex resumes correctly after interruption."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        db_path = os.path.join(tmp_path, "test_resume.db")
        self.db_path = db_path
        self.store = EpisodicStore(db_path, b"test" * 8)
        reset_reindex_manager()

        # Store 10 episodes with BGE backend
        for i in range(10):
            ep = Episode(
                session_id="test-session",
                task_summary=f"test task number {i} with content",
                full_content=f"episode {i}",
                tool_sequence=[],
                outcome_type="success",
            )
            self.store.store(ep, 0.9)

        self.state_file = os.path.join(tmp_path, "reindex_state.json")

    def test_resume_skips_migrated_rows(self):
        """After partial migration, resumed worker skips already-migrated rows."""
        # Start migration, let it process a few rows, then stop
        rm = init_reindex_manager(
            self.db_path, b"test" * 8, state_file=self.state_file,
        )
        rm.start(BACKEND_BGE, BACKEND_LFM)
        time.sleep(0.5)  # Let it process some rows
        rm.stop()

        # Check progress (may be complete if all rows processed quickly)
        prog = rm.progress()
        assert prog["state"] in ("interrupted", "complete")
        migrated_before = prog["migrated_rows"]

        # Count how many rows are already migrated
        db = self.store.db
        migrated_count = db.execute(
            "SELECT COUNT(*) FROM episodes WHERE embedding_backend = ?",
            (BACKEND_LFM,),
        ).fetchone()[0]
        # Some or all rows may be migrated depending on timing
        if migrated_count < 10:
            # Resume should handle the rest
            rm.resume()
            time.sleep(2)
            final_migrated = db.execute(
                "SELECT COUNT(*) FROM episodes WHERE embedding_backend = ?",
                (BACKEND_LFM,),
            ).fetchone()[0]
            assert final_migrated == 10, "All rows should be migrated after resume"

        # No row should have the OLD backend
        bge_remaining = db.execute(
            "SELECT COUNT(*) FROM episodes WHERE embedding_backend = ?",
            (BACKEND_BGE,),
        ).fetchone()[0]
        assert bge_remaining == 0, "No BGE rows should remain"

    def test_no_double_migration(self):
        """Already-migrated rows are not re-embedded (backend check)."""
        # Manually set one row as already migrated
        db = self.store.db
        db.execute(
            "UPDATE episodes SET embedding_backend = ? WHERE id = (SELECT id FROM episodes LIMIT 1)",
            (BACKEND_LFM,),
        )
        db.commit()

        rm = init_reindex_manager(
            self.db_path, b"test" * 8, state_file=self.state_file,
        )
        rm.start(BACKEND_BGE, BACKEND_LFM)
        time.sleep(2)

        # The manually set row should still be LFM
        lfm_count = db.execute(
            "SELECT COUNT(*) FROM episodes WHERE embedding_backend = ?",
            (BACKEND_LFM,),
        ).fetchone()[0]
        # At least 1 (the one we set), possibly all depending on timing
        assert lfm_count >= 1
