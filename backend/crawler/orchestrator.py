"""
CrawlOrchestrator — the single shared core for ALL web search in IRIS Voice.

Both entry points call this:
  - WS  `crawl_research`  (iris_gateway.py)  -> research(mode="ws")
  - Agent `crawler_query` (tool_bridge.py)   -> research(mode="agent")

It runs the Perplexity-grade funnel in a FIXED order (REQ-1 AC5):
    Plan -> Fetch -> Passage-Split -> Credibility-Score -> Passage-Rerank
    -> Extract+Cite -> Return

Fetch is isolated behind a swappable FetchBackend (REQ-17 AC4) so the subprocess
implementation can later be promoted to a long-lived crawl-worker daemon without
touching the funnel.

Quality gates (AGENTS.md):
  - Heavy deps (crawl4ai) imported lazily inside the backends, never at module load.
  - Per-page errors never abort the batch (recorded in PageData.error).
  - No shared mutable state across calls.
  - research() NEVER raises for crawl failures — returns CrawlResult.error set.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Literal, Optional

from .crawler_engine import CrawlResult, PageData
from .crawl_planner import CrawlPlan, get_crawl_planner
from .event_log import get_event_log
from .usability import UsabilityReason, page_is_usable  # REQ-1 single predicate


def _capabilities_registered() -> set[str]:
    """Lazily import the capability registry for the T12 dispatch gate.

    Import stays local so crawler paths that never use capabilities (and the
    subprocess backend) do not pay the module import at load time.
    """
    try:
        from .capabilities import CAPABILITIES

        return set(CAPABILITIES)
    except Exception:  # noqa: BLE001 — capability stack missing is not fatal
        return set()

logger = logging.getLogger(__name__)

_DEFAULT_MAX_PAGES = int(os.environ.get("CRAWL4AI_MAX_PAGES", "5"))
_DEFAULT_MIN_PAGES = int(os.environ.get("CRAWL_MIN_PAGES", "3"))
# D3 fix (T36 live smoke, 2026-08-09): kept in lockstep with crawl_runner.py's
# _DEFAULT_TIMEOUT_S (same env var, same fallback) — see that module for the
# cold-vs-warm browser-launch measurement behind the 45s->90s change.
_DEFAULT_TIMEOUT_S = float(os.environ.get("CRAWL_SUBPROCESS_TIMEOUT_S", "90"))
# REQ-10 AC1: max distinct URLs fetched concurrently by dispatch_urls().
_DEFAULT_CONCURRENCY = int(os.environ.get("CRAWL_CONCURRENCY", "3"))

# Problem-1 fix (REQ-10 escalation tier, REQ-6 AC1 edge): fresh-failure
# reasons where an interactive vision session plausibly recovers content
# crawl could not. TRANSPORT_ERROR is deliberately EXCLUDED — it is the
# reason recorded for BOTH robots.txt refusal (REQ-5 AC3: must never route
# around robots compliance) and DNS failure (vision cannot resolve a name
# crawl could not either), and fetch.vision navigates directly with no
# robots gate of its own (only crawler_engine.crawl() checks robots.txt).
# Escalating any transport_error would silently bypass robots.txt for
# exactly the URL it just refused. Only these three reasons escalate.
_FRESH_FAILURE_ESCALATE_REASONS = frozenset({
    UsabilityReason.CHALLENGE,
    UsabilityReason.EMPTY,
    UsabilityReason.TOO_SHORT,
})


def _should_escalate_fresh_failure(verdict) -> bool:
    """True when a crawl-only outcome's reason is one vision plausibly helps
    with (see `_FRESH_FAILURE_ESCALATE_REASONS` above for the full
    rationale).

    REQ-2 AC4 / T13 (specs/dag-node-execution-model): the AUTHORITATIVE
    answer now comes from advertisement — fetch.vision's NodeSpec declares
    which reasons it recovers (BT-12 pins the set). This predicate is kept
    as the fast-path guard the dispatch path uses BEFORE the router call;
    it must agree with the advertised set by construction (the router is
    consulted next and is the final authority).
    """
    return verdict.reason in _FRESH_FAILURE_ESCALATE_REASONS


def _router_recovery_node(
    reason_value: str, *, race_rollback: bool = False, step_id: str = "dispatch",
) -> Optional[str]:
    """T13: ask the node router which node advertises recovery for a reason.

    The hand-written escalation/discovery/race branches are replaced by this
    advertisement consultation (REQ-4 AC1): fetch.vision advertises
    CHALLENGE/EMPTY/TOO_SHORT, search_discovery advertises NO_CANDIDATES — no
    branch is written in the failing node's module (design D4). Returns the
    recovery node name, or None when nothing advertises the reason / the
    reason is terminal (REQ-4 AC4, REQ-8 AC3).

    ``step_id`` must be UNIQUE per originating URL/run: the router's attempt
    bound is per originating step (REQ-4 AC3), and the router is a process-wide
    singleton — sharing one step_id across consultations would let the first
    call consume the bound for all later calls.

    Kill-switch parity (REQ-7 AC4/AC5, design D8): when routing is disabled,
    the crawler's pre-change behavior is preserved — these mappings ARE the
    old branches, kept as the rollback path so the switch restores today's
    behavior byte-for-byte. The pre-change RACE gate fired on ANY recorded
    history (REQ-10 AC3), so ``race_rollback`` restores that for race
    consultations. When routing is enabled the router's advertisement table
    is the authority.
    """
    try:
        from backend.agent.nodes.outcome import NodeOutcome, NodeStatus, Reason
        from backend.agent.nodes.router import (
            RouteRequest,
            get_node_router,
            routing_enabled,
        )

        # Defensive facade registration: the search_discovery node is declared
        # when capabilities.py is imported, but a caller may reach the router
        # before that import (e.g. discovery tests that never import
        # capabilities). register_default_capabilities is idempotent — it only
        # adds what is missing, so test-fake registrations are preserved.
        try:
            from .capabilities import register_default_capabilities

            register_default_capabilities()
        except Exception:  # noqa: BLE001 — facade failure must not break routing
            pass

        # Terminal reasons are never routed around (CT-5).
        if reason_value in ("robots_refused", "permission_denied"):
            return None
        if not routing_enabled():
            # REQ-7 AC5 rollback: exactly the pre-change branch outcomes.
            if reason_value in (
                "challenge", "empty", "too_short",
            ):
                return "fetch.vision"
            if reason_value == "no_candidates":
                return "search_discovery"
            if race_rollback:
                # Pre-change race fired on ANY recorded failure history.
                return "fetch.vision"
            return None
        try:
            _reason = Reason(reason_value)
        except ValueError:
            # Not in the closed vocabulary — nothing advertises it (REQ-4 AC6).
            return None
        _outcome = NodeOutcome(status=NodeStatus.FAILED, reason=_reason, detail="")
        _router = get_node_router()
        # The crawler's escalation/race is structurally once-per-URL (each URL
        # dispatches exactly once), so the router's attempt bound is redundant
        # here — and the router is process-wide, so a bound consumed by one
        # run must not leak into the next. Reset before consulting (REQ-4 AC3
        # still governs DER's retry loops, which consult with their own
        # step_ids and keep the bound).
        _router.reset_attempts(step_id)
        _decision = _router.route(
            RouteRequest(
                task_id="crawler",
                step_id=step_id,
                node="fetch.crawl",
                outcome=_outcome,
                approved_tier="read_only",
            )
        )
        if _decision is None or _decision.selected is None:
            return None
        return _decision.selected.name
    except Exception:  # noqa: BLE001 — routing must never break dispatch
        return None


# ---------------------------------------------------------------------------
# Data structures (REQ-4, REQ-9)
# ---------------------------------------------------------------------------
@dataclass
class Passage:
    """A logical chunk of a fetched page, scored for credibility + relevance."""
    chunk_id: str
    url: str
    text: str
    credibility: float = 0.0
    score: float = 0.0
    heading_path: str = ""


@dataclass
class CredibilityMap:
    """Per-source credibility + unsourced-claim tracking (REQ-5, REQ-8)."""
    per_source: dict = field(default_factory=dict)   # url -> score in [0,1]
    unsourced_claims: list = field(default_factory=list)  # indices into claims
    top_score: float = 0.0


# Phase sequence numbers (REQ-4 AC4) — stable, monotonic, used by the frontend
# to disambiguate re-emission of the same phase.
PHASE_SEARCHING = 1
PHASE_FETCHING = 2
PHASE_EXTRACTING = 3
PHASE_RERANKING = 4
PHASE_CITING = 5
PHASE_DONE = 6


@dataclass
class CrawlProgress:
    """One unified progress event emitted via on_progress (REQ-10..13)."""
    event: str            # CRAWLER_STARTED | CRAWLER_PAGE_FETCHED | CRAWLER_PHASE | OPEN_TAB | CRAWLER_ERROR
    payload: dict


# ---------------------------------------------------------------------------
# FetchBackend (REQ-17 AC4) — swappable fetch implementation
# ---------------------------------------------------------------------------
class FetchBackend:
    """Abstract fetch backend. Subclasses return list[PageData] for a query."""

    async def fetch(
        self,
        query: str,
        urls: list[str],
        instructions: str,
        max_pages: int,
        on_page_done: Optional[Callable[[str, int, int, str, str], None]],
        timeout_s: float,
        job_id: Optional[str] = None,
    ) -> CrawlResult:  # pragma: no cover - abstract
        raise NotImplementedError


class InProcessFetchBackend(FetchBackend):
    """In-process CrawlerEngine (used by WS mode=ws)."""

    async def fetch(self, query, urls, instructions, max_pages, on_page_done, timeout_s, job_id=None):
        from .crawler_engine import CrawlerEngine
        try:
            async with CrawlerEngine() as engine:
                return await engine.crawl(
                    query=query, urls=urls, instructions=instructions,
                    max_pages=max_pages, on_page_done=on_page_done,
                    job_id=job_id,
                )
        except Exception as exc:  # CrawlerUnavailable etc.
            logger.error("[InProcessFetchBackend] fetch failed: %s", exc)
            return CrawlResult(
                query=query, pages=[], duration_ms=0,
                crawled_at=datetime.now(timezone.utc).isoformat(),
                error=f"in-process fetch failed: {exc}",
            )


class SubprocessFetchBackend(FetchBackend):
    """Isolated subprocess (used by agent mode=agent). Crash-isolated (REQ-17)."""

    async def fetch(self, query, urls, instructions, max_pages, on_page_done, timeout_s, job_id=None):
        from .crawl_runner import run_crawl_subprocess
        return await run_crawl_subprocess(
            query=query, urls=urls, instructions=instructions,
            on_page_done=on_page_done, max_pages=max_pages, timeout_s=timeout_s,
            job_id=job_id,
        )


_BACKENDS: dict[str, type[FetchBackend]] = {
    "ws": InProcessFetchBackend,
    "agent": SubprocessFetchBackend,
}


# ---------------------------------------------------------------------------
# CrawlOrchestrator — the funnel (REQ-1)
# ---------------------------------------------------------------------------
class CrawlOrchestrator:
    def __init__(self, planner=None, extractor=None) -> None:
        self._planner = planner
        self._extractor = extractor
        self._backend_override: Optional[FetchBackend] = None  # test seam (no live web)

    async def research(
        self,
        query: str,
        *,
        mode: Literal["ws", "agent"] = "agent",
        session_id: str = "",
        on_progress: Optional[Callable[[CrawlProgress], None]] = None,
        max_pages: int = _DEFAULT_MAX_PAGES,
        min_pages: int = _DEFAULT_MIN_PAGES,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        job_id: Optional[str] = None,
    ) -> CrawlResult:
        """Run the full funnel. Never raises for crawl failures (REQ-17 AC1)."""
        t_start = time.monotonic()
        if not job_id:
            job_id = uuid.uuid4().hex
        _emit = self._make_emitter(on_progress, session_id)

        # 1) PLAN (REQ-2)
        plan: CrawlPlan = await self._plan(query)
        # REQ-19 AC7: discovery attempts at most once per research run. Local
        # to this call (not instance state) — the orchestrator is a shared
        # singleton across concurrent runs (REQ-16: no shared mutable state).
        discovery_attempted = False
        discovered_urls: set[str] = set()
        if not plan.urls:
            # T13 (specs/dag-node-execution-model): the discovery trigger is
            # advertisement-driven. "Planner gave zero URLs" IS the NO_CANDIDATES
            # failure; the router picks the node that advertises recovery
            # (search_discovery). No hand-written discovery branch lives here
            # anymore (design D4). Discovery still runs at most once per run
            # (REQ-19 AC7 — local, not instance state).
            discovery_attempted = True
            if _router_recovery_node(
                "no_candidates", step_id=f"disc:{job_id}",
            ) == "search_discovery":
                discovered = await self._discover_urls_via_vision(query, job_id, _emit)
            else:
                discovered = []
            if discovered:
                discovered_urls.update(discovered)
                # REQ-19 AC3: discovered URLs re-enter the funnel as an
                # ordinary CrawlPlan and flow through the SAME dispatch below
                # planned URLs use — no second fetch path.
                plan = CrawlPlan(
                    urls=discovered,
                    instructions=plan.instructions or "Extract the page content relevant to the query.",
                    result_type=plan.result_type or "mixed",
                    title=plan.title or query[:60],
                )
            else:
                _emit("CRAWLER_ERROR", {"message": "no candidate urls"})
                await self._drain_log_tasks()
                return self._empty(query, t_start, "no candidate urls")

        _emit("CRAWLER_STARTED", {"query": query, "url_count": len(plan.urls), "session_id": session_id, "job_id": job_id})
        # REQ-4 AC1/AC3: emit phase transition — moving into search.
        _emit("CRAWLER_PHASE", {"phase": "searching", "phase_sequence": PHASE_SEARCHING})

        # 2) FETCH (REQ-3) via swappable backend (REQ-17 AC4)
        backend = self._backend_override or _BACKENDS[mode]()
        # T12 (REQ-10): concurrent per-URL dispatch through the capability
        # registry is the PRIMARY production path (no test override). The
        # `_backend_override` seam (used by hermetic tests) keeps the batch
        # backend.fetch path, preserving the tested single-subprocess funnel.
        dispatch_path = (
            self._backend_override is None
            and "fetch.crawl" in _capabilities_registered()
        )
        if dispatch_path:
            fetched = await self.dispatch_urls(
                plan.urls,
                query=query,
                job_id=job_id,
                session_id=session_id,
                on_progress=on_progress,
                max_pages=max_pages,
                timeout_s=timeout_s,
            )
        else:
            fetched = await backend.fetch(
                query=query, urls=plan.urls, instructions=plan.instructions,
                max_pages=max_pages,
                # job_id is REQUIRED here: it is what lets the browser panel build
                # /api/browser/capture/{job_id}/{page_number}. The retry and
                # single-URL paths below already passed it; this PRIMARY path did
                # not, so every normal crawl emitted job_id="" and the panel could
                # not resolve a capture to display (REQ-1 AC1).
                on_page_done=self._page_emitter(_emit, job_id),
                timeout_s=timeout_s,
                job_id=job_id,
            )
        # REQ-19 AC6: mark vision-discovered URLs' pages so their provenance
        # is distinguishable from planner-supplied URLs (REQ-18 AC2 pattern).
        self._stamp_discovery_provenance(fetched, discovered_urls)
        # Wave 0 (REQ-14/REQ-18): down-weight dead/stale domains from HAR evidence.
        self._apply_har_penalties(fetched, query)
        # Wave 0 (REQ-18/REQ-19): register successful URLs so future crawls for
        # this topic seed from learned knowledge (memory-first).
        await self._learn_from_crawl(fetched, query)

        # W3 (T15-T20): Exa retry — if the first batch returned no usable pages,
        # rewrite the query to be broader and retry once.
        # REQ-1/REQ-2: the gate reads page_is_usable, not `error is None`.
        # The old gate counted empty-markdown fallback pages as successes, so
        # this retry had fired ZERO times in 401MB of history.
        ok_pages = [p for p in fetched.pages if page_is_usable(p).usable]
        if (fetched.error or not ok_pages) and not getattr(fetched, "_retried", False):
            broader_query = _broaden_query(query)
            logger.info(
                "[CrawlOrchestrator] Exa retry job_id=%s query=%s → %s usable_pages=%d/%d (REQ-2)",
                job_id, query[:60], broader_query[:60],
                len(ok_pages), len(fetched.pages),
            )
            _emit("CRAWLER_PROGRESS", {"stage": "narrowing", "message": "Narrowing search…"})
            _emit("CRAWLER_PHASE", {"phase": "searching", "phase_sequence": PHASE_SEARCHING})
            # Re-plan with broader query
            plan = await self._plan(broader_query)
            if not plan.urls and not discovery_attempted:
                # T13 (specs/dag-node-execution-model): the BROADENED re-plan
                # came back empty — the planner itself is the failure, so
                # re-planning again would re-fail identically. Same
                # advertisement-driven discovery as the top-level path (AC7:
                # still at most once per run, shared via `discovery_attempted`).
                discovery_attempted = True
                if _router_recovery_node(
                    "no_candidates", step_id=f"disc:{job_id}",
                ) == "search_discovery":
                    discovered = await self._discover_urls_via_vision(broader_query, job_id, _emit)
                else:
                    discovered = []
                if discovered:
                    discovered_urls.update(discovered)
                    plan = CrawlPlan(
                        urls=discovered,
                        instructions=plan.instructions or "Extract the page content relevant to the query.",
                        result_type=plan.result_type or "mixed",
                        title=plan.title or broader_query[:60],
                    )
            if plan.urls:
                fetched = await backend.fetch(
                    query=broader_query, urls=plan.urls, instructions=plan.instructions,
                    max_pages=max_pages,
on_page_done=self._page_emitter(_emit, job_id),
                    timeout_s=timeout_s,
                    job_id=f"{job_id}_retry",
                )
                setattr(fetched, "_retried", True)
                self._stamp_discovery_provenance(fetched, discovered_urls)
                self._apply_har_penalties(fetched, broader_query)
                await self._learn_from_crawl(fetched, broader_query)

        if fetched.error:
            _emit("CRAWLER_ERROR", {"message": fetched.error})
            await self._drain_log_tasks()
            return self._finalize(fetched, query, t_start, error=fetched.error)

        ok_pages = [p for p in fetched.pages if page_is_usable(p).usable]
        if not ok_pages:
            _emit("CRAWLER_ERROR", {"message": "all pages failed to fetch"})
            await self._drain_log_tasks()
            return self._finalize(fetched, query, t_start, error="all pages failed to fetch")

        # REQ-4 AC1/AC3: emit phase transition — moving into extraction.
        _emit("CRAWLER_PHASE", {"phase": "extracting", "phase_sequence": PHASE_EXTRACTING})

        # 3) PASSAGE-SPLIT (REQ-4)
        passages = self._split_passages(ok_pages)

        # 4) CREDIBILITY-SCORE (REQ-5) — module implemented in T2
        from .credibility import score_credibility
        cred_map = score_credibility(ok_pages, passages)

        # 5) PASSAGE-RERANK (REQ-7/REQ-3) — module implemented in T3.
        # REQ-3 AC1: rerank returns a distinguishable state, not a bare `[]`
        # whose meaning lived only in a comment (that comment said "handled at
        # call site" and was never handled — the traced run fell through to
        # extract_and_cite with empty passages and presented model knowledge
        # as sourced).
        from .rerank import rerank_passages, RerankState, RERANK_THRESHOLD
        rerank_outcome = rerank_passages(passages, query, cred_map)

        # REQ-3 AC2: a below-threshold rerank MUST escalate, never fall through
        # to citation. Escalation shares the once-per-run broaden-retry budget
        # (REQ-2 AC4 via the `_retried` flag); if that budget is spent, this is
        # REQ-15 honest failure.
        if rerank_outcome.state == RerankState.BELOW_THRESHOLD:
            if not getattr(fetched, "_retried", False):
                broader_query = _broaden_query(query)
                logger.warning(
                    "[CrawlOrchestrator] rerank escalate job_id=%s top_score=%.3f threshold=%.3f "
                    "reason=below_threshold broaden %s → %s (REQ-3/REQ-16)",
                    job_id, rerank_outcome.top_score, RERANK_THRESHOLD,
                    query[:60], broader_query[:60],
                )
                _emit("CRAWLER_PROGRESS", {"stage": "narrowing", "message": "Refining results…"})
                _emit("CRAWLER_PHASE", {"phase": "searching", "phase_sequence": PHASE_SEARCHING})
                plan = await self._plan(broader_query)
                if plan.urls:
                    fetched = await backend.fetch(
                        query=broader_query, urls=plan.urls, instructions=plan.instructions,
                        max_pages=max_pages,
                        on_page_done=self._page_emitter(_emit, job_id),
                        timeout_s=timeout_s,
                        job_id=f"{job_id}_requery",
                    )
                    setattr(fetched, "_retried", True)
                    self._apply_har_penalties(fetched, broader_query)
                    await self._learn_from_crawl(fetched, broader_query)
                    ok_pages = [p for p in fetched.pages if page_is_usable(p).usable]
                    if not ok_pages:
                        # retry produced nothing usable -> honest failure,
                        # NEVER cite an empty passage set (REQ-3 AC3).
                        _emit("CRAWLER_ERROR", {"message": "retry produced no usable content"})
                        await self._drain_log_tasks()
                        return self._finalize(
                            fetched, query, t_start,
                            error="retry produced no usable content",
                        )
                    passages = self._split_passages(ok_pages)
                    cred_map = score_credibility(ok_pages, passages)
                    rerank_outcome = rerank_passages(passages, broader_query, cred_map)

        # REQ-3 AC3: extract_and_cite is UNREACHABLE with an empty passage set.
        # Covers: retry budget exhausted + still below threshold, retry fetched
        # nothing, and NO_PASSAGES (empty page set is REQ-2's concern — do not
        # double-escalate; fail honestly here).
        if rerank_outcome.state != RerankState.OK or not rerank_outcome.kept:
            # REQ-16 AC1/AC6: honest-failure escalation carries run id + the
            # deciding predicate value so "how often does bot protection cost
            # a search?" is answerable from logs, not intuition.
            logger.warning(
                "[CrawlOrchestrator] honest_failure job_id=%s state=%s top_score=%.3f "
                "threshold=%.3f kept=%d (REQ-15/REQ-16)",
                job_id, rerank_outcome.state.value,
                rerank_outcome.top_score, RERANK_THRESHOLD,
                len(rerank_outcome.kept or []),
            )
            _emit("CRAWLER_ERROR", {"message": "retrieved content scored below quality threshold"})
            await self._drain_log_tasks()
            return self._finalize(
                fetched, query, t_start,
                error="content below rerank threshold",
            )
        passages = rerank_outcome.kept

        # REQ-4 AC1/AC3: emit phase transition — moving into citation.
        _emit("CRAWLER_PHASE", {"phase": "citing", "phase_sequence": PHASE_CITING})

        # 6) EXTRACT + CITE (REQ-8) — module implemented in T4
        from .cite import extract_and_cite
        dashboard_data, cited_markdown, unsourced = await extract_and_cite(
            query=query, fetched=fetched, passages=passages,
            instructions=plan.instructions, result_type=plan.result_type,
            title=plan.title, extractor=self._extractor,
        )
        cred_map.unsourced_claims = unsourced
        cred_map.top_score = max((p.score for p in passages), default=0.0)

        # 7) RETURN (REQ-9)
        result = self._finalize(fetched, query, t_start)
        result.passages = passages
        result.dashboard_data = dashboard_data
        result.cited_markdown = cited_markdown
        result.credibility_map = cred_map
        # REQ-22: chunk_id -> url provenance map for pacman persistence.
        result.citation_index = {p.chunk_id: p.url for p in passages if p.chunk_id}
        _emit("OPEN_TAB", {
            "tab_type": "dashboard", "id": session_id or query,
            "title": plan.title, "data": dashboard_data,
            # REQ-11 (T13): the OPEN_TAB payload carries url + job_id so the
            # frontend can tell a content tab from a url-less dashboard tab —
            # and never force-activate a tab that has nothing to show.
            "url": None,
            "job_id": job_id,
        })
        # REQ-29/30: signal completion so a reconnecting client (SSE/WS) knows
        # the job finished and can fetch the result without re-crawling.
        _emit("CRAWLER_COMPLETE", {
            "query": query,
            "summary": dashboard_data.get("summary", ""),
            "page_count": len(ok_pages),
            "session_id": session_id,
            "job_id": job_id,
        })
        await self._drain_log_tasks()
        return result

    async def fetch_url(
        self,
        url: str,
        *,
        session_id: str = "",
        on_progress: Optional[Callable[[CrawlProgress], None]] = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        job_id: Optional[str] = None,
    ) -> CrawlResult:
        """Direct single-URL fetch (REQ-16 open_url path). No LLM planning.

        Fetches exactly ``url`` through the swappable fetch backend (agent =
        crash-isolated subprocess) and returns the CrawlResult with the page
        content. Emits CRAWLER_STARTED + CRAWLER_PAGE_FETCHED so the in-app
        browser surface sees the page load. Never raises for fetch failures
        (REQ-17 AC1). Does NOT plan URLs or run extraction — open_url wants
        the raw page, not a research dashboard.
        """
        t_start = time.monotonic()
        if not job_id:
            job_id = uuid.uuid4().hex
        _emit = self._make_emitter(on_progress, session_id)

        _emit("CRAWLER_STARTED", {"query": url, "url_count": 1, "session_id": session_id})
        _emit("CRAWLER_PHASE", {"phase": "searching", "phase_sequence": PHASE_SEARCHING})

        try:
            backend = self._backend_override or _BACKENDS["agent"]()
            fetched: CrawlResult = await backend.fetch(
                query=url,
                urls=[url],
                instructions="Extract the full page content as markdown.",
                max_pages=1,
on_page_done=self._page_emitter(_emit, job_id),
                timeout_s=timeout_s,
                job_id=job_id,
            )
        except Exception as exc:  # REQ-17 AC1: never raise for fetch failures
            logger.error("[orchestrator.fetch_url] fetch failed: %s", exc)
            return self._empty(url, t_start, f"fetch failed: {exc}")

        if fetched.error:
            _emit("CRAWLER_ERROR", {"message": fetched.error})
            await self._drain_log_tasks()
            return self._finalize(fetched, url, t_start, error=fetched.error)

        await self._drain_log_tasks()
        return fetched

    # -- T12 (REQ-10): concurrent per-URL dispatch --------------------------
    async def dispatch_urls(
        self,
        urls: list[str],
        *,
        query: str,
        job_id: str,
        session_id: str = "",
        on_progress: Optional[Callable[[CrawlProgress], None]] = None,
        max_pages: int = _DEFAULT_MAX_PAGES,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        concurrency_limit: int = _DEFAULT_CONCURRENCY,
    ) -> CrawlResult:
        """Concurrent per-URL dispatch through the capability registry (REQ-10).

        - AC1: distinct URLs fetched concurrently, bounded by concurrency_limit.
        - AC2: different URLs may run different capabilities in the same batch.
        - AC3/AC4: a domain with recorded source_registry failures is raced
          (fetch.crawl + fetch.vision, first usable wins); a domain with NO
          failure history is fetched by fetch.crawl alone — never raced.
        - AC5: when one raced capability returns first, the loser is cancelled.
        - Edge: both raced results usable -> crawl (cheaper) wins, the
          unnecessary race is logged for tuning.

        Always returns a CrawlResult (never raises). The source_registry read
        is best-effort and LOGGED (pin V2: registry reuse is unverified — we
        log both the history decision and the dispatch outcome).
        """
        from .capabilities import CAPABILITIES, get_capability

        t_start = time.monotonic()
        _emit = self._make_emitter(on_progress, session_id)
        crawl_cap = get_capability("fetch.crawl")
        vision_avail = "fetch.vision" in CAPABILITIES
        capped = urls[:max_pages]
        sem = asyncio.Semaphore(max(1, concurrency_limit))
        # Ordered slots preserve plan order in the result pages.
        slots: list[Optional[PageData]] = [None] * len(capped)
        # T12c (REQ-18 AC1): light HAR entries for EVERY dispatched outcome so
        # `_apply_har_penalties` scores vision-visited domains on the same
        # basis as crawl domains (AC5: no forked paths).
        har_entries: list[dict] = []

        async def _dispatch_one(idx: int, url: str) -> None:
            async with sem:  # AC1: bounded concurrency
                # T13 (specs/dag-node-execution-model): the race gate is
                # advertisement-driven. A domain's recorded failure history
                # names a reason; the router races fetch.vision only when a
                # node ADVERTISES recovery for that reason (REQ-4 AC1). The
                # history gate itself (REQ-10 AC3/AC4) still applies — a
                # first-time failure reaches vision via the fresh-failure
                # escalation below, not here.
                history = await self._domain_failure_history(url, query)
                if history and vision_avail and _router_recovery_node(
                    history, race_rollback=True, step_id=f"race:{url}",
                ) == "fetch.vision":
                    outcome = await self._race_url(url, query, job_id, crawl_cap, _emit)
                else:
                    if history and not vision_avail:
                        logger.info(
                            "[CrawlOrchestrator] dispatch job_id=%s url=%s history=%s "
                            "vision=unavailable -> crawl only (REQ-10 AC3 degraded)",
                            job_id, url, history,
                        )
                    outcome = await crawl_cap.fetch_one(url, query, job_id)
                    # T13 (specs/dag-node-execution-model): the fresh-failure
                    # escalation branch is REPLACED by an advertisement
                    # consultation — fetch.vision's NodeSpec declares it
                    # recovers CHALLENGE/EMPTY/TOO_SHORT, and the router picks
                    # it (REQ-4 AC1, design D4). No branch lives in this
                    # module anymore; BT-12 still passes because the
                    # advertisement encodes the same set. TRANSPORT_ERROR is
                    # deliberately NOT advertised (robots/DNS must never be
                    # routed around — REQ-5 AC3 / REQ-8 AC3).
                    usable = outcome.page is not None and outcome.verdict.usable
                    if vision_avail and not usable:
                        _recovery = _router_recovery_node(
                            outcome.verdict.reason.value, step_id=f"esc:{url}",
                        )
                        if _recovery == "fetch.vision":
                            outcome = await self._escalate_to_vision(url, query, job_id, outcome, _emit)
                # T12c (REQ-18 AC1): one HAR entry per vision/crawl outcome.
                # A walled URL records error="challenge" so the existing
                # _apply_har_penalties path penalizes the domain exactly like a
                # crawl-time challenge (no new penalty mechanism).
                wall = getattr(outcome, "wall", None)
                har_entries.append({
                    "url": url,
                    "method": "GET",
                    "status": 200 if (outcome.page is not None and outcome.verdict.usable) else None,
                    "response_headers": {},
                    "duration_ms": getattr(outcome, "duration_ms", 0) or 0,
                    "content_length": len((outcome.page.markdown if outcome.page else "") or ""),
                    "body_sha256": "",
                    "error": "challenge" if wall is not None else "",
                    "capability": getattr(outcome, "capability", "fetch.crawl"),
                })
                if outcome.page is not None and outcome.verdict.usable:
                    # T12c (REQ-18 AC2): stamp provenance on the page so the
                    # document-store path (which consumes PageData) knows the
                    # content came from vision vs crawl.
                    if getattr(outcome, "capability", "") == "fetch.vision":
                        outcome.page.metadata = dict(outcome.page.metadata or {})
                        outcome.page.metadata["origin"] = "vision"
                    slots[idx] = outcome.page
                else:
                    # T14 (REQ-13): a wall in the outcome (CAPTCHA/login/paywall
                    # from fetch.vision) parks the source — one question per
                    # domain per run (AC6) — and the run CONTINUES with the
                    # remaining URLs (AC2). Synthesis later lists parked sources
                    # (AC4) instead of blocking on them.
                    if wall is not None:
                        self._park_source(job_id, url, wall.value, _emit)
                    else:
                        logger.info(
                            "[CrawlOrchestrator] dispatch job_id=%s url=%s cap=%s "
                            "usable=%s reason=%s (REQ-10 log-both-sides)",
                            job_id, url, outcome.capability,
                            outcome.verdict.usable, outcome.verdict.reason.value,
                        )

        # REQ-16: concurrency limit reached -> queued, never dropped; the
        # semaphore queues naturally, and we log when a task had to wait.
        queued_count = 0

        async def _dispatch_with_defer_log(idx: int, url: str) -> None:
            nonlocal queued_count
            if sem.locked():
                queued_count += 1
                logger.info(
                    "[CrawlOrchestrator] dispatch queue job_id=%s url=%s queued=%d "
                    "(REQ-16 deferral, not dropped)",
                    job_id, url, queued_count,
                )
            await _dispatch_one(idx, url)

        tasks = [
            asyncio.create_task(_dispatch_with_defer_log(i, u))
            for i, u in enumerate(capped)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, exc in enumerate(results):
            if isinstance(exc, Exception):
                logger.warning(
                    "[CrawlOrchestrator] dispatch url=%s failed: %s (REQ-10)",
                    capped[i], exc,
                )

        pages = [p for p in slots if p is not None]
        _emit("CRAWLER_PHASE", {"phase": "extracting", "phase_sequence": PHASE_EXTRACTING})
        logger.info(
            "[CrawlOrchestrator] dispatch job_id=%s urls=%d usable=%d concurrency=%d (REQ-10)",
            job_id, len(capped), len(pages), concurrency_limit,
        )
        return CrawlResult(
            query=query,
            pages=pages,
            duration_ms=int((time.monotonic() - t_start) * 1000),
            crawled_at=datetime.now(timezone.utc).isoformat(),
            # T12c (REQ-18 AC1): vision/crawl HAR entries ride the same
            # CrawlResult field the batch path uses, so research()'s
            # _apply_har_penalties + _learn_from_crawl consume them unchanged.
            har_entries=har_entries,
        )

    async def _domain_failure_history(self, url: str, query: str) -> str:
        """Best-effort source_registry failure history for a URL's domain.

        Returns "" (no history / registry unreadable) or a reason like
        "challenge" / "crawl_failed". LOGGED on both sides (pin V2: the
        registry's trustworthiness is unverified — never assumed, always
        logged alongside the dispatch decision).
        """
        try:
            from urllib.parse import urlparse

            from .source_registry import get_source_registry

            domain = urlparse(url).netloc
            reg = get_source_registry()
            resolved = await reg.resolve(query, quick=True)
            sources = resolved.get("sources", []) if isinstance(resolved, dict) else []
            for s in sources:
                if s.get("domain") == domain or urlparse(s.get("url", "")).netloc == domain:
                    err = s.get("last_error") or ""
                    if err:
                        logger.info(
                            "[CrawlOrchestrator] failure-history url=%s domain=%s reason=%r "
                            "(source_registry read, pin V2 unverified)",
                            url, domain, err,
                        )
                        return err
        except Exception as exc:  # noqa: BLE001 — registry read must never break dispatch
            logger.info(
                "[CrawlOrchestrator] failure-history url=%s unreadable=%s -> no history "
                "(REQ-10 AC4: never race on unknown history)",
                url, exc,
            )
        return ""

    def _park_source(self, run_id: str, url: str, wall_kind: str, _emit) -> None:
        """T14 (REQ-13): park a walled source in the shared registry and emit
        CRAWLER_SOURCE_PARKED so the frontend lists it (AC4) and the agent can
        raise one non-blocking question per domain (AC6). Never raises."""
        try:
            from urllib.parse import urlparse

            from backend.agent.tools.ask_user_tool import (
                get_ask_user_tool,
                get_parked_source_registry,
            )

            registry = get_parked_source_registry()
            _domain = urlparse(url).netloc or url
            # REQ-13 AC2: parking alone is not the requirement — a question must
            # actually be RAISED. This previously called registry.park() directly
            # and minted a synthetic `parked_<hex>` id, so the question_id sent to
            # the frontend referenced no real question: a card click could not
            # resolve it and voice (REQ-14) could not find it either. Routing
            # through ask_non_blocking raises the card AND parks with the card's
            # own id, which is what makes AC3 resumption reachable.
            source = None
            try:
                question = get_ask_user_tool().ask_non_blocking(
                    text=(
                        f"I hit a {wall_kind} wall on {_domain} and moved on to "
                        f"other sources. Want me to keep trying that one?"
                    ),
                    options=["Skip it", "Try it again"],
                    allow_other=True,
                    run_id=run_id,
                    parked_url=url,
                    wall_kind=wall_kind,
                )
                source = registry.get(question.question_id)
            except Exception as _ask_exc:  # noqa: BLE001
                # Asking is best-effort; a failure here must still park the
                # source so the run reports it as parked (AC4).
                logger.info(
                    "[CrawlOrchestrator] non-blocking ask failed url=%s: %s "
                    "(falling back to park-only)", url, _ask_exc,
                )
                source = registry.park(run_id=run_id, url=url, wall_kind=wall_kind)
            if source is None:
                # Already parked for this domain this run — no re-ask (AC6).
                logger.info(
                    "[CrawlOrchestrator] park-skip job_id=%s url=%s wall=%s "
                    "(domain already parked this run, REQ-13 AC6)",
                    run_id, url, wall_kind,
                )
                return
            _emit("CRAWLER_SOURCE_PARKED", {
                "url": url,
                "domain": source.domain,
                "wall_kind": wall_kind,
                "run_id": run_id,
                "question_id": source.question_id,
            })
            logger.info(
                "[CrawlOrchestrator] park job_id=%s url=%s wall=%s qid=%s "
                "(REQ-13, run continues)",
                run_id, url, wall_kind, source.question_id,
            )
        except Exception as exc:  # noqa: BLE001 — parking must never break dispatch
            logger.warning("[CrawlOrchestrator] park failed url=%s: %s", url, exc)

    async def _discover_urls_via_vision(self, query: str, job_id: str, _emit) -> list[str]:
        """REQ-19: when the planner yields zero URLs, ask vision to drive a
        search engine and harvest candidate URLs. Never raises — an empty
        return means "no discovery; proceed to the honest REQ-15 no-sources
        outcome" for every failure mode (vision unavailable, wall, or
        genuinely zero results): AC8 degrades exactly like a bare empty plan.

        A wall on the search engine itself parks it via the existing
        `_park_source` (REQ-13) and is reported, never solved (AC5).
        """
        try:
            from backend.vision.search_discovery import discover_urls_via_vision
        except Exception as exc:  # noqa: BLE001 — optional capability (REQ-6 AC1 edge)
            logger.info(
                "[CrawlOrchestrator] discovery unavailable job_id=%s: %s (REQ-19 AC8)",
                job_id, exc,
            )
            return []
        try:
            result = await discover_urls_via_vision(query, job_id, _emit)
        except Exception as exc:  # noqa: BLE001 — REQ-19 must never fail the run
            logger.warning("[CrawlOrchestrator] discovery failed job_id=%s: %s", job_id, exc)
            return []
        if result.wall:
            self._park_source(job_id, result.engine_url or query, result.wall, _emit)
            logger.info(
                "[CrawlOrchestrator] discovery job_id=%s wall=%s on search engine "
                "-> parked, not solved (REQ-19 AC5)",
                job_id, result.wall,
            )
            return []
        if result.unavailable:
            logger.info(
                "[CrawlOrchestrator] discovery job_id=%s vision unavailable "
                "-> honest no-sources outcome (REQ-19 AC8)",
                job_id,
            )
            return []
        logger.info(
            "[CrawlOrchestrator] discovery job_id=%s query=%s urls=%d fallback=%s "
            "(REQ-19 AC1/AC2/AC4, REQ-16)",
            job_id, query[:60], len(result.urls), result.used_vision_fallback,
        )
        return result.urls

    @staticmethod
    def _stamp_discovery_provenance(fetched: CrawlResult, discovered_urls: set) -> None:
        """REQ-19 AC6: mark vision-discovered URLs' pages so their provenance
        is distinguishable from planner-supplied URLs, following the same
        metadata-carries-provenance pattern `_stamp_evidence` already uses
        for `content_origin` (REQ-18 AC2). Never raises (REQ-16 AC7)."""
        if not discovered_urls:
            return
        for p in getattr(fetched, "pages", None) or []:
            if p.url not in discovered_urls:
                continue
            try:
                p.metadata = dict(p.metadata or {})
                p.metadata["url_origin"] = "vision_discovered"
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _stamp_evidence(winner, outcomes: list, url: str, job_id: str) -> None:
        """Reconcile crawl vs vision text and stamp provenance on the winner.

        REQ-17 AC4 (one evidence record, both sides kept), AC5 (disagreement
        recorded), AC6 / REQ-18 AC2 (provenance travels with the content).

        Provenance rides in ``page.metadata`` rather than a new PageData field:
        metadata is already a free-form dict carried through the whole pipeline,
        so this needs no dataclass change and no ripple into the subprocess
        backend's serialisation. Never raises — evidence bookkeeping must not
        cost a page (REQ-16 AC7).
        """
        try:
            from backend.vision.frame_extraction import reconcile

            def _text_of(cap_name: str) -> Optional[str]:
                for o in outcomes:
                    if o.capability == cap_name and o.page is not None:
                        return o.page.markdown
                return None

            record = reconcile(_text_of("fetch.crawl"), _text_of("fetch.vision"), url)
            if winner.page is None:
                return
            meta = winner.page.metadata
            if not isinstance(meta, dict):
                return
            meta["content_origin"] = record.origin.value
            if record.disagreement:
                meta["evidence_disagreement"] = record.disagreement
                # A disagreement is a tuning signal, not noise — log it so the
                # crawl-extracted-a-challenge case is measurable (REQ-16).
                logger.info(
                    "[CrawlOrchestrator] evidence job_id=%s url=%s origin=%s "
                    "disagreement=%s (REQ-17 AC5)",
                    job_id, url, record.origin.value, record.disagreement,
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("[CrawlOrchestrator] evidence stamp failed: %s", exc)

    @staticmethod
    async def _vision_fetch(vision_cap, url: str, goal: str, job_id: str, _emit):
        """Call fetch.vision, passing the REQ-11 AC4 action emitter when the
        capability supports it. Capabilities implementing only the bare
        3-positional-arg protocol are called unchanged (REQ-6 AC1)."""
        def _on_action(payload: dict) -> None:
            _emit("CRAWLER_VISION_ACTION", payload)

        try:
            return await vision_cap.fetch_one(url, goal, job_id, on_action=_on_action)
        except TypeError:
            # Capability does not accept on_action — protocol-only implementation.
            return await vision_cap.fetch_one(url, goal, job_id)

    async def _escalate_to_vision(self, url: str, query: str, job_id: str, crawl_outcome, _emit) -> "FetchOutcome":
        """Problem 1 fix: escalate a FRESH crawl-only failure to fetch.vision.

        Unlike `_race_url` (which fires only when `source_registry` already
        has failure history), this fires the FIRST time a URL fails crawl
        with a reason vision plausibly recovers (see
        `_FRESH_FAILURE_ESCALATE_REASONS`). Called at most once per URL — the
        caller only reaches here after a single crawl-only attempt.

        `crawl_outcome` is already known unusable (that is why we are here),
        so the vision outcome is definitionally the better of the two; we
        still pass BOTH to `_stamp_evidence` so REQ-17 AC4/AC5 reconciliation
        and REQ-18 AC2 provenance stamping happen exactly as they do for the
        raced path. Never raises (REQ-6 AC1: a capability failure never
        breaks dispatch) — `_vision_fetch` / `fetch_one` already guarantee
        that.
        """
        from .capabilities import get_capability

        vision_cap = get_capability("fetch.vision")
        reason = crawl_outcome.verdict.reason.value
        logger.info(
            "[CrawlOrchestrator] escalate job_id=%s url=%s from=fetch.crawl reason=%s "
            "-> fetch.vision (REQ-10 fresh-failure escalation)",
            job_id, url, reason,
        )
        vision_outcome = await self._vision_fetch(vision_cap, url, query, job_id, _emit)
        result_desc = (
            "usable"
            if (vision_outcome.page is not None and vision_outcome.verdict.usable)
            else vision_outcome.verdict.reason.value
        )
        logger.info(
            "[CrawlOrchestrator] escalate job_id=%s url=%s from=fetch.crawl reason=%s "
            "-> fetch.vision result=%s (REQ-16)",
            job_id, url, reason, result_desc,
        )
        # REQ-17 AC4/AC5 + REQ-18 AC2: reconcile crawl vs vision into ONE
        # evidence record, same as the raced path — an escalated URL is not
        # a second-class citizen for provenance/reconciliation purposes.
        self._stamp_evidence(vision_outcome, [crawl_outcome, vision_outcome], url, job_id)
        return vision_outcome

    async def _race_url(self, url: str, goal: str, job_id: str, crawl_cap, _emit) -> "FetchOutcome":
        """Race fetch.crawl vs fetch.vision; first usable wins (REQ-10 AC3/AC5).

        Loser is cancelled. Both usable -> crawl wins (cheaper), race logged.
        """
        from .capabilities import FetchOutcome, get_capability

        vision_cap = get_capability("fetch.vision")
        t0 = time.monotonic()
        crawl_task = asyncio.create_task(crawl_cap.fetch_one(url, goal, job_id))
        # REQ-11 AC4: thread a per-action emitter into the vision capability so
        # each browser action reaches the panel. Passed only when the capability
        # accepts it, so a capability implementing the bare 3-arg protocol still
        # works (REQ-6 AC1).
        vision_task = asyncio.create_task(
            self._vision_fetch(vision_cap, url, goal, job_id, _emit)
        )
        done, pending = await asyncio.wait(
            {crawl_task, vision_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        # Cancel the loser (AC5); cancel releases the loser's resources.
        # Await the cancelled tasks so their CancelledError handlers (lease
        # release, session close) actually run before we return.
        for p in pending:
            p.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        outcomes: list[FetchOutcome] = []
        for t in done:
            try:
                outcomes.append(t.result())
            except Exception as exc:  # noqa: BLE001
                logger.warning("[CrawlOrchestrator] race task failed: %s", exc)
        usable = [o for o in outcomes if o.page is not None and o.verdict.usable]
        if usable:
            # Edge: prefer crawl when both raced results are usable.
            crawl_winner = next((o for o in usable if o.capability == "fetch.crawl"), None)
            winner = crawl_winner or usable[0]
            if crawl_winner is not None and len(usable) > 1:
                logger.info(
                    "[CrawlOrchestrator] race job_id=%s url=%s both usable -> crawl "
                    "(race unnecessary, tuning signal)", job_id, url,
                )
            # REQ-17 AC4/AC5 + REQ-18 AC2: reconcile crawl vs vision into ONE
            # evidence record and stamp its provenance onto the winning page.
            # Picking a winner and dropping the loser would erase the
            # disagreement, and "crawl has text but vision sees a challenge" vs
            # "vision has text but crawl is empty" are OPPOSITE diagnoses
            # (design D9). fetch_vision deferred this to "the caller" and no
            # caller ever did it — reconcile() had zero production callers.
            self._stamp_evidence(winner, outcomes, url, job_id)
            _emit("CRAWLER_PROGRESS", {
                "stage": "fetching",
                "message": f"Raced {url} via {winner.capability}",
            })
            return winner
        # No usable outcome yet — take the first non-exception outcome as-is.
        if outcomes:
            return outcomes[0]
        from .usability import UsabilityReason, UsabilityVerdict

        return FetchOutcome(
            url=url, capability="fetch.crawl", page=None,
            verdict=UsabilityVerdict(usable=False, reason=UsabilityReason.TRANSPORT_ERROR),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

    # -- helpers ----------------------------------------------------------
    async def _plan(self, query: str) -> CrawlPlan:
        planner = self._planner or get_crawl_planner()
        try:
            return await planner.plan(query)
        except Exception as exc:
            logger.warning("[CrawlOrchestrator] planner failed: %s", exc)
            return CrawlPlan(urls=[], instructions="", result_type="mixed", title=query[:60])

    def _split_passages(self, pages: list[PageData]) -> list[Passage]:
        """Split each page into ~300-600 token logical chunks (REQ-4)."""
        passages: list[Passage] = []
        for page in pages:
            text = page.markdown or (page.html or "")
            if not text.strip():
                continue
            chunks = _chunk_text(text, max_chars=2400)
            for i, chunk in enumerate(chunks):
                passages.append(Passage(
                    chunk_id=f"{page.url}#{i}",
                    url=page.url,
                    text=chunk,
                    heading_path=page.title or "",
                ))
        return passages

    def _make_emitter(self, on_progress, session_id: str = ""):
        # REQ-31: every progress event is also appended to the resilient
        # server-side event log so a disconnecting/reconnecting client can
        # replay missed events (partial replay, not full re-crawl).
        log = get_event_log() if session_id else None
        # Fire-and-forget appends can be cancelled when the loop tears down
        # (asyncio.run/_go patterns) before they execute, silently losing
        # events (REQ-31 replay gap). Track them so research() can drain
        # them on every return path.
        self._pending_log_tasks: list = []

        def _emit(event: str, payload: dict) -> None:
            if log is not None:
                try:
                    task = asyncio.ensure_future(
                        log.append(session_id, event, payload)
                    )
                    self._pending_log_tasks.append(task)
                except Exception:  # noqa: BLE001
                    pass  # never block the funnel on a log write failure
            if on_progress is not None:
                _safe(on_progress, CrawlProgress(event, payload))

        return _emit

    async def _drain_log_tasks(self) -> None:
        """Await all pending event-log appends (REQ-31: never lose events).

        research() calls this before every return path; the appends were
        scheduled fire-and-forget from sync callbacks (on_page_done), so they
        need an explicit await point to complete before the loop may close.
        """
        pending = getattr(self, "_pending_log_tasks", None)
        if not pending:
            return
        self._pending_log_tasks = []
        await asyncio.gather(*pending, return_exceptions=True)

    def _page_emitter(self, emit, job_id: str = ""):
        # REQ-11 (T14): SINGLE emission authority — the same (job_id,
        # page_number) must never emit twice. The crawl4ai worker path and the
        # plain-HTTP fallback (crawl_runner) can both reach this callback for
        # the same page (worker times out -> fallback re-fetches the same
        # URLs), which used to duplicate CRAWLER_PAGE_FETCHED and made the
        # browser panel show the page twice. First emitter wins; later
        # duplicates are dropped (the bytes are identical for the same page).
        _seen: set = set()

        def _cb(url, page_number, total, title="", snippet=""):
            # Dedup on the URL, NOT on page_number. Each URL is fetched in its
            # own sub-batch, so EVERY url arrives as page_number=1 — keying on
            # the number therefore dropped every page after the first and the
            # browser panel showed no URL progression at all. Observed live
            # 2026-08-10 18:16: 4 of 5 real URLs silently dropped as
            # "duplicates". The duplicate this guard actually exists for is the
            # worker-then-fallback re-fetch of the SAME url, which the url key
            # still catches.
            _key = (job_id, url)
            if _key in _seen:
                logger.info(
                    "[CrawlOrchestrator] CRAWLER_PAGE_FETCHED dedup drop "
                    "job=%s page=%s url=%s", job_id, page_number, url,
                )
                return
            _seen.add(_key)
            emit("CRAWLER_PAGE_FETCHED", {
                "url": url, "page_number": page_number, "total": total,
                "host": _host(url),
                "title": title,
                "snippet": snippet,
                # T5 (REQ-1 AC1): job_id lets the in-app browser panel build the
                # capture-replay URL /api/browser/capture/{job_id}/{page_number}.
                "job_id": job_id,
            })
        return _cb

    def _empty(self, query, t_start, error) -> CrawlResult:
        return CrawlResult(
            query=query, pages=[], duration_ms=_elapsed(t_start),
            crawled_at=datetime.now(timezone.utc).isoformat(), error=error,
        )

    def _finalize(self, fetched: CrawlResult, query: str, t_start, error=None) -> CrawlResult:
        return CrawlResult(
            query=query, pages=fetched.pages, duration_ms=_elapsed(t_start),
            crawled_at=datetime.now(timezone.utc).isoformat(), error=error,
            har_entries=getattr(fetched, "har_entries", []) or [],
            har_path=getattr(fetched, "har_path", None),
        )

    def _apply_har_penalties(self, fetched: CrawlResult, query: str) -> None:
        """Feed HAR outcomes into SourceRegistry via penalize_url (REQ-14).

        One-way signal: dead/stale HTTP outcomes down-weight the domain for this
        topic. Never raises into the funnel (REQ-16). Reuses the existing
        ``SourceRegistry.penalize_url`` — no new report method is invented.
        """
        entries = getattr(fetched, "har_entries", None) or []
        if not entries:
            return
        try:
            from .source_registry import get_source_registry
            reg = get_source_registry()
        except Exception:  # noqa: BLE001
            return
        for e in entries:
            status = e.get("status")
            err = (e.get("error") or "").lower()
            is_dead = status in (403, 404) or "timeout" in err or "timed out" in err
            # REQ-10 (T12): a bot-challenge interstitial is dead content — the
            # page returned boilerplate, not the page. Penalize with the
            # challenge reason so the outer loop can distinguish CAPTCHA blocks.
            is_challenge = "challenge" in err
            if not is_dead and not is_challenge:
                continue
            try:
                reg.penalize_url(
                    e.get("url", ""),
                    topics=[query],
                    last_error="challenge" if is_challenge else "crawl_failed",
                )
                logger.info(
                    "SRC PENALIZE url=%s status=%s reason=%s query=%s",
                    e.get("url"), status,
                    "challenge" if is_challenge else "crawl_failed",
                    query,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("[CrawlOrchestrator] penalize_url failed: %s", exc)

    async def _learn_from_crawl(self, fetched: CrawlResult, query: str) -> None:
        """Register successfully-crawled URLs into SourceRegistry for this topic
        (REQ-18/REQ-19). Reuses the existing ``learn()`` — no new method. The
        more the agent researches, the smarter (and cheaper) later crawls become
        because ``resolve()`` then seeds from updated knowledge. Never raises.
        """
        # REQ-1 AC1/AC3: judged by the SHARED predicate, not by `not p.error`.
        # This was the third instance of the three-way disagreement and the most
        # damaging one: a page with error=None and EMPTY markdown was learned as
        # a good source for the topic, so later crawls preferentially re-seeded
        # from URLs that had never produced content. The reference trace shows it
        # — "SourceRegistry learn ... saved=1" fired at 22:01:00 on a run whose
        # every page was unusable.
        from .usability import page_is_usable

        ok_pages = [
            p for p in getattr(fetched, "pages", [])
            if page_is_usable(p).usable
        ]
        if not ok_pages:
            return
        try:
            from .source_registry import get_source_registry
            reg = get_source_registry()
        except Exception:  # noqa: BLE001
            return
        try:
            search_result = type(
                "SR", (), {"results": [type("I", (), {"url": p.url})() for p in ok_pages]}
            )()
            await reg.learn(query, search_result)
            logger.info("SRC LEARN query=%s urls=%d", query, len(ok_pages))
        except Exception as exc:  # noqa: BLE001
            logger.debug("[CrawlOrchestrator] learn_from_crawl failed: %s", exc)

    @staticmethod
    def _healthy_har_reuse(har_entries: list, crawled_at: str, ttl_days: int) -> bool:
        """True when a prior HAR is reusable: every entry succeeded (2xx) and the
        crawl is within ``ttl_days`` (REQ-19 memory-first signal)."""
        if not har_entries:
            return False
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(crawled_at)).days
        except Exception:
            age = 0
        if age > ttl_days:
            return False
        return all((e.get("status") or 0) // 100 == 2 for e in har_entries)

    def _delta_urls(self, plan_urls: list, prior_har_entries: list,
                    prior_crawled_at: str, ttl_days: int) -> list:
        """Memory-first fetch planning (REQ-19): if the prior HAR for the same
        topic is healthy, reuse it and fetch ONLY the URLs not already covered
        (deltas). Otherwise re-fetch everything. Returns the URLs to fetch.
        """
        if not self._healthy_har_reuse(prior_har_entries, prior_crawled_at, ttl_days):
            return list(plan_urls)
        prior = {e.get("url") for e in prior_har_entries}
        return [u for u in plan_urls if u not in prior]


# ---------------------------------------------------------------------------
# small utilities
# ---------------------------------------------------------------------------
def _safe(fn, arg) -> None:
    try:
        fn(arg)
    except Exception:  # noqa: BLE001 - emitter must never break the crawl
        pass


def _elapsed(t_start: float) -> int:
    return int((time.monotonic() - t_start) * 1000)


def _host(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc
    except Exception:
        return ""


def _broaden_query(query: str) -> str:
    """Widen a query for Exa retry by prepending a broadener prefix (T17)."""
    # Remove existing quoted modifiers and add a broader scope.
    clean = query.strip().strip('"').strip("'")
    broadeners = [
        "overview of",
        "summary of",
        "what is",
    ]
    # If query is already short/generic, just return it unchanged.
    if len(clean) < 15 or any(clean.lower().startswith(b) for b in broadeners):
        return query
    return f"overview of {clean.lower()}"


def _chunk_text(text: str, max_chars: int = 2400) -> list[str]:
    """Split on paragraph/heading boundaries into <= max_chars chunks."""
    import re
    blocks = re.split(r"\n\s*\n|(?=^#{1,6}\s)", text, flags=re.MULTILINE)
    chunks: list[str] = []
    cur = ""
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if len(cur) + len(block) + 2 <= max_chars:
            cur = f"{cur}\n\n{block}" if cur else block
        else:
            if cur:
                chunks.append(cur)
            # very long single block: hard split by sentence window
            if len(block) > max_chars:
                for i in range(0, len(block), max_chars):
                    chunks.append(block[i:i + max_chars])
                cur = ""
            else:
                cur = block
    if cur:
        chunks.append(cur)
    return chunks or [text[:max_chars]]


# Module-level convenience (matches existing get_* singleton pattern)
_orchestrator: Optional[CrawlOrchestrator] = None


def get_crawl_orchestrator() -> CrawlOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = CrawlOrchestrator()
    return _orchestrator
