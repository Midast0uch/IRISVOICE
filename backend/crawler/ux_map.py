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
        action="signal crawl start; payload carries query + url_count + job_id",
    ),
    "CRAWLER_PHASE": UXMapping(
        msg_type="task:event",
        component="Orb/ContextPill",
        action="update phase (searching/reading/synthesizing); "
        "payload carries phase + phase_sequence (REQ-4 AC1/AC3)",
    ),
    "CRAWLER_PROGRESS": UXMapping(
        msg_type="crawler_progress",
        component="Orb/ContextPill",
        action="update in-flight stage message (narrowing/refining); "
        "payload carries stage + message",
    ),
    "CRAWLER_VISION_ACTION": UXMapping(
        msg_type="crawler_vision_action",
        component="Dashboard/BrowserPanel",
        action="annotate the existing browser animation surface with the action "
        "vision just performed (REQ-11 AC4); payload carries job_id + url + "
        "kind + reason + action_index + total, plus OPTIONAL best-effort "
        "cursor coordinates (REQ-16 AC7) for the particle-trail cursor mirror: "
        "click/type carry x + y (normalised 0..1 viewport fractions) + "
        "viewport_w + viewport_h; scroll carries scroll_dx + scroll_dy instead "
        "of a point (a point would drift as the page scrolls under it). "
        "escalated (specs/vision-browser-stage REQ-8): true when this session "
        "took over from a FAILED crawl — the frontend plays a one-shot "
        "'notice' beat only on escalation, never for raced sessions. "
        "Coordinates are reconstructed from the Playwright DOM target's "
        "bounding box for the frontend mirror ONLY — the vision model itself "
        "has no mouse and never sees them. Additive only — the panel's "
        "visual design and animation timing are unchanged (REQ-11 AC3)",
    ),
    "CRAWLER_SOURCE_PARKED": UXMapping(
        msg_type="crawler_source_parked",
        component="Chat/PlanCard",
        action="surface a parked source (REQ-13 AC4): a wall blocked it, one "
        "question was raised per domain; synthesis lists it as parked, never "
        "blocks. payload carries url + domain + wall_kind",
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
