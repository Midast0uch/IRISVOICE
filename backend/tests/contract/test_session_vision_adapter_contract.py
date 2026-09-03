"""Contract tests for SessionVisionAdapter (T18 live fix).

Hermetic: fake session + fake provider, no browser, no network, no live
vision server. Asserts the adapter binds BrowserSession (frames + scrolling)
and the real vision provider's img_bytes-first surface into exactly what
``frame_extraction.extract_page_frames`` expects, and — REQ-9 AC2, absolute —
that every frame the adapter hands the provider comes from the SESSION, never
``backend.tools.lfm_vl_provider.screenshot_to_bytes()`` (the desktop capture).
"""

import asyncio

import pytest

from backend.vision.browser_session import VisionAction
from backend.vision.session_vision_adapter import SessionVisionAdapter


class _FakeSession:
    """Records every screenshot/act call; returns a distinct, recognizable
    frame so a test can prove THIS bytes value (not some other source) is
    what reached the provider."""

    SESSION_FRAME = b"SESSION-SCOPED-FRAME-BYTES"

    def __init__(self):
        self.screenshot_calls = 0
        self.acts: list[VisionAction] = []

    async def screenshot(self):
        self.screenshot_calls += 1
        return self.SESSION_FRAME

    async def act(self, action: VisionAction):
        self.acts.append(action)


class _FakeProvider:
    """Records the img_bytes it was actually called with, real-signature
    shaped (img_bytes-first, synchronous — like LFMVLProvider)."""

    def __init__(self):
        self.describe_calls = []
        self.read_text_calls = []
        self.analyze_calls = []

    def describe_live_frame(self, img_bytes):
        self.describe_calls.append(img_bytes)
        return "generic description"

    def read_text(self, img_bytes):
        self.read_text_calls.append(img_bytes)
        return "ocr text"

    def analyze_screen(self, img_bytes, question=""):
        self.analyze_calls.append((img_bytes, question))
        return "analysis text"


# ── REQ-9 AC2: screenshot_to_bytes is ALWAYS session-scoped ────────────────

def test_screenshot_to_bytes_comes_from_the_session_never_the_desktop(monkeypatch):
    """The adapter must NEVER reach for lfm_vl_provider.screenshot_to_bytes
    (desktop capture). Patch the desktop function to explode — if the
    adapter ever called it, this test would fail loudly instead of silently
    leaking a desktop screenshot into a websearch path."""
    import backend.tools.lfm_vl_provider as lfm_vl_provider

    def _desktop_capture_must_never_be_called(*a, **k):
        raise AssertionError(
            "SessionVisionAdapter called the DESKTOP screenshot_to_bytes() "
            "— REQ-9 AC2 violation: vision input must be browser-scoped only"
        )

    monkeypatch.setattr(lfm_vl_provider, "screenshot_to_bytes", _desktop_capture_must_never_be_called)

    session = _FakeSession()
    provider = _FakeProvider()
    adapter = SessionVisionAdapter(session, provider)

    result = asyncio.run(adapter.screenshot_to_bytes())

    assert result == _FakeSession.SESSION_FRAME
    assert session.screenshot_calls == 1


def test_describe_live_frame_and_read_text_and_analyze_screen_use_session_frame():
    """Every VLM-facing method captures ITS frame from the session, not a
    module-level or cached desktop image, and forwards those exact bytes to
    the real provider's img_bytes-first methods."""
    session = _FakeSession()
    provider = _FakeProvider()
    adapter = SessionVisionAdapter(session, provider)

    asyncio.run(adapter.describe_live_frame("triage prompt: exactly one word"))
    asyncio.run(adapter.read_text())
    asyncio.run(adapter.analyze_screen("Extract all visible text verbatim."))

    # describe_live_frame is routed through analyze_screen (real
    # describe_live_frame ignores custom prompts — see the adapter's
    # docstring) so provider.describe_live_frame itself is never called.
    assert provider.describe_calls == []
    assert len(provider.analyze_calls) == 2
    for img_bytes, _question in provider.analyze_calls:
        assert img_bytes == _FakeSession.SESSION_FRAME
    assert provider.read_text_calls == [_FakeSession.SESSION_FRAME]
    assert session.screenshot_calls == 3  # one capture per VLM-facing call


# ── scrolling delegates to session.act(VisionAction(kind="scroll")) ────────

def test_scroll_down_drives_session_act_with_scroll_action():
    session = _FakeSession()
    adapter = SessionVisionAdapter(session, _FakeProvider())

    asyncio.run(adapter.scroll_down(delta=500))

    assert len(session.acts) == 1
    assert session.acts[0].kind == "scroll"
    assert session.acts[0].value == "500"


# ── degraded session: no frame available -> empty string, never raises ─────

def test_no_frame_available_degrades_to_empty_string_not_raise():
    class _EmptySession(_FakeSession):
        async def screenshot(self):
            self.screenshot_calls += 1
            return None

    adapter = SessionVisionAdapter(_EmptySession(), _FakeProvider())

    assert asyncio.run(adapter.describe_live_frame("prompt")) == ""
    assert asyncio.run(adapter.read_text()) == ""
    assert asyncio.run(adapter.analyze_screen("question")) == ""


# ── extract_page_frames end-to-end through the real adapter (no browser) ──

def test_adapter_satisfies_extract_page_frames_protocol_end_to_end():
    """The adapter is not just structurally compatible — driving it through
    the REAL extract_page_frames loop must actually produce frames."""
    from backend.vision.frame_extraction import SessionBounds, extract_page_frames

    class _TriageThenStopProvider(_FakeProvider):
        def __init__(self):
            super().__init__()
            self._n = 0

        def analyze_screen(self, img_bytes, question=""):
            self.analyze_calls.append((img_bytes, question))
            if "exactly one word" in question:
                self._n += 1
                return "new_content" if self._n == 1 else "no_new_content"
            return "fallback extraction text"

        def read_text(self, img_bytes):
            self.read_text_calls.append(img_bytes)
            return "adapter-routed extraction text"

    session = _FakeSession()
    provider = _TriageThenStopProvider()
    adapter = SessionVisionAdapter(session, provider)

    frames = asyncio.run(extract_page_frames(adapter, "goal", SessionBounds()))

    assert len(frames) == 1
    assert frames[0].text == "adapter-routed extraction text"
    assert len(session.acts) == 1  # one scroll between the new_content frame and the stop
