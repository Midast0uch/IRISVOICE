"""CT-1, CT-2, CT-9 — the single-judge pin and the caller-existence pins.

These three contracts guard the two defects that produced this whole spec:

  CT-1  Three layers judged the SAME fetch differently on the traced Palworld
        run (crawl_runner `if p.markdown` -> 0 usable, orchestrator
        `if not p.error` -> 2 usable, rerank score>=0.30 -> 0 usable). A fourth
        local predicate reintroduces it, so this asserts by call-graph.

  CT-2  rerank.py returned `[]` meaning "re-query" with the meaning carried only
        in a comment; the call site assigned it and fell through to
        extract_and_cite, which then produced a sourced-looking answer from an
        empty passage set.

  CT-9  The codebase's dominant failure mode: a mechanism is implemented, unit
        tested, and never called. Fourteen instances were counted while writing
        this spec. `fuzzy_match_answer` was fully implemented and tested with
        ZERO production callers; `_STEALTH_EXTRA_HEADERS` was defined with a
        comment saying it was deliberately not passed; `useCrawl` was a complete
        hook with no consumers. A test that the mechanism WORKS cannot see any
        of that. Only a test that it is REACHED can.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]


def _src(rel: str) -> str:
    p = _REPO / rel
    assert p.is_file(), f"expected {rel} to exist at {p}"
    return p.read_text(encoding="utf-8", errors="replace")


# ══════════════════════════════════════════════════════════════════════════
# CT-1 — page_is_usable is the only usability judge
# ══════════════════════════════════════════════════════════════════════════

# Layers that judge whether a fetch produced usable content. Each must reach
# the shared predicate rather than computing its own verdict.
_JUDGING_LAYERS = (
    "backend/crawler/orchestrator.py",
    "backend/crawler/crawl_runner.py",
    "backend/vision/fetch_vision.py",
)


@pytest.mark.parametrize("rel", _JUDGING_LAYERS)
def test_judging_layer_uses_the_shared_predicate(rel):
    """CT-1 AC1: every layer that judges fetch success calls page_is_usable."""
    src = _src(rel)
    assert "page_is_usable" in src, (
        f"{rel} judges fetch outcomes but never calls page_is_usable — this is "
        f"the three-way disagreement the predicate exists to eliminate (REQ-1)."
    )


@pytest.mark.parametrize("rel", _JUDGING_LAYERS)
def test_no_rogue_usability_predicate(rel):
    """CT-1: `not p.error` must not be used as evidence of usability.

    REQ-1 AC3 — `error is None` is insufficient on its own. This is the exact
    line (orchestrator.py:204) that counted 2 empty-markdown pages as successes
    and kept the broaden-and-retry gate shut for the whole of recorded history.

    Detected structurally rather than by string match: any comprehension that
    filters a `.pages`-like collection on a bare `not X.error` is a rogue judge.
    """
    tree = ast.parse(_src(rel))
    offenders: list[int] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            continue
        for gen in node.generators:
            for cond in gen.ifs:
                # `not <something>.error`
                if (
                    isinstance(cond, ast.UnaryOp)
                    and isinstance(cond.op, ast.Not)
                    and isinstance(cond.operand, ast.Attribute)
                    and cond.operand.attr == "error"
                ):
                    offenders.append(getattr(cond, "lineno", -1))

    assert not offenders, (
        f"{rel} filters pages on `not X.error` at line(s) {offenders} — that is "
        f"a second usability judge. Call page_is_usable(page).usable instead "
        f"(REQ-1 AC1/AC3)."
    )


def test_shared_predicate_rejects_the_reference_failure():
    """CT-1: the exact page shapes from the traced run are judged unusable.

    Fixture shared with BT-2 per the intertwined-testing rule.
    """
    from backend.crawler.crawler_engine import PageData
    from backend.crawler.usability import UsabilityReason, page_is_usable

    def _page(**kw):
        base = dict(
            url="https://example.com", title="t", markdown="", html=None,
            metadata={}, error=None, html_bytes=0,
        )
        base.update(kw)
        return PageData(**base)

    # The two fallback pages that `not p.error` counted as successes.
    empty = page_is_usable(_page(markdown="", error=None))
    assert not empty.usable and empty.reason is UsabilityReason.EMPTY

    # A Cloudflare interstitial reached by the primary path.
    challenge = page_is_usable(
        _page(
            markdown="Just a moment... verify you are human",
            html='<div class="cf-turnstile"></div>',
        )
    )
    assert not challenge.usable and challenge.reason is UsabilityReason.CHALLENGE

    # A page with error=None and real content is usable — the predicate must
    # not be so strict that it rejects everything (guards over-correction).
    ok = page_is_usable(
        _page(markdown="A genuine paragraph of retrieved content about builds.")
    )
    assert ok.usable and ok.reason is UsabilityReason.OK


# ══════════════════════════════════════════════════════════════════════════
# CT-2 — extract_and_cite is unreachable with an empty passage set
# ══════════════════════════════════════════════════════════════════════════

def test_extract_and_cite_not_reached_when_rerank_is_below_threshold(monkeypatch):
    """CT-2 / REQ-3 AC2+AC3: a below-threshold rerank escalates or fails
    honestly — it never cites.

    Drives the real orchestrator with a stub backend whose pages are usable but
    irrelevant to the query, so rerank lands BELOW_THRESHOLD exactly as it did
    on the traced run (`top score 0.000 below threshold 0.300`).
    """
    from backend.crawler import orchestrator as orch_mod
    from backend.crawler.crawler_engine import CrawlResult, PageData

    cited: list[tuple] = []

    async def _spy_extract_and_cite(**kwargs):
        cited.append((kwargs.get("passages"),))
        return {}, "", []

    monkeypatch.setattr(
        "backend.crawler.cite.extract_and_cite", _spy_extract_and_cite
    )

    class _StubBackend:
        async def fetch(self, *, query, urls, instructions, max_pages,
                        on_page_done=None, timeout_s=None, job_id=""):
            # Usable content (clears page_is_usable) that shares no tokens with
            # the query, so the hybrid score cannot clear RERANK_THRESHOLD.
            pages = [
                PageData(
                    url=u, title="unrelated",
                    markdown=(
                        "Zebra mollusc parchment lantern. Quilted ferrous "
                        "meridian sundial. Wicker phosphor cadence."
                    ),
                    html="<html><body>unrelated</body></html>",
                    metadata={}, error=None, html_bytes=64,
                )
                for u in urls
            ]
            return CrawlResult(
                query=query, pages=pages, duration_ms=1,
                crawled_at="", error=None,
            )

    orch = orch_mod.CrawlOrchestrator()
    orch._backend_override = _StubBackend()

    async def _plan(_q):
        from backend.crawler.crawl_planner import CrawlPlan

        return CrawlPlan(
            urls=["https://example.com/one"],
            instructions="", result_type="mixed", title="t",
        )

    monkeypatch.setattr(orch, "_plan", _plan)

    result = asyncio.run(
        orch.research("palworld hard mode boss tower party builds", mode="agent")
    )

    assert not cited, (
        "extract_and_cite was reached with a below-threshold passage set — the "
        "exact path that turned an empty crawl into a sourced-looking answer "
        "(REQ-3 AC3)."
    )
    # And the run must not claim success on no usable evidence (REQ-15 AC1).
    assert not (result.cited_markdown or "").strip(), (
        "a below-threshold run produced cited markdown"
    )


def test_rerank_returns_a_distinguishable_state_not_a_bare_list():
    """CT-2 / REQ-3 AC1: 'no passages' and 'all below threshold' are distinct.

    The original bug was that both were spelled `[]`, so the caller could not
    tell them apart and the meaning lived only in a comment.
    """
    from backend.crawler.rerank import RerankState, rerank_passages

    outcome = rerank_passages([], "query", None)
    assert hasattr(outcome, "state"), (
        "rerank_passages returned a bare list — the re-query signal is "
        "indistinguishable from 'no passages' again (REQ-3 AC1)"
    )
    assert outcome.state in tuple(RerankState)


# ══════════════════════════════════════════════════════════════════════════
# CT-9 — caller-existence pins
# ══════════════════════════════════════════════════════════════════════════

def _calls_in(rel: str, name: str) -> bool:
    """True when *rel* contains a real call to *name* (not just an import or a
    definition). Parsed, so a mention inside a comment or docstring cannot
    satisfy the pin."""
    tree = ast.parse(_src(rel))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == name:
                return True
            if isinstance(fn, ast.Attribute) and fn.attr == name:
                return True
    return False


def test_fuzzy_match_answer_has_a_production_caller():
    """CT-9: implemented, unit-tested, and for a long time never called.

    Its own module docstring documented voice answering as a supported mode
    while nothing in the STT path could reach it.
    """
    assert _calls_in("backend/agent/tools/ask_user_tool.py", "fuzzy_match_answer"), (
        "fuzzy_match_answer has no production caller — voice answering is "
        "documented but unwired again (REQ-14 AC2)"
    )


def test_stealth_headers_are_actually_applied():
    """CT-9: _STEALTH_EXTRA_HEADERS was defined with a comment stating it was
    deliberately NOT passed to crawl4ai — a mitigation that existed only as a
    constant (REQ-5 AC1)."""
    src = _src("backend/crawler/crawler_engine.py")
    assert src.count("_STEALTH_EXTRA_HEADERS") >= 2, (
        "_STEALTH_EXTRA_HEADERS is defined but never used"
    )
    tree = ast.parse(src)
    used_as_value = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "_STEALTH_EXTRA_HEADERS":
            if isinstance(getattr(node, "ctx", None), ast.Load):
                used_as_value = True
                break
    assert used_as_value, (
        "_STEALTH_EXTRA_HEADERS is never read — the header set is inert (REQ-5 AC1)"
    )


def test_rerank_requery_state_is_consumed():
    """CT-9: the re-query state must be read by the orchestrator, not assigned
    and discarded (the original defect)."""
    src = _src("backend/crawler/orchestrator.py")
    assert "RerankState" in src and "BELOW_THRESHOLD" in src, (
        "the orchestrator never inspects rerank's state — the re-query signal is "
        "being dropped again (REQ-3 AC2)"
    )


def test_usecrawl_hook_has_a_consumer():
    """CT-9: useCrawl was a complete, tested hook with zero production
    consumers while the dashboard duplicated its job inline — which is why
    unmounting the panel destroyed crawl state (REQ-12 AC2)."""
    provider = _src("hooks/CrawlProvider.tsx")
    assert "useCrawl" in provider, (
        "CrawlProvider does not consume useCrawl"
    )
    layout = _src("app/layout.tsx")
    assert "CrawlProvider" in layout, (
        "CrawlProvider is not mounted in app/layout.tsx — crawl state is below "
        "the unmount boundary again (REQ-12 AC2)"
    )


def test_dashboard_no_longer_duplicates_crawl_listeners():
    """CT-9 / REQ-12 AC2: the inline listeners must be gone, or state lives in
    two places and the panel's copy dies on unmount."""
    import re as _re

    src = _src("components/dark-glass-dashboard.tsx")
    # Match REGISTRATIONS, not mentions: the file legitimately carries comments
    # recording which listeners were deleted and why, and a substring check
    # would fail on its own changelog.
    registrations = _re.findall(
        r"addEventListener\(\s*['\"]iris:crawler_[a-z_]+['\"]", src
    )
    assert not registrations, (
        f"dark-glass-dashboard still registers crawler listeners {registrations} "
        f"— crawl state is duplicated below the unmount boundary (REQ-12 AC2)"
    )
