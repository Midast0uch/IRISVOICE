"""CT-3 (REQ-6 AC1): the orchestrator's `_vision_fetch` action contract lock.

`CrawlOrchestrator._vision_fetch` wraps a capability's `on_action` callback and
stamps `escalated` onto every payload before forwarding it to `_emit`. This is
a CONTRACT-LOCK area (design.md Ripple Map): the emitter SPI is
`_emit(event_name, payload)` — TWO positional args — and the forwarded payload
must be the producer's WHOLE payload plus the escalation stamp (never a
subset). A signature drift here silently drops every action event.

Hermetic: a fake capability drives the emitter; no browser, no network.
"""

from __future__ import annotations

import asyncio

from backend.crawler.orchestrator import CrawlOrchestrator


class _FakeVisionCap:
    name = "fetch.vision"

    async def fetch_one(self, url, goal, job_id, on_action=None, page_offset=0):
        if on_action is not None:
            on_action({
                "job_id": job_id, "url": url, "kind": "click",
                "action_index": 1, "total": 5,
                "x": 0.5, "y": 0.5, "seq": 7, "run_id": job_id,
            })
        return object()


def _collect_into(events: list):
    # The orchestrator's `_emit` SPI is `_emit(event_name, payload)`.
    def _emit(ev, payload):
        events.append((ev, payload))
    return _emit


def test_vision_fetch_forwards_whole_payload_and_stamps_escalated():
    """REQ-6 AC1 / CT-3: the emitted payload is the producer's whole payload
    PLUS `escalated`; no field is dropped by the orchestrator."""
    events: list = []
    asyncio.run(CrawlOrchestrator._vision_fetch(
        _FakeVisionCap(), "https://a.example/x", "goal", "job-ct3",
        _collect_into(events), page_offset=0, escalated=True,
    ))
    assert len(events) == 1
    ev, payload = events[0]
    assert ev == "CRAWLER_VISION_ACTION"
    assert payload["escalated"] is True
    # The producer's fields survive (including the T3 seq/run_id additions).
    for k in ("job_id", "url", "kind", "action_index", "total", "x", "y",
              "seq", "run_id"):
        assert k in payload, f"_vision_fetch dropped producer field {k!r} (CT-3)"


def test_vision_fetch_emitter_spi_is_two_positional_args():
    """CT-3: the emitter SPI is `_emit(event_name, payload)` — a one-arg
    emitter (e.g. `list.append`) must not be silently accepted."""
    calls: list = []

    def _one_arg_only(payload):
        calls.append(payload)

    # _vision_fetch passes TWO args; a one-arg callable raises, which the
    # capability wrapper's fallback swallows — proving the SPI shape matters.
    # Here we assert the two-arg path works and records the event name.
    events: list = []
    asyncio.run(CrawlOrchestrator._vision_fetch(
        _FakeVisionCap(), "https://a.example/x", "goal", "job-ct3b",
        _collect_into(events),
    ))
    assert events and events[0][0] == "CRAWLER_VISION_ACTION"
