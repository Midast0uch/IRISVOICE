"""The crawl->panel forwarder must not be where fields go to die.

`_crawl_ui_emitter` sits between the orchestrator (which builds the payload) and
the WebSocket (which the panel reads). It was a hand-written per-event allowlist,
and it failed the same way three times, each time with BOTH ends correct and only
the middle wrong:

  1. It dropped ``job_id`` — the panel's tab listener bails without it, so no web
     tab was created and the panel URL never changed for a whole crawl.
  2. It dropped the progress emitter entirely (pin_883b20571a56).
  3. It dropped ``capture_page`` — the panel fell back to the UI counter and
     requested /api/browser/capture/<job>/5 while the bytes were saved at 101.
     Live 2026-08-11 22:47: 404 on pages 4 and 5 with 1.html, 2.html, 102.html,
     103.html and 202.html all present on disk.

And it gated the EVENTS too: only started/page_fetched/open_tab/complete/error
had a branch, so CRAWLER_VISION_ACTION, CRAWLER_SOURCE_PARKED, CRAWLER_PHASE and
CRAWLER_SOURCES_ADDED never reached the client on the agent path at all — the
particle cursor had nothing to render from, which is why it was never seen live
despite being complete and tested.

These tests pin the two properties that make the class impossible: every crawler
event the orchestrator can emit is forwarded, and each one's payload arrives
WHOLE rather than filtered through a field list.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from backend.agent.tool_bridge import _UI_EVENT_DEFAULTS

_REPO = Path(__file__).resolve().parents[3]
_ORCH = _REPO / "backend" / "crawler" / "orchestrator.py"


def _emitted_event_names() -> set:
    """Every literal event name the orchestrator emits via its `_emit` helper.

    Read from the SOURCE rather than from a hand-kept list, so a newly added
    event is caught here instead of being silently undeliverable.
    """
    tree = ast.parse(_ORCH.read_text(encoding="utf-8", errors="replace"))
    names: set = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        fn_name = getattr(fn, "id", None) or getattr(fn, "attr", None)
        if fn_name not in {"_emit", "emit"}:
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            val = node.args[0].value
            if isinstance(val, str) and val.isupper():
                names.add(val)
    return names


def test_every_orchestrator_crawler_event_is_forwarded():
    emitted = _emitted_event_names()
    assert emitted, "parsed no events from orchestrator.py — the AST walk is wrong"

    missing = sorted(e for e in emitted if e not in _UI_EVENT_DEFAULTS)
    assert not missing, (
        f"the orchestrator emits {missing} but the forwarder has no entry, so "
        f"those events never reach the panel. Anything the UI is meant to react "
        f"to must be in _UI_EVENT_DEFAULTS; that membership is the only gate."
    )


@pytest.mark.parametrize(
    "event,payload,must_survive",
    [
        (
            "CRAWLER_PAGE_FETCHED",
            {
                "url": "https://e.example/a", "page_number": 5, "total": 5,
                "host": "e.example", "job_id": "job-x", "title": "t",
                "capture_page": 401, "capture_available": True,
            },
            # capture_page is the whole point: page_number is the counter, and
            # building the iframe src from it is what 404'd.
            ["capture_page", "capture_available", "job_id", "page_number"],
        ),
        (
            "CRAWLER_STARTED",
            {"query": "q", "url_count": 5, "urls": ["https://a", "https://b"],
             "discovered_urls": [], "job_id": "job-x", "session_id": "s"},
            # The plan card lists the sources the agent INTENDS to read; the
            # count alone cannot express that.
            ["urls", "discovered_urls"],
        ),
        (
            "CRAWLER_VISION_ACTION",
            {"job_id": "j", "url": "https://e", "kind": "click", "x": 0.5,
             "y": 0.25, "viewport_w": 1280, "viewport_h": 720, "capture_page": 102},
            # The particle cursor's coordinates. Dropped, it has nothing to draw.
            ["x", "y", "viewport_w", "viewport_h", "capture_page"],
        ),
        (
            "CRAWLER_SOURCES_ADDED",
            {"job_id": "j", "urls": ["https://new"], "reason": "broadened_replan"},
            ["urls", "reason"],
        ),
    ],
)
def test_payload_fields_survive_the_forwarder(event, payload, must_survive, monkeypatch):
    sent = _forward(event, payload, monkeypatch)

    assert sent, f"{event} was not forwarded to the panel at all"
    msg = sent[-1]
    assert msg["type"] == event.lower(), (
        f"forwarded as {msg['type']!r}; the frontend switches on {event.lower()!r}"
    )
    for key in must_survive:
        assert key in msg, (
            f"{event} lost {key!r} crossing the forwarder. Present: "
            f"{sorted(msg)}"
        )
        assert msg[key] == payload[key], (
            f"{event}.{key} changed value: {payload[key]!r} -> {msg[key]!r}"
        )


def test_capture_page_is_not_silently_defaulted_to_the_counter(monkeypatch):
    """Degrading to page_number here would reinstate the exact 404 in silence."""
    sent = _forward(
        "CRAWLER_PAGE_FETCHED",
        {"url": "https://e/a", "page_number": 4, "total": 5, "job_id": "j"},
        monkeypatch,
    )

    assert sent
    assert sent[-1].get("capture_page") != 4, (
        "an absent capture_page was defaulted to the UI counter — the panel "
        "would request the counter as an address, which is the original bug"
    )


class _FakeWS:
    """Records what would be broadcast to the panel."""

    def __init__(self, sink: list):
        self._sink = sink

    def get_clients_for_session(self, _sid):
        return ["client-1"]

    async def broadcast_to_session(self, _sid, msg):
        self._sink.append(msg)


def _install_fake_ws(monkeypatch, sink: list):
    """Patch the manager the emitter actually resolves.

    It imports `get_websocket_manager` from backend.ws_manager INSIDE the call,
    so the patch must land on that module, not on tool_bridge.
    """
    import backend.ws_manager as wsm

    monkeypatch.setattr(wsm, "get_websocket_manager", lambda *_a, **_k: _FakeWS(sink))


def _forward(event: str, payload: dict, monkeypatch) -> list:
    """Run one event through the emitter inside a loop, return what was sent.

    The emitter is called SYNCHRONOUSLY by the orchestrator and schedules its
    sends with ensure_future, so there must be a running loop or every send is
    created and dropped — which would make these tests pass vacuously against a
    forwarder that sends nothing.
    """
    import asyncio

    from backend.agent.tool_bridge import _crawl_ui_emitter
    from backend.crawler.orchestrator import CrawlProgress

    sent: list = []
    _install_fake_ws(monkeypatch, sink=sent)

    async def _run():
        _crawl_ui_emitter("sess-fwd")(CrawlProgress(event, payload))
        # Let the scheduled broadcast task actually run.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(_run())
    return sent
