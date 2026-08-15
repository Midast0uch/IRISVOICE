"""
Behavioral test: crash safety — vector written BEFORE backend mark.

If the worker crashes between writing the new vector and updating the
embedding_backend column, the row should still read as unmigrated and
be retried on resume.  No row is ever "migrated without a vector."

The test simulates this by creating a row whose vector has been updated
(to the LFM backend encoding) but whose embedding_backend still says BGE.
This is the state that would result from a crash after the first UPDATE.
"""

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
from backend.memory.episodic import EpisodicStore, Episode, _pack_embedding, _unpack_embedding
from backend.memory.reindex import (
    ReindexManager,
    init_reindex_manager,
    reset_reindex_manager,
    get_reindex_manager,
)


def _bge_vec(text: str) -> list:
    import hashlib, math
    h = hashlib.sha256(f"bge:{text}".encode()).digest()
    vec = [(h[i % len(h)] / 255.0) * 2 - 1 for i in range(64)]
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec + [0.0] * (1024 - 64)


def _lfm_vec(text: str) -> list:
    import hashlib, math
    h = hashlib.sha256(f"lfm:{text}".encode()).digest()
    vec = [(h[i % len(h)] / 255.0) * 2 - 1 for i in range(64)]
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec + [0.0] * (1024 - 64)


class TestWriteBeforeMark:
    """Crash between vector write and backend mark does not corrupt state."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        EmbeddingService.reset_instance()
        svc = EmbeddingService()
        svc._backend = BACKEND_BGE
        # TEST-INPUT FIX (2026-08-12, called out per AGENTS.md test rule):
        # `_load_active_backend()` resolves the backend from `_selected`, which
        # `__init__` takes from the config default — now `lfm25-emb-350m` after
        # the encoder migration. Without pinning `_selected` here, seeded rows
        # are stored as LFM and the test's premise ("row reads as BGE before
        # the mark is written") is silently void. Pinning `_selected` restores
        # the original fixture contract; assertions are unchanged.
        svc._selected = BACKEND_BGE
        svc._models = {BACKEND_HASH: "hash", BACKEND_BGE: "mock-bge", BACKEND_LFM: "mock-lfm"}
        svc._encode_chunk_with = lambda text, backend: (
            _bge_vec(text) if backend == BACKEND_BGE
            else _lfm_vec(text) if backend == BACKEND_LFM
            else _bge_vec(text)
        )

        db_path = os.path.join(tmp_path, "test_crash.db")
        self.db_path = db_path
        self.store = EpisodicStore(db_path, b"test" * 8)
        reset_reindex_manager()

        # Store 5 episodes
        for i in range(5):
            ep = Episode(
                session_id="test-session",
                task_summary=f"task number {i}",
                full_content=f"content {i}",
                tool_sequence=[],
                outcome_type="success",
            )
            self.store.store(ep, 0.9)

        self.state_file = os.path.join(tmp_path, "reindex_state.json")

        yield

        EmbeddingService.reset_instance()

    def test_half_migrated_row_is_retried(self):
        """A row with updated vector but OLD backend is retried on resume."""
        db = self.store.db

        # Get the first row's id and current state
        first_row = db.execute(
            "SELECT id, task_summary FROM episodes ORDER BY id LIMIT 1"
        ).fetchone()
        row_id, row_text = first_row

        # Simulate crash scenario: vector was updated to LFM encoding,
        # but backend was NOT updated (still BGE).
        lfm_vec = _lfm_vec(row_text)
        lfm_blob = _pack_embedding(lfm_vec)

        # Write the new vector (as if migration's first UPDATE happened)
        db.execute(
            "UPDATE episodes SET embedding = ? WHERE id = ?",
            (lfm_blob, row_id),
        )
        db.commit()
        # Do NOT update embedding_backend — this simulates the crash

        # Verify: row still reads as BACKEND_BGE (unmigrated)
        row = db.execute(
            "SELECT embedding_backend FROM episodes WHERE id = ?",
            (row_id,),
        ).fetchone()
        assert row[0] == BACKEND_BGE, "Backend should still be BGE after half-write"

        # Verify: the stored vector IS the LFM vector (migration started)
        stored_blob = db.execute(
            "SELECT embedding FROM episodes WHERE id = ?",
            (row_id,),
        ).fetchone()[0]
        stored_vec = _unpack_embedding(stored_blob)
        # 32-bit pack/unpack introduces slight precision loss; use approx
        for i in range(len(lfm_vec)):
            assert abs(stored_vec[i] - lfm_vec[i]) < 1e-5, (
                f"Vector mismatch at dim {i}: {stored_vec[i]} vs {lfm_vec[i]}"
            )

        # Resume should re-process this row (backend != LFM triggers re-embed)
        rm = init_reindex_manager(
            self.db_path, b"test" * 8, state_file=self.state_file,
        )
        rm.start(BACKEND_BGE, BACKEND_LFM)
        time.sleep(3)

        # After resume, row should be fully migrated
        final_row = db.execute(
            "SELECT embedding_backend FROM episodes WHERE id = ?",
            (row_id,),
        ).fetchone()
        assert final_row[0] == BACKEND_LFM, (
            f"Half-migrated row should be retried and migrated. "
            f"Got backend={final_row[0]}"
        )

    def test_fully_migrated_row_not_re_embedded(self):
        """A row already matching the target backend is untouched."""
        db = self.store.db

        # Pre-migrate one row manually
        first_row = db.execute(
            "SELECT id FROM episodes ORDER BY id LIMIT 1"
        ).fetchone()
        row_id = first_row[0]

        db.execute(
            "UPDATE episodes SET embedding_backend = ? WHERE id = ?",
            (BACKEND_LFM, row_id),
        )
        db.commit()

        # Start migration — verify the pre-migrated row keeps its backend
        rm = init_reindex_manager(
            self.db_path, b"test" * 8, state_file=self.state_file,
        )
        rm.start(BACKEND_BGE, BACKEND_LFM)
        time.sleep(3)

        row = db.execute(
            "SELECT embedding_backend FROM episodes WHERE id = ?",
            (row_id,),
        ).fetchone()
        assert row[0] == BACKEND_LFM, "Pre-migrated row should stay LFM"
