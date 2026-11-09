"""A failed app-store write is closed and visible (2026-11-09 memory writer audit).

  * app_write's fallback path rolled nothing back: a failed statement left the
    implicit transaction - and the WAL write lock - open on a SHARED
    connection until some later commit. It now rolls back and still raises.
  * a row the native writer FAILED or DROPPED was counted only inside
    ffi_native_write_stats(), which nothing but a test read. The turn end now
    logs the growth (report_native_write_losses).
"""
from __future__ import annotations

import logging
import sqlite3

import pytest

from backend.memory import db as memdb


def test_a_failed_fallback_write_leaves_no_open_transaction():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (x INTEGER PRIMARY KEY)")
    memdb.app_write(conn, "INSERT INTO t VALUES (1)")
    conn.execute("BEGIN")
    conn.execute("INSERT INTO t VALUES (2)")  # a write left pending before the failure
    with pytest.raises(sqlite3.IntegrityError):
        memdb.app_write(conn, "INSERT INTO t VALUES (1)")
    assert not conn.in_transaction, "the failed write left the transaction open"


def test_native_losses_are_logged_once_per_growth(monkeypatch, caplog):
    import backend.gateway.iris_ffi as ffi

    stats = {"queued": 10, "written": 8, "failed": 0, "dropped": 0}
    monkeypatch.setattr(ffi, "ffi_native_write_stats", lambda: dict(stats))
    monkeypatch.setattr(memdb, "_LAST_WRITE_LOSSES", {"failed": 0, "dropped": 0})
    caplog.set_level(logging.WARNING, logger=memdb.logger.name)
    assert memdb.report_native_write_losses("t1") == {"failed": 0, "dropped": 0}
    assert not caplog.records
    stats.update(failed=2, dropped=1)
    assert memdb.report_native_write_losses("t2") == {"failed": 2, "dropped": 1}
    assert any("failed +2 dropped +1" in r.getMessage() for r in caplog.records)
    caplog.clear()
    memdb.report_native_write_losses("t3")
    assert not caplog.records, "no growth, no warning"
