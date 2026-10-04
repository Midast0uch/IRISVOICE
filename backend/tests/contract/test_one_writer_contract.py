"""ONE WRITER (2026-10-04) - app-store writes go to the native core's writer.

data/memory.db is WAL: one writer at a time. Several Python connections and the
native core each wrote it, so every write waited on the others' lock
(busy_timeout 5 s) and then failed: live 2026-10-04 a 22 s gap in a 42 s reply,
8 lost rows in 5 eval tasks.

Contract (backend/memory/db.py app_write -> iris_ffi.ffi_native_write ->
iris_core db_submit_write):
  1. a write to the file the native core owns is QUEUED: the caller returns at
     once even while another connection holds the write lock (the old path,
     conn.execute + commit, waits the 5 s busy_timeout);
  2. the queued rows land, in order, once the lock is free (app_flush);
  3. a connection the native core does not own writes itself, as before.
Runs against the real iris_core.dll on a temporary plaintext store.
"""
from __future__ import annotations

import sqlite3
import time

import pytest

from backend.gateway import iris_ffi
from backend.memory import db as memdb

pytestmark = pytest.mark.skipif(
    iris_ffi._find_dll() is None, reason="iris_core.dll not built on this machine")


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    path = tmp_path_factory.mktemp("one_writer") / "memory.db"
    seed = sqlite3.connect(path)
    seed.execute("PRAGMA journal_mode=WAL")
    seed.execute("CREATE TABLE ow_rows (k INTEGER, v TEXT, b BLOB, f REAL, n TEXT)")
    seed.commit()
    seed.close()
    prev = iris_ffi._engine
    iris_ffi._engine = None
    iris_ffi.IrisCoreEngine._instance = None
    assert iris_ffi.ffi_init_engine(str(path), "00" * 32)
    eng = iris_ffi._engine
    if not getattr(getattr(eng, "_ffi", None), "has_writer", False):
        pytest.skip("iris_core.dll has no db_submit_write (old build)")
    conn = memdb.open_encrypted_memory(str(path), b"\x00" * 32)
    yield path, conn
    conn.close()
    iris_ffi._engine = prev


def _count(path, where="1=1"):
    c = sqlite3.connect(path)
    try:
        return c.execute(f"SELECT count(*) FROM ow_rows WHERE {where}").fetchone()[0]
    finally:
        c.close()


def test_app_write_is_queued_while_the_store_is_locked(store):
    path, conn = store
    assert getattr(conn, "store_path", ""), "the app-store connection knows its file"
    blocker = sqlite3.connect(path, timeout=0.1)
    blocker.execute("BEGIN IMMEDIATE")  # another writer holds the lock
    try:
        t0 = time.perf_counter()
        for k in range(100):
            memdb.app_write(conn, "INSERT INTO ow_rows (k, v, b, f, n) VALUES (?, ?, ?, ?, ?)",
                            (k, f"row {k}", b"\x00\x01", k / 2, None))
        took = time.perf_counter() - t0
        # The old path waits busy_timeout (5 s) on the FIRST row. 1 s is far
        # above 100 queue submits (measured ~ms) and far below one lock wait.
        assert took < 1.0, f"app_write waited on the locked store ({took:.2f} s)"
    finally:
        blocker.rollback()
        blocker.close()
    assert memdb.app_flush(10.0)
    assert _count(path, "v LIKE 'row %'") == 100
    c = sqlite3.connect(path)
    row = c.execute("SELECT k, v, b, f, n FROM ow_rows WHERE k = 7").fetchone()
    c.close()
    assert row == (7, "row 7", b"\x00\x01", 3.5, None), "every type round-trips"


def test_queued_rows_land_in_order(store):
    path, conn = store
    for k in range(1000, 1300):
        memdb.app_write(conn, "INSERT INTO ow_rows (k, v) VALUES (?, ?)", (k, "ordered"))
    assert memdb.app_flush(10.0)
    c = sqlite3.connect(path)
    ks = [r[0] for r in c.execute("SELECT k FROM ow_rows WHERE v = 'ordered' ORDER BY rowid")]
    c.close()
    assert ks == list(range(1000, 1300))
    stats = iris_ffi.ffi_native_write_stats()
    assert stats["written"] >= 400 and stats["dropped"] == 0


def test_a_connection_the_native_core_does_not_own_writes_itself(tmp_path):
    other = sqlite3.connect(tmp_path / "other.db")
    other.execute("CREATE TABLE t (x INTEGER)")
    memdb.app_write(other, "INSERT INTO t (x) VALUES (?)", (5,))
    assert other.execute("SELECT x FROM t").fetchall() == [(5,)]
    other.close()
