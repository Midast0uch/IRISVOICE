"""Crawl job registry for background completion + command routing (REQ-29, REQ-31).

When crawler_query runs in background mode (REQ-29 AC1) the result is stored
here keyed by job_id so a reconnecting client can fetch it via HTTP GET
/api/crawl/result/{job_id} instead of re-running the crawl. The registry also
tracks cancellation so an HTTP POST /api/crawl/command can stop an in-flight
job (REQ-31 AC6).

Bounded: completed results are evicted after a TTL so memory does not grow
unbounded (quality-check requirement).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_RESULT_TTL_S = float(600)  # 10 minutes


@dataclass
class CrawlJob:
    job_id: str
    session_id: str
    query: str
    status: str = "running"  # running | complete | error | cancelled
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    # Async waiter resolved when the job finishes (background completion signal).
    _event: "asyncio.Event" = field(default_factory=asyncio.Event)

    def mark_complete(self, result: dict) -> None:
        self.status = "complete"
        self.result = result
        self.finished_at = time.time()
        self._event.set()

    def mark_error(self, error: str) -> None:
        self.status = "error"
        self.error = error
        self.finished_at = time.time()
        self._event.set()

    def mark_cancelled(self) -> None:
        self.status = "cancelled"
        self.finished_at = time.time()
        self._event.set()

    async def wait(self, timeout: Optional[float] = None) -> None:
        try:
            await asyncio.wait_for(self._event.wait(), timeout)
        except asyncio.TimeoutError:
            pass


class JobRegistry:
    """Process-wide registry of in-flight / recently-finished crawl jobs."""

    def __init__(self, result_ttl_s: float = DEFAULT_RESULT_TTL_S) -> None:
        self._ttl_s = result_ttl_s
        self._lock = asyncio.Lock()
        self._jobs: Dict[str, CrawlJob] = {}

    async def register(self, job_id: str, session_id: str, query: str) -> CrawlJob:
        async with self._lock:
            job = CrawlJob(job_id=job_id, session_id=session_id, query=query)
            self._jobs[job_id] = job
            return job

    async def get(self, job_id: str) -> Optional[CrawlJob]:
        async with self._lock:
            self._evict()
            return self._jobs.get(job_id)

    async def cancel(self, job_id: str) -> bool:
        """Request cancellation. Returns True if the job was running."""
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "running":
                return False
            job.mark_cancelled()
            return True

    async def complete(self, job_id: str, result: dict) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.mark_complete(result)

    async def fail(self, job_id: str, error: str) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.mark_error(error)

    async def evict_now(self, job_id: str) -> None:
        async with self._lock:
            self._jobs.pop(job_id, None)

    def _evict(self) -> None:
        cutoff = time.time() - self._ttl_s
        expired = [
            jid for jid, job in self._jobs.items()
            if job.finished_at is not None and job.finished_at < cutoff
        ]
        for jid in expired:
            self._jobs.pop(jid, None)


_registry_instance: Optional[JobRegistry] = None


def get_job_registry() -> JobRegistry:
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = JobRegistry()
    return _registry_instance
