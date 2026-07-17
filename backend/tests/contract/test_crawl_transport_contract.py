"""Tier 1+2 contract tests for resilient transport + background completion.

Covers REQ-31 (event log + SSE parity) and REQ-29 (job registry / background
completion) without any live network. Uses the in-process singletons directly.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from crawler.event_log import SessionEventLog, get_event_log
from crawler.job_registry import JobRegistry, get_job_registry
from crawler.ux_map import UX_MAP, known_events, map_event


# ── REQ-31: SessionEventLog ────────────────────────────────────────────────
def test_event_log_sequence_and_replay():
    """Events get monotonic seq; replay(after_seq) returns only newer ones."""
    log = SessionEventLog(ttl_s=60)

    async def _run():
        seqs = await asyncio.gather(
            log.append("s1", "CRAWLER_STARTED", {"query": "q"}),
            log.append("s1", "CRAWLER_PAGE_FETCHED", {"url": "u1", "page_number": 1, "total": 2}),
            log.append("s1", "CRAWLER_PAGE_FETCHED", {"url": "u2", "page_number": 2, "total": 2}),
        )
        replayed = await log.replay("s1", after_seq=1)
        await log.append("s2", "CRAWLER_STARTED", {"query": "other"})
        s2 = await log.replay("s2", after_seq=0)
        return seqs, replayed, s2

    seqs, replayed, s2 = asyncio.run(_run())
    assert seqs == [1, 2, 3], seqs
    assert [e.seq for e in replayed] == [2, 3]
    # Different session is isolated.
    assert s2[0].seq == 1


def test_event_log_ttl_eviction():
    """Events older than TTL are evicted (bounded memory)."""
    log = SessionEventLog(ttl_s=0.05)
    asyncio.run(log.append("s1", "CRAWLER_STARTED", {}))
    asyncio.run(asyncio.sleep(0.1))
    # append triggers eviction of the stale event
    asyncio.run(log.append("s1", "CRAWLER_PAGE_FETCHED", {}))
    snap = asyncio.run(log.snapshot("s1"))
    assert snap[0] == 2  # counter advanced
    assert len(snap[1]) == 1  # only the fresh event remains


def test_event_log_singleton():
    assert get_event_log() is get_event_log()


# ── REQ-29: JobRegistry (background completion + cancel) ───────────────────
def test_job_registry_background_complete_and_fetch():
    """A completed job stores its result; get() returns it after finish."""
    reg = JobRegistry(result_ttl_s=60)
    job = asyncio.run(reg.register("j1", "s1", "q"))
    asyncio.run(reg.complete("j1", {"summary": "done", "pages": []}))
    fetched = asyncio.run(reg.get("j1"))
    assert fetched is not None
    assert fetched.status == "complete"
    assert fetched.result["summary"] == "done"


def test_job_registry_cancel_stops_running():
    """cancel() only succeeds while running; marks cancelled."""
    reg = JobRegistry(result_ttl_s=60)
    asyncio.run(reg.register("j2", "s1", "q"))
    assert asyncio.run(reg.cancel("j2")) is True
    job = asyncio.run(reg.get("j2"))
    assert job.status == "cancelled"
    # Second cancel is a no-op (already finished).
    assert asyncio.run(reg.cancel("j2")) is False


def test_job_registry_wait_signals_completion():
    """wait() returns once the job completes (background completion signal)."""
    reg = JobRegistry(result_ttl_s=60)
    job = asyncio.run(reg.register("j3", "s1", "q"))

    async def _drive():
        await asyncio.sleep(0.05)
        await reg.complete("j3", {"ok": True})
        await job.wait(timeout=1.0)
        return job.status

    status = asyncio.run(_drive())
    assert status == "complete"


# ── REQ-30 AC4: UX map is exhaustive over emitted events ───────────────────
def test_ux_map_covers_all_emitted_events():
    """Every CrawlProgress event the orchestrator can emit has a UX mapping."""
    # The orchestrator emits: CRAWLER_STARTED, CRAWLER_PAGE_FETCHED, OPEN_TAB,
    # CRAWLER_COMPLETE, CRAWLER_ERROR.
    expected = {
        "CRAWLER_STARTED",
        "CRAWLER_PAGE_FETCHED",
        "OPEN_TAB",
        "CRAWLER_COMPLETE",
        "CRAWLER_ERROR",
    }
    assert expected.issubset(known_events()), known_events()
    for ev in expected:
        m = map_event(ev)
        assert m.msg_type and m.component and m.action


def test_ux_map_msg_types_unique_per_component():
    """No two events map to the same frontend msg_type (no dispatch ambiguity)."""
    types = [m.msg_type for m in UX_MAP.values()]
    assert len(types) == len(set(types)), types


# ── REQ-31 edge / T23: TTL eviction -> sync_required + full snapshot ───────
def test_event_log_sync_required_on_eviction():
    """When TTL eviction drops un-replayed events, sync_required is flagged."""
    log = SessionEventLog(ttl_s=0.05)
    asyncio.run(log.append("s1", "CRAWLER_STARTED", {"query": "q"}))
    asyncio.run(asyncio.sleep(0.1))
    # append triggers eviction of the stale event -> sync_required set
    asyncio.run(log.append("s1", "CRAWLER_PAGE_FETCHED", {"url": "u1"}))
    flag = asyncio.run(log.consume_sync_required("s1"))
    assert flag is True
    # consume clears it
    assert asyncio.run(log.consume_sync_required("s1")) is False


def test_event_log_snapshot_returns_full_state():
    """snapshot() returns all current events + sync_required flag."""
    log = SessionEventLog(ttl_s=60)
    asyncio.run(log.append("s1", "CRAWLER_STARTED", {"query": "q"}))
    asyncio.run(log.append("s1", "CRAWLER_PAGE_FETCHED", {"url": "u1", "page_number": 1, "total": 1}))

    async def _run():
        last, events, sync = await log.snapshot("s1")
        flag = await log.consume_sync_required("s1")
        return last, events, sync, flag

    last, events, sync, flag = asyncio.run(_run())
    assert last == 2
    assert len(events) == 2
    assert sync is False
    assert flag is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
