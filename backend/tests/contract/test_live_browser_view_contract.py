"""The agent's live browser reaches the panel, and the user can act in it
(2026-10-12).

Live finding: the panel only ever replayed saved HTML. The CDP screencast and
the input channel existed for a CAPTCHA hand-over, but every path to them was
broken - each pin below FAILS on that old state:

  - the gateway router never sent takeover_input / takeover_frame_ack to the
    handler that owns them ("Unknown message type"): no click reached the
    page, and with no ack the panel got ONE frame;
  - a click arrived as a fraction of the frame (0..1) and was dispatched as
    CSS pixels - every click landed in the page's top-left corner;
  - the wheel sent the pointer POSITION as the scroll distance;
  - Enter carried no key code, so Chromium never submitted a form;
  - frames flowed only during a hand-over, so the user could never WATCH the
    agent drive the page.

Hermetic: a fake CDP session, no browser.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

from backend.vision import cdp_takeover as cdp

_GATEWAY = Path(__file__).resolve().parents[2] / "iris_gateway.py"


class _FakeCDP:
    def __init__(self):
        self.sent: list = []
        self._handlers: dict = {}

    def on(self, event, handler):
        self._handlers[event] = handler

    async def send(self, method, params):
        self.sent.append((method, params))

    async def detach(self):
        pass

    def fire_frame(self, w=1000, h=800):
        self._handlers["Page.screencastFrame"]({
            "data": "QUJD", "sessionId": 1,
            "metadata": {"deviceWidth": w, "deviceHeight": h},
        })


@pytest.fixture(autouse=True)
def _clean_registry():
    cdp.clear_registry()
    yield
    cdp.clear_registry()


def _manager(frames):
    fake = _FakeCDP()
    mgr = cdp.TakeoverManager(run_id="run-1", cdp_factory=lambda _p: fake,
                              frame_sink=frames.append)
    return mgr, fake


def test_the_router_hands_the_live_view_messages_to_their_handler():
    """takeover_input, takeover_frame_ack and browser_control are handled in
    _handle_chat; the router's list for it must name them."""
    tree = ast.parse(_GATEWAY.read_text(encoding="utf-8"))
    routed = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.List):
            names = {e.value for e in node.elts if isinstance(e, ast.Constant)}
            if "question_response" in names and "text_message" in names:
                routed |= names
    assert {"takeover_input", "takeover_frame_ack", "browser_control",
            "browser_viewport"} <= routed, routed


def test_the_live_view_messages_never_wait_behind_the_turn():
    """Live: every frame ack and viewport message was processed ~2 min late,
    together, at the turn's end - they waited on the per-session message lock
    the running turn holds, so the panel got ONE frame per turn and the user
    could not take control mid-turn."""
    main_py = Path(__file__).resolve().parents[2] / "main.py"
    tree = ast.parse(main_py.read_text(encoding="utf-8"))
    unlocked = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_UNLOCKED_FRAMES" for t in node.targets):
            unlocked = {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
    assert {"takeover_frame_ack", "takeover_input", "browser_control",
            "browser_viewport"} <= unlocked, unlocked


class _FakePage:
    def __init__(self):
        self.viewport_size = {"width": 1366, "height": 768}
        self.sizes: list = []

    async def set_viewport_size(self, size):
        self.sizes.append(dict(size))
        self.viewport_size = dict(size)


def test_the_live_page_takes_the_panels_shape():
    """Live: the page rendered 1366x768 in a ~344x688 panel - a small strip in
    wide bars ("the site does not fit, it looks cropped"). The viewport now
    takes the panel's aspect at a readable width, and the stream follows it."""
    from backend.vision.browser_session import BrowserSession, SessionBounds

    s = BrowserSession(job_id="fit-1", url="https://example.com", goal="g",
                       bounds=SessionBounds(max_actions=5, max_wall_ms=60_000))
    s._page = _FakePage()
    frames: list = []
    mgr, _fake = _manager(frames)
    s._takeover_mgr = mgr
    asyncio.run(mgr.start_watch(s._page))

    out = asyncio.run(s.fit_viewport_to_panel(344, 688))
    assert out == {"width": 800, "height": 1600}, out
    assert s._page.sizes[-1] == {"width": 800, "height": 1600}
    assert (mgr._max_w, mgr._max_h) == (800, 1600) and mgr.watching
    # the same panel again changes nothing; a collapsed panel is ignored
    assert asyncio.run(s.fit_viewport_to_panel(344, 688)) is None
    assert asyncio.run(s.fit_viewport_to_panel(40, 30)) is None


def test_frames_reach_a_typed_chat_not_only_voice_mode():
    """The gateway's frame sink sent frames to `_conversation_sessions` - the
    VOICE conversation-mode set - so a typed chat got none (live: 0 frames)."""
    tree = ast.parse(_GATEWAY.read_text(encoding="utf-8"))
    sinks = [n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name == "_frame_sink"]
    assert sinks, "the gateway no longer defines the screencast frame sink"
    body = ast.unparse(sinks[0])
    assert "_conversation_sessions" not in body, "frames go to voice-mode sessions only"
    assert "broadcast(" in body


def test_watch_frames_flow_without_a_grant_and_say_who_holds_the_page():
    frames: list = []
    mgr, fake = _manager(frames)
    assert asyncio.run(mgr.start_watch(object()))
    fake.fire_frame()
    assert len(frames) == 1, "the user cannot watch the agent drive the page"
    assert frames[0]["control"] is False and frames[0]["question_id"] == ""

    mgr.ack_frame()
    mgr.open_grant(question_id="user", wall_kind="user_control")
    fake.fire_frame()
    assert frames[-1]["control"] is True and frames[-1]["question_id"] == "user"


def test_a_click_lands_where_the_user_pointed():
    frames: list = []
    mgr, fake = _manager(frames)
    asyncio.run(mgr.start_watch(object()))
    fake.fire_frame(w=1000, h=800)
    mgr.open_grant(question_id="user", wall_kind="user_control")
    asyncio.run(mgr.deliver_input(cdp.TakeoverInput(kind="pointer", x=0.5, y=0.25)))
    pressed = [p for m, p in fake.sent if m == "Input.dispatchMouseEvent"
               and p.get("type") == "mousePressed"]
    assert pressed and (pressed[0]["x"], pressed[0]["y"]) == (500.0, 200.0), pressed


def test_the_wheel_scrolls_by_its_distance_not_its_position():
    frames: list = []
    mgr, fake = _manager(frames)
    asyncio.run(mgr.start_watch(object()))
    fake.fire_frame()
    mgr.open_grant(question_id="user", wall_kind="user_control")
    asyncio.run(mgr.deliver_input(cdp.TakeoverInput(kind="wheel", x=0.5, y=0.5, dx=0, dy=120)))
    wheel = [p for m, p in fake.sent if p.get("type") == "mouseWheel"]
    assert wheel and wheel[0]["deltaY"] == 120.0 and wheel[0]["deltaX"] == 0.0, wheel


def test_enter_carries_its_key_code_and_text():
    frames: list = []
    mgr, fake = _manager(frames)
    asyncio.run(mgr.start_watch(object()))
    mgr.open_grant(question_id="user", wall_kind="user_control")
    asyncio.run(mgr.deliver_input(cdp.TakeoverInput(kind="key", key="Enter")))
    keys = [p for m, p in fake.sent if m == "Input.dispatchKeyEvent"]
    assert any(p.get("windowsVirtualKeyCode") == 13 for p in keys), keys
    assert any(p.get("type") == "char" and p.get("text") == "\r" for p in keys), keys


class _HeldSession:
    """Holds the page for `held_s` seconds, like a user who then hands back."""

    def __init__(self, held_s):
        import time as _t
        self._until = _t.monotonic() + held_s

    def user_has_control(self):
        import time as _t
        return _t.monotonic() < self._until


def test_an_agent_action_waits_for_the_hand_back(monkeypatch):
    """Live: the act failed in 67 ms while the user held the page and the reply
    said "the click action failed". The agent now waits for Hand back."""
    from backend.agent.tools import browser_tools as bt

    monkeypatch.setitem(bt._RT.sessions, "held-conv", bt._Entry(session=_HeldSession(1.5)))
    monkeypatch.setattr(bt, "_HAND_BACK_WAIT_S", 10.0)
    assert asyncio.run(bt._wait_for_hand_back("held-conv")) is None


def test_a_page_still_held_is_reported_as_the_users(monkeypatch):
    from backend.agent.tools import browser_tools as bt

    monkeypatch.setitem(bt._RT.sessions, "held-conv", bt._Entry(session=_HeldSession(60)))
    monkeypatch.setattr(bt, "_HAND_BACK_WAIT_S", 1.5)
    msg = asyncio.run(bt._wait_for_hand_back("held-conv"))
    assert msg and "Hand back" in msg


@pytest.mark.parametrize("goal,acts", [
    ("Open https://books.toscrape.com in the browser and click the Travel category", True),
    ("type 'Ada Lovelace' into the page's search box", True),
    ("log in to the site and add the first book to the cart", True),
    ("scroll down and press Enter", True),
    ("research the latest prices of OLED TVs", False),
    ("what type of battery does the Model 3 use", False),
    ("summarize the press release about the merger", False),
])
def test_a_browser_action_goal_skips_the_web_search_precommit(goal, acts):
    """The DER web pre-commit answered a web goal with `search`, so a goal that
    acts on a site ("open X in the browser and click Y") never opened the
    browser. A goal with an action verb now goes to the tool choice."""
    from backend.agent.agent_kernel import _BROWSER_ACTION_RE

    assert bool(_BROWSER_ACTION_RE.search(goal)) is acts


def test_a_reconnected_panel_gets_the_latest_frame_and_the_stream_unsticks():
    """A socket drop loses the ack of the frame in flight: the stream would hold
    every later frame for good. On reconnect the slot is freed and the latest
    frame sent again (and a reconnect to a NEW backend shows no dead view)."""
    frames: list = []
    mgr, fake = _manager(frames)
    cdp.register_active(mgr)
    asyncio.run(mgr.start_watch(object()))
    fake.fire_frame()          # delivered, its ack never comes back
    fake.fire_frame()          # held: one frame in flight
    assert len(frames) == 1
    assert cdp.resend_latest_frames() == 1
    assert len(frames) == 2 and frames[-1]["frame_seq"] == 2


class _LivePageSession:
    url = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"

    class _page:  # noqa: N801 - a stand-in for the Playwright page
        url = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"

    def available(self):
        return True

    async def screenshot(self):
        return b"LIVE-PNG"


def test_a_screenshot_shows_the_agents_live_page(monkeypatch):
    """screenshot_page opened a NEW session at the URL: the picture lost the
    agent's clicks, login and scroll, and paid a second browser. With the live
    page open (no URL, or the same URL) it photographs that page."""
    from backend.agent.tools import browser_tools as bt

    monkeypatch.setitem(bt._RT.sessions, "shot-conv", bt._Entry(session=_LivePageSession()))
    assert asyncio.run(bt.live_page_screenshot("shot-conv", "")) == b"LIVE-PNG"
    assert asyncio.run(bt.live_page_screenshot(
        "shot-conv", "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html/")) == b"LIVE-PNG"
    assert asyncio.run(bt.live_page_screenshot("shot-conv", "https://example.com/")) is None
    assert asyncio.run(bt.live_page_screenshot("no-such-conv", "")) is None


@pytest.mark.parametrize("url,expected", [
    ("http://books.toscrape.com", "https://books.toscrape.com"),
    ("http://example.com/a?b=1", "https://example.com/a?b=1"),
    ("https://example.com", ""),            # already secure
    ("http://127.0.0.1:8000/", ""),         # a local server has no TLS
    ("http://localhost:3000", ""),
    ("http://10.0.0.5/admin", ""),
])
def test_browser_open_tries_https_first_for_a_public_http_address(url, expected):
    """Live: the model opened http://books.toscrape.com - 33.8 s for the main
    document over plain http on this network, 0.5 s over https."""
    from backend.agent.tools import browser_tools as bt

    assert bt._https_first(url) == expected


class _Store:
    def __init__(self):
        self.blobs = {}

    def store_blob(self, doc_id, data, mime):
        self.blobs[doc_id] = (data, mime)
        return True


class _Kernel:
    def __init__(self):
        self.store = _Store()
        self.artifacts = []

    def _get_document_store(self):
        return self.store

    def create_artifact(self, **kw):
        self.artifacts.append(kw)
        return {"success": True, "artifact_id": kw["extra"]["document_id"]}


def test_a_screenshot_reaches_the_chat_through_the_one_card_door(monkeypatch):
    """Live: the image was stored and served, but the tool wrote its own row and
    DOCUMENT_RENDER - the second door S62 closed - so no card reached the chat
    and the reply quoted a document id. It now goes through create_artifact,
    keyed to the stored image."""
    from backend.agent.tools import browser_tools as bt
    from backend.agent.tools import screenshot_page_tool as spt

    async def _live(_conv, _url=""):
        return b"PNGDATA"

    monkeypatch.setattr(bt, "live_page_screenshot", _live)
    monkeypatch.setitem(bt._RT.sessions, "card-conv", bt._Entry(session=_LivePageSession()))
    k = _Kernel()
    out = asyncio.run(spt.capture_page_screenshot("", k, conversation_id="conv-1",
                                                  turn_id="t1", browser_key="card-conv"))
    assert out["success"] is True, out
    assert len(k.artifacts) == 1
    art = k.artifacts[0]
    assert art["kind"] == "image" and art["turn_id"] == "t1" and art["conversation_id"] == "conv-1"
    doc_id = art["extra"]["document_id"]
    assert k.store.blobs[doc_id][0] == b"PNGDATA"
    assert art["content"] == f"/api/documents/{doc_id}/image"


def test_input_without_a_grant_is_still_refused_while_watching():
    """Watching is not control: the agent's page takes no user input until the
    user takes control (one writer, REQ-15 AC4)."""
    frames: list = []
    mgr, fake = _manager(frames)
    asyncio.run(mgr.start_watch(object()))
    ok = asyncio.run(mgr.deliver_input(cdp.TakeoverInput(kind="pointer", x=0.5, y=0.5)))
    assert ok is False
    assert not [m for m, _ in fake.sent if m == "Input.dispatchMouseEvent"]


class _PanelSession:
    """A stand-in for BrowserSession: records the fit and the observe in order.
    ``_action_lock`` is the lock an agent action holds while it drives the page."""

    _job_id = "r1"

    def __init__(self):
        self._action_lock = asyncio.Lock()
        self.calls: list = []

    def available(self):
        return True

    def user_has_control(self):
        return False

    async def fit_viewport_to_panel(self, w, h):
        async with self._action_lock:  # as the real fit: never resize under an action
            self.calls.append(("fit", w, h))
        return {"width": w, "height": h}

    async def observe(self, marked_screenshot, emit):
        self.calls.append(("observe",))
        return {"ok": True, "marks": [], "marks_seq": 1, "title": "t", "url": "u", "digest": "d"}


def test_panel_size_during_an_action_is_applied_by_the_next_observe(monkeypatch):
    """Live 2026-10-12 (run browser-c9f117159a4f): the panel reported its size while
    an observe held the page lock. The fit waited 20 s for the lock, then was
    dropped, and the page stayed 1366x768 in a tall panel. Now the fit returns at
    once and keeps the size; the next observe applies it before the marks."""
    from backend.agent.tools import browser_tools as bt

    async def _main():
        session = _PanelSession()
        monkeypatch.setattr(bt, "_PANEL_SIZE", {})
        monkeypatch.setitem(bt._RT.sessions, "c1", bt._Entry(session=session))
        await session._action_lock.acquire()
        try:
            out = await asyncio.wait_for(bt.fit_live_viewport("r1", 344, 671), 1.0)
        finally:
            session._action_lock.release()
        assert out is None and session.calls == [], session.calls
        assert bt._PANEL_SIZE == {"width": 344, "height": 671}, bt._PANEL_SIZE
        await bt._do_observe("c1", False, None)
        assert session.calls[:2] == [("fit", 344, 671), ("observe",)], session.calls

    asyncio.run(_main())


def test_an_observe_fits_the_panel_before_it_takes_the_marks(monkeypatch):
    """A resize after the marks would move every box, so the panel's shape is
    applied first. Pins the order of the fit and the observe."""
    from backend.agent.tools import browser_tools as bt

    async def _main():
        session = _PanelSession()
        monkeypatch.setattr(bt, "_PANEL_SIZE", {"width": 344, "height": 671})
        monkeypatch.setitem(bt._RT.sessions, "c1", bt._Entry(session=session))
        await bt._do_observe("c1", False, None)
        return session.calls

    assert asyncio.run(_main()) == [("fit", 344, 671), ("observe",)]
