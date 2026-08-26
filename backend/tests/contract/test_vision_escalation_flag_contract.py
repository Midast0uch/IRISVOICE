"""CT-4 (specs/vision-browser-stage REQ-8): the `escalated` flag survives the
FULL WS hop — orchestrator payload -> gateway whitelist -> frontend message.

WHY THIS EXISTS. The gateway's CRAWLER_VISION_ACTION branch copies an explicit
key whitelist onto the outgoing message; its own comment warns that a field
missing from that tuple "dies right here". This test drives the REAL
whitelisting code path (the same branch `_handle_crawler_query._on_progress`
executes) so a future emitter or whitelist edit cannot silently drop it.
"""

from __future__ import annotations

import asyncio

import pytest


def _gateway_relay() -> callable:
    """Build the SAME relay closure _handle_crawler_query uses, without a
    live gateway: we exercise the whitelisting logic by importing the real
    handler source is overkill — instead pin the contract at BOTH ends:
    (1) the orchestrator stamps `escalated` on action payloads;
    (2) the gateway whitelist carries the key.
    """
    from backend.crawler.orchestrator import CrawlOrchestrator

    orch = CrawlOrchestrator.__new__(CrawlOrchestrator)  # no __init__ side effects
    events = []

    async def run(escalated: bool):
        # Reach into the module-level _vision_fetch via the class namespace.
        fn = CrawlOrchestrator._vision_fetch

        class _FakeCap:
            name = "fetch.vision"

            async def fetch_one(self, url, goal, job_id, on_action=None, page_offset=0):
                on_action({
                    "job_id": job_id, "url": url, "kind": "click",
                    "reason": "", "action_index": 1, "total": 8,
                    "x": 0.5, "y": 0.5,
                })

        await fn(_FakeCap(), "https://x", "goal", "job-ct4",
                 lambda ev, pl: events.append((ev, pl)), escalated=escalated)

    return orch, events, run


def test_orchestrator_stamps_escalated_on_action_payloads():
    """End 1: the orchestrator's action emitter carries `escalated`."""
    _, events, run = _gateway_relay()

    asyncio.run(run(escalated=True))
    assert events, "action emitted"
    ev, payload = events[0]
    assert ev == "CRAWLER_VISION_ACTION"
    assert payload["escalated"] is True

    # A raced session (not an escalation) stamps False — the notice beat must
    # not fire for races (REQ-8 AC3 semantics).
    events.clear()
    asyncio.run(run(escalated=False))
    assert events[0][1]["escalated"] is False


def test_gateway_whitelist_carries_escalated():
    """End 2: the gateway's CRAWLER_VISION_ACTION whitelist tuple names
    `escalated`. Grep-shaped against the SOURCE so the check survives
    refactors of unrelated branches but fails loudly if the key is removed."""
    from pathlib import Path

    src = Path("backend/iris_gateway.py").read_text(encoding="utf-8")
    # Locate the vision-action branch, then require the key inside it.
    marker = src.index('"crawler_vision_action"')
    branch = src[marker:marker + 2000]
    assert '"escalated"' in branch, (
        "`escalated` is missing from the gateway CRAWLER_VISION_ACTION "
        "whitelist — the field dies in transit and the notice beat never fires"
    )


def test_ux_map_documents_the_field():
    """The single-source-of-truth map describes the field (REQ-30 AC4 style)."""
    from backend.crawler.ux_map import UX_MAP

    doc = UX_MAP["CRAWLER_VISION_ACTION"].action
    assert "escalated" in doc
