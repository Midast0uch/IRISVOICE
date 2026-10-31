"""Contract: the native `forget` tool removes a stored fact from BOTH records.

`forget` is the undo of `remember`. Two records carry a taught fact, so both
must be touched:

  * the pin (`mycelium_pins`, title `fact:<attribute>`) — removed through
    `corrections.correct(..., "unpin", ...)`, the app's own delete, which writes
    the PIN_CORRECTED ledger event and keeps a 600 s undo;
  * the Immortus chain rows that quote the value — marked `stale = 1`, so they
    stay as history but leave every recall leg.

Measured 2026-10-30: with only the pin deleted, the next turn still answered the
value, because the recall legs read the chain. Before this tool the agent had no
way to delete a fact at all — only the memory UI could.
"""
from __future__ import annotations

import sqlite3

from backend.agent.tool_bridge import (
    _forget_memory_payload,
    _recall_memory_payload,
    _remember_memory_payload,
)
from backend.memory.pin_store import PinStore

VALUE = "locker-live-77"


def _make_app_db(tmp_path) -> sqlite3.Connection:
    """A FILE-backed, thread-safe store: corrections run on the memory lane, so
    an in-memory connection created on the test thread cannot be used there."""
    conn = sqlite3.connect(str(tmp_path / "app.db"), check_same_thread=False)
    conn.executescript("""
        CREATE TABLE mycelium_pins (
            pin_id TEXT PRIMARY KEY, title TEXT NOT NULL,
            pin_type TEXT DEFAULT 'note', content TEXT,
            tags TEXT DEFAULT '[]', file_refs TEXT DEFAULT '[]',
            image_refs TEXT DEFAULT '[]', url_refs TEXT DEFAULT '[]',
            project_id TEXT, origin_id TEXT,
            created_at REAL NOT NULL, updated_at REAL NOT NULL,
            is_permanent INTEGER DEFAULT 0
        );
        CREATE TABLE mycelium_pin_links (
            link_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL, source_id TEXT NOT NULL,
            target_type TEXT NOT NULL, target_id TEXT NOT NULL,
            relationship TEXT NOT NULL, weight REAL DEFAULT 1.0,
            created_at REAL NOT NULL
        );
        CREATE TABLE memory_chain (
            entry_id INTEGER PRIMARY KEY, thread_id TEXT, role TEXT,
            insight TEXT, content TEXT, node_type TEXT, stale INTEGER DEFAULT 0
        );
        CREATE TABLE context_chunks (
            id INTEGER PRIMARY KEY, session_id TEXT, chunk_type TEXT,
            zone TEXT, content TEXT, tool_name TEXT, folded_into TEXT
        );
    """)
    return conn


def _teach_in_chain(conn, text: str) -> None:
    conn.execute(
        "INSERT INTO memory_chain (thread_id, role, insight, content, node_type) "
        "VALUES ('conv-1', 'user', ?, ?, 'user_turn')", (text, text)
    )
    conn.commit()


class _EpisodicStub:
    def __init__(self, conn):
        self.db = conn

    def retrieve_context_chunks(self, *a, **k):
        return []

    def retrieve_similar(self, *a, **k):
        return []


def test_forget_deletes_the_pin_and_recall_stops_returning_it(tmp_path):
    conn = _make_app_db(tmp_path)
    _remember_memory_payload(conn, "locker code", VALUE)
    assert _recall_memory_payload(_EpisodicStub(conn), "locker code")["pins"]

    out = _forget_memory_payload(conn, "locker code")

    assert out["success"] is True and out["deleted"] is True
    assert PinStore(conn).list() == []
    assert _recall_memory_payload(
        _EpisodicStub(conn), "locker code"
    )["pins"] == []


def test_forget_writes_the_corrections_ledger_so_it_can_be_undone(tmp_path):
    conn = _make_app_db(tmp_path)
    _remember_memory_payload(conn, "locker code", VALUE)

    out = _forget_memory_payload(conn, "locker code")

    assert out["correction_id"], "the delete left no ledger record"
    assert out["undo_until"], "the delete has no undo window"
    rows = conn.execute(
        "SELECT COUNT(*) FROM memory_events WHERE family='memory' AND label='PIN_CORRECTED'"
    ).fetchone()[0]
    assert rows >= 1, "no PIN_CORRECTED event was written"


def test_forget_takes_the_value_out_of_every_recall_leg(tmp_path):
    """Three records can carry the fact. Staling the chain alone was not enough:
    measured 2026-10-30, the turn-pair chunk still carried the value and the next
    turn answered it."""
    conn = _make_app_db(tmp_path)
    _remember_memory_payload(conn, "locker code", VALUE)
    _teach_in_chain(conn, f"Remember this for later: my locker code is {VALUE}.")
    conn.execute(
        "INSERT INTO context_chunks (session_id, chunk_type, content, tool_name) "
        "VALUES ('conv-1', 'context_fragment', ?, 'user_turn')",
        (f"User: my locker code is {VALUE}\nAssistant: noted",),
    )
    conn.commit()

    out = _forget_memory_payload(conn, "locker code")

    assert out["chain_rows_staled"] == 1
    assert out["chunks_folded"] == 1
    assert conn.execute(
        "SELECT stale FROM memory_chain WHERE node_type='user_turn'"
    ).fetchone()[0] == 1, "the chain still offers the forgotten value to recall"
    assert conn.execute(
        "SELECT folded_into FROM context_chunks"
    ).fetchone()[0] == "forgotten-by-user", "the chunk still offers it to recall"


def test_forget_of_a_missing_fact_is_a_success_with_deleted_false(tmp_path):
    conn = _make_app_db(tmp_path)
    out = _forget_memory_payload(conn, "blood type")
    assert out["success"] is True
    assert out["deleted"] is False


def test_forget_refuses_when_the_value_does_not_match(tmp_path):
    conn = _make_app_db(tmp_path)
    _remember_memory_payload(conn, "locker code", "990001")

    out = _forget_memory_payload(conn, "locker code", "880417")

    assert out["success"] is False
    assert out["deleted"] is False
    assert len(PinStore(conn).list()) == 1, "a stale value must not delete the fact"


def test_forget_accepts_a_matching_value(tmp_path):
    conn = _make_app_db(tmp_path)
    _remember_memory_payload(conn, "locker code", "990001")

    out = _forget_memory_payload(conn, "locker code", "990001")

    assert out["success"] is True and out["deleted"] is True
    assert PinStore(conn).list() == []


def test_forget_rejects_an_empty_attribute(tmp_path):
    conn = _make_app_db(tmp_path)
    assert _forget_memory_payload(conn, "")["success"] is False
    assert _forget_memory_payload(conn, "   ")["success"] is False


def test_forget_is_in_the_bridge_menu_the_model_actually_sees():
    """DEFECT (2026-10-30, measured live): `forget` was added to the registry but
    NOT to ``AgentToolBridge.get_available_tools()``, which is the menu the direct
    path hands to the model. The model never saw the tool, so it answered "Done —
    I've wiped your locker code from memory" without calling anything, and the pin
    was still in the store. TWO menus exist; both must list it.
    """
    from backend.agent.tool_bridge import AgentToolBridge

    names = {t.get("name") for t in AgentToolBridge().get_available_tools()}
    assert "forget" in names, "the model cannot call a tool it is not offered"
    assert "remember" in names
    assert "recall_memory" in names


def test_forget_is_registered_and_not_offered_inside_a_node():
    from backend.agent.node_executor import NODE_TOOLS
    from backend.agent.tool_registry import resolve_tool

    spec = resolve_tool("forget")
    assert spec is not None, "the model cannot call a tool that is not registered"
    assert spec.permission_tier == "side_effect"
    assert "forget" not in NODE_TOOLS, "a DER step must not delete user facts"
