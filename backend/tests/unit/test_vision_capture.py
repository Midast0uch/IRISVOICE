"""Unit tests: screenshot capture dedup (REQ-5, T5).

AC5.1  the vision server's buffer is reused, not a second capture.
AC5.2  no duplicate screen capture per vision action.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.agent.tool_bridge import AgentToolBridge


class _VisionServer:
    """Stand-in that counts captures and offers a recent frame."""

    def __init__(self):
        self.capture_calls = 0
        self._recent = b"png-bytes"

    def recent_image(self, max_age_s: float = 5.0):
        return self._recent

    def screenshot_to_bytes(self):
        self.capture_calls += 1
        return b"fresh-png-bytes"


def _bridge(vision_server) -> AgentToolBridge:
    b = AgentToolBridge.__new__(AgentToolBridge)
    b._mcp_servers = {"vision": vision_server}
    return b


class TestReuseVisionServerBuffer:
    def test_reuse_vision_server_buffer(self):
        """AC5.1: the frame the vision tool JUST analyzed is reused — no
        second synchronous capture."""
        vs = _VisionServer()
        b = _bridge(vs)
        blob = b._capture_screenshot_blob()
        assert blob == b"png-bytes"
        assert vs.capture_calls == 0, "a second capture was executed"

    def test_no_duplicate_screen_capture(self):
        """AC5.2: no duplicate capture — the recent frame short-circuits."""
        vs = _VisionServer()
        b = _bridge(vs)
        for _ in range(3):
            b._capture_screenshot_blob()
        assert vs.capture_calls == 0

    def test_stale_frame_falls_back_to_fresh_capture(self):
        """A stale (or absent) recent frame falls back to a fresh capture —
        the dedup never attaches a frame the tool did not just analyze."""
        vs = _VisionServer()
        vs._recent = None
        b = _bridge(vs)
        blob = b._capture_screenshot_blob()
        assert blob == b"fresh-png-bytes"
        assert vs.capture_calls == 1

    def test_no_vision_server_returns_none(self):
        """No vision server → None, never raises."""
        b = AgentToolBridge.__new__(AgentToolBridge)
        b._mcp_servers = {}
        assert b._capture_screenshot_blob() is None
