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


# ── REQ-5 AC5.4/AC5.5 (oracle-native-decision-surface, Wave 4): the capture
# returns the measured scale factor and the screen origin, additively. ──────

import pytest

from backend.vision import screen_capture as sc


class _FakeMss:
    """A two-monitor rig: 2560x1440 at (100, 50), 1280x720 at (0, 0)."""

    def __init__(self):
        self.monitors = [
            {"left": 0, "top": 0, "width": 3840, "height": 2160},
            {"left": 100, "top": 50, "width": 2560, "height": 1440},
            {"left": 0, "top": 0, "width": 1280, "height": 720},
        ]

    def grab(self, monitor):
        w, h = int(monitor["width"]), int(monitor["height"])
        return SimpleNamespace(width=w, height=h, rgb=b"\x00" * (w * h * 3))


@pytest.fixture
def capture():
    pytest.importorskip("PIL.Image")
    sc.ScreenCapture._instance = None
    sc.ScreenCapture._initialized = False
    cap = sc.ScreenCapture(max_width=1280)
    cap._mss = _FakeMss()
    cap._pil_available = True
    yield cap
    sc.ScreenCapture._instance = None
    sc.ScreenCapture._initialized = False


class TestCaptureFrameGeometry:
    def test_the_scale_factor_is_returned_not_dropped(self, capture):
        """AC5.4: a 2560-wide screen downscaled to max_width 1280 reports
        scale 0.5 - image px per screen px."""
        frame = capture.capture_frame(monitor_index=1, force=True)
        assert frame.is_new is True
        assert frame.scale == pytest.approx(0.5)
        assert frame.origin == (100, 50)

    def test_no_resize_means_scale_1(self, capture):
        """AC5.5: physical pixels are what mss returns; without a resize the
        scale is exactly 1, not a DPR guess."""
        frame = capture.capture_frame(monitor_index=2, force=True)
        assert frame.scale == pytest.approx(1.0)
        assert frame.origin == (0, 0)

    def test_a_region_capture_reports_the_region_origin(self, capture):
        frame = capture.capture_frame(region=(640, 360, 800, 600), force=True)
        assert frame.origin == (640, 360)
        assert frame.scale == pytest.approx(1.0)  # 800 wide < max_width

    def test_capture_base64_keeps_its_two_tuple(self, capture):
        """AC13.1: the additive shape is CapturedFrame; the historical
        2-tuple return of capture_base64 is UNCHANGED (its callers unpack
        exactly two values)."""
        b64, is_new = capture.capture_base64(monitor_index=1, force=True)
        assert isinstance(b64, str) and is_new is True

    def test_the_cached_frame_carries_its_geometry(self, capture):
        capture.capture_frame(monitor_index=1, force=True)
        cached = capture.capture_frame(monitor_index=1)  # TTL hit
        assert cached.is_new is False
        assert cached.scale == pytest.approx(0.5)
        assert cached.origin == (100, 50)

