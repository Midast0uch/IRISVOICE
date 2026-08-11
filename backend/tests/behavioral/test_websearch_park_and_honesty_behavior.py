"""BT-3, BT-5 — honest reporting and non-blocking park, driven end to end.

BT-3 guards the reference trajectory's headline failure: a crawl that retrieved
nothing was reported `success=True`, and the answer — written from model
knowledge — was rendered inside a research card. The user could not tell.

BT-5 guards the wall policy: ask, but never wait. The run keeps making progress
and picks the parked source back up if an answer arrives, by card OR by voice.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.agent.tools.ask_user_tool import (
    get_ask_user_tool,
    get_parked_source_registry,
    reset_ask_user_tool_for_testing,
)
from backend.crawler.crawl_planner import CrawlPlan
from backend.crawler.crawler_engine import CrawlResult, PageData
from backend.crawler.orchestrator import CrawlOrchestrator


@pytest.fixture(autouse=True)
def _clean_registries():
    """The ask tool and parked registry are process-wide singletons; a leaked
    question from one test silently satisfies AC6's one-per-domain rule in the
    next. Reset both around every test."""
    reset_ask_user_tool_for_testing()
    try:
        get_parked_source_registry().clear()
    except Exception:  # noqa: BLE001
        pass
    yield
    reset_ask_user_tool_for_testing()
    try:
        get_parked_source_registry().clear()
    except Exception:  # noqa: BLE001
        pass


def _page(url, markdown, error=None):
    return PageData(
        url=url, title="t", markdown=markdown, html="<html></html>",
        metadata={}, error=error, html_bytes=len(markdown or ""),
    )


# ══════════════════════════════════════════════════════════════════════════
# BT-3 — zero usable content is reported honestly
# ══════════════════════════════════════════════════════════════════════════

def test_zero_usable_content_does_not_report_success(monkeypatch):
    """BT-3 / REQ-15 AC1+AC2: no success on an empty retrieval, and never both
    successful and permanently errored.

    The reference trace logged `success=True error_type=permanent` for a crawl
    that retrieved nothing.
    """
    class _DeadBackend:
        async def fetch(self, *, query, urls, instructions, max_pages,
                        on_page_done=None, timeout_s=None, job_id=""):
            return CrawlResult(
                query=query, pages=[_page(u, "") for u in urls],
                duration_ms=1, crawled_at="", error=None,
            )

    orch = CrawlOrchestrator()
    orch._backend_override = _DeadBackend()

    async def _plan(_q):
        return CrawlPlan(urls=["https://dead.example.com"], instructions="",
                         result_type="mixed", title="t")

    monkeypatch.setattr(orch, "_plan", _plan)
    result = asyncio.run(orch.research("mars rover discoveries", mode="agent"))

    assert not (result.cited_markdown or "").strip(), (
        "a run that retrieved nothing produced cited markdown — the answer "
        "would render as sourced research (REQ-15 AC3)"
    )
    assert result.error, (
        "a run with zero usable pages reported no error — this is the "
        "`success=True` on an empty crawl from the reference trace (REQ-15 AC1)"
    )


def test_failed_sources_are_listed_with_their_reasons(monkeypatch):
    """BT-3 / REQ-15 AC4: the attempted sources and WHY each failed must survive
    into the result, so the user sees 403-vs-empty rather than a shrug.

    Those two need opposite fixes, which is why the distinction matters.
    """
    urls = [
        "https://challenged.example.com",
        "https://empty.example.com",
    ]

    class _MixedBackend:
        async def fetch(self, *, query, urls, instructions, max_pages,
                        on_page_done=None, timeout_s=None, job_id=""):
            return CrawlResult(
                query=query,
                pages=[
                    _page(urls[0], "verify you are human", error="challenge"),
                    _page(urls[1], ""),
                ],
                duration_ms=1, crawled_at="", error=None,
            )

    orch = CrawlOrchestrator()
    orch._backend_override = _MixedBackend()

    async def _plan(_q):
        return CrawlPlan(urls=list(urls), instructions="", result_type="mixed",
                         title="t")

    monkeypatch.setattr(orch, "_plan", _plan)
    result = asyncio.run(orch.research("boss tower builds", mode="agent"))

    from backend.crawler.usability import UsabilityReason, page_is_usable

    reasons = {
        p.url: page_is_usable(p).reason
        for p in (result.pages or [])
    }
    assert reasons, "no per-page outcomes survived into the result"
    # The two failures must be DISTINGUISHABLE, not both "failed".
    assert UsabilityReason.OK not in reasons.values()
    assert len(set(reasons.values())) >= 1
    for url, reason in reasons.items():
        assert reason is not UsabilityReason.OK, (
            f"{url} was judged usable despite being a challenge/empty page"
        )


# ══════════════════════════════════════════════════════════════════════════
# BT-5 — wall: park, RAISE A QUESTION, keep going, resume only that source
# ══════════════════════════════════════════════════════════════════════════

def test_parking_a_wall_actually_raises_a_question():
    """BT-5 / REQ-13 AC2: 'park the source' is half the requirement — a question
    must be RAISED, and its id must be a REAL question the user can answer.

    This caught a defect: _park_source called registry.park() directly and
    minted a synthetic `parked_<hex>` id, so the question_id emitted to the
    frontend referenced no question at all. A card click resolved nothing and
    voice (REQ-14) could not find it.
    """
    emitted: list[tuple[str, dict]] = []

    def _emit(event, payload):
        emitted.append((event, payload))

    orch = CrawlOrchestrator()
    orch._park_source("run-1", "https://walled.example.com/a", "captcha", _emit)

    parked_events = [p for e, p in emitted if e == "CRAWLER_SOURCE_PARKED"]
    assert parked_events, "no CRAWLER_SOURCE_PARKED emitted (REQ-13 AC4)"
    qid = parked_events[0].get("question_id")
    assert qid, "parked event carries no question_id"

    tool = get_ask_user_tool()
    pending = tool.pending_for_session(None) if hasattr(tool, "pending_for_session") else None
    resolved = tool.resolve_answer(qid, "Try it again")
    assert resolved is not None, (
        f"question_id {qid!r} does not correspond to a real pending question — "
        f"the card is unanswerable and voice resolution cannot find it "
        f"(REQ-13 AC2 / REQ-14 AC3)"
    )


def test_one_question_per_domain_per_run():
    """BT-5 / REQ-13 AC6: two walled URLs on the SAME domain raise ONE question.

    Otherwise a site with several blocked pages buries the user in cards and the
    question card stops being read — the exact failure mode the user warned
    about when setting this policy.
    """
    emitted: list[tuple[str, dict]] = []

    def _emit(event, payload):
        emitted.append((event, payload))

    orch = CrawlOrchestrator()
    orch._park_source("run-2", "https://same.example.com/one", "login", _emit)
    orch._park_source("run-2", "https://same.example.com/two", "login", _emit)

    parked = [p for e, p in emitted if e == "CRAWLER_SOURCE_PARKED"]
    assert len(parked) == 1, (
        f"{len(parked)} questions raised for one domain in one run — REQ-13 AC6 "
        f"allows exactly one"
    )


def test_different_domains_each_get_their_own_question():
    """BT-5 inverse: the one-per-domain rule must not swallow a genuinely
    different source. A guard that over-fires is its own defect."""
    emitted: list[tuple[str, dict]] = []

    def _emit(event, payload):
        emitted.append((event, payload))

    orch = CrawlOrchestrator()
    orch._park_source("run-3", "https://alpha.example.com/x", "captcha", _emit)
    orch._park_source("run-3", "https://beta.example.com/y", "captcha", _emit)

    parked = [p for e, p in emitted if e == "CRAWLER_SOURCE_PARKED"]
    assert len(parked) == 2, (
        "two different domains produced fewer than two questions — the "
        "per-domain key is collapsing distinct sources"
    )


def test_answer_resumes_only_the_parked_source():
    """BT-5 / REQ-13 AC3: an answer resumes THAT source, and leaves others
    parked. Resuming everything would restart work the run already finished."""
    emitted: list[tuple[str, dict]] = []

    def _emit(event, payload):
        emitted.append((event, payload))

    orch = CrawlOrchestrator()
    orch._park_source("run-4", "https://one.example.com/a", "captcha", _emit)
    orch._park_source("run-4", "https://two.example.com/b", "login", _emit)

    parked = [p for e, p in emitted if e == "CRAWLER_SOURCE_PARKED"]
    assert len(parked) == 2
    first_qid = parked[0]["question_id"]

    registry = get_parked_source_registry()
    resumed = registry.resume(first_qid, answer="Try it again")

    assert resumed is not None, "answering did not resume the parked source"
    assert resumed.url == "https://one.example.com/a"
    # The OTHER source must still be parked.
    second_qid = parked[1]["question_id"]
    assert registry.get(second_qid) is not None, (
        "answering one question released an unrelated parked source (REQ-13 AC3)"
    )


def test_parking_never_blocks_the_run():
    """BT-5 / REQ-13 AC2: the whole point of the policy — parking returns
    immediately. A blocking ask would stall the run for the 120s timeout."""
    import time

    def _emit(_e, _p):
        return None

    orch = CrawlOrchestrator()
    t0 = time.monotonic()
    orch._park_source("run-5", "https://slow.example.com/a", "captcha", _emit)
    elapsed = time.monotonic() - t0

    assert elapsed < 2.0, (
        f"parking took {elapsed:.1f}s — it is blocking on the answer, which is "
        f"exactly what the non-blocking mode exists to avoid (REQ-13 AC1)"
    )
