"""BT-5 (vision-goal-directed-search T26, REQ-10): the takeover LOOP
behavior — wall detected -> takeover question asked -> user resolves ->
wall re-verified on the live page -> automation resumes.

The unit suite (test_browser_takeover.py) pins the AskUserTool payloads. This
suite drives the BrowserSession seam: the full funnel ON THE LIVE SESSION
(real request_takeover + real AskUserTool on a fresh EventBus, fake page
content) and the terminal outcomes the caller relies on (resume-on-clear
vs fall-through-to-park, never raise, paywall never enters).
"""
from __future__ import annotations

import asyncio
import threading

import pytest

import backend.agent.tools.ask_user_tool as ask_mod
from backend.agent.event_bus import EventBus, IRISStreamEvent
from backend.agent.tools.ask_user_tool import AskUserTool
from backend.vision.browser_session import BrowserSession, WallKind


LOGIN_HTML = (
    '<html><body><form><input type="text">'
    '<input type="password" name="pw"></form></body></html>'
)
CLEAN_HTML = "<html><body>Welcome back — full dashboard content here.</body></html>"


class _TakeoverPage:
    """Fake Playwright page whose DOM flips from walled to clean once the
    user finishes solving in the panel (set by the test's answer thread)."""

    def __init__(self, url: str, walled_html: str):
        self.url = url
        self._html = walled_html

    async def content(self) -> str:
        return self._html

    # The "user solved it externally" transition point.
    def clear_wall(self) -> None:
        self._html = CLEAN_HTML


def _session_and_tool(events: list, monkeypatch: pytest.MonkeyPatch):
    tool = AskUserTool(event_bus=EventBus())
    tool._bus.subscribe(
        IRISStreamEvent.QUESTION_ASK,
        lambda p: events.append(("question:ask", dict(p.data or {}))),
    )
    tool._bus.subscribe(
        IRISStreamEvent.BROWSER_TAKEOVER_REQUESTED,
        lambda p: events.append(("browser:takeover_requested", dict(p.data or {}))),
    )
    monkeypatch.setattr(ask_mod, "get_ask_user_tool", lambda: tool)
    return tool


def _session(page: _TakeoverPage) -> BrowserSession:
    s = BrowserSession(job_id="j-takeover", url=page.url, goal="read the page")
    s._page = page
    # Frame publish is exercised by browser_session's own contract tests; here
    # it must be observable but side-effect-free.
    s._published: list[bool] = []

    async def _publish():
        s._published.append(True)
        return ""

    s._publish_frame = _publish  # type: ignore[method-assign]
    return s


def test_wall_resolves_and_automation_resumes(monkeypatch):
    """AC10.1→AC10.3 happy path: wall detected, takeover asked, user clicks
    'I've Completed It', the page is re-checked (real detect_wall on the
    flipped DOM), the frame publishes, automation resumes."""
    events: list = []
    tool = _session_and_tool(events, monkeypatch)
    page = _TakeoverPage("https://bank.example/2fa", LOGIN_HTML)
    session = _session(page)

    # The user resolves the question from a background thread (exactly like
    # the frontend card does via sendMessage → question_response).
    def _user_solves():
        qid = None
        # Spin until the question EXISTS (the ask runs before any wait).
        for _ in range(200):
            if tool._pending:
                qid = next(iter(tool._pending))
                break
            import time as _t

            _t.sleep(0.01)
        assert qid is not None, "takeover question was never asked"
        resolved = tool.resolve_answer(qid, "completed")
        assert resolved is not None and resolved.answer == "completed"
        # AC10.3: the page NOW reports un-walled.
        page.clear_wall()

    t = threading.Thread(target=_user_solves, daemon=True)
    t.start()
    ok = asyncio.run(session.request_takeover(WallKind.LOGIN, timeout_seconds=10))
    t.join(timeout=5)

    assert ok is True, "a cleared wall did not resume automation"
    assert session._published, "the post-takeover settle frame was never published"
    kinds = [k for k, _ in events]
    assert "question:ask" in kinds and "browser:takeover_requested" in kinds, (
        f"the panel had nothing to unlock from: {kinds}"
    )
    # Order: the question precedes the unlock event (the card shows, then the
    # panel opens) — the pairing the frontend takeover banner keys off.
    assert kinds.index("question:ask") < kinds.index("browser:takeover_requested")
    payload = dict(events[-1][1])
    assert payload["takeover_url"] == "https://bank.example/2fa"
    assert payload["job_id"] == "j-takeover"


def test_completed_but_wall_persists_refuses_resume(monkeypatch):
    """AC10.3: 'I've Completed It' is a CLAIM, not proof — the session
    re-checks the live page and must NOT trust the user click. The caller
    parks the URL exactly as if the takeover never happened."""
    events: list = []
    tool = _session_and_tool(events, monkeypatch)
    page = _TakeoverPage("https://bank.example/login", LOGIN_HTML)
    session = _session(page)

    def _misclick():
        for _ in range(500):
            if tool._pending:
                tool.resolve_answer(next(iter(tool._pending)), "completed")
                return
            import time as _t

            _t.sleep(0.01)

    t = threading.Thread(target=_misclick, daemon=True)
    t.start()
    ok = asyncio.run(session.request_takeover(WallKind.LOGIN, timeout_seconds=10))
    t.join(timeout=5)

    assert ok is False, "takeover claimed completed but the wall persisted — resumed anyway"
    assert not session._published


def test_paywall_never_asks_the_user():
    """Non-Goal: paywalls are not solvable by the user — the tool is never
    touched, no events fire, and the caller parks immediately."""
    page = _TakeoverPage("https://news.example/article", "<html>paywall</html>")
    session = _session(page)

    # If this were reached, get_ask_user_tool is real and would emit on the
    # global bus; the absence of any tool construction is the assertion.
    ok = asyncio.run(session.request_takeover(WallKind.PAYWALL))
    assert ok is False


def test_timeout_returns_false_without_crashing(monkeypatch):
    """Edge: user walks away — timeout is a terminal OUTCOME, never a
    raise, and the parked-source path continues normally."""
    events: list = []
    _session_and_tool(events, monkeypatch)
    page = _TakeoverPage("https://bank.example/login", LOGIN_HTML)
    session = _session(page)

    ok = asyncio.run(session.request_takeover(WallKind.LOGIN, timeout_seconds=0.05))
    assert ok is False
    assert any(k == "question:ask" for k, _ in events), (
        "the takeover was never presented before its own timeout — the user "
        "cannot resolve a question they never saw"
    )


def test_missing_tooling_fails_closed(monkeypatch):
    """A backend without the ask tool (import failure / gateway not up) must
    degrade the takeover to False — never kill the crawl."""
    monkeypatch.delattr(ask_mod, "get_ask_user_tool")
    page = _TakeoverPage("https://bank.example/login", LOGIN_HTML)
    session = _session(page)
    assert asyncio.run(session.request_takeover(WallKind.LOGIN)) is False
