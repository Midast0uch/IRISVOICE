"""Verify the media-pipeline 'black box' dispatch in ToolBridge routes
correctly to backend.tools.media_tools, resolving sources via MediaSource.

The downstream tools (ffmpeg/Parakeet/vision) are mocked so this tests the
wiring only — not the heavy analysis.
"""
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.agent.tool_bridge import AgentToolBridge  # noqa: E402


def _write_tmp(content=b"dummy", suffix=".mp4"):
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="iris_test_media_")
    os.write(fd, content)
    os.close(fd)
    return path


def test_execute_media_tool_transcribe_routes_and_resolves():
    p = _write_tmp()
    try:
        bridge = AgentToolBridge()
        canned = {"success": True, "transcript": "hello world", "language": "en"}
        with patch("backend.tools.media_tools.transcribe_media", return_value=canned) as m:
            import asyncio

            res = asyncio.run(
                bridge.execute_media_tool("transcribe_media", {"audio_path": p}, "sess")
            )
        assert res == canned
        # MediaSource resolved the local path and passed it through
        m.assert_called_once()
        assert m.call_args.args[0] == p
    finally:
        os.unlink(p)


def test_execute_media_tool_missing_file_returns_error():
    bridge = AgentToolBridge()
    import asyncio

    res = asyncio.run(
        bridge.execute_media_tool(
            "transcribe_media", {"audio_path": "C:\\nope\\missing.mp4"}, "sess"
        )
    )
    assert res.get("success") is False
    assert "not found" in res.get("error", "").lower()


def test_execute_media_tool_unknown_returns_error():
    bridge = AgentToolBridge()
    import asyncio

    res = asyncio.run(
        bridge.execute_media_tool("not_a_media_tool", {"x": 1}, "sess")
    )
    assert res.get("success") is False
    assert "unknown media tool" in res.get("error", "")
