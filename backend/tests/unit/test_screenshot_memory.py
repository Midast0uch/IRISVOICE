"""Tests: screenshots are stored in the application memory (SQLite system_events)
attached to the tool-execution event, like every other event.

Covers:
- The SQLite writer (_PythonFallbackEngine.ingest_event) stores a screenshot BLOB.
- ToolBridge._capture_screenshot_blob returns bytes when the vision server can
  capture, None otherwise.
- ToolBridge._record_tool_event forwards screenshot_blob to ffi_ingest_event.
"""
import os
import sys
import tempfile
import sqlite3
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.gateway.iris_ffi import _PythonFallbackEngine  # noqa: E402
from backend.agent.tool_bridge import AgentToolBridge  # noqa: E402


def _read_back(db: str):
    """Read back the way the engine wrote it (Dilithium migration: the
    fallback engine encrypts with sqlcipher3 when available, so a plain
    sqlite3 open fails with 'file is not a database')."""
    try:
        import sqlcipher3  # type: ignore[import]
    except ImportError:
        return sqlite3.connect(db)
    conn = sqlcipher3.connect(db)
    conn.execute("PRAGMA key = \"x'" + ("00" * 32) + "'\";")
    return conn


def test_fallback_ingest_event_stores_screenshot_blob():
    db = tempfile.mktemp(suffix=".db")
    eng = _PythonFallbackEngine(db, "00" * 32)
    try:
        rc = eng.ingest_event(
            "sess1", "SYSTEM", "tool_execution", "agent", "success",
            "take_screenshot", '{"tool": "take_screenshot"}',
            screenshot_blob=b"FAKEPNGDATA",
        )
        assert rc == 0
        conn = _read_back(db)
        try:
            row = conn.execute("SELECT screenshot FROM system_events").fetchone()
            assert row is not None
            assert row[0] == b"FAKEPNGDATA"
        finally:
            conn.close()
    finally:
        eng._conn.close()
        if os.path.exists(db):
            os.unlink(db)


def test_fallback_ingest_event_without_screenshot_is_null():
    db = tempfile.mktemp(suffix=".db")
    eng = _PythonFallbackEngine(db, "00" * 32)
    try:
        eng.ingest_event(
            "sess1", "SYSTEM", "tool_execution", "agent", "success",
            "speak", '{"tool": "speak"}',
        )
        conn = _read_back(db)
        try:
            row = conn.execute("SELECT screenshot FROM system_events").fetchone()
            assert row[0] is None
        finally:
            conn.close()
    finally:
        eng._conn.close()
        if os.path.exists(db):
            os.unlink(db)


def test_capture_screenshot_blob_returns_bytes_when_vision_available():
    bridge = AgentToolBridge()
    vision_server = MagicMock()
    vision_server.screenshot_to_bytes.return_value = b"PNG_BYTES"
    bridge._mcp_servers = {"vision": vision_server}
    assert bridge._capture_screenshot_blob() == b"PNG_BYTES"


def test_capture_screenshot_blob_returns_none_when_no_vision():
    bridge = AgentToolBridge()
    bridge._mcp_servers = {}
    assert bridge._capture_screenshot_blob() is None


def test_record_tool_event_forwards_screenshot_blob():
    bridge = AgentToolBridge()
    with patch("backend.gateway.iris_ffi.ffi_ingest_event") as mock_ingest:
        bridge._record_tool_event(
            "sess1", "take_screenshot", "success",
            {"x": 1}, {"success": True}, screenshot_blob=b"SHOT",
        )
    assert mock_ingest.called
    _, kwargs = mock_ingest.call_args
    assert kwargs.get("screenshot_blob") == b"SHOT"
    assert kwargs.get("event_type") == "tool_execution"
