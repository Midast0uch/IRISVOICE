"""CT-1 (vision-goal-directed-search REQ-3 AC3.2, T23): the full
CRAWLER_VISION_ACTION wire shape.

The pre-existing CT chain (test_crawl_event_shapes_contract.py) pins the
ROUND TRIP of kind/action_index and the x/y/viewport fields. This contract
pins the FULL ac20.23-committed CT-1 surface, end to end:

    BrowserSession.act() records last_action_point
      -> fetch.vision folds it into the action payload (x, y, scroll_y,
         scroll_height, viewport_w, viewport_h)
      -> orchestrator._vision_fetch stamps `escalated`
      -> the forwarded payload carries ALL of: kind, action_index, total,
         x, y, scroll_y, scroll_height, viewport_w, viewport_h, escalated

All assertions are producer-side (no network, no browser): the capability
loop is driven with fake session/provider objects, exactly like
test_crawl_event_shapes_contract.py's existing vision test.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.vision.fetch_vision import FetchVisionCapability


CT1_REQUIRED = (
    "kind",
    "action_index",
    "total",
    "x",
    "y",
    "scroll_y",
    "scroll_height",
    "viewport_w",
    "viewport_h",
    "escalated",
)


class _FakeSession:
    """Minimal BrowserSession stand-in producing the CT-1 point fields."""

    def __init__(self, *_a, **_k):
        self.last_action_point: dict = {}
        self._capture_page: int | None = None

    async def open(self):
        return None

    def available(self):
        return True

    async def detect_wall(self):
        return None

    async def screenshot(self):
        return b"frame-bytes"

    async def act(self, action):
        kind = getattr(action, "kind", "act")
        if kind == "click":
            self.last_action_point = {
                "x": 0.42, "y": 0.61, "viewport_w": 1280, "viewport_h": 800,
            }
        elif kind == "scroll":
            self.last_action_point = {
                "scroll_y": 420, "scroll_height": 3000,
                "viewport_w": 1280, "viewport_h": 800,
            }
        self._capture_page = 103

    # Must mirror browser_session.py's DECLARATION SHAPE: it is a @property,
    # not a method — the first draft of this fake made it a method and the
    # emit's int(property_result) crashed silently inside fetch_vision's
    # must-never-break except handler, producing zero events. The failure was
    # in the fake, not the production code.
    @property
    def current_capture_page(self):
        return self._capture_page

    async def settle(self):
        return "<html><body>settled content long enough to pass</body></html>"

    async def close(self):
        return None


class _ScriptedProvider:
    """Suggests one click, one scroll, then ends the loop with an error
    sentinel (the loop's stop-without-frames path, identical to the existing
    vision contract test)."""

    def __init__(self):
        self.calls = 0

    def suggest_action(self, img_bytes, goal, **_k):
        self.calls += 1
        if self.calls == 1:
            return {"action": "click", "target": "#cta", "reasoning": "open panel"}
        if self.calls == 2:
            return {"action": "scroll", "target": "", "reasoning": "reveal more"}
        return {"action": "error", "target": "", "reasoning": "done"}

    def describe_live_frame(self, img_bytes, **_k):
        return "no new content"

    def read_text(self, img_bytes, **_k):
        return ""

    def analyze_screen(self, img_bytes, question, **_k):
        return ""


def test_vision_action_payload_carries_full_ct1_shape():
    """AC3.2 (CT-1): EVERY emitted action carries the full CT-1 field set.

    CT-1 is the handshake between the backend vision loop and the saccadic
    cursor / scroll mirror on the overlay. A missing field here dies silently
    in the renderer (undefined keeps the last value) — so it has to be
    asserted at production.
    """
    emitted: list[dict] = []
    cap = FetchVisionCapability(provider=_ScriptedProvider(), session_cls=_FakeSession)
    asyncio.run(
        cap.fetch_one(
            "https://example.com/goal", "a goal", "job-ct1",
            on_action=emitted.append,
        )
    )

    assert len(emitted) == 2, (
        f"expected the scripted click+scroll to emit exactly 2 actions, "
        f"got {len(emitted)}"
    )

    click, scroll = emitted
    # Base shape pinned by the pre-existing CT-3 chain, re-pinned here as the
    # foundation CT-1 extends.
    for p, expected_kind in ((click, "click"), (scroll, "scroll")):
        assert p["kind"] == expected_kind
        assert p["job_id"] == "job-ct1"
        assert p["url"] == "https://example.com/goal"

    # Cursor point rides the click exactly as BrowserSession captured it.
    assert click["x"] == pytest.approx(0.42)
    assert click["y"] == pytest.approx(0.61)
    assert click["viewport_w"] == 1280
    assert click["viewport_h"] == 800

    # Scroll mirror rides the scroll action.
    assert scroll["scroll_y"] == 420
    assert scroll["scroll_height"] == 3000

    # The capture address must travel with the frame it was published for
    # (the REQ-3 AC5 / capture_store.ts alignment, REQ-11 AC4 fix).
    assert click.get("capture_page") == 103
    assert scroll.get("capture_page") == 103

    # `escalated` is NOT fetch.vision's to set — the orchestrator stamps it in
    # `_vision_fetch` because the escalated truth is a ROUTING fact, not an
    # action fact. Asserted separately in test_escalated_stamp below.
    # action_index is 1-based and strictly increasing per the existing chain.
    assert click["action_index"] == 1
    assert scroll["action_index"] == 2
    assert click["total"] == scroll["total"] and click["total"] > 0


class _FakeVisionCap:
    """fetch.vision per the FetchCapability protocol (+ on_action) stamping a
    canned CT-1 payload through the orchestrator's `_vision_fetch`."""

    name = "fetch.vision"

    async def fetch_one(self, url, goal, job_id, on_action=None, page_offset=0):
        if on_action is not None:
            on_action({
                "job_id": job_id, "url": url, "kind": "click",
                "action_index": 1, "total": 1,
                "x": 0.5, "y": 0.5, "viewport_w": 1280, "viewport_h": 800,
                "scroll_y": 0, "scroll_height": 0,
                "capture_page": page_offset + 2,
            })
        # Object stand-in for FetchOutcome — _vision_fetch returns it
        # untouched; only the emitter shape is under contract here.
        return object()


def _collect_into(events: list) -> "object":
    """The orchestrator's `_emit` SPI is `_emit(event_name, payload)` — two
    positional args, not one. (A first draft passed `list.append`; the
    resulting TypeError is swallowed by `_vision_fetch`'s fallback path and
    zero events arrive — a swallowed-signature-mismatch trap worth pinning
    by construction here.)"""

    def _emit(ev, payload):
        events.append((ev, payload))

    return _emit


@pytest.mark.parametrize("escalated", [True, False])
def test_escalated_stamp_honors_routing_truth(escalated):
    """AC (CT-1 completion): orchestrator._vision_fetch stamps `escalated`
    onto every action payload so the overlay's "notice" beat fires ONLY for
    genuine escalations (a raced session is not an escalation)."""
    from backend.crawler.orchestrator import CrawlOrchestrator

    events: list = []
    asyncio.run(
        CrawlOrchestrator._vision_fetch(
            _FakeVisionCap(), "https://example.com/x", "goal", "job-esc",
            _collect_into(events), page_offset=2, escalated=escalated,
        )
    )
    assert len(events) == 1
    ev, payload = events[0]
    assert ev == "CRAWLER_VISION_ACTION"
    assert payload["escalated"] is escalated

    # Full CT-1 key check on the FINAL emitted payload — the stamp is
    # additive; it must never drop the producer's fields.
    assert set(CT1_REQUIRED) <= set(payload), (
        f"forwarded vision action payload lost CT-1 fields: "
        f"{set(CT1_REQUIRED) - set(payload)}"
    )


def test_capture_page_offset_flows_from_the_dispatch_slot():
    """AC (CT-3 alignment, REQ-3 AC5): page_offset reaches the frame's
    capture_page so vision frames land in the URL's OWN reserved slot block,
    not the job root."""
    from backend.crawler.orchestrator import CrawlOrchestrator

    events: list = []
    asyncio.run(
        CrawlOrchestrator._vision_fetch(
            _FakeVisionCap(), "https://example.com/x", "goal", "job-off",
            _collect_into(events), page_offset=7, escalated=False,
        )
    )
    assert events[0][1]["capture_page"] == 9  # 7 + 2 — slot block starts at offset+2
