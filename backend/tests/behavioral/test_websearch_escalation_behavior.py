"""BT-1, BT-7, BT-8, BT-9, BT-10 — full-loop behaviour of the escalation path.

These drive the real orchestrator / real capability objects and assert EMERGENT
properties, not unit behaviour. Every defect in the reference trajectory
(conv_1786327042255_pjtfyybj2, 2026-08-09 22:00:35) passed its unit tests; what
was missing was a test that ran the system the way it actually runs.

Reference baseline for BT-1: `grep -c "Exa retry" logs/iris.log` = 0 across
401MB of history. The broaden-and-retry path has never once fired in production
because its gate asked `not p.error` while the pages it judged had error=None
and empty markdown.
"""
from __future__ import annotations

import asyncio

from backend.crawler.capabilities import FetchOutcome
from backend.crawler.crawl_planner import CrawlPlan
from backend.crawler.crawler_engine import CrawlResult, PageData
from backend.crawler.orchestrator import CrawlOrchestrator
from backend.crawler.usability import UsabilityReason, UsabilityVerdict, page_is_usable

# A realistic Cloudflare interstitial: LONGER than the real content it hides.
# That length matters — see BT-9.
CHALLENGE_TEXT = (
    "Just a moment... Checking your browser before accessing the site. "
    "This process is automatic. Your browser will redirect to your requested "
    "content shortly. Please allow up to 5 seconds. DDoS protection by "
    "Cloudflare. Ray ID: 8f2a1c9d4e7b. Enable JavaScript and cookies to "
    "continue. verify you are human. Performance & security by Cloudflare."
)
REAL_TEXT = (
    "Run a tank to soak boss damage, a dedicated healer, and one burst "
    "attacker to melt the health bar once the boss is stunned."
)


def _page(url: str, markdown: str, *, html: str | None = "<html></html>",
          error=None) -> PageData:
    return PageData(
        url=url, title="t", markdown=markdown, html=html,
        metadata={}, error=error, html_bytes=len(markdown or ""),
    )


def _ok() -> UsabilityVerdict:
    return UsabilityVerdict(True, UsabilityReason.OK, "")


# ══════════════════════════════════════════════════════════════════════════
# BT-1 — broaden-and-retry fires exactly once on an all-dead run
# ══════════════════════════════════════════════════════════════════════════

def test_all_urls_dead_triggers_exactly_one_broaden_and_retry(monkeypatch):
    """BT-1: the regression guard for 0-fires-in-401MB.

    Every page comes back with error=None and empty markdown — the exact shape
    the old `not p.error` gate scored as success. The retry must fire, and must
    fire ONCE (REQ-2 AC2/AC4).
    """
    fetch_calls: list[list[str]] = []
    planned: list[str] = []

    class _DeadBackend:
        async def fetch(self, *, query, urls, instructions, max_pages,
                        on_page_done=None, timeout_s=None, job_id=""):
            fetch_calls.append(list(urls))
            # error=None + empty markdown: the reference-trace failure shape.
            return CrawlResult(
                query=query,
                pages=[_page(u, "", html=None) for u in urls],
                duration_ms=1, crawled_at="", error=None,
            )

    orch = CrawlOrchestrator()
    orch._backend_override = _DeadBackend()

    async def _plan(q):
        planned.append(q)
        return CrawlPlan(
            urls=[f"https://dead{len(planned)}.example.com"],
            instructions="", result_type="mixed", title="t",
        )

    monkeypatch.setattr(orch, "_plan", _plan)

    asyncio.run(orch.research("latest mars rover discoveries", mode="agent"))

    assert len(fetch_calls) == 2, (
        f"expected exactly 2 fetches (initial + one broadened retry), got "
        f"{len(fetch_calls)}. 1 = the retry never fired (the 0-in-401MB bug); "
        f">2 = REQ-2 AC4's once-only bound is broken."
    )
    assert len(planned) == 2, "the retry must RE-PLAN with a broadened query"
    assert planned[0] != planned[1], (
        "the retry re-planned with the identical query — 'broaden' is a no-op"
    )


def test_usable_first_pass_does_not_retry(monkeypatch):
    """BT-1 inverse: a good run must not pay for a retry.

    Without this, 'always retry' would pass the test above while doubling the
    cost of every successful search.
    """
    fetch_calls: list[list[str]] = []

    class _GoodBackend:
        async def fetch(self, *, query, urls, instructions, max_pages,
                        on_page_done=None, timeout_s=None, job_id=""):
            fetch_calls.append(list(urls))
            return CrawlResult(
                query=query,
                pages=[_page(u, REAL_TEXT + " " + query) for u in urls],
                duration_ms=1, crawled_at="", error=None,
            )

    orch = CrawlOrchestrator()
    orch._backend_override = _GoodBackend()

    async def _plan(q):
        return CrawlPlan(urls=["https://good.example.com"], instructions="",
                         result_type="mixed", title="t")

    monkeypatch.setattr(orch, "_plan", _plan)
    asyncio.run(orch.research("boss tower party builds", mode="agent"))

    assert len(fetch_calls) == 1, (
        f"a first pass with usable content triggered {len(fetch_calls)} fetches "
        f"— the retry gate is now firing on success"
    )


# ══════════════════════════════════════════════════════════════════════════
# BT-9 — a challenge must not win the merge, even when it is longer
# ══════════════════════════════════════════════════════════════════════════

def test_challenge_text_does_not_win_the_merge_against_real_content():
    """BT-9: crawl extracted a Cloudflare interstitial AS CONTENT while vision
    read the real page. The disagreement must be recorded AND the challenge
    boilerplate must not become the merged evidence.

    The length is the trap: real interstitials are verbose, so a
    'merge = longer text' rule hands the win to the challenge. This is the
    reference trajectory's failure mode exactly — the crawler extracted
    challenge boilerplate and the synthesis step reasoned over it.
    """
    from backend.vision.frame_extraction import ContentOrigin, reconcile

    assert len(CHALLENGE_TEXT) > len(REAL_TEXT), (
        "fixture invalid: the challenge must be the LONGER text for this test "
        "to exercise the trap"
    )

    record = reconcile(CHALLENGE_TEXT, REAL_TEXT, "https://example.com/x")

    assert record.disagreement, (
        "crawl and vision produced materially different text and no "
        "disagreement was recorded (REQ-17 AC5)"
    )
    assert CHALLENGE_TEXT not in record.merged_text, (
        "challenge boilerplate won the merge and became the evidence — the "
        "exact defect the reference trajectory shows (BT-9)"
    )
    assert record.merged_text.strip() == REAL_TEXT.strip(), (
        "the real page content must be the merged evidence"
    )
    assert record.origin is ContentOrigin.RECONCILED


def test_merged_evidence_is_judged_by_the_shared_predicate():
    """BT-9 corollary: vision output is not trusted for being vision output.

    A challenge page read by OCR is still a challenge (REQ-17 edge case).
    """
    record_page = _page("https://example.com/y", CHALLENGE_TEXT)
    verdict = page_is_usable(record_page)
    assert not verdict.usable and verdict.reason is UsabilityReason.CHALLENGE, (
        "challenge boilerplate passed the shared predicate — vision-derived "
        "text must go through page_is_usable like any other content"
    )


# ══════════════════════════════════════════════════════════════════════════
# BT-8 — image-heavy page: vision content is usable and marked vision-origin
# ══════════════════════════════════════════════════════════════════════════

def test_image_heavy_page_yields_vision_origin_evidence():
    """BT-8: DOM text near-empty, vision reads the rendered frame.

    The result must be usable AND flagged vision-origin, so downstream trust
    scoring can tell it from DOM text (REQ-17 AC6 / REQ-18 AC2).
    """
    url = "https://example.com/infographic"
    vision_out = FetchOutcome(
        url=url, capability="fetch.vision",
        page=_page(url, REAL_TEXT), verdict=_ok(),
    )
    crawl_out = FetchOutcome(
        url=url, capability="fetch.crawl",
        page=_page(url, ""),  # DOM had essentially nothing
        verdict=UsabilityVerdict(False, UsabilityReason.EMPTY, "markdown len=0"),
    )

    CrawlOrchestrator()._stamp_evidence(
        vision_out, [crawl_out, vision_out], url, "job-bt8"
    )

    meta = vision_out.page.metadata
    assert meta["content_origin"] == "vision", (
        "vision-only content was not flagged as vision-origin — once persisted "
        "it is indistinguishable from DOM text (REQ-17 AC6)"
    )
    assert meta.get("evidence_disagreement") == "vision_has_text_crawl_empty", (
        "'vision has text, crawl empty' is a diagnosis worth keeping — it says "
        "the crawler under-captured rather than the page being empty"
    )
    assert page_is_usable(vision_out.page).usable


# ══════════════════════════════════════════════════════════════════════════
# BT-10 — triage rejects unchanged frames (the cost model behind design D8)
# ══════════════════════════════════════════════════════════════════════════

def test_triage_costs_less_than_extraction_on_a_static_page():
    """BT-10: on a page that does not change while scrolling, full extraction
    calls must stay BELOW the number of frames triaged.

    Without this the feature can work perfectly and still be uneconomic: full
    VLM extraction on every scroll frame would be the dominant cost of the whole
    escalation path (design D8).
    """
    from backend.vision.frame_extraction import SessionBounds, extract_page_frames

    class _CountingProvider:
        """ASYNC (matching frame_extraction.VisionProvider) — extract_page_frames
        itself became async so it can be awaited from inside the already-running
        event loop of FetchVisionCapability.fetch_one (see
        backend/vision/session_vision_adapter.py). Only the calling convention
        changed here (asyncio.run below) — every assertion is unchanged."""

        def __init__(self):
            self.triage_calls = 0
            self.extract_calls = 0

        async def describe_live_frame(self, img_bytes, **_k):
            self.triage_calls += 1
            return "no new content"

        async def read_text(self, img_bytes, **_k):
            self.extract_calls += 1
            return REAL_TEXT

        async def analyze_screen(self, img_bytes, question, **_k):
            self.extract_calls += 1
            return REAL_TEXT

    provider = _CountingProvider()
    asyncio.run(extract_page_frames(provider, "goal", SessionBounds()))

    assert provider.triage_calls >= 1, "triage never ran"
    assert provider.extract_calls < max(1, provider.triage_calls), (
        f"extraction ran {provider.extract_calls}x against {provider.triage_calls} "
        f"triage calls on a STATIC page — triage is not gating extraction, so "
        f"design D8's cost model does not hold (BT-10)"
    )


# ══════════════════════════════════════════════════════════════════════════
# BT-7 — the reversal edge: vision settles, crawl extracts
# ══════════════════════════════════════════════════════════════════════════

def test_vision_hands_settled_dom_back_for_crawl_extraction():
    """BT-7: `crawl -> vision -> crawl` is a normal traversal (REQ-6 AC5).

    Vision's common job is to SETTLE a page (dismiss the banner, pass the
    interstitial, trigger lazy-load) and hand the DOM back — not to be the
    extractor. The outcome must carry settled_dom for that to be possible.
    """
    from backend.vision.fetch_vision import FetchVisionCapability

    settled_html = f"<html><body><article>{REAL_TEXT}</article></body></html>"

    class _FakeSession:
        def __init__(self, *_a, **_k):
            pass

        async def open(self):
            return None

        def available(self):
            return True

        async def detect_wall(self):
            return None

        async def screenshot(self):
            return b"frame"

        async def act(self, action):
            return None

        async def settle(self):
            return settled_html

        async def close(self):
            return None

    class _FakeProvider:
        def __init__(self):
            self.n = 0

        def suggest_action(self, img_bytes, goal, **_k):
            self.n += 1
            return (
                {"action": "scroll", "target": "", "reasoning": "reveal"}
                if self.n <= 1
                else {"action": "error", "target": "", "reasoning": "done"}
            )

        def describe_live_frame(self, img_bytes, **_k):
            return "no new content"

        def read_text(self, img_bytes, **_k):
            return ""

        def analyze_screen(self, img_bytes, question, **_k):
            return ""

    cap = FetchVisionCapability(provider=_FakeProvider(), session_cls=_FakeSession)
    outcome = asyncio.run(cap.fetch_one("https://example.com/z", "goal", "job-bt7"))

    assert outcome.settled_dom, (
        "no settled DOM handed back — the reversal edge cannot exist, so "
        "vision must act as extractor for every page (REQ-6 AC5)"
    )
    assert REAL_TEXT in outcome.settled_dom, (
        "the settled DOM does not contain the content vision unblocked"
    )
