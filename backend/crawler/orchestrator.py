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

logger = logging.getLogger(__name__)

_DEFAULT_MAX_PAGES = int(os.environ.get("CRAWL4AI_MAX_PAGES", "5"))
_DEFAULT_MIN_PAGES = int(os.environ.get("CRAWL_MIN_PAGES", "3"))
_DEFAULT_TIMEOUT_S = float(os.environ.get("CRAWL_SUBPROCESS_TIMEOUT_S", "90"))


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
        if not plan.urls:
            _emit("CRAWLER_ERROR", {"message": "no candidate urls"})
            return self._empty(query, t_start, "no candidate urls")

        _emit("CRAWLER_STARTED", {"query": query, "url_count": len(plan.urls), "session_id": session_id})
        # REQ-4 AC1/AC3: emit phase transition — moving into search.
        _emit("CRAWLER_PHASE", {"phase": "searching", "phase_sequence": PHASE_SEARCHING})

        # 2) FETCH (REQ-3) via swappable backend (REQ-17 AC4)
        backend = self._backend_override or _BACKENDS[mode]()
        fetched: CrawlResult = await backend.fetch(
            query=query, urls=plan.urls, instructions=plan.instructions,
            max_pages=max_pages,
            on_page_done=self._page_emitter(_emit),
            timeout_s=timeout_s,
            job_id=job_id,
        )
        # Wave 0 (REQ-14/REQ-18): down-weight dead/stale domains from HAR evidence.
        self._apply_har_penalties(fetched, query)
        # Wave 0 (REQ-18/REQ-19): register successful URLs so future crawls for
        # this topic seed from learned knowledge (memory-first).
        await self._learn_from_crawl(fetched, query)

        # W3 (T15-T20): Exa retry — if the first batch returned no usable pages,
        # rewrite the query to be broader and retry once.
        ok_pages = [p for p in fetched.pages if not p.error]
        if (fetched.error or not ok_pages) and not getattr(fetched, "_retried", False):
            broader_query = _broaden_query(query)
            logger.info(
                "[CrawlOrchestrator] Exa retry query=%s → %s pages=%d",
                query[:60], broader_query[:60], len(ok_pages),
            )
            _emit("CRAWLER_PROGRESS", {"stage": "narrowing", "message": "Narrowing search…"})
            _emit("CRAWLER_PHASE", {"phase": "searching", "phase_sequence": PHASE_SEARCHING})
            # Re-plan with broader query
            plan = await self._plan(broader_query)
            if plan.urls:
                fetched = await backend.fetch(
                    query=broader_query, urls=plan.urls, instructions=plan.instructions,
                    max_pages=max_pages,
                    on_page_done=self._page_emitter(_emit),
                    timeout_s=timeout_s,
                    job_id=f"{job_id}_retry",
                )
                setattr(fetched, "_retried", True)
                self._apply_har_penalties(fetched, broader_query)
                await self._learn_from_crawl(fetched, broader_query)

        if fetched.error:
            _emit("CRAWLER_ERROR", {"message": fetched.error})
            return self._finalize(fetched, query, t_start, error=fetched.error)

        ok_pages = [p for p in fetched.pages if not p.error]
        if not ok_pages:
            _emit("CRAWLER_ERROR", {"message": "all pages failed to fetch"})
            return self._finalize(fetched, query, t_start, error="all pages failed to fetch")

        # REQ-4 AC1/AC3: emit phase transition — moving into extraction.
        _emit("CRAWLER_PHASE", {"phase": "extracting", "phase_sequence": PHASE_EXTRACTING})

        # 3) PASSAGE-SPLIT (REQ-4)
        passages = self._split_passages(ok_pages)

        # 4) CREDIBILITY-SCORE (REQ-5) — module implemented in T2
        from .credibility import score_credibility
        cred_map = score_credibility(ok_pages, passages)

        # 5) PASSAGE-RERANK (REQ-7) — module implemented in T3
        from .rerank import rerank_passages
        passages = rerank_passages(passages, query, cred_map)

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
        })
        # REQ-29/30: signal completion so a reconnecting client (SSE/WS) knows
        # the job finished and can fetch the result without re-crawling.
        _emit("CRAWLER_COMPLETE", {
            "query": query,
            "summary": dashboard_data.get("summary", ""),
            "cited_markdown": cited_markdown,
            "credibility_top_score": cred_map.top_score,
        })
        return result

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

        def _emit(event: str, payload: dict) -> None:
            if log is not None:
                try:
                    asyncio.ensure_future(log.append(session_id, event, payload))
                except Exception:  # noqa: BLE001
                    pass  # never block the funnel on a log write failure
            if on_progress is not None:
                _safe(on_progress, CrawlProgress(event, payload))

        return _emit

    def _page_emitter(self, emit):
        def _cb(url, page_number, total, title="", snippet=""):
            emit("CRAWLER_PAGE_FETCHED", {
                "url": url, "page_number": page_number, "total": total,
                "host": _host(url),
                "title": title,
                "snippet": snippet,
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
            if not is_dead:
                continue
            try:
                reg.penalize_url(e.get("url", ""), topics=[query])
                logger.info(
                    "SRC PENALIZE url=%s status=%s query=%s", e.get("url"), status, query
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("[CrawlOrchestrator] penalize_url failed: %s", exc)

    async def _learn_from_crawl(self, fetched: CrawlResult, query: str) -> None:
        """Register successfully-crawled URLs into SourceRegistry for this topic
        (REQ-18/REQ-19). Reuses the existing ``learn()`` — no new method. The
        more the agent researches, the smarter (and cheaper) later crawls become
        because ``resolve()`` then seeds from updated knowledge. Never raises.
        """
        ok_pages = [p for p in getattr(fetched, "pages", []) if not p.error]
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
