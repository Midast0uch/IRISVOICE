"""Fetch capabilities — REQ-6.

Capability registry for the fetch layer. Each capability is a named, async
single-URL fetcher that returns a standardized :class:`FetchOutcome`. The
research orchestrator selects between ``fetch.crawl`` (headless markdown
extraction) and ``fetch.vision`` (vision-guided browser session) per URL
(REQ-6 AC3, design D2).

The registry is the integration point the DER node machinery consumes: the
orchestrator's per-URL dispatch (T12) and any DER plan step that needs a
``fetch.*`` node read from :data:`CAPABILITIES` instead of hard-coding a
backend. No agent_kernel edits are required here.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol

logger = logging.getLogger(__name__)


class WallKind(str, Enum):
    """Interstitial walls a vision session can hit (REQ-7)."""

    CAPTCHA = "captcha"
    LOGIN = "login"
    PAYWALL = "paywall"
    UNKNOWN = "unknown"


class FetchCapability(Protocol):
    """A named way to fetch one URL (design.md verbatim interface)."""

    name: str  # "fetch.crawl" | "fetch.vision"

    async def available(self) -> bool: ...

    async def fetch_one(self, url: str, goal: str, job_id: str) -> "FetchOutcome": ...


@dataclass
class FetchOutcome:
    """Outcome of one capability fetch (design.md verbatim interface)."""

    url: str
    capability: str
    page: Optional["PageData"]  # noqa: F821 — imported lazily for typing
    verdict: "UsabilityVerdict"  # noqa: F821
    settled_dom: Optional[str] = None  # vision hands this to crawl (REQ-6 AC5)
    wall: Optional[WallKind] = None  # CAPTCHA | LOGIN | PAYWALL | UNKNOWN
    actions_taken: int = 0
    duration_ms: int = 0


class FetchCrawlCapability:
    """``fetch.crawl`` — the existing headless crawl path (REQ-6 AC2)."""

    name = "fetch.crawl"

    async def available(self) -> bool:
        # Headless extraction is always available; no external server needed.
        return True

    async def fetch_one(self, url: str, goal: str, job_id: str) -> FetchOutcome:
        from backend.crawler.capture_store import _safe_job  # noqa: F401  (typing only)
        from backend.crawler.orchestrator import CrawlOrchestrator
        from backend.crawler.usability import page_is_usable

        t_start = time.monotonic()
        result = await CrawlOrchestrator().fetch_url(
            url=url,
            session_id=job_id,
            job_id=job_id,
        )
        duration_ms = int((time.monotonic() - t_start) * 1000)

        page = result.pages[0] if getattr(result, "pages", None) else None
        if result.error or page is None or page.error:
            verdict = page_is_usable(page) if page is not None else _unusable_verdict()
            logger.info(
                "[capabilities][job_id=%s] fetch.crawl failed: %s", job_id, result.error
            )
            return FetchOutcome(
                url=url,
                capability=self.name,
                page=None,
                verdict=verdict,
                duration_ms=duration_ms,
            )

        verdict = page_is_usable(page)
        if not verdict.usable:
            logger.info(
                "[capabilities][job_id=%s] fetch.crawl page unusable: %s",
                job_id,
                verdict.reason.value,
            )
        return FetchOutcome(
            url=url,
            capability=self.name,
            page=page,
            verdict=verdict,
            duration_ms=duration_ms,
        )


# Registry (REQ-6 AC3: dispatch reads CAPABILITIES, never hard-coded backends).
# REQ-2 AC4 (specs/dag-node-execution-model, T11): the registry is a FACADE
# over the unified tool registry — every capability registered here ALSO
# declares its NodeSpec (artifact types + advertised recovery) in
# backend.agent.tool_registry, so the parallel node-registry mechanism is
# retired: node metadata has ONE home, and the planner sees fetch.crawl /
# fetch.vision exactly like any other node (REQ-2 AC3). The dict below
# remains as the EXECUTION binding (capability object -> fetch_one), not as
# a second place to declare routing behavior.
CAPABILITIES: dict[str, FetchCapability] = {}


def register_capability(cap: FetchCapability) -> None:
    """Register a fetch capability (execution) + its node metadata (REQ-2 AC4).

    Execution binding lives in :data:`CAPABILITIES`; node metadata (produces/
    emits/recovers) is declared ONCE in the unified registry via NodeSpec, so
    the router can match failure reasons to this capability's advertised
    recovery (REQ-4 AC1) and the planner can compose it (REQ-3 AC1).
    """
    CAPABILITIES[cap.name] = cap
    _declare_node_metadata(cap)


def _declare_node_metadata(cap: FetchCapability) -> None:
    """Declare the capability's NodeSpec in the unified registry (REQ-2 AC4).

    Advertisements encode the recovery decisions the websearch spec previously
    hand-wrote as branches (T13 deletes those branches; the advertisement is
    their replacement):
      * fetch.vision  recovers CHALLENGE / EMPTY / TOO_SHORT  — the fresh-
        failure escalation set (never TRANSPORT_ERROR: robots/DNS must not be
        routed around — REQ-5 AC3 / REQ-8 AC3, pinned by BT-12).
      * search_discovery recovers NO_CANDIDATES — the planner-gave-nothing
        pivot (REQ-19), replacing the hand-written discovery trigger.
      * fetch.crawl emits the UsabilityReason-derived set and recovers nothing.
    """
    from backend.agent.nodes.outcome import Reason
    from backend.agent.nodes.spec import NodeSpec
    from backend.agent.tool_registry import (
        ToolSpec,
        get_node_spec,
        register_node,
        register_tool,
        resolve_tool,
    )

    if get_node_spec(cap.name) is not None:
        return  # already declared (idempotent facade)

    _produces = "pages" if cap.name.startswith("fetch.") else "text"
    _emits = frozenset({
        Reason.EMPTY, Reason.TOO_SHORT, Reason.CHALLENGE, Reason.TRANSPORT_ERROR,
    })
    _recovers: frozenset = frozenset()
    if cap.name == "fetch.vision":
        # BT-12 pins this exact set: challenge/empty/too_short escalate;
        # transport_error (robots.txt refusal, DNS) NEVER routes around
        # compliance (REQ-5 AC3 / REQ-8 AC3).
        _recovers = frozenset({
            Reason.CHALLENGE, Reason.EMPTY, Reason.TOO_SHORT,
        })
    elif cap.name == "search_discovery":
        _recovers = frozenset({Reason.NO_CANDIDATES})
    try:
        if resolve_tool(cap.name) is None:
            register_tool(ToolSpec(
                name=cap.name,
                description=f"{cap.name} fetch capability (REQ-2 AC4)",
                parameters={},
                category="web",
                permission_tier="read_only",
                executor="crawler",
            ))
        register_node(NodeSpec(
            tool=resolve_tool(cap.name),
            produces=_produces,
            emits_reasons=_emits,
            recovers_reasons=_recovers,
        ))
    except Exception as _decl_exc:  # noqa: BLE001 — declaration must never break registration
        logger.warning("[capabilities] node metadata declaration for %s failed: %s", cap.name, _decl_exc)


def get_capability(name: str) -> FetchCapability:
    """Look up a capability by name. Raises KeyError for unknown names."""
    try:
        return CAPABILITIES[name]
    except KeyError:
        raise KeyError(f"unknown fetch capability: {name!r}") from None


def register_default_capabilities() -> dict[str, FetchCapability]:
    """Register fetch.crawl always; fetch.vision best-effort (REQ-6 AC3).

    A missing/import-broken vision stack must never break fetch.crawl, so the
    vision capability is registered inside try/except.
    """
    if "fetch.crawl" not in CAPABILITIES:
        register_capability(FetchCrawlCapability())
    if "fetch.vision" not in CAPABILITIES:
        try:
            from backend.vision.fetch_vision import FetchVisionCapability

            register_capability(FetchVisionCapability())
        except Exception as exc:  # noqa: BLE001 — optional capability
            logger.warning("[capabilities] fetch.vision unavailable: %s", exc)
    _register_search_discovery_node()
    _register_crawler_query_composite()
    return CAPABILITIES


def _register_crawler_query_composite() -> None:
    """Declare crawler_query as the reference composite (REQ-3 AC5 / T12).

    ``crawler_query`` stays a SINGLE callable unit — one outer outcome, so the
    existing UI card and callers are unchanged (REQ-3 AC4, design D5) — while
    its sub-graph (fetch.crawl / fetch.vision / search_discovery) is declared
    as ``composite_of`` so the planner can see and re-route at sub-node
    boundaries (REQ-3 AC2/AC3). Idempotent.
    """
    from backend.agent.nodes.outcome import Reason  # noqa: F401 — frozenset members
    from backend.agent.nodes.spec import NodeSpec
    from backend.agent.tool_registry import (
        ToolSpec,
        get_node_spec,
        register_node,
        register_tool,
        resolve_tool,
    )

    if get_node_spec("crawler_query") is not None:
        return
    try:
        if resolve_tool("crawler_query") is None:
            register_tool(ToolSpec(
                name="crawler_query",
                description=(
                    "Deep web research crawl — the reference composite "
                    "(REQ-3 AC5): plans URLs, fetches via fetch.crawl / "
                    "fetch.vision with advertisement-driven recovery, and "
                    "returns a structured summary + extracted content."
                ),
                parameters={"query": {"type": "string", "description": "The research topic"}},
                category="web",
                permission_tier="read_only",
                executor="crawler",
                requires_internet=True,
            ))
        register_node(NodeSpec(
            tool=resolve_tool("crawler_query"),
            produces="pages",
            emits_reasons=frozenset({
                Reason.NO_CANDIDATES,
                Reason.CHALLENGE,
                Reason.EMPTY,
                Reason.TOO_SHORT,
                Reason.TRANSPORT_ERROR,
                Reason.BUDGET_EXCEEDED,
            }),
            recovers_reasons=frozenset(),
            composite_of=("fetch.crawl", "fetch.vision", "search_discovery"),
        ))
    except Exception as _cq_exc:  # noqa: BLE001 — declaration must never break import
        logger.warning("[capabilities] crawler_query composite declaration failed: %s", _cq_exc)


def _register_search_discovery_node() -> None:
    """Declare the vision search-discovery node (REQ-19 / T13).

    ``search_discovery`` is a module function (backend/vision/search_discovery
    ``discover_urls_via_vision``), not a FetchCapability — it does not live in
    CAPABILITIES. It is registered as a node advertising NO_CANDIDATES recovery
    so the orchestrator's zero-URL pivot consults the router instead of a
    hand-written discovery branch (design D4: no branch in the failing node's
    module). Idempotent.
    """
    from backend.agent.nodes.outcome import Reason
    from backend.agent.nodes.spec import NodeSpec
    from backend.agent.tool_registry import (
        ToolSpec,
        get_node_spec,
        register_node,
        register_tool,
        resolve_tool,
    )

    if get_node_spec("search_discovery") is not None:
        return
    try:
        if resolve_tool("search_discovery") is None:
            register_tool(ToolSpec(
                name="search_discovery",
                description=(
                    "Drive a search engine in a vision browser session and "
                    "harvest candidate result URLs (REQ-19 discovery)"
                ),
                parameters={},
                category="web",
                permission_tier="read_only",
                executor="crawler",
            ))
        register_node(NodeSpec(
            tool=resolve_tool("search_discovery"),
            produces="urls",
            emits_reasons=frozenset(),
            recovers_reasons=frozenset({Reason.NO_CANDIDATES}),
        ))
    except Exception as _sd_exc:  # noqa: BLE001 — declaration must never break import
        logger.warning("[capabilities] search_discovery node declaration failed: %s", _sd_exc)


def _unusable_verdict():
    from backend.crawler.usability import UsabilityReason, UsabilityVerdict

    return UsabilityVerdict(usable=False, reason=UsabilityReason.TRANSPORT_ERROR)


# module-level convenience (REQ-6 AC3): importing the crawler package registers
# the default capabilities so orchestrator dispatch works out of the box.
try:
    register_default_capabilities()
except Exception:  # noqa: BLE001 — import-time registration must never break import
    logger.exception("[capabilities] default registration failed")
