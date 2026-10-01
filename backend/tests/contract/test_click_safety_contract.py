"""Contract: browser tools are self-gated, and every element action passes the
click-safety gate (specs/research-memory-chain-browser W2, REQ-7).

  * no generic PERMISSION_REQUEST for browser_* with auto-approve OFF (a control
    tool that is not self-gated still asks);
  * the rules classify a fixture set: money / deletion / password submit / downloads
    are unsafe; navigation, paging, search, cookie decline are safe; an ambiguous
    "Continue" is unsure;
  * unsure + Brain unsure + no user answer -> ok=false, pivot=true, NO input
    dispatched; unsure + user yes -> acts; a refused element is not asked again;
  * one click_safety shadow row per assessment, paired with the gate's verdict.

No browser: the session is a recording fake on the real BrowserHost loop, so the
real ``browser_act`` -> ``_do_act`` -> gate path runs.
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from backend.agent import click_safety_shadow, permissions
from backend.agent.tools import browser_tools, click_safety
from backend.agent.tools.ask_user_tool import get_ask_user_tool, reset_ask_user_tool_for_testing
from backend.agent.tool_registry import resolve_tool

_BROWSER_TOOLS = ("browser_open", "browser_observe", "browser_act")


def _btn(name, **kw):
    return {"id": 1, "role": "button", "name": name, "tag": "button", **kw}


def _link(name, href):
    return {"id": 1, "role": "link", "name": name, "tag": "a", "href": href}


_LOGIN_FORM = {"fields": ["text::user", "password:current-password:pw"], "action": "/login"}
_SEARCH_FORM = {"fields": ["search::q"], "action": "/search"}

# (action, mark, expected verdict)
_FIXTURES = [
    ("click", _btn("Buy now"), "unsafe"),
    ("click", _btn("Checkout"), "unsafe"),
    ("click", _btn("Delete account"), "unsafe"),
    ("click", _btn("Log in", type="submit", form=_LOGIN_FORM), "unsafe"),
    ("click", _link("Report", "https://x.test/files/setup.exe"), "unsafe"),
    ("click", _link("Sign in with Google", "https://accounts.google.com/o/oauth2/auth?x=1"), "unsafe"),
    ("type", {"id": 1, "role": "textbox", "name": "Password", "tag": "input", "type": "password"}, "unsafe"),
    ("click", _link("Pricing", "/pricing"), "safe"),
    ("click", _btn("Next page"), "safe"),
    ("click", _btn("Reject all"), "safe"),
    ("type", {"id": 1, "role": "searchbox", "name": "Search", "tag": "input"}, "safe"),
    ("press", {"id": 1, "role": "searchbox", "name": "Search", "tag": "input", "form": _SEARCH_FORM}, "safe"),
    ("click", _btn("Continue", form={"fields": ["text::note"]}), "unsure"),
    ("click", _btn("Accept all"), "unsure"),
]


@pytest.mark.parametrize("action,mark,expected", _FIXTURES, ids=[f"{a}-{m['name']}" for a, m, _ in _FIXTURES])
def test_rules_classify_the_fixture_set(action, mark, expected):
    verdict, reason = click_safety.rule_verdict(action, mark, "https://shop.test/cart")
    assert verdict == expected, (verdict, reason)
    assert reason


# ── no generic consent prompt ──────────────────────────────────────────────


def test_browser_tools_are_self_gated_and_others_are_not():
    for name in _BROWSER_TOOLS:
        assert resolve_tool(name).self_gated is True, name
    assert resolve_tool("write_file").self_gated is False
    # W3: browser_explore reads other pages of the site and acts on nothing.
    explore = resolve_tool("browser_explore")
    assert explore.self_gated is True and explore.permission_tier == "read_only"
    assert explore.required == ["goal"] and explore.requires_internet is True
    from backend.agent.mcm_protocol.actions.pacman_fragment import is_external_tool

    assert is_external_tool("browser_explore")


async def test_no_permission_request_for_browser_tools_with_auto_approve_off(monkeypatch):
    from backend.agent.tool_bridge import AgentToolBridge
    from backend.agent import tool_registry

    monkeypatch.setattr(tool_registry, "_internet_provider", lambda: True)
    monkeypatch.setattr(permissions, "get_auto_approve", lambda: False)
    asked: list = []
    real = permissions.ToolPermissionSystem.request_permission

    def spy(self, tool_name, *a, **k):
        asked.append(tool_name)
        return real(self, tool_name, *a, **k)

    monkeypatch.setattr(permissions.ToolPermissionSystem, "request_permission", spy)

    async def fake_act(conversation_id, action, element_id=None, text=None, emit=None):
        return {"success": True}

    async def fake_open(conversation_id, url, emit=None):
        return {"success": True}

    async def fake_observe(conversation_id, emit=None):
        return {"success": True}

    monkeypatch.setattr(browser_tools, "browser_act", fake_act)
    monkeypatch.setattr(browser_tools, "browser_open", fake_open)
    monkeypatch.setattr(browser_tools, "browser_observe", fake_observe)
    bridge = AgentToolBridge()
    for name, params in (("browser_open", {"url": "https://x.test"}), ("browser_observe", {}),
                         ("browser_act", {"action": "click", "element_id": 1})):
        result = await bridge.execute_tool(name, params, "sess-cs")
        assert result.get("success") is True, (name, result)
    assert asked == [], f"the generic prompt fired for {asked}"


# ── the gate on the real browser_act path ──────────────────────────────────


class _Session:
    """Records every input; stands in for BrowserSession behind the real tool."""

    url = "https://shop.test/cart"

    def __init__(self, mark):
        self.last_marks = [mark]
        self._page = SimpleNamespace(url=self.url)
        self.interacts: list = []

    def available(self):
        return True

    def _budget_error(self):
        return ""

    async def interact(self, action, element_id, text, emit):
        self.interacts.append((action, element_id, text))
        return {"ok": True, "action": action, "changed": False, "title": "Cart", "url": self.url, "marks_seq": 1}

    async def close(self):
        pass


class _Engine:
    def decide(self, consumer_id, options, frame):
        return SimpleNamespace(chosen="unsure", confidence=0.5, engine_latency_ms=1)


@pytest.fixture
def gate(monkeypatch):
    """A session on the host loop, a stub Brain judge, a short answer window, a row sink."""
    reset_ask_user_tool_for_testing()
    rows: list = []
    monkeypatch.setattr(click_safety_shadow, "ENGINE", _Engine())
    monkeypatch.setattr(click_safety_shadow, "register_consumer", lambda: None)
    click_safety_shadow.set_row_sink(rows.append)
    judged: list = []

    def judge(prompt):
        judged.append(prompt)
        return '{"verdict": "unsure", "reason": "cannot tell"}'

    monkeypatch.setattr(click_safety, "_call_llm", judge)
    monkeypatch.setattr(click_safety, "ASK_TIMEOUT_S", 1)
    conv = f"cs-{time.monotonic_ns()}"
    state = SimpleNamespace(rows=rows, judged=judged, conv=conv, session=None)

    def install(mark):
        state.session = _Session(mark)
        browser_tools._RT.sessions[conv] = browser_tools._Entry(session=state.session)
        return state.session

    state.install = install
    yield state
    browser_tools._RT.sessions.pop(conv, None)
    click_safety_shadow.set_row_sink(None)
    reset_ask_user_tool_for_testing()


def _rows(state):
    from backend.utils.durability_queue import lane

    assert lane("click_safety_shadow").flush(5.0)
    return state.rows


async def test_unsafe_is_refused_with_a_pivot_and_no_input(gate):
    session = gate.install(_btn("Buy now"))
    res = await browser_tools.browser_act(gate.conv, "click", 1)
    assert res["success"] is False and res["ok"] is False and res["pivot"] is True
    assert "Buy now" in res["error"] and session.interacts == []
    assert [r["brain_choice"] for r in _rows(gate)] == ["unsafe"]


async def test_safe_acts_without_asking_and_writes_one_row(gate):
    session = gate.install(_link("Pricing", "/pricing"))
    asked: list = []
    tool = get_ask_user_tool()
    real = tool.ask
    tool.ask = lambda *a, **k: asked.append(1) or real(*a, **k)
    res = await browser_tools.browser_act(gate.conv, "click", 1)
    assert res["success"] is True and session.interacts == [("click", 1, None)]
    assert asked == [] and gate.judged == []
    (row,) = _rows(gate)
    assert row["consumer_id"] == "click_safety" and row["brain_choice"] == "safe" and row["shadow"] is True


async def test_unsure_with_no_answer_pivots_and_is_not_asked_twice(gate):
    session = gate.install(_btn("Continue", form={"fields": ["text::note"]}))
    tool = get_ask_user_tool()
    questions: list = []
    real = tool.ask
    tool.ask = lambda *a, **k: questions.append(k.get("text")) or real(*a, **k)
    res = await browser_tools.browser_act(gate.conv, "click", 1)
    assert res["success"] is False and res["ok"] is False and res["pivot"] is True
    assert session.interacts == [], "no input may be dispatched without an approval"
    assert len(gate.judged) == 1, "the Brain judged once before the user was asked"
    assert len(questions) == 1 and "Continue" in questions[0] and "Why I ask" in questions[0]

    again = await browser_tools.browser_act(gate.conv, "click", 1)  # same element, same task
    assert again["pivot"] is True and "already refused" in again["error"]
    assert len(questions) == 1 and session.interacts == []
    assert [r["brain_choice"] for r in _rows(gate)] == ["unsure"], "a remembered refusal is not a new assessment"


async def test_unsure_with_user_yes_acts(gate, monkeypatch):
    session = gate.install(_btn("Continue", form={"fields": ["text::note"]}))
    monkeypatch_answer = threading.Event()

    def answer_when_asked():
        tool = get_ask_user_tool()
        deadline = time.time() + 5
        while time.time() < deadline:
            pending = list(tool._pending)
            if pending:
                tool.resolve_answer(pending[0], "Yes, do it")
                monkeypatch_answer.set()
                return
            time.sleep(0.02)

    monkeypatch.setattr(click_safety, "ASK_TIMEOUT_S", 20)  # the answer arrives in milliseconds
    threading.Thread(target=answer_when_asked, daemon=True).start()
    res = await browser_tools.browser_act(gate.conv, "click", 1)
    assert monkeypatch_answer.is_set()
    assert res["success"] is True and session.interacts == [("click", 1, None)]
    assert [r["brain_choice"] for r in _rows(gate)] == ["unsure"], "the row carries the GATE verdict, not the answer"


async def test_the_task_goal_reaches_the_gate_on_the_host_loop(gate, monkeypatch):
    seen: list = []

    async def fake_assess(goal, action, mark, page_url="", text=None):
        seen.append(goal)
        return "safe", "ok"

    monkeypatch.setattr(click_safety, "assess", fake_assess)
    gate.install(_link("Pricing", "/pricing"))
    token = click_safety.ACT_CONTEXT.set({"goal": "find the pricing page", "conversation_id": gate.conv})
    try:
        await browser_tools.browser_act(gate.conv, "click", 1)
    finally:
        click_safety.ACT_CONTEXT.reset(token)
    assert seen == ["find the pricing page"]
