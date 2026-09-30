"""Contract: the live-browser tools and their event shape
(specs/websearch-vision-browser B2/B4, REQ-4 / REQ-5).

Boundaries pinned here, all producer-side (no browser, no network):
  * tool registry  -> the LLM sees browser_open / browser_observe / browser_act with
    schemas, tiers and the internet gate; `fetch.vision` is NOT LLM-facing.
  * session -> panel: a CRAWLER_VISION_ACTION keeps every existing field and adds
    `phase` / `ok` / `error`; the page event carries what the panel addresses by.
  * fetch.vision -> panel: a failed action is emitted `ok=false`, never as a success.
  * tool bridge -> session: the bridge hands the session an emitter that reaches the
    crawl-UI forwarder.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.agent import tool_registry
from backend.agent.tool_registry import (
    get_node_spec, get_registry_tools, resolve_tool, to_function_schema, validate_tool_call,
)

_BROWSER_TOOLS = ("browser_open", "browser_observe", "browser_act")


@pytest.fixture
def internet_on(monkeypatch):
    monkeypatch.setattr(tool_registry, "_internet_provider", lambda: True)


# ── registry ───────────────────────────────────────────────────────────────


def test_registry_exposes_the_three_browser_tools_with_schemas(internet_on):
    """B4 DONE: the three tools are LLM-facing, with valid function schemas."""
    tools = {t["name"]: t for t in get_registry_tools()}
    for name in _BROWSER_TOOLS:
        assert name in tools, f"{name} missing from the LLM-facing registry"
    fn = {f["function"]["name"]: f["function"] for f in to_function_schema(
        [tools[n] for n in _BROWSER_TOOLS])}

    assert fn["browser_open"]["parameters"]["properties"]["url"]["type"] == "string"
    assert fn["browser_open"]["parameters"]["required"] == ["url"]
    assert fn["browser_observe"]["parameters"]["properties"] == {}
    act = fn["browser_act"]["parameters"]
    assert act["properties"]["action"]["enum"] == ["click", "type", "select", "scroll", "back", "press"]
    assert act["properties"]["element_id"]["type"] == "integer"
    assert act["required"] == ["action"], "element_id and text are optional"


def test_browser_tools_are_internet_gated_and_tiered(monkeypatch):
    """Web mode off -> the agent sees none of them. Typing is not read-only."""
    monkeypatch.setattr(tool_registry, "_internet_provider", lambda: False)
    assert not {t["name"] for t in get_registry_tools()} & set(_BROWSER_TOOLS)
    assert resolve_tool("browser_open").permission_tier == "read_only"
    assert resolve_tool("browser_observe").permission_tier == "read_only"
    assert resolve_tool("browser_act").permission_tier == "side_effect"
    for name in _BROWSER_TOOLS:
        assert resolve_tool(name).requires_internet is True


def test_required_parameters_are_enforced():
    assert validate_tool_call("browser_act", {})[0] is False
    assert validate_tool_call("browser_act", {"action": "click", "element_id": 3})[0] is True
    assert validate_tool_call("browser_open", {})[0] is False
    assert validate_tool_call("browser_observe", {})[0] is True


def test_fetch_vision_is_not_llm_facing(internet_on):
    """B4 DONE: fetch.vision (the crawl's internal session) never reaches the
    tool-model grammar; the node router still knows it."""
    from backend.crawler import capabilities

    # Idempotent. Importing backend.vision.fetch_vision BEFORE the capabilities module
    # (the order some test modules collect in) makes the import-time registration hit
    # a half-initialised module and skip fetch.vision; registering again is complete.
    capabilities.register_default_capabilities()

    spec = resolve_tool("fetch.vision")
    assert spec is not None and spec.hidden is True
    assert "fetch.vision" not in {t["name"] for t in get_registry_tools()}
    assert get_node_spec("fetch.vision") is not None, "hiding must not unregister the node"


def test_browser_results_are_untrusted_external_content():
    from backend.agent.mcm_protocol.actions.pacman_fragment import is_external_tool

    assert all(is_external_tool(n) for n in _BROWSER_TOOLS)


# ── event shape ────────────────────────────────────────────────────────────


def _session():
    from backend.vision.browser_session import BrowserSession

    return BrowserSession(job_id="job-contract", url="https://example.com/", goal="g")


def test_vision_action_events_keep_every_existing_field_and_add_phase_ok_error():
    """B2 / AC5.1-5.2: approach carries the existing CT-1 fields + phase; done
    carries ok (+ error when false); seq is strictly increasing."""
    from backend.agent.tool_bridge import _UI_EVENT_DEFAULTS

    got: list = []
    s = _session()
    point = {"x": 0.25, "y": 0.5, "viewport_w": 1366, "viewport_h": 768,
             "scroll_y": 0, "scroll_height": 2000}
    s._emit_action(lambda ev, p: got.append((ev, p)), "approach", "click", 1, point, element_id=4)
    s._emit_action(lambda ev, p: got.append((ev, p)), "done", "click", 1, None,
                   ok=False, error="click failed: boom", element_id=4)

    (ev1, approach), (ev2, done) = got
    assert ev1 == ev2 == "CRAWLER_VISION_ACTION"
    for key in _UI_EVENT_DEFAULTS["CRAWLER_VISION_ACTION"]:
        assert key in approach and key in done, f"{key} missing: the forwarder/overlay read it"
    for key in ("x", "y", "viewport_w", "viewport_h", "scroll_y", "scroll_height", "escalated"):
        assert key in approach, key
    assert approach["phase"] == "approach" and "ok" not in approach
    assert 0 <= approach["x"] <= 1 and 0 <= approach["y"] <= 1
    assert done["phase"] == "done" and done["ok"] is False and done["error"] == "click failed: boom"
    assert "visionX" not in approach and "action_status" not in approach, "names no consumer reads"
    assert approach["seq"] < done["seq"] and approach["run_id"] == done["run_id"]


def test_emitter_failure_never_fails_an_action():
    """AC5.4: a dead frontend (emit raising) must not break the action."""
    def boom(*_a):
        raise RuntimeError("socket gone")

    _session()._emit_action(boom, "approach", "click", 1, {})  # must not raise
    _session()._emit_action(None, "done", "click", 1, {}, ok=True)


def test_tool_bridge_hands_the_session_an_emitter_that_reaches_the_ui_forwarder(monkeypatch):
    """The bridge's emit adapter wraps (event, payload) into the object the crawl-UI
    forwarder reads, under the conversation's own id."""
    from backend.agent import tool_bridge
    from backend.agent.tools import browser_tools

    forwarded: list = []
    seen: dict = {}
    monkeypatch.setattr(tool_bridge, "_crawl_ui_emitter", lambda sid: forwarded.append)

    async def fake_open(conversation_id, url, emit=None):
        seen.update(conv=conversation_id, url=url)
        emit("CRAWLER_VISION_ACTION", {"phase": "approach", "kind": "click"})
        return {"success": True}

    monkeypatch.setattr(browser_tools, "browser_open", fake_open)
    bridge = tool_bridge.AgentToolBridge.__new__(tool_bridge.AgentToolBridge)
    bridge._active_conversation_id = {"sess-1": "conv-9"}

    result = asyncio.run(bridge._execute_browser_tool("browser_open", {"url": "https://x.test"}, "sess-1"))

    assert result == {"success": True} and seen == {"conv": "conv-9", "url": "https://x.test"}
    assert [(p.event, p.payload["phase"]) for p in forwarded] == [("CRAWLER_VISION_ACTION", "approach")]


def test_browser_cursor_events_reach_the_web_timing_line_from_the_sessions_thread(monkeypatch):
    """REQ-7: the session emits from its own loop thread, where the call's timing
    ContextVar is not set. The bridge must still count the pair as 2 cursor events
    and ONE browser action."""
    import threading

    from backend.agent import tool_bridge
    from backend.agent.tools import browser_tools

    monkeypatch.setattr(tool_bridge, "_crawl_ui_emitter", lambda sid: (lambda _p: None))

    async def fake_act(conversation_id, action, element_id=None, text=None, emit=None):
        def _from_the_browser_thread():
            emit("CRAWLER_VISION_ACTION", {"phase": "approach"})
            emit("CRAWLER_VISION_ACTION", {"phase": "done", "ok": True})

        t = threading.Thread(target=_from_the_browser_thread)
        t.start()
        t.join()
        return {"success": True}

    monkeypatch.setattr(browser_tools, "browser_act", fake_act)
    bridge = tool_bridge.AgentToolBridge.__new__(tool_bridge.AgentToolBridge)
    bridge._active_conversation_id = {}
    timing: dict = {}

    async def go():
        token = tool_bridge._WEB_TIMING.set(timing)
        try:
            await bridge._execute_browser_tool("browser_act", {"action": "click", "element_id": 1}, "s")
        finally:
            tool_bridge._WEB_TIMING.reset(token)

    asyncio.run(go())
    assert timing == {"cursor_events": 2, "browser_actions": 1}


def test_page_event_carries_what_the_panel_addresses_a_capture_by():
    """B3: CRAWLER_PAGE_FETCHED from the session has every key the forwarder
    defaults (job_id + capture_page are how the iframe finds the bytes)."""
    from backend.agent.tool_bridge import _UI_EVENT_DEFAULTS

    class _Page:
        url = "https://example.com/next"

        async def title(self):
            return "Next"

    got: list = []
    s = _session()
    s._page = _Page()
    s._last_published = "<html>x</html>"
    s._page_number = 3
    s._frames_published = 3

    async def publish():
        s._frames_published += 1
        s._page_number += 1
        return "<html>y</html>"

    s._publish_frame = publish
    asyncio.run(s._announce_page(lambda ev, p: got.append((ev, p))))

    ((ev, payload),) = got
    assert ev == "CRAWLER_PAGE_FETCHED"
    for key in _UI_EVENT_DEFAULTS["CRAWLER_PAGE_FETCHED"]:
        assert key in payload, key
    assert payload["job_id"] == "job-contract" and payload["capture_page"] == 4
    assert payload["capture_available"] is True


# ── fetch.vision: a failed action is not an ok action ──────────────────────


class _FailingSession:
    """BrowserSession stand-in whose click fails the way act() reports failure:
    it does NOT raise, it records `last_error`."""

    def __init__(self, *_a, **_k):
        self.last_action_point: dict = {}
        self.last_error = None

    async def open(self):
        return None

    def available(self):
        return True

    async def detect_wall(self):
        return None

    async def screenshot(self):
        return b"frame"

    async def act(self, action):
        self.last_error = "click failed: element not found" if action.kind == "click" else None

    current_capture_page = None

    async def settle(self):
        return "<html><body>settled content long enough to pass the floor</body></html>"

    async def close(self):
        return None


class _TwoActionProvider:
    def __init__(self):
        self.calls = 0

    def suggest_action(self, img_bytes, goal, **_k):
        self.calls += 1
        if self.calls == 1:
            return {"action": "click", "target": "#missing", "reasoning": "r"}
        if self.calls == 2:
            return {"action": "scroll", "target": "", "reasoning": "r"}
        return {"action": "error", "target": "", "reasoning": "done"}

    def describe_live_frame(self, *_a, **_k):
        return ""

    def read_text(self, *_a, **_k):
        return ""

    def analyze_screen(self, *_a, **_k):
        return ""


def test_fetch_vision_emits_a_failed_action_as_ok_false():
    """B2 / AC5.2 (RC8): act() swallows a failure into `last_error`; the loop
    used to emit that action as a success. It must report ok=false + the error."""
    from backend.vision.fetch_vision import FetchVisionCapability

    emitted: list = []
    cap = FetchVisionCapability(provider=_TwoActionProvider(), session_cls=_FailingSession)
    asyncio.run(cap.fetch_one("https://example.com/x", "goal", "job-fail", on_action=emitted.append))

    click, scroll = emitted
    assert click["kind"] == "click" and click["ok"] is False
    assert "element not found" in click["error"]
    assert scroll["kind"] == "scroll" and scroll["ok"] is True and "error" not in scroll


def test_handoff_hint_names_the_tool_and_the_unreadable_pages():
    """B4 / AC4.6: the crawl hands a page it could not read to the live browser."""
    from backend.agent.tools.browser_tools import handoff_hint

    hint = handoff_hint(["https://a.test/x", "not-a-url", "https://b.test/y"])
    assert "browser_open" in hint and "https://a.test/x" in hint and "https://b.test/y" in hint
    assert "not-a-url" not in hint
    assert handoff_hint([]) == "" and handoff_hint(None) == ""
