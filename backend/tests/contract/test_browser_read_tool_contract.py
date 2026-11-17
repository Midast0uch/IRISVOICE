"""Contract: `browser_read` (CLM Round 6, C5) - the open page's main text and links.

A read-only browser tool for browser code nodes: it is a normal browser tool
(claim, gather family, read-only tier, external tool) but NOT on the node menu
(`NODE_TOOLS`), so the menu prompt does not grow. No browser: a fake page stands
in for the session's page.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.agent import external_reference, node_executor, tool_registry
from backend.agent.kernel.base import _NODE_CLAIMS
from backend.agent.tool_envelope import tool_family
from backend.agent.tools import browser_tools as bt


class _FakePage:
    url = "https://example.test/doc"

    def __init__(self, text: str, links):
        self._text, self._links, self.calls = text, links, []

    async def evaluate(self, js):
        self.calls.append(js)
        return self._text if js == bt._MAIN_TEXT_JS else self._links

    async def title(self):
        return "A Doc"


class _FakeSession:
    url = "https://example.test/doc"

    def __init__(self, page):
        self._page = page

    def available(self):
        return True


@pytest.fixture
def conv(monkeypatch):
    async def _run(coro, timeout):
        return await coro

    monkeypatch.setattr(bt._RT, "run", _run)
    monkeypatch.setattr(bt._RT, "sessions", type(bt._RT.sessions)())
    return "read-conv"


def _open(monkeypatch, conv, text, links=()):
    page = _FakePage(text, [list(x) for x in links])
    monkeypatch.setitem(bt._RT.sessions, conv, bt._Entry(session=_FakeSession(page)))
    return page


def test_spec_exists_with_max_chars_and_read_only_tier():
    spec = next((s for s in tool_registry.get_all_specs() if s.name == "browser_read"), None)
    assert spec is not None
    assert "max_chars" in spec.parameters
    assert spec.permission_tier == "read_only"


def test_it_is_a_normal_browser_tool_but_not_on_the_node_menu():
    assert "browser_read" in _NODE_CLAIMS["browser"]
    assert tool_family("browser_read") == "gather"
    assert "browser_read" in external_reference.EXTERNAL_TOOLS
    assert "browser_read" not in node_executor.NODE_TOOLS


def test_read_returns_text_capped_links_untrusted_and_no_image(conv, monkeypatch):
    _open(monkeypatch, conv, "word " * 1000, [("https://example.test/a", "Alpha")])
    res = asyncio.run(bt.browser_read(conv, 100))
    assert res["success"] is True
    assert len(res["text"]) <= 100 and res["truncated"] is True
    assert res["links"] == [{"href": "https://example.test/a", "text": "Alpha"}]
    assert "https://example.test/a" in res["content"]
    assert res["trust"] == "untrusted"
    assert res["url"] == "https://example.test/doc" and res["title"] == "A Doc"
    assert "marked_screenshot" not in res and "marks" not in res


def test_max_chars_is_clamped_to_the_hard_maximum(conv, monkeypatch):
    _open(monkeypatch, conv, "x" * 250_000)
    res = asyncio.run(bt.browser_read(conv, 10_000_000))
    assert len(res["text"]) == 200_000


def test_read_never_navigates_or_acts(conv, monkeypatch):
    page = _open(monkeypatch, conv, "hello")
    asyncio.run(bt.browser_read(conv))
    assert set(page.calls) <= {bt._MAIN_TEXT_JS, bt._LINKS_JS}


def test_read_fails_cleanly_with_no_page(conv):
    res = asyncio.run(bt.browser_read(conv))
    assert res["success"] is False and "browser_open" in res["error"]
