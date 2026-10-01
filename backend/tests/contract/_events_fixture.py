"""Shared fixture of the rule-emitter contract tests (taxonomy build step 2).

A REAL memory_events store (the Python chain engine on a temp file) behind the
REAL ``lane("memory_events")``: a chokepoint emits, the lane writes, the test
reads the row. Nothing about the writer is stubbed.
"""
from __future__ import annotations

import sqlite3
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import backend.gateway.iris_ffi as _ffi
from backend.memory import memory_events as me
from backend.utils.durability_queue import lane


@pytest.fixture()
def store(monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="evrule-")) / "memory.db"
    eng = _ffi._PythonFallbackEngine(db_path=str(tmp), key_hex="00" * 32)
    monkeypatch.setattr(_ffi, "_engine", eng)
    conn = sqlite3.connect(str(tmp), check_same_thread=False)
    me.ensure_schema(conn)
    yield conn
    lane("memory_events").flush(5.0)
    conn.close()
    eng._conn.close()


def memory_interface(conn):
    """The minimum the emit path reads: ``resolve_mycelium_conn`` finds ``_mycelium._conn``."""
    return SimpleNamespace(_mycelium=SimpleNamespace(_conn=conn))


def rows(conn, label=None):
    """Wait for the lane to drain, then the memory_events rows (oldest first)."""
    assert lane("memory_events").flush(10.0), "memory_events lane did not drain"
    cur = conn.execute("SELECT * FROM memory_events ORDER BY ts, rowid")
    cols = [d[0] for d in cur.description]
    out = [dict(zip(cols, r)) for r in cur.fetchall()]
    return [r for r in out if label is None or r["label"] == label]


class BlockedLane:
    """Hold lane("memory_events") busy so a test can prove a chokepoint does not wait on it."""

    def __init__(self):
        self.release = threading.Event()
        self.started = threading.Event()

    def __enter__(self):
        def _hold():
            self.started.set()
            self.release.wait(15)

        lane("memory_events").submit("test:block", _hold)
        assert self.started.wait(5), "the blocking job never started"
        return self

    def __exit__(self, *exc):
        self.release.set()
        lane("memory_events").flush(10.0)
