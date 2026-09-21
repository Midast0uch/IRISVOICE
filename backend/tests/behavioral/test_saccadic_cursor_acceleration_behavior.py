"""BT-2 (vision-goal-directed-search T24, REQ-3 AC3.3 + DESIGN §"Rapid Action
Burst"): a burst of vision actions arrives over the event wire at machine
speed — the backend side of saccadic acceleration is that every action lands
IMMEDIATELY, in order, with monotonically increasing indices — nothing is
dropped, buffered, or re-sequenced. (The ≤180ms transit compression itself
is exercised in the frontend suites — T19 —; this file pins that the
producer side never queues a burst.)

Drives orchestrator._vision_fetch with a fake capability firing a 5-action
burst (the Error-Handling matrix's canonical burst pattern).
"""
from __future__ import annotations

import asyncio

from backend.crawler.orchestrator import CrawlOrchestrator


class _BurstVisionCap:
    name = "fetch.vision"

    def __init__(self, burst: int = 5):
        self._burst = burst

    async def fetch_one(self, url, goal, job_id, on_action=None, page_offset=0):
        # Machine-speed burst: five actions back-to-back with no awaiting
        # between them — 5/1s burst, exactly the saccadic trigger family.
        for i in range(self._burst):
            if on_action is not None:
                on_action({
                    "job_id": job_id, "url": url, "kind": "click",
                    "action_index": i + 1, "total": self._burst,
                    "x": 0.5, "y": 0.5,
                })
        return object()


def test_rapid_action_burst_arrives_ordered_and_undropped():
    import time as _t

    events: list = []

    def _emit(ev, payload):
        events.append((_t.monotonic(), ev, payload))

    t0 = _t.monotonic()
    asyncio.run(
        CrawlOrchestrator._vision_fetch(
            _BurstVisionCap(5), "https://ex.example/x", "g", "j-burst", _emit,
            page_offset=0, escalated=True,
        )
    )
    elapsed = _t.monotonic() - t0

    assert len(events) == 5, f"burst dropped/coalesced events: got {len(events)}"
    assert all(ev == "CRAWLER_VISION_ACTION" for _, ev, _ in events)
    # Indices strictly ascending and exactly 1..5 — order is identity for the
    # cursor's action_index derivation.
    assert [p["action_index"] for _, _, p in events] == [1, 2, 3, 4, 5]
    # Machine-speed: 5 actions delivered inside a small window — the travel
    # budget the saccadic mode exists for is ~620ms each; the PRODUCER must
    # never add latency of its own.
    assert elapsed < 0.5, (
        f"5-action burst delivered in {elapsed*1000:.0f}ms — producer-side "
        f"delay defeats the saccadic frontend"
    )
    # Escalated propagation persists across the burst (rides every payload).
    assert all(p["escalated"] is True for _, _, p in events)


def test_burst_preserves_emission_even_when_first_action_omits_coords():
    """A burst whose FIRST action is a scroll (no x/y) must still emit — the
    overlay holds the last point for scroll actions rather than teleporting
    to (0,0), and the action_index sequence must not skip."""
    class _ScrollFirst(_BurstVisionCap):
        async def fetch_one(self, url, goal, job_id, on_action=None, page_offset=0):
            if on_action is not None:
                on_action({
                    "job_id": job_id, "url": url, "kind": "scroll",
                    "action_index": 1, "total": self._burst,
                    "scroll_y": 0, "scroll_height": 2400,
                })
                for i in range(1, self._burst):
                    on_action({
                        "job_id": job_id, "url": url, "kind": "scroll",
                        "action_index": i + 1, "total": self._burst,
                        "scroll_y": i * 400, "scroll_height": 2400,
                    })
            return object()

    events: list = []

    def _emit(ev, payload):
        if ev == "CRAWLER_VISION_ACTION":
            events.append(payload)

    asyncio.run(
        CrawlOrchestrator._vision_fetch(
            _ScrollFirst(5), "https://ex.example/y", "g", "j-scrollburst", _emit,
        )
    )
    assert len(events) == 5
    assert [p.get("action_index") for p in events] == [1, 2, 3, 4, 5]
    assert all("scroll_y" in p for p in events), (
        "scroll bursts lost the absolute scroll position — the iframe mirror "
        "would drift off the page the model is actually reading"
    )
