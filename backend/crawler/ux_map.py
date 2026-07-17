"""Single source of truth: crawl event -> UI component/action map (REQ-30 AC4).

Both the WS handler (iris_gateway.crawl_research) and the SSE endpoint
(/api/crawl/stream) translate CrawlProgress events into frontend messages using
THIS table, so the two transports can never diverge. The frontend (useCrawl /
useTaskProgress) consumes the resulting message types.

Each entry maps an internal CrawlProgress event name to:
  - msg_type: the WS/SSE message "type" the frontend switches on
  - component: which UI surface reacts (Orb, ContextPill, PlanCard, Dashboard, Chat)
  - action: what the component does
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class UXMapping:
    msg_type: str
    component: str
    action: str


# CrawlProgress.event -> UX mapping. Keep this exhaustive: every event the
# orchestrator can emit MUST have an entry (enforced by a test).
UX_MAP: Dict[str, UXMapping] = {
    "CRAWLER_STARTED": UXMapping(
        msg_type="crawler_started",
        component="Orb/ContextPill",
        action="enter processing_tool (SEARCHING); show source-count badge",
    ),
    "CRAWLER_PAGE_FETCHED": UXMapping(
        msg_type="crawler_page_fetched",
        component="PlanCard/ContextPill",
        action="update in-progress step text to 'Reading <host> (N/M)'",
    ),
    "OPEN_TAB": UXMapping(
        msg_type="open_tab",
        component="Dashboard",
        action="open dashboard tab with structured data",
    ),
    "CRAWLER_COMPLETE": UXMapping(
        msg_type="crawler_complete",
        component="Orb/ContextPill",
        action="return to idle/thinking; surface summary + citations",
    ),
    "CRAWLER_ERROR": UXMapping(
        msg_type="crawler_error",
        component="Chat/Orb",
        action="show error toast; return orb to idle",
    ),
}


def map_event(event: str) -> UXMapping:
    """Return the UX mapping for an event, or raise KeyError if unmapped."""
    return UX_MAP[event]


def known_events() -> frozenset:
    return frozenset(UX_MAP.keys())
