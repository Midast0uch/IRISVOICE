"""Contract: deleting a thread must purge its Immortus chain, and say so truthfully.

DEFECT (measured 2026-10-30, conv-5087): ``DELETE /api/chat/threads/{id}``
returned ``{"deleted": true}`` while all 17 chain rows were still present.
Two faults, one shape — a claim about the store that nobody checked:

  * ``IrisCoreEngine.immortus_chain_keep_latest`` asked the NATIVE core first
    and returned its ``-1`` as final. Measured on a healthy freshly-initialized
    store (probe 2026-10-31: 5 appends, ``keep_latest(thread, 0) -> -1``, all 5
    rows still present), so the native symbol cannot purge at all, and the
    Python engine that CAN purge was never called.
  * The endpoint wrapped the call in ``except Exception: pass`` and never
    looked at the return value.

A surviving chain row is not cosmetic: the recall legs read ``memory_chain``,
so the next turn can still answer a fact from a "deleted" thread.

Read path: ``GET /api/chat/threads/{id}`` used to read ``_engine._conn`` and
order by ``chain_index``. IrisCoreEngine has no ``_conn`` and no schema has a
``chain_index`` column, so both raised into a debug-level catch and the thread
detail always showed an empty chain.
"""
from __future__ import annotations

import sqlite3

import pytest

from backend.gateway.iris_ffi import IrisCoreEngine, _PythonFallbackEngine


KEY_HEX = "00" * 32
THREAD = "conv-purge-test"


def _engine_on(tmp_path) -> _PythonFallbackEngine:
    eng = _PythonFallbackEngine(str(tmp_path / "memory.db"), KEY_HEX)
    for i in range(5):
        eng._conn.execute(
            "INSERT INTO memory_chain (chain_id, thread_id, result, insight, "
            "created_at) VALUES (?, ?, 'chat', ?, ?)",
            (f"c{i}", THREAD, f"insight {i}", 1000.0 + i),
        )
    eng._conn.execute(
        "INSERT INTO memory_chain (chain_id, thread_id, result, insight, "
        "created_at) VALUES ('other', 'other-thread', 'chat', 'keep me', 2000.0)"
    )
    eng._conn.commit()
    return eng


class _NativeStub:
    """The native symbol's measured behaviour: -1, nothing deleted."""

    def __init__(self, rc: int = -1):
        self.rc = rc
        self.calls = 0

    def immortus_chain_keep_latest(self, thread_id, keep_count):
        self.calls += 1
        return self.rc


def _rows(eng: _PythonFallbackEngine, thread: str = THREAD) -> int:
    return eng._conn.execute(
        "SELECT COUNT(*) FROM memory_chain WHERE thread_id = ?", (thread,)
    ).fetchone()[0]


# ── the Python engine: actual rows, not a plan ───────────────────────────


def test_purge_removes_every_row_of_the_thread(tmp_path):
    eng = _engine_on(tmp_path)
    assert eng.immortus_chain_keep_latest(THREAD, 0) == 5
    assert _rows(eng) == 0
    assert _rows(eng, "other-thread") == 1, "another thread's rows must survive"


def test_purge_keeps_the_latest_n_and_reports_what_left(tmp_path):
    eng = _engine_on(tmp_path)
    assert eng.immortus_chain_keep_latest(THREAD, 2) == 3
    assert _rows(eng) == 2
    kept = [
        r[0]
        for r in eng._conn.execute(
            "SELECT insight FROM memory_chain WHERE thread_id = ? "
            "ORDER BY created_at",
            (THREAD,),
        )
    ]
    assert kept == ["insight 3", "insight 4"], "the newest rows must be the kept ones"


def test_purge_purges_rows_with_a_null_chain_id(tmp_path):
    """1,820 live rows have a NULL chain_id. When such a row is among the rows
    being KEPT, ``chain_id NOT IN (SELECT chain_id ...)`` compares against NULL
    and every comparison is NULL — the DELETE removes nothing, while the old
    return value (``total - keep_count``) still reported a purge."""
    eng = _engine_on(tmp_path)
    eng._conn.execute(
        "INSERT INTO memory_chain (chain_id, thread_id, result, created_at) "
        "VALUES (NULL, ?, 'chat', 9000.0)",
        (THREAD,),
    )
    eng._conn.commit()

    assert eng.immortus_chain_keep_latest(THREAD, 1) == 5
    assert _rows(eng) == 1, "the keep-latest row must be the NULL-chain_id one"
    kept = eng._conn.execute(
        "SELECT chain_id FROM memory_chain WHERE thread_id = ?", (THREAD,)
    ).fetchone()[0]
    assert kept is None


def test_purge_returns_minus_one_when_the_delete_never_lands(tmp_path, monkeypatch):
    """A queued write that is dropped must not be reported as a purge."""
    eng = _engine_on(tmp_path)
    import backend.memory.db as db

    monkeypatch.setattr(db, "app_write", lambda *a, **k: None)
    assert eng.immortus_chain_keep_latest(THREAD, 0) == -1
    assert _rows(eng) == 5, "the test must prove the rows really survived"


# ── the wrapper: a native -1 is not an answer ────────────────────────────


def test_native_minus_one_falls_back_to_the_python_engine(tmp_path):
    """THE D1 GUARD. The old wrapper returned the native -1 and stopped."""
    eng = object.__new__(IrisCoreEngine)
    eng._ffi = _NativeStub(-1)
    eng._fallback = _engine_on(tmp_path)

    removed = eng.immortus_chain_keep_latest(THREAD, 0)

    assert removed == 5, "the purge must happen through the Python engine"
    assert _rows(eng._fallback) == 0
    assert eng._ffi.calls == 1, "the native engine is still tried first"
    assert _rows(eng._fallback, "other-thread") == 1


def test_native_success_is_not_double_deleted(tmp_path):
    eng = object.__new__(IrisCoreEngine)
    eng._ffi = _NativeStub(0)
    eng._fallback = _engine_on(tmp_path)

    assert eng.immortus_chain_keep_latest(THREAD, 0) == 0
    assert _rows(eng._fallback) == 5, "a native rc>=0 must not be re-run on Python"


def test_no_engine_at_all_returns_minus_one():
    eng = object.__new__(IrisCoreEngine)
    eng._ffi = None
    eng._fallback = None
    assert eng.immortus_chain_keep_latest(THREAD, 0) == -1


# ── the read path the API uses ───────────────────────────────────────────


def test_thread_detail_reads_the_chain_newest_first(tmp_path):
    eng = object.__new__(IrisCoreEngine)
    eng._ffi = None
    eng._fallback = _engine_on(tmp_path)

    rows = eng.immortus_chain_recent(THREAD, limit=3)

    assert [r["insight"] for r in rows] == ["insight 4", "insight 3", "insight 2"]
    assert rows[0]["result"] == "chat"


def test_thread_detail_is_empty_without_an_engine():
    eng = object.__new__(IrisCoreEngine)
    eng._ffi = None
    eng._fallback = None
    assert eng.immortus_chain_recent(THREAD) == []


# ── the endpoint: report what happened ───────────────────────────────────


@pytest.fixture()
def api_thread():
    from backend.conversation_store import create_conversation, delete_conversation

    conv = create_conversation(
        conv_id="conv-delete-contract", title="Delete Contract"
    )
    yield conv["id"]
    delete_conversation(conv["id"])


def test_delete_endpoint_reports_a_failed_purge(api_thread, monkeypatch):
    import backend.gateway.iris_ffi as ffi
    from fastapi.testclient import TestClient
    from backend.main import app

    monkeypatch.setattr(
        ffi, "ffi_immortus_chain_keep_latest", lambda thread_id, keep: -1
    )

    data = TestClient(app).delete(f"/api/chat/threads/{api_thread}").json()

    assert data["deleted"] is True
    assert data["chain_purged"] is False, (
        "the endpoint must not claim a purge the engine refused"
    )
    assert data["chain_rows_removed"] is None


def test_delete_endpoint_reports_the_rows_it_removed(api_thread, monkeypatch):
    import backend.gateway.iris_ffi as ffi
    from fastapi.testclient import TestClient
    from backend.main import app

    monkeypatch.setattr(
        ffi, "ffi_immortus_chain_keep_latest", lambda thread_id, keep: 17
    )

    data = TestClient(app).delete(f"/api/chat/threads/{api_thread}").json()

    assert data["deleted"] is True
    assert data["chain_purged"] is True
    assert data["chain_rows_removed"] == 17


def test_thread_detail_endpoint_shows_the_chain(api_thread, monkeypatch):
    import backend.gateway.iris_ffi as ffi
    from fastapi.testclient import TestClient
    from backend.main import app

    monkeypatch.setattr(
        ffi,
        "ffi_immortus_chain_recent",
        lambda thread_id, limit=20: [
            {"result": "chat", "nbl_outcome": "answered", "insight": "hello",
             "coords_from": None, "coords_to": None, "timestamp": 1.0}
        ],
    )

    data = TestClient(app).get(f"/api/chat/threads/{api_thread}").json()

    assert [r["insight"] for r in data["immortus_chain"]] == ["hello"]
