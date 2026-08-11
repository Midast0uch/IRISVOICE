"""Contract CT-N1/N2/N3: the coordinate memory_chain store.

REQ-2 (design CT-N1/N2/N3):
  - CT-N1 (row shape): a DER step's chain row carries coords_from/coords_to,
    the outcome, and the insight — the coordinate contract.
  - CT-N2 (ALTER idempotence): running the engine migration twice leaves the
    schema and existing rows unchanged.
  - CT-N3 (db_path is the resolved target): resolve_memory_store_path returns
    exactly the memory_config.json db_path, repo-root-anchored — the ONE
    source of truth for every reader/writer (the decoy backend/data/memory.db
    must never be selected).
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile

import pytest

from backend.gateway.iris_ffi import _PythonFallbackEngine


def _copy_real_store(tmp_path) -> str:
    """Copy the configured store (data/memory.db) to a temp path so these
    contract tests never touch the real database."""
    src = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "memory.db")
    src = os.path.abspath(src)
    if not os.path.exists(src):
        pytest.skip(f"real store not found: {src}")
    dst = os.path.join(str(tmp_path), "memory.db")
    shutil.copy2(src, dst)
    return dst


def _cols(conn: sqlite3.Connection) -> set:
    return {r[1] for r in conn.execute("PRAGMA table_info(memory_chain)")}


class TestCTN1RowShape:
    def test_chain_row_carries_coords_outcome_insight(self, tmp_path):
        """CT-N1: an appended chain row lands with coords + outcome + insight."""
        db = _copy_real_store(tmp_path)
        eng = _PythonFallbackEngine(db_path=db, key_hex="00" * 32)
        rc = eng.immortus_chain_append(
            thread_id="ctn1-thread",
            result="success",
            coords_from="(0.1,0.2,1.0,0.3)",
            coords_to="(0.4,0.5,1.0,0.8)",
            nbl_outcome="step_1",
            insight="contract row",
            file_path="",
            landmark_id="",
        )
        assert rc == 0
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT chain_id, thread_id, result, coords_from, coords_to, "
            "nbl_outcome, insight FROM memory_chain WHERE thread_id=? "
            "ORDER BY rowid DESC LIMIT 1",
            ("ctn1-thread",),
        ).fetchone()
        conn.close()
        assert row is not None
        chain_id, thread_id, result, cfrom, cto, nbl, insight = row
        assert chain_id and thread_id == "ctn1-thread"
        assert result == "success"
        assert cfrom == "(0.1,0.2,1.0,0.3)"
        assert cto == "(0.4,0.5,1.0,0.8)"
        assert nbl == "step_1"
        assert insight == "contract row"


class TestCTN2AlterIdempotence:
    def test_migration_twice_is_identical(self, tmp_path):
        """CT-N2: two init() passes leave schema + legacy rows unchanged."""
        db = _copy_real_store(tmp_path)
        before_rows = sqlite3.connect(db).execute(
            "SELECT COUNT(*) FROM memory_chain"
        ).fetchone()[0]

        eng1 = _PythonFallbackEngine(db_path=db, key_hex="00" * 32)
        cols1 = _cols(sqlite3.connect(db))

        eng2 = _PythonFallbackEngine(db_path=db, key_hex="00" * 32)
        cols2 = _cols(sqlite3.connect(db))
        after_rows = sqlite3.connect(db).execute(
            "SELECT COUNT(*) FROM memory_chain"
        ).fetchone()[0]

        assert cols1 == cols2, f"schema drifted: {cols1} != {cols2}"
        assert after_rows == before_rows, f"rows changed: {before_rows} -> {after_rows}"
        assert {"chain_id", "coords_from", "coords_to", "stale"} <= cols2

    def test_legacy_rows_preserved_with_null_coords(self, tmp_path):
        """CT-N2/AC3: the original 1825 legacy rows survive with null coords."""
        db = _copy_real_store(tmp_path)
        _PythonFallbackEngine(db_path=db, key_hex="00" * 32)
        conn = sqlite3.connect(db)
        total = conn.execute("SELECT COUNT(*) FROM memory_chain").fetchone()[0]
        null_coords = conn.execute(
            "SELECT COUNT(*) FROM memory_chain WHERE coords_from IS NULL "
            "AND coords_to IS NULL"
        ).fetchone()[0]
        conn.close()
        assert total == 1825, f"expected 1825 legacy rows, got {total}"
        assert null_coords == 1825, f"expected all legacy coords null, got {null_coords}"


class TestCTN3DbPathSourceOfTruth:
    def test_resolver_returns_config_db_path(self):
        """CT-N3: resolve_memory_store_path returns the config's db_path,
        repo-root-anchored (never the decoy backend/data/memory.db)."""
        from backend.memory.config import (
            REPO_ROOT,
            resolve_memory_store_path,
        )

        p = resolve_memory_store_path()
        assert p.is_absolute()
        # Config says db_path = "data/memory.db" -> anchored at repo root.
        assert p == REPO_ROOT / "data" / "memory.db", p
        assert "backend" not in p.parts[-2], p  # never backend/data/...
