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
from typing import TYPE_CHECKING, Callable, Literal, Optional

if TYPE_CHECKING:  # pragma: no cover — typing only, zero runtime cost
    from backend.core_models import GoalAnatomy

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
# Quorum return (spec A3, D4): once `min_pages` usable pages are in, dispatch_urls
# waits at most this long for the remaining URLs, then cancels them. Without it
# the crawl waited for its slowest URL (measured 2026-09-30: 3 pages in ~6 s, then
# ~30 s more for two URLs that could not succeed).
_QUORUM_GRACE_S = float(os.environ.get("IRIS_CRAWL_QUORUM_GRACE_S", "2"))
# D6 same-site hop: fewer kept passages than this, from a site that produced relevant
# ones, earns ONE hop to that site's most goal-relevant links (depth 1, bounded).
_HOP_MIN_KEPT = 3
_HOP_MAX_LINKS = 4
_HOP_BUDGET_S = 15.0
# D3 fix (T36 live smoke, 2026-08-09): kept in lockstep with crawl_runner.py's
# _DEFAULT_TIMEOUT_S (same env var, same fallback) — see that module for the
# cold-vs-warm browser-launch measurement behind the 45s->90s change.
# Session 365 — the per-run subprocess bound, sized to fit INSIDE the 25 s run
# ceiling above (it was 90 s, i.e. it could never be the thing that stopped a
# run: the outer bound always won, and the failure surfaced as a bare
# TimeoutError rather than an honest per-run limit).
_DEFAULT_TIMEOUT_S = float(os.environ.get("CRAWL_SUBPROCESS_TIMEOUT_S", "25"))
# REQ-10 AC1: max distinct URLs fetched concurrently by dispatch_urls().
_DEFAULT_CONCURRENCY = int(os.environ.get("CRAWL_CONCURRENCY", "3"))

# THE RUN CEILING. One deadline for the whole dispatch, enforced with wait_for
# rather than checked and hoped for.
#
# Every bound before this one was per-subsystem and advisory: the session had
# max_wall_ms=60_000 and ran to elapsed_ms=243_112 because the code that noticed
# only logged, and the crawl subprocess had its own 90s that said nothing about
# the run as a whole. Measured end to end on 2026-08-11: 7m43s for five URLs.
#
# The number of sources must NOT change how long a search takes — a run gathers
# what it can inside the ceiling and reports honestly on the rest, rather than
# growing without limit as the planner returns more candidates.
# Session 247: raised 90s -> 150s. Live evidence (conv-42/conv-46): with the
# boot pre-warm the worker INIT is fast, but heavy real-world pages (press
# sites, electrive) legitimately need 60-120s — at 90s they were parked as
# run_budget mid-fetch even though nothing was wrong, which both lost sources
# and spammed REQ-13 question cards for pseudo-walls. 150s still bounds the
# worst case (a hung page cannot eat more than its share) while letting real
# pages finish.
# Session 365 — THE RUN CEILING IS A CEILING, NOT A TARGET. This was 150000 ms
# (2.5 min) and a failing crawl SPENT it: measured 254 s wall for a
# crawler_query that then crashed with a bare TimeoutError, and 157 s before
# that. The owner's requirement is explicit: a web step must finish well inside
# 30 s or fail fast, because the user is waiting on a spoken answer. The budget
# bounds the whole run, so it must be the OUTER bound — the per-source and
# per-page limits below are sized to fit inside it, never the other way round.
_RUN_BUDGET_MS = int(os.environ.get("IRIS_WEBSEARCH_MAX_WALL_MS", "25000"))

# Problem-1 fix (REQ-10 escalation tier, REQ-6 AC1 edge): fresh-failure
# reasons where an interactive vision session plausibly recovers content
# crawl could not. TRANSPORT_ERROR is deliberately EXCLUDED — it is the
# reason recorded for BOTH robots.txt refusal (REQ-5 AC3: must never route
# around robots compliance) and DNS failure (vision cannot resolve a name
# crawl could not either), and fetch.vision navigates directly with no
# robots gate of its own (only crawler_engine.crawl() checks robots.txt).
# Escalating any transport_error would silently bypass robots.txt for
# exactly the URL it just refused.
#
# CHALLENGE is excluded too (2026-08-12 decision, capabilities.py
# fetch.vision NodeSpec): escalating a wall to a headless browser measured
# 0/3 across three live attempts costing 240s + 188s + 243s of a
# seven-minute turn with zero content gained. A wall is PARKED (the
# CHALLENGE branch in _dispatch_one) and, when it empties the whole batch,
# rescued by the REQ-19 AC9 exhaustion discovery — never re-fought by the
# tier that provably loses to it. This set now matches fetch.vision's
# advertised recovers_reasons exactly.
_FRESH_FAILURE_ESCALATE_REASONS = frozenset({
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
        page_offset: int = 0,
    ) -> CrawlResult:  # pragma: no cover - abstract
        raise NotImplementedError


class InProcessFetchBackend(FetchBackend):
    """In-process CrawlerEngine (used by WS mode=ws)."""

    async def fetch(self, query, urls, instructions, max_pages, on_page_done, timeout_s, job_id=None, page_offset=0):
        from .crawler_engine import CrawlerEngine
        try:
            async with CrawlerEngine() as engine:
                return await engine.crawl(
                    query=query, urls=urls, instructions=instructions,
                    max_pages=max_pages, on_page_done=on_page_done,
                    job_id=job_id, page_offset=page_offset,
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

    async def fetch(self, query, urls, instructions, max_pages, on_page_done, timeout_s, job_id=None, page_offset=0):
        from .crawl_runner import run_crawl_subprocess
        return await run_crawl_subprocess(
            query=query, urls=urls, instructions=instructions,
            on_page_done=on_page_done, max_pages=max_pages, timeout_s=timeout_s,
            job_id=job_id, page_offset=page_offset,
        )


_BACKENDS: dict[str, type[FetchBackend]] = {
    "ws": InProcessFetchBackend,
    "agent": SubprocessFetchBackend,
}


async def _call_fetch_one(
    cap, url: str, goal: str, job_id: str, *, on_progress=None, page_offset: int = 0,
):
    """``cap.fetch_one`` with whichever optional kwargs the capability accepts.

    The FetchCapability protocol call is 3-positional so capabilities stay
    interchangeable (REQ-6 AC1); ``on_progress`` and ``page_offset`` are
    independent optional extensions.

    Support is decided PER KWARG and by SIGNATURE. The previous shape — pass both
    and fall back to the bare 3-arg call on TypeError — has two failure modes,
    and one of them bit immediately: a capability that accepted on_progress but
    not page_offset lost its EMITTER on the retry, so no page event reached the
    panel at all (the regression pinned in pin_883b20571a56, caught here by
    test_page_events_carry_the_outer_runs_numbering). The other is that fetch_one
    performs a whole network fetch, so a TypeError raised anywhere inside it
    would be misread as a signature mismatch and re-run the entire fetch.
    """
    import inspect

    kwargs: dict = {}
    try:
        _params = inspect.signature(cap.fetch_one).parameters
        _var_kw = any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in _params.values()
        )
        if on_progress is not None and (_var_kw or "on_progress" in _params):
            kwargs["on_progress"] = on_progress
        if page_offset and (_var_kw or "page_offset" in _params):
            kwargs["page_offset"] = page_offset
    except (TypeError, ValueError):  # unintrospectable callable — bare protocol
        kwargs = {}
    return await cap.fetch_one(url, goal, job_id, **kwargs)


# ---------------------------------------------------------------------------
# CrawlOrchestrator — the funnel (REQ-1)
# ---------------------------------------------------------------------------
class CrawlOrchestrator:
    def __init__(self, planner=None, extractor=None) -> None:
        self._planner = planner
        self._extractor = extractor
        self._backend_override: Optional[FetchBackend] = None  # test seam (no live web)
        # Session 244: per-run park ledger — job_id -> [(domain, wall_kind)].
        # Populated by _park_source; consumed to build CrawlResult.park_summary
        # (the structured outcome DER's reviewer reads instead of a content-free
        # "empty_result") and to skip the provably-futile broadened retry.
        self._parks_by_job: dict[str, list[tuple[str, str]]] = {}
        # Session 247: zero-yield cutoff — per-session rolling record of recent
        # job outcomes. Two consecutive jobs with ZERO usable pages inside the
        # window means the environment is not yielding content right now (walls,
        # dead sources, offline); further full-funnel runs would each burn their
        # whole budget to learn the same thing. The next research() for that
        # session fails fast and honestly instead. Keyed by session so one
        # busy session can never suppress another's searches.
        self._zero_yield_window_s = float(
            os.environ.get("IRIS_ZERO_YIELD_WINDOW_S", "600")
        )
        self._zero_yield_limit = int(os.environ.get("IRIS_ZERO_YIELD_LIMIT", "2"))
        self._recent_yields: dict[str, list[tuple[float, int]]] = {}

    def _record_yield(self, session_id: str, usable: int) -> None:
        """Append a job outcome to the session's zero-yield window. Never raises."""
        try:
            now = time.monotonic()
            buf = self._recent_yields.setdefault(session_id or "", [])
            buf.append((now, usable))
            cutoff = now - self._zero_yield_window_s
            while buf and buf[0][0] < cutoff:
                buf.pop(0)
            # Bound memory: the window only ever needs the last few outcomes.
            while len(buf) > 8:
                buf.pop(0)
        except Exception:
            pass

    def _zero_yield_tripped(self, session_id: str) -> bool:
        """True when the last N (limit) jobs in this session's window ALL had
        zero usable pages — the stop-throwing-good-budget-after-bad signal."""
        try:
            now = time.monotonic()
            cutoff = now - self._zero_yield_window_s
            buf = self._recent_yields.get(session_id or "") or []
            # Prune expired entries on read too: a quiet period must clear the
            # streak even if no new job ran to trigger _record_yield's prune.
            buf = [e for e in buf if e[0] >= cutoff]
            if session_id:
                self._recent_yields[session_id] = buf
            if len(buf) < self._zero_yield_limit:
                return False
            return all(u == 0 for _, u in buf[-self._zero_yield_limit:])
        except Exception:
            return False

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
        excluded_urls: Optional[list] = None,
        seed_urls: Optional[list] = None,
        defer_extraction: bool = False,
    ) -> CrawlResult:
        """Public entry point. REQ-18 AC2 (T20): declare that this RUN needs the
        browser for its whole duration, so the pool's idle-stop cannot fire
        between two URLs of the same run and force a second cold launch. The
        declaration is released on EVERY exit path (finally). Never raises on
        the declare/release itself — warmth is best-effort and must never break
        a crawl.
        """
        try:
            from backend.vision import browser_pool as _bp20

            _bp20.declare_browser_run()
            _declared = True
        except Exception:  # noqa: BLE001 — warmth is best-effort
            _bp20 = None
            _declared = False
        _wt: dict = {}
        try:
            _result = await self._research_inner(
                query, mode=mode, session_id=session_id, on_progress=on_progress,
                max_pages=max_pages, min_pages=min_pages, timeout_s=timeout_s,
                job_id=job_id, excluded_urls=excluded_urls, seed_urls=seed_urls,
                defer_extraction=defer_extraction, _timing=_wt,
            )
            try:
                _wt["pages_usable"] = sum(
                    1 for _p in (_result.pages or []) if page_is_usable(_p).usable
                )
                _wt["pages_cancelled"] = len(getattr(_result, "cancelled_enough", []) or [])
                _result.web_timing = dict(_wt)
            except Exception:  # noqa: BLE001 — a timing note never fails a run
                pass
            return _result
        finally:
            if _declared and _bp20 is not None:
                try:
                    _bp20.release_browser_run()
                except Exception:  # noqa: BLE001
                    pass

    async def _research_inner(
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
        excluded_urls: Optional[list] = None,
        seed_urls: Optional[list] = None,
        defer_extraction: bool = False,
        _timing: Optional[dict] = None,
    ) -> CrawlResult:
        """Run the full funnel. Never raises for crawl failures (REQ-17 AC1).

        ``defer_extraction`` (spec websearch-vision-browser REQ-3 AC3.1 / D5):
        the agent path consumes raw page ``content``, never the DataExtractor
        JSON, so the extractor leaves the answer path. research() returns
        right after rerank and the extraction runs on
        ``durability_queue.lane("web_extract")``; that job emits the SAME
        OPEN_TAB (dashboard payload) then CRAWLER_COMPLETE when it lands. The
        default (False) is the synchronous path the gateway consumes.
        """
        t_start = time.monotonic()

        def _wt_add(key: str, t0: float) -> None:
            # Spec A7: accumulate this phase's wall time into the caller's dict.
            if _timing is not None:
                _timing[key] = _timing.get(key, 0) + int((time.monotonic() - t0) * 1000)

        if not job_id:
            job_id = uuid.uuid4().hex
        # Session-326 shield 2 (owner: no dark gaps): the funnel speaks at
        # every gate — entry here, plan answer inside the planner, dispatch
        # below. A stall then shows its last station in the log tail.
        logger.info(
            "[CrawlOrchestrator] research start job_id=%s mode=%s query=%r",
            job_id, mode, query[:60],
        )
        # Session-318 (REQ-9 AC9.1/AC9.2): turn visited set for seed
        # exclusion. Arrives per-call (the orchestrator is a shared
        # singleton — REQ-16: no shared mutable state); empty = no-op.
        _excluded: set = set()
        try:
            _excluded = {
                str(u).strip() for u in (excluded_urls or [])
                if isinstance(u, str) and str(u).strip().startswith("http")
            }
        except Exception:
            _excluded = set()
        _emit = self._make_emitter(on_progress, session_id)

        # Session-326 (owner: warm at plan, only when the brain lacks sight).
        # Fire-and-forget browser prewarm during LLM planning so a later
        # vision discovery finds a warm pool. Skipped when the live brain
        # already sees. Chromium and the model loader are separate resources;
        # this warms Chromium only. Never raises into research; undetermined
        # means warm (the safe direction — one launch beats a cold stall).
        try:
            _ploop = asyncio.get_running_loop()
            _ploop.create_task(self._maybe_prewarm_browser_for_discovery(job_id))
        except Exception:
            pass

        # Session 247: zero-yield cutoff. When this session's last N jobs ALL
        # returned zero usable pages inside the window, the environment is not
        # yielding content — run the full funnel again and it will burn its
        # whole budget (planner + dispatch + rerank + extract) to relearn that.
        # Fail fast and honestly instead; DER synthesizes from what it has.
        # Fast-fail outcomes are deliberately NOT recorded, so the window
        # ages out and a real attempt happens again after the quiet period.
        if self._zero_yield_tripped(session_id):
            logger.warning(
                "[CrawlOrchestrator] zero_yield_cutoff session=%s query=%s — "
                "last %d jobs yielded 0 usable pages within %.0fs; failing fast "
                "(honest REQ-15 outcome)",
                session_id or "unknown", query[:60],
                self._zero_yield_limit, self._zero_yield_window_s,
            )
            _emit("CRAWLER_ERROR", {"message": "recent crawls yielded no usable content"})
            await self._drain_log_tasks()
            return self._empty(query, t_start, "recent crawls yielded no usable content")

        # 1) PLAN (REQ-2) — or recovery seeds, which re-enter the funnel as
        # an ordinary CrawlPlan (REQ-19 AC3 precedent): planner/discovery
        # skipped, exclusions still enforced, broaden retry still available.
        _seed_urls = [
            u for u in (seed_urls or [])
            if isinstance(u, str) and u.startswith("http")
        ]
        if _seed_urls:
            _seed_fresh = self._exclude_visited(
                _seed_urls, _excluded, job_id, "recovery-seeds"
            )
            if not _seed_fresh:
                _emit("CRAWLER_ERROR", {"message": "recovery seeds already visited this turn"})
                try:
                    from backend.agent.write_counters import bump as _bump_sref
                    _bump_sref("crawler.seeds_refused")
                except Exception:
                    pass
                await self._drain_log_tasks()
                return self._empty(query, t_start, "recovery seeds already visited this turn")
            plan = CrawlPlan(
                urls=_seed_fresh,
                instructions="Extract the page content relevant to the query.",
                result_type="mixed",
                title=query[:60],
            )
            logger.info(
                "[CrawlOrchestrator] recovery seeds job_id=%s urls=%d",
                job_id, len(_seed_fresh),
            )
        else:
            _tp = time.monotonic()
            plan: CrawlPlan = await self._plan(query)
            _wt_add("search_ms", _tp)
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

        # Session-318 (REQ-9 AC9.1/AC9.2): filter planner/discovered seeds
        # against the turn visited set BEFORE paying. Empty → the same
        # honest-empty the no-candidate path returns (never a forced crawl).
        plan.urls = self._exclude_visited(plan.urls, _excluded, job_id, "plan")
        if not plan.urls:
            _emit("CRAWLER_ERROR", {"message": "all planned urls already visited this turn"})
            try:
                from backend.agent.write_counters import bump as _bump_ref
                _bump_ref("crawler.seeds_refused")
            except Exception:
                pass
            await self._drain_log_tasks()
            return self._empty(query, t_start, "all planned urls already visited this turn")
        # `urls` is the PLANNED SET, not just its size. The plan card shows the
        # user which sources the agent intends to read BEFORE it reads them, and
        # url_count alone cannot express that — the panel could only ever count.
        # The set is not final: vision discovery (typing a query into a search
        # engine) and a broadened re-plan both ADD sources mid-run, each announced
        # by CRAWLER_SOURCES_ADDED so the card appends rather than resets.
        _emit("CRAWLER_STARTED", {
            "query": query,
            "url_count": len(plan.urls),
            "urls": list(plan.urls),
            "session_id": session_id,
            "job_id": job_id,
            # REQ-19: distinguish planner-supplied sources from vision-discovered
            # ones, so the card can say WHERE a source came from.
            "discovered_urls": sorted(discovered_urls),
        })
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
        _tf = time.monotonic()
        if dispatch_path:
            fetched = await self.dispatch_urls(
                plan.urls,
                query=query,
                job_id=job_id,
                session_id=session_id,
                on_progress=on_progress,
                max_pages=max_pages,
                min_pages=min_pages,
                timeout_s=timeout_s,
                excluded_urls=sorted(_excluded),
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
        _wt_add("crawl_ms", _tf)
        # REQ-19 AC6: mark vision-discovered URLs' pages so their provenance
        # is distinguishable from planner-supplied URLs (REQ-18 AC2 pattern).
        self._stamp_discovery_provenance(fetched, discovered_urls)
        # Session 244: attach the structured park outcome. DER's reviewer reads
        # THIS instead of a content-free "empty_result" — it can then tell
        # "no information exists" apart from "our sources got walled" and branch
        # accordingly (diversify / ask user / report honestly).
        _parks = self._parks_by_job.get(job_id) or []
        if _parks:
            from collections import Counter
            # Session 245 FIX (unpack bug, pin_69bb11e9b513): the Counter was
            # built over STRINGS f"{d}:{k}", but the summary below unpacks each
            # key as a (d, k) tuple — iterating a longer string as the key
            # raised "too many values to unpack (expected 2)" and failed every
            # crawl that had parked sources. Tuple keys make the unpacking
            # below valid.
            _by = Counter((d, k) for d, k in _parks)
            _domains = sorted({d for d, _ in _parks})
            fetched.park_summary = (
                f"{len(_parks)}/{len(plan.urls)} sources parked "
                f"({'; '.join(f'{d}: {k} x{n}' for (d, k), n in _by.most_common())}; "
                f"distinct domains: {len(_domains)})"
            )
            logger.info(
                "[CrawlOrchestrator] park_summary job_id=%s %s", job_id,
                fetched.park_summary,
            )
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
        # Session 244: FUTILE-RETRY GUARD — when every planned URL was parked
        # on a single domain, a broadened re-plan of the SAME query re-asks for
        # the same walled site; skip the wave and let the typed park_summary
        # drive DER's decision instead. This is what turned one slow GitHub
        # page into a 14-minute park/re-dispatch loop.
        _futile = (
            not ok_pages
            and _parks
            and len(_parks) >= len(plan.urls)
            and len({d for d, _ in _parks}) == 1
        )
        if _futile:
            logger.info(
                "[CrawlOrchestrator] skipping futile broadened retry job_id=%s — "
                "all %d sources parked on one domain (%s)",
                job_id, len(_parks), next(iter({d for d, _ in _parks})),
            )
        elif (fetched.error or not ok_pages) and not getattr(fetched, "_retried", False):
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
            plan.urls = self._exclude_visited(
                plan.urls, _excluded, f"{job_id}_retry", "broaden"
            )
            if plan.urls:
                # The broadened re-plan (and any vision discovery inside it) is
                # where the source set GROWS mid-run — a fresh Exa plan for the
                # broader query, or URLs the vision model found by typing into a
                # search engine. Announce the additions so the plan card APPENDS
                # them; without this the card would still be showing the original
                # five while the agent reads a different set entirely.
                _emit("CRAWLER_SOURCES_ADDED", {
                    "job_id": job_id,
                    "urls": list(plan.urls),
                    "discovered_urls": sorted(discovered_urls),
                    "query": broader_query,
                    "reason": "broadened_replan",
                })
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
        # Session 247: record this job's yield for the zero-yield cutoff.
        # Placed AFTER the broadened-retry branch so the record reflects the
        # job's final fetch outcome, not a zero the retry was about to rescue.
        self._record_yield(session_id, len(ok_pages))
        if not ok_pages and not discovery_attempted:
            # REQ-19 AC9 (T27): EXHAUSTION trigger — every planned URL (broadened
            # re-plan included) yielded nothing usable, so the run is one step
            # from the honest failure report below. Before reporting, spend this
            # run's ONE discovery attempt (AC7's bound is shared with the AC1
            # empty-plan trigger via `discovery_attempted`): a browser typing the
            # query into a search engine is a different acquisition channel than
            # re-planning, and it stayed idle in the 2026-09-18 live wall run —
            # every planned URL Cloudflare-blocked, discovery never consulted
            # because the planner itself was not empty, apology delivered.
            discovery_attempted = True
            if _router_recovery_node(
                "no_candidates", step_id=f"disc:{job_id}",
            ) == "search_discovery":
                discovered = await self._discover_urls_via_vision(query, job_id, _emit)
            else:
                discovered = []
            # Discovery feeds the SAME fetch selection the run already made
            # (AC3: one dispatch path — `dispatch_urls` in production,
            # `backend.fetch` under the test seam). Already-attempted URLs are
            # excluded: a search engine often re-surfaces the very walled pages
            # that just failed, and re-paying for them re-fails identically.
            discovered = self._exclude_visited(
                discovered,
                _excluded | {p.url for p in (fetched.pages or []) if p.url},
                f"{job_id}_ac9",
                "ac9-exhaustion",
            )
            if discovered:
                discovered_urls.update(discovered)
                _emit("CRAWLER_PROGRESS", {"stage": "narrowing", "message": "Finding new sources…"})
                _emit("CRAWLER_PHASE", {"phase": "searching", "phase_sequence": PHASE_SEARCHING})
                _emit("CRAWLER_SOURCES_ADDED", {
                    "job_id": job_id,
                    "urls": list(discovered),
                    "discovered_urls": sorted(discovered_urls),
                    "query": query,
                    "reason": "exhaustion_discovery",
                })
                if dispatch_path:
                    fetched = await self.dispatch_urls(
                        discovered,
                        query=query, job_id=job_id, session_id=session_id,
                        on_progress=on_progress, max_pages=max_pages,
                        timeout_s=timeout_s, excluded_urls=sorted(_excluded),
                    )
                else:
                    fetched = await backend.fetch(
                        query=query, urls=discovered,
                        instructions=plan.instructions,
                        max_pages=max_pages,
                        on_page_done=self._page_emitter(_emit, job_id),
                        timeout_s=timeout_s,
                        job_id=f"{job_id}_ac9",
                    )
                # The broaden retry budget is spent the same way here — AC9 IS
                # this run's other rescue; the rerank escalate must not re-plan.
                setattr(fetched, "_retried", True)
                self._stamp_discovery_provenance(fetched, discovered_urls)
                self._apply_har_penalties(fetched, query)
                await self._learn_from_crawl(fetched, query)
                ok_pages = [p for p in fetched.pages if page_is_usable(p).usable]
                self._record_yield(session_id, len(ok_pages))
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
                plan.urls = self._exclude_visited(
                    plan.urls, _excluded, f"{job_id}_requery", "escalate"
                )
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

        # D6 / W3: the kept passages are few, from a site that produced relevant ones ->
        # one same-site hop. Keep the hop's result only if it kept at least as much.
        if rerank_outcome.state == RerankState.OK and len(rerank_outcome.kept) < _HOP_MIN_KEPT:
            _hop_pages = await self._same_site_hop(
                query, ok_pages, rerank_outcome.kept, backend=backend, plan=plan,
                _emit=_emit, job_id=job_id, excluded=_excluded, max_pages=max_pages,
            )
            if _hop_pages:
                _hop_all = ok_pages + _hop_pages
                _hop_passages = self._split_passages(_hop_all)
                _hop_cred = score_credibility(_hop_all, _hop_passages)
                _hop_outcome = rerank_passages(_hop_passages, query, _hop_cred)
                if _hop_outcome.state == RerankState.OK and len(_hop_outcome.kept) >= len(rerank_outcome.kept):
                    ok_pages, passages, cred_map, rerank_outcome = (
                        _hop_all, _hop_passages, _hop_cred, _hop_outcome,
                    )
                    fetched.pages.extend(_hop_pages)

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
        if defer_extraction:
            # REQ-3 AC3.1 / D5: the answer path returns now; the extractor and
            # the dashboard events land later on the web_extract lane.
            cred_map.top_score = max((p.score for p in passages), default=0.0)
            result = self._finalize(fetched, query, t_start)
            result.passages = passages
            result.credibility_map = cred_map
            result.citation_index = {p.chunk_id: p.url for p in passages if p.chunk_id}
            self._submit_deferred_extract(
                _emit, query=query, fetched=fetched, passages=passages, plan=plan,
                cred_map=cred_map, session_id=session_id, job_id=job_id,
                page_count=len(ok_pages),
            )
            await self._drain_log_tasks()
            return result

        from .cite import extract_and_cite
        _te = time.monotonic()
        dashboard_data, cited_markdown, unsourced = await extract_and_cite(
            query=query, fetched=fetched, passages=passages,
            instructions=plan.instructions, result_type=plan.result_type,
            title=plan.title, extractor=self._extractor,
        )
        _wt_add("extract_ms", _te)
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
        self._emit_dashboard(
            _emit, query=query, title=plan.title, dashboard_data=dashboard_data,
            session_id=session_id, job_id=job_id, page_count=len(ok_pages),
        )
        await self._drain_log_tasks()
        return result

    @staticmethod
    def _emit_dashboard(
        _emit, *, query: str, title: str, dashboard_data: dict,
        session_id: str, job_id: str, page_count: int,
    ) -> None:
        """OPEN_TAB (dashboard payload) then CRAWLER_COMPLETE — one shape for
        the synchronous path and the deferred web_extract lane job."""
        _emit("OPEN_TAB", {
            "tab_type": "dashboard", "id": session_id or query,
            "title": title, "data": dashboard_data,
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
            "page_count": page_count,
            "session_id": session_id,
            "job_id": job_id,
        })

    def _submit_deferred_extract(
        self, _emit, *, query: str, fetched: CrawlResult, passages: list,
        plan: CrawlPlan, cred_map, session_id: str, job_id: str, page_count: int,
    ) -> None:
        """REQ-3 AC3.1: run extract_and_cite on durability_queue.lane("web_extract").

        The lane thread runs the extraction on its own short-lived event loop
        (the model call is synchronous on the light path anyway), then hands
        the events back to the caller's loop with call_soon_threadsafe: the
        emitter schedules event-log appends with ensure_future, so it must run
        on the loop that owns the session. Never raises into research().
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        extractor = self._extractor
        title = plan.title
        instructions = plan.instructions
        result_type = plan.result_type

        def _job() -> None:
            from .cite import extract_and_cite

            t0 = time.monotonic()
            try:
                dashboard_data, _cited, unsourced = asyncio.run(extract_and_cite(
                    query=query, fetched=fetched, passages=passages,
                    instructions=instructions, result_type=result_type,
                    title=title, extractor=extractor,
                ))
            except Exception as exc:  # noqa: BLE001 — the dashboard still lands
                logger.warning(
                    "[CrawlOrchestrator] deferred extract failed job_id=%s: %s", job_id, exc,
                )
                dashboard_data = {"title": title, "summary": "", "key_findings": [], "sources": []}
                unsourced = []
            cred_map.unsourced_claims = unsourced
            logger.info(
                "[web_timing] job_id=%s deferred extract_ms=%d",
                job_id, int((time.monotonic() - t0) * 1000),
            )
            if loop is None or loop.is_closed():
                logger.warning(
                    "[CrawlOrchestrator] deferred dashboard not emitted job_id=%s: "
                    "caller loop gone", job_id,
                )
                return
            try:
                loop.call_soon_threadsafe(lambda: self._emit_dashboard(
                    _emit, query=query, title=title, dashboard_data=dashboard_data,
                    session_id=session_id, job_id=job_id, page_count=page_count,
                ))
            except RuntimeError as exc:  # loop closed between check and call
                logger.warning(
                    "[CrawlOrchestrator] deferred dashboard not emitted job_id=%s: %s",
                    job_id, exc,
                )

        from backend.utils.durability_queue import lane

        if not lane("web_extract").submit(f"web_extract:{job_id}", _job):
            logger.warning(
                "[CrawlOrchestrator] web_extract lane full job_id=%s: dashboard dropped",
                job_id,
            )

    async def fetch_url(
        self,
        url: str,
        *,
        session_id: str = "",
        on_progress: Optional[Callable[[CrawlProgress], None]] = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        job_id: Optional[str] = None,
        page_offset: int = 0,
    ) -> CrawlResult:
        """Direct single-URL fetch (REQ-16 open_url path). No LLM planning.

        Fetches exactly ``url`` through the swappable fetch backend (agent =
        crash-isolated subprocess) and returns the CrawlResult with the page
        content. Emits CRAWLER_STARTED + CRAWLER_PAGE_FETCHED so the in-app
        browser surface sees the page load. Never raises for fetch failures
        (REQ-17 AC1). Does NOT plan URLs or run extraction — open_url wants
        the raw page, not a research dashboard.

        ``page_offset`` reserves this fetch's block of the job's CAPTURE address
        space. A single-URL fetch numbers its only page 1, so five of them under
        one job_id all wrote <job>/1.html and the panel's replay URL 404'd for
        pages 2..5. dispatch_urls passes each URL's reserved offset.
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
                page_offset=page_offset,
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
        query: str | GoalAnatomy,
        job_id: str,
        session_id: str = "",
        on_progress: Optional[Callable[[CrawlProgress], None]] = None,
        max_pages: int = _DEFAULT_MAX_PAGES,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        concurrency_limit: int = _DEFAULT_CONCURRENCY,
        min_pages: int = _DEFAULT_MIN_PAGES,
        output_schema: Optional[dict] = None,
        extract: Optional[Callable[["PageData"], Optional[dict]]] = None,
        on_missing_fields: Optional[Callable[[list], list]] = None,
        _followup_depth: int = 0,
        _shared_findings=None,
        _shared_covered: Optional[dict] = None,
        _base_offset: int = 0,
        excluded_urls: Optional[list] = None,
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
        - Quorum (spec A3): when ``min_pages`` usable pages are in, the rest get
          ``_QUORUM_GRACE_S`` to finish, then are CANCELLED (``cancelled_enough``
          — logged, never parked, never recorded as a wall). A schema journey
          (``output_schema``) is exempt: its completeness is field coverage.
        - AC2.3 (REQ-2, T29): when ``output_schema`` declares required fields,
          completeness is evaluated after EVERY page outcome — the moment all
          required fields hold a non-None value the remaining queued and
          in-flight fetches are CANCELLED (early termination). ``extract`` is
          the caller's projection hook (structured extraction per page); when
          absent, page.metadata keys are the projection. Sparse and honest:
          no schema -> no gate, no cost.

        Always returns a CrawlResult (never raises). The source_registry read
        is best-effort and LOGGED (pin V2: registry reuse is unverified — we
        log both the history decision and the dispatch outcome).
        """
        from .capabilities import CAPABILITIES, get_capability
        from .capture_store import slot_capture_offset

        t_start = time.monotonic()
        _emit = self._make_emitter(on_progress, session_id)
        # REQ-26 AC26.1–26.2 (T39): a structured goal rides the union. Text edges
        # (result shape, registry, crawl-only leg) render via str() — the string
        # protocol holds end to end; goal edges (_race_url, escalation,
        # follow-up dispatch) carry the object so guardrails survive.
        try:
            _query_text = query if isinstance(query, str) else str(query)
        except Exception:  # noqa: BLE001 — rendering never breaks dispatch
            _query_text = ""
        # REQ-21 AC21.2 (T31): strict 12-keyword allowlist on output_schema
        # BEFORE any fetch burns. Fail closed with an explicit CrawlResult
        # error (this funnel never raises) so a bad contract surfaces
        # instead of silently degrading to unprojected metadata.
        if output_schema is not None:
            try:
                from backend.vision.schema_validator import validate_schema
                _schema_errors = validate_schema(output_schema)
            except Exception:  # noqa: BLE001 — validator never breaks dispatch
                _schema_errors = []
            if _schema_errors:
                _msg = "; ".join(_schema_errors)
                logger.warning(
                    "[CrawlOrchestrator] schema_validation job_id=%s: %s",
                    job_id, _msg,
                )
                return CrawlResult(
                    query=_query_text,
                    pages=[],
                    duration_ms=int((time.monotonic() - t_start) * 1000),
                    crawled_at=datetime.now(timezone.utc).isoformat(),
                    error=f"schema_validation: {_msg}",
                )
        crawl_cap = get_capability("fetch.crawl")
        vision_avail = "fetch.vision" in CAPABILITIES
        # Session-318 (REQ-9 AC9.2): queue-time choke point — resolved seeds
        # checked against the turn visited set here too, so direct callers
        # and follow-up rounds are covered, not just research().
        _dq_excluded: set = set()
        try:
            _dq_excluded = {
                str(u).strip() for u in (excluded_urls or [])
                if isinstance(u, str) and str(u).strip().startswith("http")
            }
        except Exception:
            _dq_excluded = set()
        _urls_in = [u for u in (urls or []) if u not in _dq_excluded]
        _dq_n = len(urls or []) - len(_urls_in)
        if _dq_n:
            logger.info(
                "[CrawlOrchestrator] exclusion filtered %d/%d (turn-visited) "
                "job_id=%s where=queue",
                _dq_n, len(urls or []), job_id,
            )
            try:
                from backend.agent.write_counters import bump as _bump_q
                _bump_q("crawler.exclusions_applied", _dq_n)
            except Exception:
                pass
        capped = _urls_in[:max_pages]
        sem = asyncio.Semaphore(max(1, concurrency_limit))
        # Ordered slots preserve plan order in the result pages.
        slots: list[Optional[PageData]] = [None] * len(capped)
        # REQ-7 AC1 (T12): per-host semaphore — at most 2 concurrent fetches
        # against the same netloc regardless of the global batch limit. With
        # the global semaphore alone, three same-host URLs could run in
        # parallel and trip the site's rate limiter together — hence the
        # additional gate. Lazy-created per hostname; lives ONLY for this
        # dispatch call (no cross-run leakage, REQ-16 AC4 pattern).
        host_semaphores: dict[str, asyncio.Semaphore] = {}
        # REQ-7 AC2 (T12): consecutive 429/503 on one host trips a circuit
        # breaker for THIS RUN — the remaining same-host URLs are marked
        # rate_limited and never sent, so we never hammer. Cleared on exit;
        # the run ends, the host gets a fresh chance next run.
        host_429_streak: dict[str, int] = {}

        def _host_of(u: str) -> str:
            try:
                from urllib.parse import urlparse
                return (urlparse(u).netloc or u).lower()
            except Exception:  # noqa: BLE001 — fall through, never fail a fetch
                return u.lower()

        def _host_semaphore(host: str) -> asyncio.Semaphore:
            s = host_semaphores.get(host)
            if s is None:
                s = host_semaphores[host] = asyncio.Semaphore(2)
            return s

        def _outcome_transport_status(o) -> Optional[int]:
            """429/503 from the HAR block the capability recorded for this URL."""
            for e in (getattr(o, "har_entries", None) or []):
                try:
                    s = e.get("status")
                except Exception:
                    continue
                if s in (429, 503):
                    return s
            return None

        # T12c (REQ-18 AC1): light HAR entries for EVERY dispatched outcome so
        # `_apply_har_penalties` scores vision-visited domains on the same
        # basis as crawl domains (AC5: no forked paths).
        har_entries: list[dict] = []

        # REQ-2 AC2.3 (T29): early schema termination state. Empty when no
        # output_schema is declared — the gate then costs nothing per page.
        _required_fields: list[str] = []
        if output_schema:
            try:
                _req = (output_schema.get("required") or []) or list(
                    (output_schema.get("properties") or {}).keys()
                )
                _required_fields = [str(k) for k in _req if str(k).strip()]
            except Exception:  # noqa: BLE001 — a bad schema never breaks dispatch
                _required_fields = []
        _covered: dict[str, object] = {}
        _early_terminator: Optional["asyncio.Event"] = (
            asyncio.Event() if _required_fields else None
        )
        # REQ-8/REQ-11 (T27): when a schema journey runs, every usable page
        # feeds the StepFindingsAccumulator so the CrawlResult carries a
        # cross-source verification snapshot (the card's ✓/⚠ pills). Same
        # projection the AC2.3 gate uses — no second extract pass.
        # When this dispatch IS a follow-up dispatch (REQ-13 in-flight
        # adaptation), the parent's accumulator and coverage are SHARED so
        # follow-up pages extend the quorum of the run that triggered them.
        if _shared_findings is not None:
            _findings = _shared_findings
        elif _required_fields:
            try:
                from backend.agent.der_loop import StepFindingsAccumulator

                _findings = StepFindingsAccumulator(goal_fields=set(_required_fields))
            except Exception as exc:  # noqa: BLE001 — verification is best-effort
                logger.debug("[CrawlOrchestrator] findings accumulator unavailable: %s", exc)
                _findings = None
        else:
            _findings = None
        if _shared_covered is not None:
            _covered = _shared_covered

        async def _dispatch_one(idx: int, url: str) -> None:
            # Each URL owns a reserved block of the job's capture address space:
            # its crawl page takes offset+1 and any vision frames take offset+2
            # onward. Without this every single-URL fetch wrote <job>/1.html and
            # every vision session restarted at 1 on top of it — the first
            # 404'd pages 2..N, the second served ANOTHER url's bytes.
            # _base_offset continues the block for follow-up (REQ-13) child
            # dispatches sharing this job_id, so a child slot never collides
            # with a parent slot.
            _slot_offset = _base_offset + slot_capture_offset(idx)
            async with sem:  # AC1: bounded concurrency
                host = _host_of(url)
                # T12 / REQ-7 AC1: per-host run gate. Bypassed entirely if a
                # capability races fetch.vision — the overlay sees both crawl
                # and vision states, and per-host contract governance only
                # makes sense against a crawl that's actually dispatched.
                if host_429_streak.get(host, 0) >= 2:
                    # Two consecutive 429/503 on this host already — don't send;
                    # the breaker is the honest outcome, never a crawl.
                    logger.warning(
                        "[CrawlOrchestrator] host circuit open job_id=%s host=%s — marking "
                        "%s rate_limited (no fetch)", job_id, host, url,
                    )
                    slots[idx] = PageData(
                        url=url,
                        title="",
                        markdown="",
                        html=None,
                        metadata={"rate_limited": True, "host": host},
                        error="rate_limited",
                    )
                    return
                async with _host_semaphore(host):
                    history = await self._domain_failure_history(url, _query_text)
                    if history and vision_avail and _router_recovery_node(
                        history, race_rollback=True, step_id=f"race:{url}",
                    ) == "fetch.vision":
                        outcome = await self._race_url(
                            url, query, job_id, crawl_cap, _emit,
                            page_offset=_slot_offset,
                        )
                    else:
                        if history and not vision_avail:
                            logger.info(
                                "[CrawlOrchestrator] dispatch job_id=%s url=%s history=%s "
                                "vision=unavailable -> crawl only (REQ-10 AC3 degraded)",
                                job_id, url, history,
                            )
                        # Forward this run's emitter into the capability so per-URL
                        # CRAWLER_PAGE_FETCHED events reach the panel — the nav
                        # overlay's progressive animation advances on exactly those
                        # events. The inner orchestrator re-wraps it, so hand it a
                        # CrawlProgress consumer that feeds our (event, payload)
                        # emitter. Optional kwarg, tolerated if a capability
                        # implements only the bare 3-arg protocol (REQ-6 AC1).
                        # FILTER, don't forward wholesale. fetch_url runs a
                        # single-URL research of its own and emits its OWN lifecycle
                        # events — CRAWLER_STARTED with url_count=1, plus COMPLETE /
                        # OPEN_TAB / ERROR. Forwarding those let each per-URL fetch
                        # restart the outer run in the UI: the overlay reset to
                        # `loading` (killing the shutter animation and wiping the
                        # cursor), pagesDone reset to 0, and pagesTotal became 1 —
                        # which is what rendered as "3/1" live on 2026-08-11 09:18.
                        # The OUTER run owns the lifecycle; only the per-page signal
                        # belongs to it, renumbered to this URL's real slot.
                        #
                        # page_number/total are the OUTER run's counter and are
                        # rewritten here (the inner single-URL run only knows 1/1).
                        # capture_page is NOT rewritten: the inner run already
                        # reported the address it actually saved under, and
                        # overwriting it with the counter is exactly what made the
                        # iframe request /capture/<job>/3 when only /1 existed.
                        def _forward(p, _i=idx):
                            if p.event != "CRAWLER_PAGE_FETCHED":
                                return
                            payload = dict(p.payload or {})
                            payload["page_number"] = _i + 1
                            payload["total"] = len(capped)
                            _emit("CRAWLER_PAGE_FETCHED", payload)

                        outcome = await _call_fetch_one(
                            crawl_cap, url, _query_text, job_id,
                            on_progress=_forward, page_offset=_slot_offset,
                        )
                        # CONFLICT-FLAG (stash pop): stashed side called
                        # crawl_cap.fetch_one with wholesale forwarding + TypeError
                        # fallback; kept upstream filtered _forward (fixes "3/1"
                        # overlay reset + wrong capture slot of 2026-08-11).
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
                                outcome = await self._escalate_to_vision(
                                    url, query, job_id, outcome, _emit,
                                    page_offset=_slot_offset,
                                )
                # T12c (REQ-18 AC1): one HAR entry per vision/crawl outcome.
                # A walled URL records error="challenge" so the existing
                # _apply_har_penalties path penalizes the domain exactly like a
                # crawl-time challenge (no new penalty mechanism).
                wall = getattr(outcome, "wall", None)
                _cap_har = getattr(outcome, "har_entries", None) or []
                if _cap_har:
                    # The hybrid fetch tiers carry REAL per-request HAR evidence
                    # (status, response headers, body sha256) — prefer it over a
                    # synthesized light entry so penalties score actual transport
                    # facts (REQ-13).
                    har_entries.extend(_cap_har)
                else:
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
                # T12 (REQ-7 AC2): count consecutive 429/503 on this host. Two
                # in a row opens the breaker for the REST of this run's calls
                # on that host; the streak resets on any clean outcome.
                _st = _outcome_transport_status(outcome)
                if _st in (429, 503):
                    host_429_streak[host] = host_429_streak.get(host, 0) + 1
                    if host_429_streak[host] == 2:
                        logger.warning(
                            "[CrawlOrchestrator] host circuit OPEN job_id=%s host=%s "
                            "after 2 consecutive %s — remaining same-host URLs "
                            "will be rate_limited", job_id, host, _st,
                        )
                else:
                    host_429_streak[host] = 0
                if outcome.page is not None and outcome.verdict.usable:
                    # T12c (REQ-18 AC2): stamp provenance on the page so the
                    # document-store path (which consumes PageData) knows the
                    # content came from vision vs crawl.
                    if getattr(outcome, "capability", "") == "fetch.vision":
                        outcome.page.metadata = dict(outcome.page.metadata or {})
                        outcome.page.metadata["origin"] = "vision"
                    slots[idx] = outcome.page
                    # REQ-2 AC2.3 (T29): schema completeness is re-evaluated
                    # after EVERY page outcome. The moment every required field
                    # holds a non-None value the batch signals early terminate;
                    # the terminator task below cancels the rest of the queue.
                    if _required_fields:
                        try:
                            _payload = (
                                extract(outcome.page)
                                if extract is not None
                                else dict(outcome.page.metadata or {})
                            )
                        except Exception:  # noqa: BLE001 — projection never fails the page
                            _payload = None
                        # REQ-25 AC25.1–25.3 (T38): ONE self-correction pass on the
                        # extracted payload. Only when BOTH schema and hook are
                        # declared (AC25.4: the unprojected path costs nothing).
                        # The error is stated on page.metadata so hooks keep their
                        # 1-arg shape; still-invalid accepts-and-flags on the page.
                        if (
                            output_schema is not None
                            and extract is not None
                            and isinstance(_payload, dict)
                        ):
                            try:
                                from backend.vision.schema_validator import (
                                    validate_instance as _validate_instance,
                                )
                                _violations = _validate_instance(
                                    _payload, output_schema
                                )
                            except Exception:  # noqa: BLE001 — validator never breaks dispatch
                                _violations = []
                            if _violations:
                                try:
                                    outcome.page.metadata = dict(
                                        outcome.page.metadata or {}
                                    )
                                    outcome.page.metadata["_validation_error"] = (
                                        "; ".join(_violations)
                                    )
                                    _payload = extract(outcome.page)
                                except Exception:  # noqa: BLE001 — re-extract never fails the page
                                    _payload = None
                                if isinstance(_payload, dict):
                                    try:
                                        _violations = _validate_instance(
                                            _payload, output_schema
                                        )
                                    except Exception:  # noqa: BLE001
                                        _violations = []
                                else:
                                    _violations = []
                                try:
                                    outcome.page.metadata = dict(
                                        outcome.page.metadata or {}
                                    )
                                    outcome.page.metadata.pop(
                                        "_validation_error", None
                                    )
                                    if _violations:
                                        outcome.page.metadata["unvalidated"] = True
                                        outcome.page.metadata["_validation_errors"] = (
                                            list(_violations)
                                        )
                                        logger.warning(
                                            "[CrawlOrchestrator] extract accept-and-flag "
                                            "job_id=%s url=%s errors=%s",
                                            job_id, url, "; ".join(_violations),
                                        )
                                    else:
                                        logger.info(
                                            "[CrawlOrchestrator] extract self-corrected "
                                            "job_id=%s url=%s",
                                            job_id, url,
                                        )
                                except Exception:  # noqa: BLE001 — flagging never fails the page
                                    pass
                    else:
                        _payload = None
                    # REQ-8 AC1 strict projection: only schema fields reach the
                    # accumulator; the page's raw body never does.
                    if _findings is not None and isinstance(_payload, dict):
                        _findings.add(outcome.page.url, _payload)
                    if _required_fields and _early_terminator is not None and not _early_terminator.is_set():
                        if isinstance(_payload, dict):
                            for _k in _required_fields:
                                if _payload.get(_k) is not None and _k not in _covered:
                                    _covered[_k] = _payload[_k]
                        if all(k in _covered for k in _required_fields):
                            _early_terminator.set()
                            logger.info(
                                "[CrawlOrchestrator] dispatch early terminate job_id=%s "
                                "fields=%s (AC2.3)", job_id, sorted(_covered),
                            )
                else:
                    # T14 (REQ-13): a wall in the outcome (CAPTCHA/login/paywall
                    # from fetch.vision) parks the source — one question per
                    # domain per run (AC6) — and the run CONTINUES with the
                    # remaining URLs (AC2). Synthesis later lists parked sources
                    # (AC4) instead of blocking on them.
                    if wall is not None:
                        self._park_source(job_id, url, wall.value, _emit)
                    elif outcome.verdict.reason == UsabilityReason.CHALLENGE:
                        # A wall found by the CRAWL, not by vision. This used to
                        # be invisible here because a challenge always escalated
                        # and vision reported the wall instead. Vision no longer
                        # takes challenges, so without this a walled source would
                        # be silently dropped — the run would simply have fewer
                        # citations and never say why (REQ-13 AC4 / REQ-15).
                        self._park_source(job_id, url, "challenge", _emit)
                    elif outcome.verdict.reason == UsabilityReason.BLOCKED:
                        # Bare 401/403 (spec A2): parked AND recorded by
                        # _park_source (record_wall) so the next run skips the
                        # domain; Tier 2 never ran for it.
                        self._park_source(job_id, url, "blocked", _emit)
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
        _run_deadline = time.monotonic() + (_RUN_BUDGET_MS / 1000.0)

        async def _dispatch_with_defer_log(idx: int, url: str) -> None:
            nonlocal queued_count
            # Session 247 (FAULTLINE read-side): consult the wall ledger BEFORE
            # spending a round-trip. A domain that recently proved itself
            # walled (challenge/bot-block — retryable:no by label definition)
            # is skipped, not re-fetched. Recorded as parked so the park
            # summary stays honest about what was NOT read; no user question
            # is raised (one was already raised when the wall was first hit).
            try:
                from urllib.parse import urlparse as _up3

                _dom = _up3(url).netloc or url
                from backend.agent.tool_errors import is_walled

                if is_walled(_dom):
                    logger.info(
                        "[CrawlOrchestrator] FAULTLINE skip job_id=%s url=%s "
                        "domain=%s reason=walled_recent (retryable:no, ledger TTL)",
                        job_id, url[:100], _dom,
                    )
                    self._parks_by_job.setdefault(job_id, []).append((_dom, "walled_recent"))
                    return
            except Exception:
                pass  # ledger read must never break dispatch (REQ-10 AC4)
            if sem.locked():
                queued_count += 1
                logger.info(
                    "[CrawlOrchestrator] dispatch queue job_id=%s url=%s queued=%d "
                    "(REQ-16 deferral, not dropped)",
                    job_id, url, queued_count,
                )
            # Enforce the run ceiling on EVERY url, with wait_for so it actually
            # interrupts rather than being noticed after the fact. A url that
            # runs out of budget is parked and SAID so — an unread source has to
            # be visible, not quietly missing from the citation list (REQ-15).
            _left = _run_deadline - time.monotonic()
            if _left <= 0:
                logger.info(
                    "[CrawlOrchestrator] run budget spent job_id=%s url=%s — not "
                    "started (ceiling %dms)", job_id, url, _RUN_BUDGET_MS,
                )
                self._park_source(job_id, url, "run_budget", _emit)
                return
            try:
                await asyncio.wait_for(_dispatch_one(idx, url), timeout=_left)
            except asyncio.TimeoutError:
                logger.info(
                    "[CrawlOrchestrator] run budget spent job_id=%s url=%s — "
                    "cut off after %.1fs (ceiling %dms)",
                    job_id, url, _left, _RUN_BUDGET_MS,
                )
                self._park_source(job_id, url, "run_budget", _emit)

        tasks = [
            asyncio.create_task(_dispatch_with_defer_log(i, u))
            for i, u in enumerate(capped)
        ]
        # REQ-2 AC2.3: the terminator watches for schema satisfaction and
        # cancels UNFINISHED per-URL tasks. Cancellation of an in-flight
        # fetch surfaces as CancelledError inside the task — asyncio.gather
        # with return_exceptions=True collects it (it is NOT an Exception
        # subclass and never lands in the failure log below).
        async def _terminate_on_satisfied() -> None:
            if _early_terminator is None:
                return
            await _early_terminator.wait()
            for t in tasks:
                if not t.done():
                    t.cancel()

        _terminator = asyncio.create_task(_terminate_on_satisfied()) if _early_terminator else None
        # Quorum wait (spec A3, D4): FIRST_COMPLETED loop instead of one gather.
        # Usable-ness is the single predicate (page_is_usable) over the filled slots.
        _cancelled_enough: list[str] = []
        _pending = set(tasks)
        _quorum_at: Optional[float] = None
        while _pending:
            _wait_s = None if _quorum_at is None else max(0.0, _quorum_at - time.monotonic())
            _done, _pending = await asyncio.wait(
                _pending, timeout=_wait_s, return_when=asyncio.FIRST_COMPLETED,
            )
            if not _pending or _required_fields or min_pages < 1:
                continue
            if _quorum_at is None:
                _usable_n = sum(1 for p in slots if p is not None and page_is_usable(p).usable)
                if _usable_n >= min_pages:
                    _quorum_at = time.monotonic() + _QUORUM_GRACE_S
            elif time.monotonic() >= _quorum_at:
                break
        if _pending:
            for _t in _pending:
                _t.cancel()
                _cu = capped[tasks.index(_t)]
                _cancelled_enough.append(_cu)
                logger.info(
                    "[CrawlOrchestrator] cancelled_enough job_id=%s url=%s — %d usable "
                    "page(s) in (min_pages=%d), grace %.1fs spent (not parked, not a wall)",
                    job_id, _cu[:100], sum(
                        1 for p in slots if p is not None and page_is_usable(p).usable
                    ), min_pages, _QUORUM_GRACE_S,
                )
        results = await asyncio.gather(*tasks, return_exceptions=True)
        if _terminator is not None:
            _terminator.cancel()
            try:
                await _terminator
            except BaseException:  # noqa: BLE001 — CancelledError
                pass
        for i, exc in enumerate(results):
            if isinstance(exc, Exception):
                logger.warning(
                    "[CrawlOrchestrator] dispatch url=%s failed: %s (REQ-10)",
                    capped[i], exc,
                )

        pages = [p for p in slots if p is not None]
        # T12c assembled har_entries for every dispatched outcome and then
        # returned them WITHOUT ever writing the file. _write_har_file is called
        # from crawl_runner (batch/fallback) and from inside the worker, neither
        # of which the per-URL dispatch path goes through — so the live path
        # produced no HAR at all. Verified 2026-08-11: job
        # 40e4e52342334e28827bbeea8418df25 crawled five URLs and data/har/ held
        # nothing newer than a probe from two days earlier, leaving REQ-13/REQ-18
        # evidence unrecorded and every document's har_path null.
        _har_path = None
        if har_entries and job_id:
            try:
                from .crawler_engine import _write_har_file

                _har_path = _write_har_file(job_id, har_entries)
                logger.info(
                    "[CrawlOrchestrator] HAR written job_id=%s entries=%d path=%s",
                    job_id, len(har_entries), _har_path,
                )
            except Exception as exc:  # noqa: BLE001 — evidence must not fail the crawl
                logger.warning("[CrawlOrchestrator] HAR write failed job_id=%s: %s", job_id, exc)
        _emit("CRAWLER_PHASE", {"phase": "extracting", "phase_sequence": PHASE_EXTRACTING})
        logger.info(
            "[CrawlOrchestrator] dispatch job_id=%s urls=%d usable=%d concurrency=%d (REQ-10)",
            job_id, len(capped), len(pages), concurrency_limit,
        )
        # REQ-13 AC13.3 (T30): in-flight dynamic query adaptation. When a
        # schema journey ended with required fields STILL uncovered and the
        # caller supplied a Brain hook (`on_missing_fields`), the Brain
        # synthesizes targeted follow-up URLs and they're fetched IN THE SAME
        # RUN — the active DAG grows; nothing restarts, nothing replans.
        # Bounded: at most one follow-up round per depth level, and the child
        # dispatch shares the parent's accumulator + coverage so its pages
        # extend the quorum rather than reset it.
        if (
            on_missing_fields is not None
            and _required_fields
            and _followup_depth == 0
        ):
            _missing = [k for k in _required_fields if k not in _covered]
            if _missing:
                try:
                    _more = [u for u in (on_missing_fields(list(_missing)) or [])
                             if isinstance(u, str) and u.strip()]
                except Exception as exc:  # noqa: BLE001 — adaptation never kills the run
                    logger.info(
                        "[CrawlOrchestrator] follow-up synthesis failed job_id=%s: %s",
                        job_id, exc,
                    )
                    _more = []
                # Deduplicate against URLs already attempted in this run;
                # the same normalized URL must never be re-fetched once.
                seen = {u.strip() for u in capped}
                fresh: list[str] = []
                for u in _more:
                    u2 = u.strip()
                    if u2 not in seen and u2 not in fresh:
                        fresh.append(u2)
                if fresh:
                    logger.info(
                        "[CrawlOrchestrator] in-flight query adaptation job_id=%s missing=%s followups=%d (REQ-13 AC3)",
                        job_id, _missing, len(fresh),
                    )
                    _child_depth = _followup_depth + 1
                    _follow = await self.dispatch_urls(
                        fresh[: max(1, len(fresh))],
                        query=query,
                        job_id=job_id,
                        session_id=session_id,
                        on_progress=on_progress,
                        max_pages=max(max_pages, len(fresh)),
                        timeout_s=timeout_s,
                        concurrency_limit=concurrency_limit,
                        output_schema=output_schema,
                        extract=extract,
                        on_missing_fields=on_missing_fields,
                        _followup_depth=_child_depth,
                        _shared_findings=_findings,
                        _shared_covered=_covered,
                        _base_offset=_base_offset + slot_capture_offset(len(capped)),
                        excluded_urls=list(_dq_excluded),
                    )
                    pages = pages + [p for p in _follow.pages if isinstance(p, PageData)]
                    # Follow-up pages joined the accumulator; slots for the
                    # brief persist path live on _follow.har_entries. Merge
                    # (harmless when empty) so _apply_har_penalties sees them.
                    har_entries = har_entries + list(_follow.har_entries or [])

        # Session-318 T17 (REQ-10 AC10.2): collect per-URL deaths before
        # the result is built (slots/exc/results all in scope here).
        _dead_urls: list = []
        try:
            for _di, _du in enumerate(capped or []):
                _slot = slots[_di] if _di < len(slots or []) else None
                _exc = results[_di] if _di < len(results or []) else None
                _dead = _slot is None or isinstance(_exc, Exception)
                if _du in _cancelled_enough:
                    _dead = False  # cut by the quorum, never attempted to the end
                if not _dead and _slot is not None:
                    try:
                        _dead = not page_is_usable(_slot).usable
                    except Exception:
                        _dead = False
                if _dead and _du and _du not in _dead_urls:
                    _dead_urls.append(_du)
        except Exception:
            _dead_urls = []
        # REQ-8/REQ-11 (T27): the run's cross-source verification snapshot
        # rides the result when a schema journey ran. Follow-up child runs
        # share the parent's accumulator and do NOT snapshot their own (the
        # parent's commit point is below — a child snapshot would read the
        # accumulator mid-merge).
        verification: Optional[dict] = None
        if _findings is not None and _shared_findings is None:
            try:
                verification = _findings.snapshot()
            except Exception as exc:  # noqa: BLE001 — best-effort, logged
                logger.debug("[CrawlOrchestrator] findings snapshot failed job_id=%s: %s", job_id, exc)
        return CrawlResult(
            query=_query_text,
            pages=pages,
            duration_ms=int((time.monotonic() - t_start) * 1000),
            crawled_at=datetime.now(timezone.utc).isoformat(),
            # Session-318 T17 (REQ-10 AC10.2): dead-address memory. Per-URL
            # outcomes (slot None, exception, unusable body) land here even
            # when zero usable pages come back — the Attempted line
            # downstream only covers pages that produced PageData.
            dead_urls=_dead_urls,
            # T12c (REQ-18 AC1): vision/crawl HAR entries ride the same
            # CrawlResult field the batch path uses, so research()'s
            # _apply_har_penalties + _learn_from_crawl consume them unchanged.
            har_entries=har_entries,
            har_path=_har_path,
            verification=verification,
            cancelled_enough=list(_cancelled_enough),
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
        # Session 247 (FAULTLINE read-side): a non-retryable wall is a typed
        # lesson, not just a per-run note. Record it domain-keyed so LATER
        # jobs (new run_ids every round) skip instead of re-losing the
        # round-trip — this is what stopped spacedaily.com being re-fetched
        # 17 minutes after it proved itself walled.
        try:
            if wall_kind in ("challenge", "walled", "bot_block", "blocked"):
                from urllib.parse import urlparse as _up2
                from backend.agent.tool_errors import record_wall

                record_wall(_up2(url).netloc or url)
        except Exception:
            pass
        # Session 244: ledger the park for this run so research() can attach a
        # structured park_summary to the CrawlResult (DAG awareness).
        try:
            from urllib.parse import urlparse as _up
            self._parks_by_job.setdefault(run_id, []).append(
                (_up(url).netloc or url, wall_kind)
            )
        except Exception:
            pass
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
            # Session 248 POLICY CHANGE (user direction, pin_587a3e612558
            # item #7): a run_budget wall is OUR budget expiring, not a wall
            # the user can help with — the agent should PERSIST toward its
            # goal, not interrupt with "want me to keep trying?". Run-budget
            # parks are therefore SILENT: still ledgered, still emitted as
            # CRAWLER_SOURCE_PARKED (the sources list stays honest), still
            # folded into park_summary — but NO QuestionCard. Challenge walls
            # (bot blocks a user could solve, e.g. by logging in) keep the ask.
            if wall_kind == "run_budget":
                try:
                    source = registry.park(run_id=run_id, url=url, wall_kind=wall_kind)
                    logger.info(
                        "[CrawlOrchestrator] silent park job_id=%s url=%s "
                        "wall=run_budget (policy: no user question for "
                        "self-inflicted budget walls)",
                        run_id, url,
                    )
                except Exception as _park_exc:
                    logger.info(
                        "[CrawlOrchestrator] silent park failed url=%s: %s",
                        url, _park_exc,
                    )
                    return
            else:
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

    async def _maybe_prewarm_browser_for_discovery(self, job_id: str = "") -> None:
        """Session-326: warm the pooled browser at plan time, conditionally.

        Fires only when the live brain lacks sight (owner choice): a seeing
        brain already covers the vision-fallback read, so warming Chromium
        would spend a launch for nothing. Undetermined => warm (safe
        direction). Acquires then releases at once — the browser stays warm
        under the idle watchdog without pinning a lease. Never raises."""
        try:
            _has_sight = False
            try:
                from backend.agent import get_agent_kernel as _gak326
                from backend.agent.inference.router import (
                    supports_vision as _sv326,
                )
                _k326 = _gak326("crawl_prewarm")
                _router326 = getattr(_k326, "_router", None)
                if _router326 is not None and hasattr(_router326, "resolve"):
                    try:
                        _inst326 = _router326.resolve("reasoning")
                    except Exception:
                        _inst326 = None
                    if _inst326 is not None:
                        _has_sight = bool(_sv326(_inst326))
            except Exception:
                _has_sight = False
            if _has_sight:
                logger.info(
                    "[CrawlOrchestrator] brain sees — skipping browser prewarm job_id=%s",
                    job_id,
                )
                return
            from backend.vision import browser_pool as _bp326
            try:
                # Session-326 hardening: a wedged Chromium launch must never
                # pin this background task (or the pool start lock) forever —
                # fail open and let discovery cold-start on demand instead.
                _b326, _lease326 = await asyncio.wait_for(
                    _bp326.acquire_browser(), timeout=90.0
                )
            except Exception as _pxc326:
                logger.info(
                    "[CrawlOrchestrator] browser prewarm failed open job_id=%s: %s",
                    job_id,
                    _pxc326,
                )
                return
            try:
                _lease326.release()
            except Exception:
                pass
            logger.info(
                "[CrawlOrchestrator] browser prewarmed at plan job_id=%s (brain lacks sight)",
                job_id,
            )
        except Exception:
            pass

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
    async def _vision_fetch(vision_cap, url: str, goal: str | GoalAnatomy, job_id: str, _emit, page_offset: int = 0, escalated: bool = False):
        """Call fetch.vision, passing the REQ-11 AC4 action emitter when the
        capability supports it. Capabilities implementing only the bare
        3-positional-arg protocol are called unchanged (REQ-6 AC1).

        ``page_offset`` is this URL's reserved block of the job's capture address
        space. A vision session publishes MANY frames for ONE url; every session
        used to start at page 1 under the shared job_id, so URL 4's frames
        overwrote URL 1's captured page and the panel served the wrong bytes.

        ``escalated`` (specs/vision-browser-stage REQ-8): stamped onto every
        action payload so the frontend's "notice" beat fires only when vision
        took over from a FAILED crawl — a raced session is not an escalation.
        """
        def _on_action(payload: dict) -> None:
            payload["escalated"] = escalated
            _emit("CRAWLER_VISION_ACTION", payload)

        try:
            return await vision_cap.fetch_one(
                url, goal, job_id, on_action=_on_action, page_offset=page_offset,
            )
        except TypeError:
            # Capability does not accept on_action — protocol-only implementation.
            return await vision_cap.fetch_one(url, goal, job_id)

    async def _escalate_to_vision(self, url: str, query: str | GoalAnatomy, job_id: str, crawl_outcome, _emit, page_offset: int = 0) -> "FetchOutcome":
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
        _t_esc_start = time.monotonic()
        vision_outcome = await self._vision_fetch(
            vision_cap, url, query, job_id, _emit, page_offset=page_offset,
            escalated=True,
        )
        # REQ-9 AC1/AC4 (specs/dag-node-execution-model, T18): every recovery
        # node execution is logged with node name + typed reason + duration +
        # task identifier, so the executed graph is reconstructable from the
        # log alone. Off the critical path — logging failure never propagates.
        try:
            from backend.agent.nodes.telemetry import log_node_execution

            log_node_execution(
                task_id=job_id,
                node="fetch.vision",
                status=(
                    "ok"
                    if (vision_outcome.page is not None and vision_outcome.verdict.usable)
                    else vision_outcome.verdict.reason.value
                ),
                reason=reason,
                duration_ms=int((time.monotonic() - _t_esc_start) * 1000),
            )
        except Exception:  # noqa: BLE001 — REQ-9 AC5
            pass
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

    async def _race_url(self, url: str, goal: str | GoalAnatomy, job_id: str, crawl_cap, _emit, page_offset: int = 0) -> "FetchOutcome":
        """Race fetch.crawl vs fetch.vision; first usable wins (REQ-10 AC3/AC5).

        Loser is cancelled. Both usable -> crawl wins (cheaper), race logged.

        REQ-26 (T39): the crawl leg takes rendered text (no guardrail consumer
        there); the vision leg takes the object so its REQ-20 gate sees the
        goal's own guardrails.
        """
        from .capabilities import FetchOutcome, get_capability

        try:
            _goal_text = goal if isinstance(goal, str) else str(goal)
        except Exception:  # noqa: BLE001 — rendering never breaks dispatch
            _goal_text = ""
        vision_cap = get_capability("fetch.vision")
        t0 = time.monotonic()
        # Both racers write into this URL's reserved capture block: crawl takes
        # offset+1, vision frames take offset+2 onward, so the loser can never
        # clobber the winner's bytes or a neighbouring URL's.
        crawl_task = asyncio.create_task(
            _call_fetch_one(crawl_cap, url, _goal_text, job_id, page_offset=page_offset)
        )
        # REQ-11 AC4: thread a per-action emitter into the vision capability so
        # each browser action reaches the panel. Passed only when the capability
        # accepts it, so a capability implementing the bare 3-arg protocol still
        # works (REQ-6 AC1).
        vision_task = asyncio.create_task(
            self._vision_fetch(vision_cap, url, goal, job_id, _emit, page_offset=page_offset)
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
    def _exclude_visited(self, urls, excluded, job_id, where):
        """Session-318 (REQ-9 AC9.1/AC9.2): filter resolved seeds against
        the turn visited set BEFORE paying for the fetch. Callers already
        treat an empty seed set as honest-empty — never a forced crawl.
        Compares NORMALIZED addresses (tool_envelope.normalize_url) so a
        trailing slash or fragment drift cannot re-open a visited page.
        Never raises."""
        try:
            from backend.agent.tool_envelope import normalize_url as _norm_url
            _in = list(urls or [])
            _excl_norm = set()
            try:
                for _e in (excluded or set()):
                    _n = _norm_url(str(_e))
                    if _n:
                        _excl_norm.add(_n)
            except Exception:
                _excl_norm = set()
            _fresh = [u for u in _in if _norm_url(str(u)) not in _excl_norm]
            _n = len(_in) - len(_fresh)
            if _n:
                logger.info(
                    "[CrawlOrchestrator] exclusion filtered %d/%d "
                    "(turn-visited) job_id=%s where=%s",
                    _n, len(_in), job_id, where,
                )
                try:
                    from backend.agent.write_counters import bump as _bump_excl
                    _bump_excl("crawler.exclusions_applied", _n)
                except Exception:
                    pass
            return _fresh
        except Exception:
            return list(urls or [])

    async def _plan(self, query: str) -> CrawlPlan:
        planner = self._planner or get_crawl_planner()
        try:
            return await planner.plan(query)
        except Exception as exc:
            logger.warning("[CrawlOrchestrator] planner failed: %s", exc)
            return CrawlPlan(urls=[], instructions="", result_type="mixed", title=query[:60])

    async def _same_site_hop(
        self, query: str, ok_pages: list[PageData], kept: list, *, backend, plan,
        _emit, job_id: str, excluded: set, max_pages: int,
    ) -> list[PageData]:
        """Fetch the most goal-relevant same-site links of the hosts whose pages
        produced the kept passages: one hop (depth 1), at most ``_HOP_MAX_LINKS``
        pages, ``_HOP_BUDGET_S`` seconds, through the same fetch backend. Returns the
        usable new pages; never raises (a failed hop is just no extra pages)."""
        try:
            from urllib.parse import urlparse

            from .site_links import extract_links, rank_same_site

            relevant_hosts = {(urlparse(p.url).netloc or "").lower() for p in kept}
            seen = {p.url for p in ok_pages} | set(excluded)
            ranked: list[str] = []
            for page in ok_pages:
                if (urlparse(page.url).netloc or "").lower() not in relevant_hosts:
                    continue
                links = extract_links(page.markdown or "", page.html or "", page.url)
                for url in rank_same_site(links, page.url, query, exclude=seen | set(ranked),
                                          limit=_HOP_MAX_LINKS):
                    ranked.append(url)
            urls = ranked[:_HOP_MAX_LINKS]
            if not urls:
                return []
            logger.info(
                "[CrawlOrchestrator] same-site hop job_id=%s kept=%d urls=%d",
                job_id, len(kept), len(urls),
            )
            _emit("CRAWLER_PROGRESS", {"stage": "exploring", "message": "Reading related pages…"})
            hop = await asyncio.wait_for(
                backend.fetch(
                    query=query, urls=urls, instructions=plan.instructions,
                    max_pages=min(max_pages, _HOP_MAX_LINKS),
                    on_page_done=self._page_emitter(_emit, f"{job_id}_hop"),
                    timeout_s=_HOP_BUDGET_S, job_id=f"{job_id}_hop",
                ),
                _HOP_BUDGET_S + 2.0,
            )
            return [p for p in hop.pages if page_is_usable(p).usable]
        except Exception as exc:  # noqa: BLE001 - the hop is a bonus, never a failure
            logger.info("[CrawlOrchestrator] same-site hop skipped job_id=%s: %s", job_id, exc)
            return []

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

        # Only await what THIS loop owns.
        #
        # _emit is a SYNC callback invoked from wherever the crawl happens to
        # be — including worker threads running their own event loop — and its
        # asyncio.ensure_future() binds each task to the loop live at that
        # moment. So this list can hold tasks from several loops, and
        # asyncio.gather() refuses a future from a foreign loop:
        #   ValueError: The future belongs to a different loop than the one
        #               specified as the loop argument
        # which aborted the whole crawl at its final drain, after 7.7 minutes
        # of successful work, and surfaced to the user as
        # "[crawler_query] research failed".
        #
        # A foreign-loop task is not lost: it runs and completes on its own
        # loop. It simply cannot be awaited from here, so it is counted and
        # skipped rather than allowed to raise.
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            return

        mine, foreign = [], 0
        for task in pending:
            try:
                if task.get_loop() is current:
                    mine.append(task)
                else:
                    foreign += 1
            except Exception:  # noqa: BLE001 — not a future we can inspect
                foreign += 1

        if foreign:
            logger.debug(
                "[orchestrator] drain skipped %d log task(s) owned by another loop",
                foreign,
            )
        if mine:
            await asyncio.gather(*mine, return_exceptions=True)

    def _page_emitter(self, emit, job_id: str = ""):
        # REQ-11 (T14): SINGLE emission authority — the same (job_id,
        # page_number) must never emit twice. The crawl4ai worker path and the
        # plain-HTTP fallback (crawl_runner) can both reach this callback for
        # the same page (worker times out -> fallback re-fetches the same
        # URLs), which used to duplicate CRAWLER_PAGE_FETCHED and made the
        # browser panel show the page twice. First emitter wins; later
        # duplicates are dropped (the bytes are identical for the same page).
        _seen: set = set()

        def _cb(url, page_number, total, title="", snippet="", capture_page=None):
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
            # The capture ADDRESS is not the UI counter. page_number counts the
            # outer run's progress ("reading 3 of 5"); capture_page is where the
            # bytes live. They diverge under per-URL dispatch (every single-URL
            # crawl numbers its only page 1) and under vision escalation (many
            # frames for one URL). Falling back to page_number preserves the
            # batch path exactly, where the two genuinely coincide.
            _addr = int(capture_page) if capture_page is not None else int(page_number)
            # A challenged page is DELIBERATELY not persisted (REQ-4 AC2 — the
            # interstitial's boilerplate must not poison replay), so an iframe
            # pointed at it 404s BY DESIGN. Tell the panel whether bytes exist so
            # it can render a "blocked by the site" state instead of a dead
            # frame. The save always precedes this callback, so the check is
            # authoritative; it is one stat() off the hot path.
            try:
                from .capture_store import get_capture_store

                _has_capture = get_capture_store().has(job_id, _addr)
            except Exception:  # noqa: BLE001 — never fail a progress emit
                _has_capture = False
            emit("CRAWLER_PAGE_FETCHED", {
                "url": url, "page_number": page_number, "total": total,
                "host": _host(url),
                "title": title,
                "snippet": snippet,
                # T5 (REQ-1 AC1): job_id + capture_page let the in-app browser
                # panel build the replay URL /api/browser/capture/{job_id}/{capture_page}.
                "job_id": job_id,
                "capture_page": _addr,
                "capture_available": _has_capture,
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
            cancelled_enough=list(getattr(fetched, "cancelled_enough", []) or []),
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
