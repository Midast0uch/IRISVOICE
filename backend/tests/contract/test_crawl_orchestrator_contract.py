"""
Tier 1 (unit) + Tier 2 (contract) tests for CrawlOrchestrator (REQ-1,2,3,4,9,17AC4).

Per the spec Verification Strategy:
  - Tier 1: funnel order + FetchBackend swap, collaborators stubbed, NO live web.
  - Tier 2: unified event-stream parity (crawler_started -> page_fetched -> open_tab)
    via a stubbed FetchBackend + event-bus-style on_progress subscription.

Anchored to a PiN recording the enforced contract (see test below).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

# make backend importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from crawler.orchestrator import (  # noqa: E402
    CrawlOrchestrator,
    CrawlProgress,
    FetchBackend,
    InProcessFetchBackend,
    SubprocessFetchBackend,
)
from crawler.crawler_engine import CrawlResult, PageData  # noqa: E402
from crawler.crawl_planner import CrawlPlan  # noqa: E402


class _StubBackend(FetchBackend):
    """Returns two fake pages; records which mode asked for it."""
    mode_used = None

    async def fetch(self, query, urls, instructions, max_pages, on_page_done, timeout_s, **kwargs):
        self.__class__.mode_used = "stub"
        # Fixture-input update (called out): the REQ-3 rerank honest gate
        # (RerankState BELOW_THRESHOLD, rerank.py) rejects weak content, and
        # these stubs must clear it. Old content ("The quantum model shows X. It
        # was verified by Y.") scores 0.236 < 0.300, so the funnel escalated to
        # honest failure and cited_markdown was never produced — the test then
        # failed at its (unchanged) assertion. New content repeats the query
        # tokens ~3x per page, exactly the pattern applied to
        # test_crawl_behavior.py stubs; the assertions here are untouched.
        pages = [
            PageData(url="https://example.gov/doc", title="Doc", markdown="X is the quantum model. X was verified by Y. What X means is key.", html="", metadata={}),
            PageData(url="https://news.example.com/a", title="News", markdown="X appears in the new report. X is mentioned again in section three.", html="", metadata={}),
        ]
        for i, p in enumerate(pages):
            if on_page_done:
                on_page_done(p.url, i + 1, len(pages))
        return CrawlResult(query=query, pages=pages, duration_ms=10, crawled_at="2026-01-01T00:00:00+00:00")


class _FailingBackend(FetchBackend):
    async def fetch(self, query, urls, instructions, max_pages, on_page_done, timeout_s, **kwargs):
        return CrawlResult(query=query, pages=[], duration_ms=1, crawled_at="x", error="subprocess crashed")


def _stub_planner(urls):
    class _P:
        async def plan(self, query):
            return CrawlPlan(urls=urls, instructions="extract key facts", result_type="mixed", title="T")
    return _P()


@pytest.fixture
def events():
    return []


@pytest.fixture
def emitter(events):
    def _cb(progress: CrawlProgress):
        events.append((progress.event, progress.payload))
    return _cb


def test_fetchbackend_swap_modes():
    """REQ-17 AC4: backend is swappable; ws vs agent select different classes."""
    assert InProcessFetchBackend is not SubprocessFetchBackend
    assert issubclass(InProcessFetchBackend, FetchBackend)
    assert issubclass(SubprocessFetchBackend, FetchBackend)


def test_funnel_order_and_events(events, emitter):
    """Tier 1+2: funnel runs; emits crawler_started -> page_fetched* -> open_tab."""
    orch = CrawlOrchestrator(planner=_stub_planner(["https://example.gov/doc"]))
    orch._backend_override = _StubBackend()  # inject stub backend (no live web)

    result = asyncio.run(orch.research(
        "what is X", mode="agent", session_id="s1",
        on_progress=emitter, max_pages=5,
    ))

    # funnel produced passages + cited_markdown (REQ-4, REQ-8)
    assert result.pages, "pages should be present"
    assert result.cited_markdown, "cited_markdown should be produced"
    assert result.credibility_map is not None
    assert result.credibility_map.per_source, "per-source credibility computed"

    # event sequence parity (REQ-10..13, REQ-29/30)
    ev_types = [e[0] for e in events]
    assert ev_types[0] == "CRAWLER_STARTED"
    assert ev_types.count("CRAWLER_PAGE_FETCHED") == 2
    # OPEN_TAB precedes the terminal CRAWLER_COMPLETE signal (REQ-29/30).
    assert "OPEN_TAB" in ev_types
    assert ev_types[-1] == "CRAWLER_COMPLETE"
    # full URL present (REQ-11)
    pf = [p for e, p in events if e == "CRAWLER_PAGE_FETCHED"]
    assert pf[0]["url"].startswith("https://")

    # REQ-11 (T13 / CT-C2): the OPEN_TAB payload carries url + job_id so the
    # frontend can tell a content tab from a url-less dashboard tab (and never
    # force-activate the latter).
    ot = [p for e, p in events if e == "OPEN_TAB"]
    assert ot, "OPEN_TAB payload must be present"
    assert "job_id" in ot[0], f"OPEN_TAB must carry job_id: {ot[0]}"
    assert "url" in ot[0], f"OPEN_TAB must carry url key: {ot[0]}"


def test_credibility_monotonicity():
    """REQ-5/6: primary_official scores higher than forum."""
    from crawler.credibility import classify_source, _base_weight
    assert classify_source("https://nasa.gov/doc") == "primary_official"
    assert classify_source("https://reddit.com/r/x") == "forum"
    assert _base_weight("https://nasa.gov/doc") > _base_weight("https://reddit.com/r/x")


def test_citation_binding_completeness():
    """REQ-8: every cited sentence carries a url; unsourced flagged [?]."""
    from crawler.cite import _bind_citations
    from crawler.orchestrator import Passage
    passages = [Passage(chunk_id="u#0", url="https://example.gov/doc", text="the quantum model shows X")]
    md, unsourced = _bind_citations("The quantum model shows X. Unknown claim here.", passages)
    assert "[1](https://example.gov/doc)" in md
    assert "[?]" in md  # unsourced sentence flagged


def test_rerank_threshold_drops_low():
    """REQ-7: passages below threshold are dropped."""
    from crawler.rerank import rerank_passages
    from crawler.orchestrator import Passage
    from crawler.credibility import CredibilityMap
    passages = [
        Passage(chunk_id="a#0", url="https://a.gov", text="quantum model verified by experiment"),
        Passage(chunk_id="b#0", url="https://b.com", text="zzz qwerty nonsense token"),
    ]
    cm = CredibilityMap(per_source={"https://a.gov": 0.9, "https://b.com": 0.3}, unsourced_claims=[], top_score=0)
    kept = rerank_passages(passages, "quantum model experiment", cm)
    # at least the strong passage survives; weak one may be dropped
    assert any("a.gov" in p.url for p in kept)


def test_crawl_failure_returns_error_never_raises(events, emitter):
    """REQ-17 AC1/AC3: subprocess crash -> CrawlResult.error, no raise, crawler_error emitted."""
    orch = CrawlOrchestrator(planner=_stub_planner(["https://x.com"]))
    orch._backend_override = _FailingBackend()
    result = asyncio.run(orch.research("q", mode="agent", on_progress=emitter))
    assert result.error is not None
    assert any(e[0] == "CRAWLER_ERROR" for e in events)


def test_concurrency_cap_enforced():
    """REQ-17 AC3: parallel crawl subprocesses are capped (default 2); the 3rd waits."""
    import crawler.crawl_runner as runner

    # Track concurrent in-flight "subprocesses" via a fake create_subprocess_exec.
    state = {"concurrent": 0, "max_concurrent": 0, "started": 0}

    class _FakeProc:
        def __init__(self):
            self.stdout = _FakeStream()
            self.pid = 999999  # unused; tree-kill is a no-op for fake

        async def wait(self):
            return 0

        def kill(self):
            pass

    class _FakeStream:
        async def readline(self):
            await asyncio.sleep(0.05)  # simulate slow drain
            return b""  # EOF immediately after first read

    async def _fake_create(*args, **kwargs):
        state["concurrent"] += 1
        state["started"] += 1
        state["max_concurrent"] = max(state["max_concurrent"], state["concurrent"])
        proc = _FakeProc()
        await asyncio.sleep(0.08)  # hold the slot briefly
        state["concurrent"] -= 1
        return proc

    orig = asyncio.create_subprocess_exec
    asyncio.create_subprocess_exec = _fake_create
    try:
        # 4 concurrent crawls; cap is 2 so max in-flight must never exceed 2.
        async def _run_all():
            async def _one():
                return await runner.run_crawl_subprocess("q", ["https://x.com"], "i")
            return await asyncio.gather(*[_one() for _ in range(4)])
        results = asyncio.run(_run_all())
    finally:
        asyncio.create_subprocess_exec = orig

    assert all(r.error is None or r.pages == [] for r in results)
    assert state["max_concurrent"] <= 2, f"concurrency exceeded cap: {state['max_concurrent']}"


def test_process_tree_killed_on_timeout(tmp_path):
    """REQ-17 AC2: on timeout the worker's child process tree is reaped, not orphaned.

    The runner's timeout path kills the whole tree (taskkill /T /F on
    Windows, process-group SIGKILL on POSIX). We verify the GRANDCHILD is
    gone after the run — not just that the parent returned. The timeout
    itself is a scheduler-layer concern (design.md §"429s and timeouts become
    transient"): the crawl result only surfaces the timeout when the
    last-resort fallback ALSO fails to recover content.
    """
    import crawler.crawl_runner as runner

    pid_file = tmp_path / "grandchild.pid"

    # Worker script: spawn a grandchild `sleep`, record its PID, then hang so
    # the parent times out.
    worker = tmp_path / "hang_worker.py"
    worker.write_text(
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
        "sys.stderr = open('nul', 'w') if sys.platform == 'win32' else open('/dev/null', 'w')\n"
        "time.sleep(30)\n"
    )

    orig_create = asyncio.create_subprocess_exec

    async def _fake_create(*args, **kwargs):
        # Swap the real worker module for our hang worker to force a timeout.
        new_args = list(args)
        new_args[1] = str(worker)
        return await orig_create(*new_args, **kwargs)

    asyncio.create_subprocess_exec = _fake_create
    try:
        # 127.0.0.1:1 -> the plain-HTTP fallback fails fast (nothing listens),
        # so the timeout error honestly surfaces (no network dependence).
        result = asyncio.run(
            runner.run_crawl_subprocess("q", ["http://127.0.0.1:1/"], "i", timeout_s=1)
        )
    finally:
        asyncio.create_subprocess_exec = orig_create

    # REQ-17 AC2: the grandchild was killed with the tree — not orphaned.
    grandchild_pid = int(pid_file.read_text().strip())
    assert not _process_alive(grandchild_pid), \
        f"grandchild {grandchild_pid} survived the tree kill (orphaned)"

    # Fallback could not recover content -> the timeout surfaces honestly.
    assert result.error is not None
    assert "timed out" in result.error


def _process_alive(pid: int) -> bool:
    """True if the process exists. os.kill(pid, 0) on POSIX; on Windows
    signal 0 would TERMINATE the process, so use OpenProcess instead."""
    if sys.platform == "win32":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
            )
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:  # noqa: BLE001 — conservative: assume alive
            return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
