"""CT-3: crawler_vision_action / crawler_source_parked event shapes (REQ-11 AC4, REQ-13 AC4).

This test exists because of a gap it caught on 2026-08-10: the ENTIRE frontend
for ``crawler_vision_action`` was built and wired — ``types/iris.ts``
``CrawlerVisionActionMsg``, ``useCrawl.ts`` storing ``visionActions[]``,
``useIRISWebSocket.ts`` dispatching ``iris:crawler_vision_action`` — while the
backend had ZERO emitters and no ``UX_MAP`` entry. Every isolated test passed.

That is the codebase's dominant failure mode inverted: consumer built, producer
missing. A test that asserts the emitter works, or that the listener works, sees
nothing wrong. Only a test that walks the whole chain does.

So CT-3 asserts the ROUND TRIP for both events:
    orchestrator emits  ->  UX_MAP maps it  ->  gateway forwards that msg_type
                        ->  frontend type declares the same fields

The frontend half is asserted by reading types/iris.ts rather than by running
TS: a Python contract test that stops at the WS boundary would have passed
throughout the outage described above.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.crawler.ux_map import UX_MAP, known_events, map_event

_REPO = Path(__file__).resolve().parents[3]


def _read(rel: str) -> str:
    p = _REPO / rel
    assert p.is_file(), f"expected {rel} to exist at {p}"
    return p.read_text(encoding="utf-8", errors="replace")


# ── the two events under contract ─────────────────────────────────────────
# (internal event name, WS msg_type, TS interface, required payload fields)
_CONTRACTS = [
    (
        "CRAWLER_VISION_ACTION",
        "crawler_vision_action",
        "CrawlerVisionActionMsg",
        (
            "job_id", "url", "kind", "reason", "action_index", "total",
            # REQ-16 AC7: best-effort particle-trail cursor coordinates —
            # x/y/viewport_w/viewport_h for click/type, scroll_dx/scroll_dy
            # for scroll. Optional (the field regex below accepts `field?:`),
            # since bounding_box() capture is best-effort and must never block
            # the action it is attached to.
            "x", "y", "viewport_w", "viewport_h", "scroll_dx", "scroll_dy",
        ),
    ),
    (
        "CRAWLER_SOURCE_PARKED",
        "crawler_source_parked",
        "CrawlerSourceParkedMsg",
        ("url",),
    ),
]


@pytest.mark.parametrize("event,msg_type,_ts,_fields", _CONTRACTS)
def test_event_is_in_ux_map(event, msg_type, _ts, _fields):
    """AC: every event the orchestrator can emit has a UX_MAP entry.

    ux_map.py's own comment says "Keep this exhaustive ... (enforced by a test)".
    CRAWLER_VISION_ACTION was absent while the frontend already consumed it.
    """
    assert event in known_events(), (
        f"{event} has no UX_MAP entry — the WS and SSE transports derive their "
        f"msg_type from this table, so an unmapped event reaches neither."
    )
    assert map_event(event).msg_type == msg_type


@pytest.mark.parametrize("event,msg_type,_ts,_fields", _CONTRACTS)
def test_gateway_forwards_the_mapped_msg_type(event, msg_type, _ts, _fields):
    """AC: the gateway's _on_progress handler forwards the event's msg_type.

    A UX_MAP entry with no matching branch in the gateway is a mapped event that
    still never reaches a client.
    """
    gw = _read("backend/iris_gateway.py")
    assert f'ev == "{event}"' in gw, (
        f"iris_gateway._on_progress has no branch for {event}"
    )
    assert f'"type": "{msg_type}"' in gw, (
        f"iris_gateway never sends a {msg_type!r} message"
    )


@pytest.mark.parametrize("event,msg_type,ts_iface,fields", _CONTRACTS)
def test_frontend_type_declares_the_same_shape(event, msg_type, ts_iface, fields):
    """AC: the TS interface exists and declares the payload fields the backend
    sends. Pins both halves against silent drift in either direction."""
    iris_ts = _read("types/iris.ts")
    assert f"interface {ts_iface}" in iris_ts, (
        f"types/iris.ts has no {ts_iface}"
    )
    body = iris_ts.split(f"interface {ts_iface}", 1)[1].split("}", 1)[0]
    assert f"'{msg_type}'" in body, (
        f"{ts_iface}.type is not '{msg_type}'"
    )
    for field in fields:
        assert re.search(rf"\b{field}\b\??:", body), (
            f"{ts_iface} is missing field {field!r} that the backend sends"
        )


@pytest.mark.parametrize("event,msg_type,_ts,_fields", _CONTRACTS)
def test_frontend_listens_for_the_dispatched_event(event, msg_type, _ts, _fields):
    """AC: useIRISWebSocket dispatches iris:<msg_type> AND useCrawl listens.

    The producer-missing outage was only visible end to end; this closes the
    last link so neither half can be removed without a red test.
    """
    ws = _read("hooks/useIRISWebSocket.ts")
    assert f'case "{msg_type}"' in ws, (
        f"useIRISWebSocket has no case for {msg_type!r}"
    )
    assert f"'iris:{msg_type}'" in ws, (
        f"useIRISWebSocket never dispatches iris:{msg_type}"
    )
    crawl = _read("hooks/useCrawl.ts")
    assert f'"iris:{msg_type}"' in crawl, (
        f"useCrawl does not listen for iris:{msg_type}"
    )


def test_vision_capability_actually_emits_the_action_event():
    """AC (REQ-11 AC4): fetch.vision emits one CRAWLER_VISION_ACTION per action.

    This is the assertion that was missing. It drives the real capability with a
    fake session/provider and asserts events come out — not that a function
    exists that could emit them.
    """
    import asyncio

    from backend.vision.fetch_vision import FetchVisionCapability

    class _FakeSession:
        def __init__(self, *_a, **_k):
            self.acted = []

        async def open(self):
            return None

        def available(self):
            return True

        async def detect_wall(self):
            return None

        async def screenshot(self):
            return b"frame-bytes"

        async def act(self, action):
            self.acted.append(action.kind)

        async def settle(self):
            return "<html><body>settled content well past the minimum</body></html>"

        async def close(self):
            return None

    # Suggests two scrolls then stops, so the loop performs exactly 2 actions.
    class _FakeProvider:
        def __init__(self):
            self.calls = 0

        def suggest_action(self, img_bytes, goal, **_k):
            self.calls += 1
            if self.calls <= 2:
                return {"action": "scroll", "target": "", "reasoning": "reveal more"}
            return {"action": "error", "target": "", "reasoning": "done"}

        def describe_live_frame(self, img_bytes, **_k):
            return "no new content"

        def read_text(self, img_bytes, **_k):
            return ""

        def analyze_screen(self, img_bytes, question, **_k):
            return ""

    emitted: list[dict] = []
    cap = FetchVisionCapability(provider=_FakeProvider(), session_cls=_FakeSession)
    asyncio.run(
        cap.fetch_one(
            "https://example.com/a", "goal", "job-1",
            on_action=emitted.append,
        )
    )

    assert emitted, (
        "fetch.vision performed actions but emitted no CRAWLER_VISION_ACTION "
        "payloads — REQ-11 AC4 unwired (the original defect)"
    )
    required = {"job_id", "url", "kind", "reason", "action_index", "total"}
    for payload in emitted:
        assert required <= set(payload), (
            f"emitted payload missing fields: {required - set(payload)}"
        )
    # action_index is 1-based and strictly increasing — the panel renders "n of N".
    assert [p["action_index"] for p in emitted] == list(
        range(1, len(emitted) + 1)
    )
    assert all(p["job_id"] == "job-1" for p in emitted)
    assert all(p["url"] == "https://example.com/a" for p in emitted)


def test_emitter_failure_never_breaks_the_vision_loop():
    """AC (REQ-16 AC7): instrumentation is off the critical path.

    A raising on_action must not fail the fetch — logging is never allowed to
    cost a page.
    """
    import asyncio

    from backend.vision.fetch_vision import FetchVisionCapability

    class _FakeSession:
        def __init__(self, *_a, **_k):
            pass

        async def open(self):
            return None

        def available(self):
            return True

        async def detect_wall(self):
            return None

        async def screenshot(self):
            return b"frame-bytes"

        async def act(self, action):
            return None

        async def settle(self):
            return "<html><body>settled content well past the minimum</body></html>"

        async def close(self):
            return None

    class _FakeProvider:
        def __init__(self):
            self.calls = 0

        def suggest_action(self, img_bytes, goal, **_k):
            self.calls += 1
            return (
                {"action": "scroll", "target": "", "reasoning": "r"}
                if self.calls <= 1
                else {"action": "error", "target": "", "reasoning": "done"}
            )

        def describe_live_frame(self, img_bytes, **_k):
            return "no new content"

        def read_text(self, img_bytes, **_k):
            return ""

        def analyze_screen(self, img_bytes, question, **_k):
            return ""

    def _boom(_payload):
        raise RuntimeError("emitter exploded")

    cap = FetchVisionCapability(provider=_FakeProvider(), session_cls=_FakeSession)
    outcome = asyncio.run(
        cap.fetch_one("https://example.com/b", "goal", "job-2", on_action=_boom)
    )
    assert outcome is not None
    assert outcome.actions_taken >= 1, (
        "a raising emitter aborted the action loop — instrumentation must be "
        "off the critical path"
    )
