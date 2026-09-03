"""Contract tests for the fetch.vision node (T10, REQ-6/REQ-7).

Hermetic: a FAKE BrowserSession subclass + fake vision provider replace
Playwright and the VLM — no browser, no server, no network. The production
FetchVisionCapability logic (loop, wall detection, settled-DOM handback, lease
release) runs for real.

Why the ORIGINAL ``_FakeProvider`` here missed the live production TypeError
(``extract_page_frames() got multiple values for argument 'provider'`` — every
vision session, job c3e083435f4c4076ad9aee1db70f67fb, 2026-08-10 23:28-23:30):
the call-site bug raised BEFORE a single line of ``extract_page_frames`` ran,
so nothing about the fake's method SIGNATURES was ever exercised — the
TypeError came from Python's own argument binding at the call site itself.
``fetch_one`` swallows that into ``frames = []`` (the pre-initialized default)
and falls back to settled-DOM text, which was always non-empty in these
fixtures. The only assertion that touched the result,
``len(outcome.page.markdown) > 0``, is true either way — it cannot
distinguish "vision actually ran" from "vision silently no-opped". Nothing
here asserted the provider's triage/extraction methods were ever CALLED, or
that markdown came from vision text specifically. The new tests below close
that hole directly.
"""

import asyncio

import pytest

from backend.crawler.capabilities import WallKind
from backend.crawler.usability import UsabilityReason
from backend.vision.browser_session import SessionBounds, VisionAction
from backend.vision.fetch_vision import FetchVisionCapability


class _FakeSession:
    """In-memory BrowserSession stand-in. Records what the loop did."""

    def __init__(self, job_id, url, goal, bounds=None):
        self.job_id = job_id
        self.url = url
        self.goal = goal
        self.bounds = bounds or SessionBounds()
        self.acts: list[VisionAction] = []
        self.closed = False
        self.available_flag = True
        self.walls: list = []        # detect_wall results, consumed in order
        self.suggestions: list = []  # suggest_action results, consumed in order
        self.dom = "<html><body><p>useful quantum verification content here for the model</p></body></html>"
        self.screenshot_calls = 0

    # BrowserSession surface (subset the capability drives)
    async def open(self):
        pass

    def available(self):
        return self.available_flag

    async def detect_wall(self):
        if self.walls:
            return self.walls.pop(0)
        return None

    async def screenshot(self):
        self.screenshot_calls += 1
        return b"PNG"

    async def act(self, action: VisionAction):
        self.acts.append(action)

    async def settle(self):
        return self.dom

    async def close(self):
        self.closed = True


class _FakeProvider:
    """VLM stand-in matching the REAL LFMVLProvider surface (img_bytes-first,
    synchronous, no per-call state) — every method takes the screenshot
    bytes the SessionVisionAdapter captured from the session, never a bare
    string.

    ``analyze_screen`` is asked TWO different questions by
    SessionVisionAdapter: the cheap TRIAGE question
    (frame_extraction._triage_frame's "reply with exactly one word...") and
    the FULL-EXTRACTION fallback question ("Extract all visible text
    verbatim.", only reached when ``read_text`` comes back empty). Which one
    is answered is detected by matching the "exactly one word" text the
    triage prompt always carries, exactly the way the real triage prompt is
    built.
    """

    def __init__(
        self,
        suggestions=None,
        suggest_fail=False,
        triage_answer="no_new_content",
        triage_sequence=None,
        extract_text="",
    ):
        self._suggestions = suggestions or [
            {"action": "scroll", "target": "", "reasoning": "more content below"},
            {"action": "done", "target": "", "reasoning": "goal met"},
        ]
        self._suggest_fail = suggest_fail
        self._triage_answer = triage_answer
        self._triage_sequence = list(triage_sequence) if triage_sequence else None
        self._triage_idx = 0
        self._extract_text = extract_text
        self.calls = 0
        self.read_text_calls = 0
        self.analyze_calls = 0
        self.describe_calls = 0  # kept for provider-surface parity; the
        # adapter routes triage through analyze_screen (see
        # backend/vision/session_vision_adapter.py docstring) — the real
        # describe_live_frame ignores any caller prompt, so it cannot answer
        # a goal-specific triage question and is not exercised by extraction.

    def suggest_action(self, img_bytes, goal):
        self.calls += 1
        if self._suggest_fail:
            raise RuntimeError("vision down")
        idx = min(self.calls - 1, len(self._suggestions) - 1)
        return self._suggestions[idx]

    def describe_live_frame(self, img_bytes):
        self.describe_calls += 1
        return "generic frame description"

    def read_text(self, img_bytes):
        self.read_text_calls += 1
        return self._extract_text

    def analyze_screen(self, img_bytes, question=""):
        self.analyze_calls += 1
        if "exactly one word" in question:
            if self._triage_sequence is not None:
                idx = min(self._triage_idx, len(self._triage_sequence) - 1)
                self._triage_idx += 1
                return self._triage_sequence[idx]
            return self._triage_answer
        return self._extract_text


# ── happy path: loop -> settle -> handback ─────────────────────────────────

def test_fetch_vision_happy_path_settled_dom_handback():
    """REQ-6 AC5: usable page + settled_dom handed back for a crawl pass."""
    sess = _FakeSession("j", "https://a.example/", "read the article")
    cap = FetchVisionCapability(provider=_FakeProvider(), session_cls=lambda *a, **k: sess)

    outcome = asyncio.run(cap.fetch_one("https://a.example/", "read", "j1"))

    assert outcome.capability == "fetch.vision"
    assert outcome.page is not None
    assert outcome.verdict.usable is True
    assert outcome.settled_dom == sess.dom
    assert outcome.wall is None
    assert outcome.actions_taken >= 1
    # vision text went through page_is_usable like any other content
    assert len(outcome.page.markdown) > 0
    assert sess.closed is True  # resources released


def test_fetch_vision_wall_detection_captcha():
    """REQ-7: CAPTCHA wall stops the loop and is surfaced in the outcome."""
    sess = _FakeSession("j", "https://a.example/", "read")
    sess.walls = [WallKind.CAPTCHA]
    cap = FetchVisionCapability(provider=_FakeProvider(), session_cls=lambda *a, **k: sess)

    outcome = asyncio.run(cap.fetch_one("https://a.example/", "read", "j2"))

    assert outcome.wall == WallKind.CAPTCHA
    assert sess.acts == []  # loop never executed an action after the wall


def test_fetch_vision_wall_detection_login_and_paywall():
    for kind in (WallKind.LOGIN, WallKind.PAYWALL):
        sess = _FakeSession("j", "https://a.example/", "read")
        sess.walls = [kind]
        cap = FetchVisionCapability(provider=_FakeProvider(), session_cls=lambda *a, **k: sess)
        outcome = asyncio.run(cap.fetch_one("https://a.example/", "read", "j3"))
        assert outcome.wall == kind


# ── wall on a later step (after some actions) ──────────────────────────────

def test_fetch_vision_wall_detected_after_actions():
    """A wall appearing mid-loop stops further actions (REQ-7 AC3)."""
    sess = _FakeSession("j", "https://a.example/", "read")
    sess.walls = [None, WallKind.LOGIN]
    cap = FetchVisionCapability(provider=_FakeProvider(), session_cls=lambda *a, **k: sess)

    outcome = asyncio.run(cap.fetch_one("https://a.example/", "read", "j4"))

    assert outcome.wall == WallKind.LOGIN
    assert len(sess.acts) == 1  # one action before the wall appeared


# ── stuck-loop prevention ──────────────────────────────────────────────────

def test_fetch_vision_stops_on_repeated_action():
    """3 identical action kinds in a row = stuck -> settle (REQ-7 loop guard)."""
    sess = _FakeSession("j", "https://a.example/", "read")
    provider = _FakeProvider(suggestions=[
        {"action": "click", "target": "button", "reasoning": "x"},
        {"action": "click", "target": "button", "reasoning": "x"},
        {"action": "click", "target": "button", "reasoning": "x"},
        {"action": "click", "target": "button", "reasoning": "x"},
    ])
    cap = FetchVisionCapability(provider=provider, session_cls=lambda *a, **k: sess)

    outcome = asyncio.run(cap.fetch_one("https://a.example/", "read", "j5"))

    assert len(sess.acts) <= 3  # stopped before the 4th click


# ── degraded vision: provider failure still returns an outcome ─────────────

def test_fetch_vision_provider_down_returns_outcome_from_settled_dom():
    """Vision down -> fetch_one still returns an outcome, never raises
    (REQ-6 AC1). The page falls back to the settled-DOM text (REQ-17 AC5:
    content is judged by page_is_usable, not by which capability produced it)."""
    sess = _FakeSession("j", "https://a.example/", "read")
    sess.dom = "<html><body><p>quantum verification content extracted from settled DOM</p></body></html>"
    cap = FetchVisionCapability(
        provider=_FakeProvider(suggest_fail=True),
        session_cls=lambda *a, **k: sess,
    )

    outcome = asyncio.run(cap.fetch_one("https://a.example/", "read", "j6"))

    assert outcome.page is not None
    assert outcome.verdict.usable is True
    assert "settled DOM" in outcome.page.markdown  # DOM fallback, not vision text
    assert sess.closed is True  # lease/session released even on failure


def test_fetch_vision_provider_down_and_empty_dom_is_unusable():
    """Vision down AND no DOM text -> unusable TRANSPORT_ERROR outcome."""
    sess = _FakeSession("j", "https://a.example/", "read")
    sess.dom = ""
    cap = FetchVisionCapability(
        provider=_FakeProvider(suggest_fail=True),
        session_cls=lambda *a, **k: sess,
    )

    outcome = asyncio.run(cap.fetch_one("https://a.example/", "read", "j6b"))

    assert outcome.page is None
    assert outcome.verdict.usable is False
    assert sess.closed is True


# ── unavailable session ────────────────────────────────────────────────────

def test_fetch_vision_browser_unavailable():
    """open() succeeded but no page attached -> transport error, clean close."""
    sess = _FakeSession("j", "https://a.example/", "read")
    sess.available_flag = False
    cap = FetchVisionCapability(provider=_FakeProvider(), session_cls=lambda *a, **k: sess)

    outcome = asyncio.run(cap.fetch_one("https://a.example/", "read", "j7"))

    assert outcome.page is None
    assert outcome.verdict.usable is False
    assert sess.closed is True


# ── lease release on exception ─────────────────────────────────────────────

def test_fetch_vision_closes_session_when_suggest_raises():
    """suggest_action raising must still close the session (finally)."""
    sess = _FakeSession("j", "https://a.example/", "read")
    cap = FetchVisionCapability(provider=_FakeProvider(suggest_fail=True), session_cls=lambda *a, **k: sess)

    asyncio.run(cap.fetch_one("https://a.example/", "read", "j8"))
    assert sess.closed is True


# ── loop step cap ──────────────────────────────────────────────────────────

def test_fetch_vision_respects_max_loop_steps(monkeypatch):
    """The loop never runs more than _MAX_LOOP_STEPS even if the model keeps
    suggesting actions."""
    import backend.vision.fetch_vision as fv

    monkeypatch.setattr(fv, "_MAX_LOOP_STEPS", 3)
    sess = _FakeSession("j", "https://a.example/", "read")
    provider = _FakeProvider(suggestions=[
        {"action": "scroll", "target": "", "reasoning": "a"},
        {"action": "scroll", "target": "", "reasoning": "b"},
        {"action": "scroll", "target": "", "reasoning": "c"},
        {"action": "scroll", "target": "", "reasoning": "d"},
    ])
    cap = FetchVisionCapability(provider=provider, session_cls=lambda *a, **k: sess)

    asyncio.run(cap.fetch_one("https://a.example/", "read", "j9"))
    assert len(sess.acts) <= 3
    assert sess.closed is True


# ── extraction actually running (closes the production TypeError hole) ─────

def test_fetch_vision_extraction_actually_runs_and_reaches_markdown():
    """THE KEY CONTRACT TEST: drive fetch_one with a fake session + fake
    provider and assert extract_page_frames actually RAN (not swallowed by
    the TypeError this whole fix exists for) and its frames reached
    FetchOutcome.page.markdown.

    Distinct from the happy-path test above: sess.dom here is deliberately
    DIFFERENT from the vision text, so a pass can only mean the vision path
    produced the markdown — not the DOM fallback masking a no-op extraction
    (exactly how the original production TypeError went undetected).
    """
    sess = _FakeSession("j", "https://a.example/", "read the article")
    sess.dom = "<html><body><p>dom fallback text, must NOT win</p></body></html>"
    provider = _FakeProvider(
        triage_sequence=["new_content", "no_new_content"],
        extract_text="fresh vision-extracted article text",
    )
    cap = FetchVisionCapability(provider=provider, session_cls=lambda *a, **k: sess)

    outcome = asyncio.run(cap.fetch_one("https://a.example/", "read the article", "j-key"))

    assert provider.analyze_calls >= 1, "triage never called analyze_screen — extraction did not run"
    assert provider.read_text_calls >= 1, "full extraction tier never ran"
    assert outcome.page is not None
    assert "fresh vision-extracted article text" in outcome.page.markdown, (
        f"vision-extracted text did not reach FetchOutcome.page.markdown "
        f"(got {outcome.page.markdown!r}) — extract_page_frames either did "
        f"not run or its output was discarded, exactly the production hole "
        f"this test exists to close"
    )
    assert "dom fallback text" not in outcome.page.markdown, (
        "markdown came from the DOM fallback, not vision — extraction silently no-opped"
    )
    assert sess.closed is True


def test_fetch_vision_image_heavy_page_vision_text_reaches_markdown():
    """REQ-17: DOM is empty (image-heavy page) — vision-extracted text must
    still reach FetchOutcome.page.markdown and be judged usable."""
    sess = _FakeSession("j", "https://a.example/infographic", "read the infographic")
    sess.dom = ""  # nothing for the DOM-strip fallback to produce
    provider = _FakeProvider(
        triage_sequence=["new_content", "no_new_content"],
        extract_text="infographic caption text read by vision OCR",
    )
    cap = FetchVisionCapability(provider=provider, session_cls=lambda *a, **k: sess)

    outcome = asyncio.run(cap.fetch_one("https://a.example/infographic", "read the infographic", "j-req17"))

    assert outcome.page is not None
    assert "infographic caption text read by vision OCR" in outcome.page.markdown
    assert outcome.verdict.usable is True
    assert sess.closed is True


def test_fetch_vision_extraction_failure_logs_warning_not_info(caplog):
    """The extraction try/except must log LOUDLY (WARNING) with job_id/url —
    it silently ran as `logger.info` in production for weeks.

    Triggers a REAL failure that escapes extract_page_frames itself
    (BudgetExceeded, backend/vision/frame_extraction.py) rather than one of
    the failures frame_extraction already swallows internally (triage/
    extract exceptions degrade in-loop by design and never reach this
    log line) — max_extractions is set to 2 with a provider that always
    reports new_content so the budget is guaranteed to be hit.
    """
    import logging

    from backend.vision.browser_session import SessionBounds as _Bounds

    sess = _FakeSession("j", "https://a.example/", "read")
    provider = _FakeProvider(triage_answer="new_content")
    cap = FetchVisionCapability(
        provider=provider,
        session_cls=lambda *a, **k: sess,
        bounds=_Bounds(max_actions=12, max_wall_ms=60_000, max_extractions=2),
    )

    with caplog.at_level(logging.WARNING, logger="backend.vision.fetch_vision"):
        outcome = asyncio.run(cap.fetch_one("https://a.example/", "read", "j-warn"))

    assert outcome.page is not None, "extraction failure must stay non-fatal (settled DOM still returned)"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("extraction failed" in r.message and "j-warn" in r.message for r in warnings), (
        f"no WARNING-level extraction-failure log carrying the job_id found; got: "
        f"{[r.message for r in caplog.records]}"
    )
