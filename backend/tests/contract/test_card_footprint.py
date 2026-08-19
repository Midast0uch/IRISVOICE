"""T5 (REQ-11): card footprints keyed by card_id.

Exercises backend/memory/card_footprint.py against a REAL SemanticStore
(tmp_path-isolated SQLite — never touches data/databases/memory.db), the
same "MemoryInterface.semantic" boundary backend/memory/skills.py already
writes through. No new store is exercised here — this pins that the
EXISTING SemanticStore.update/get interface is sufficient for REQ-11.
"""
import tempfile
from pathlib import Path

import pytest

from backend.memory.card_footprint import (
    CARD_FOOTPRINT_CATEGORY,
    get_card_footprint,
    save_card_footprint,
)
from backend.memory.semantic import SemanticStore


class _FakeMemoryInterface:
    """Minimal stand-in exposing only the `.semantic` boundary
    card_footprint.py actually uses — avoids paying for Mycelium/Caducean
    init that a real MemoryInterface pulls in."""

    def __init__(self, semantic: SemanticStore) -> None:
        self.semantic = semantic


@pytest.fixture
def memory():
    tmp_dir = Path(tempfile.mkdtemp(prefix="iris_test_card_footprint_"))
    db_path = tmp_dir / "test_semantic.db"
    store = SemanticStore(str(db_path), biometric_key=b"test_key_32_bytes_long_for_testing_")
    yield _FakeMemoryInterface(store)
    import gc
    import shutil

    del store
    gc.collect()
    shutil.rmtree(str(tmp_dir), ignore_errors=True)


class TestFootprintRoundTrip:
    def test_footprint_retrievable_by_card_id(self, memory):
        ok = save_card_footprint(
            memory,
            card_id="card_fp_1",
            conversation_id="conv_fp_1",
            objective="Research the weather",
            steps=[{"id": "s1", "verb": "search", "status": "done"}],
            tools_used=["web_search"],
            files_touched=[],
            outcome="converged",
        )
        assert ok is True

        footprint = get_card_footprint(memory, "card_fp_1")
        assert footprint is not None
        assert footprint["card_id"] == "card_fp_1"
        assert footprint["conversation_id"] == "conv_fp_1"
        assert footprint["objective"] == "Research the weather"
        assert footprint["tools_used"] == ["web_search"]
        assert footprint["outcome"] == "converged"
        assert "created_at" in footprint and "updated_at" in footprint

    def test_unknown_card_id_returns_none(self, memory):
        assert get_card_footprint(memory, "card_never_written") is None

    def test_retrieval_is_a_direct_keyed_lookup_not_a_scan(self, memory):
        """AC4: retrievable by card_id WITHOUT loading the whole
        conversation. Write several footprints across conversations, then
        confirm one card_id resolves to exactly its own record via
        SemanticStore.get(category, key) — a primary-key read, not a filter
        over every stored footprint."""
        for i in range(5):
            save_card_footprint(
                memory,
                card_id=f"card_{i}",
                conversation_id=f"conv_{i}",
                objective=f"task {i}",
                steps=[],
                tools_used=[],
                files_touched=[],
                outcome="converged",
            )
        entry = memory.semantic.get(CARD_FOOTPRINT_CATEGORY, "card_3")
        assert entry is not None
        footprint = get_card_footprint(memory, "card_3")
        assert footprint["card_id"] == "card_3"
        assert footprint["conversation_id"] == "conv_3"


class TestDuplicateCardIdUpdatesExisting:
    def test_duplicate_write_updates_rather_than_duplicates(self, memory):
        save_card_footprint(
            memory,
            card_id="card_dup",
            conversation_id="conv_dup",
            objective="first pass",
            steps=[],
            tools_used=[],
            files_touched=[],
            outcome="unknown",
        )
        first = get_card_footprint(memory, "card_dup")

        save_card_footprint(
            memory,
            card_id="card_dup",
            conversation_id="conv_dup",
            objective="revised objective",
            steps=[{"id": "s1", "status": "done"}],
            tools_used=["write_file"],
            files_touched=["foo.py"],
            outcome="converged",
        )
        second = get_card_footprint(memory, "card_dup")

        assert second["objective"] == "revised objective"
        assert second["outcome"] == "converged"
        assert second["files_touched"] == ["foo.py"]
        # created_at survives the update — only one footprint ever existed.
        assert second["created_at"] == first["created_at"]
        assert len(memory.semantic.get_by_category(CARD_FOOTPRINT_CATEGORY)) == 1


class TestUnfinishedCardRecordsActualState:
    def test_card_that_never_completes_records_reached_state(self, memory):
        """Edge case: a card never completes -> footprint records the
        TERMINAL state actually reached, never a fabricated success."""
        save_card_footprint(
            memory,
            card_id="card_abandoned",
            conversation_id="conv_abandoned",
            objective="Something interrupted",
            steps=[{"id": "s1", "status": "working"}],
            tools_used=["web_search"],
            files_touched=[],
            outcome="abandoned",
        )
        footprint = get_card_footprint(memory, "card_abandoned")
        assert footprint["outcome"] == "abandoned"


class TestFailedFootprintWriteNeverBlocks:
    """A failed footprint write must never block execution (REQ-11 edge
    case / T5 rule): save_card_footprint must swallow the failure and
    return False, never raise."""

    def test_save_returns_false_on_write_failure(self, memory, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("simulated semantic store failure")

        monkeypatch.setattr(memory.semantic, "update", _boom)

        result = save_card_footprint(
            memory,
            card_id="card_boom",
            conversation_id="conv_boom",
            objective="x",
            steps=[],
            tools_used=[],
            files_touched=[],
            outcome="unknown",
        )
        assert result is False

    def test_get_returns_none_on_read_failure(self, memory, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("simulated semantic store failure")

        monkeypatch.setattr(memory.semantic, "get", _boom)

        result = get_card_footprint(memory, "card_anything")
        assert result is None

    def test_missing_card_id_is_a_no_op_not_a_crash(self, memory):
        assert save_card_footprint(
            memory,
            card_id="",
            conversation_id="conv_x",
            objective="x",
            steps=[],
            tools_used=[],
            files_touched=[],
            outcome="unknown",
        ) is False
        assert get_card_footprint(memory, "") is None
