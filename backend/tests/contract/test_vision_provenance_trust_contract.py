"""CT-10: vision provenance reaches the store, and its trust has a ceiling.

REQ-18 AC2 (provenance persisted) / AC3 (trust never above crawled web content)
and REQ-17 AC4/AC5 (one evidence record, disagreement kept).

Why this file exists: ``ContentOrigin`` was defined in
``backend/vision/frame_extraction.py`` and used ONLY inside that module. It never
reached ``_store_document_data`` or pacman, so once persisted, vision output was
indistinguishable from DOM-derived text. Worse, ``reconcile()`` — the function
that produces the origin and the disagreement — was imported by
``fetch_vision.py`` and called by nobody: its own comment deferred the work to
"the caller (orchestrator)", and the orchestrator never did it.

Two mechanisms, both fully implemented, both unreachable. That is instances #15
and #16 of this codebase's dominant failure mode, and it is exactly what CT-9's
caller-existence pins exist to prevent — extended here to the persistence layer.

The trust ceiling is asserted at the choke point rather than per call site: a
guard every document passes through cannot be forgotten by a future caller.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]


def _src(rel: str) -> str:
    p = _REPO / rel
    assert p.is_file(), f"expected {rel} at {p}"
    return p.read_text(encoding="utf-8", errors="replace")


# ══════════════════════════════════════════════════════════════════════════
# reconcile() must actually be called (REQ-17 AC4)
# ══════════════════════════════════════════════════════════════════════════

def test_reconcile_has_a_production_caller():
    """CT-9-style pin extended to REQ-17 AC4.

    An AST call check, not a substring: ``fetch_vision.py`` imports reconcile
    and mentions it in a comment while never invoking it, and a text match would
    have been satisfied by exactly that.
    """
    called_in: list[str] = []
    for rel in (
        "backend/crawler/orchestrator.py",
        "backend/vision/fetch_vision.py",
    ):
        tree = ast.parse(_src(rel))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = (
                    fn.id if isinstance(fn, ast.Name)
                    else fn.attr if isinstance(fn, ast.Attribute)
                    else None
                )
                if name == "reconcile":
                    called_in.append(rel)
                    break

    assert called_in, (
        "reconcile() has no production caller — crawl/vision evidence is never "
        "merged, so the disagreement diagnostic (design D9) does not exist at "
        "runtime (REQ-17 AC4)"
    )


def test_race_stamps_provenance_and_keeps_the_disagreement():
    """REQ-17 AC4/AC5 + REQ-18 AC2 through the real orchestrator race path.

    Crawl returns challenge boilerplate it wrongly extracted as content; vision
    sees the real page. Both are 'usable' by length, crawl wins the race by the
    cheaper-preferred rule — but the disagreement MUST survive, because that is
    the signal distinguishing 'crawl read a challenge' from 'vision missed
    something'.
    """
    import inspect

    from backend.crawler.capabilities import FetchOutcome
    from backend.crawler.crawler_engine import PageData
    from backend.crawler.orchestrator import CrawlOrchestrator
    from backend.crawler.usability import UsabilityReason, UsabilityVerdict

    def _page(url, markdown):
        return PageData(
            url=url, title="t", markdown=markdown, html="<html></html>",
            metadata={}, error=None, html_bytes=len(markdown),
        )

    url = "https://example.com/contested"
    ok = UsabilityVerdict(True, UsabilityReason.OK, "")
    crawl_out = FetchOutcome(
        url=url, capability="fetch.crawl",
        page=_page(url, "Enable JavaScript and cookies to continue browsing."),
        verdict=ok,
    )
    vision_out = FetchOutcome(
        url=url, capability="fetch.vision",
        page=_page(
            url,
            "Recommended party composition: a tank to absorb hits, a dedicated "
            "healer, and a burst damage dealer for the boss tower fight.",
        ),
        verdict=ok,
    )

    orch = CrawlOrchestrator()
    orch._stamp_evidence(crawl_out, [crawl_out, vision_out], url, "job-x")

    meta = crawl_out.page.metadata
    assert "content_origin" in meta, (
        "no provenance stamped on the winning page — vision-derived content is "
        "indistinguishable once persisted (REQ-18 AC2)"
    )
    assert meta["content_origin"] == "reconciled"
    assert meta.get("evidence_disagreement"), (
        "both sides produced text that diverges, but no disagreement was "
        "recorded — picking a winner silently erases the diagnosis (REQ-17 AC5)"
    )
    # _stamp_evidence is deliberately synchronous: it runs inside the race's hot
    # path and must not introduce an await point there.
    assert not inspect.iscoroutinefunction(orch._stamp_evidence)


def test_vision_only_result_is_marked_vision_origin():
    """REQ-17 AC6: vision-only content is flagged as such, not laundered into
    looking DOM-derived."""
    from backend.crawler.capabilities import FetchOutcome
    from backend.crawler.crawler_engine import PageData
    from backend.crawler.orchestrator import CrawlOrchestrator
    from backend.crawler.usability import UsabilityReason, UsabilityVerdict

    url = "https://example.com/image-heavy"
    page = PageData(
        url=url, title="t",
        markdown="Text that only the rendered page shows, read from the frame.",
        html="<html></html>", metadata={}, error=None, html_bytes=10,
    )
    vision_out = FetchOutcome(
        url=url, capability="fetch.vision", page=page,
        verdict=UsabilityVerdict(True, UsabilityReason.OK, ""),
    )
    CrawlOrchestrator()._stamp_evidence(vision_out, [vision_out], url, "job-y")
    assert page.metadata["content_origin"] == "vision"
    assert page.metadata.get("evidence_disagreement") == "vision_has_text_crawl_empty"


# ══════════════════════════════════════════════════════════════════════════
# Trust ceiling (REQ-18 AC3)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("origin", ["vision", "reconciled"])
def test_vision_content_cannot_be_stored_above_untrusted(origin):
    """REQ-18 AC3: a caller passing trust='trusted' with vision-derived content
    is DOWNGRADED, not honoured. Provenance beats the caller's claim."""
    from backend.agent.agent_kernel import AgentKernel

    assert AgentKernel._apply_trust_ceiling("trusted", origin) == "untrusted", (
        f"{origin}-derived content kept trust='trusted' — the ceiling must hold "
        f"even when the caller asks for more (REQ-18 AC3)"
    )
    # Already-untrusted stays untrusted (idempotent).
    assert AgentKernel._apply_trust_ceiling("untrusted", origin) == "untrusted"


def test_crawl_content_trust_is_unchanged_by_the_ceiling():
    """The ceiling must not downgrade ordinary documents — a guard that
    over-fires is its own defect."""
    from backend.agent.agent_kernel import AgentKernel

    assert AgentKernel._apply_trust_ceiling("trusted", "crawl") == "trusted"
    assert AgentKernel._apply_trust_ceiling("untrusted", "crawl") == "untrusted"


def test_store_document_data_applies_the_ceiling_and_persists_provenance():
    """Caller-existence pin for the ceiling itself (REQ-18 AC2/AC3).

    A pure guard nothing calls is the exact failure this spec exists to prevent,
    so assert by AST that ``_store_document_data`` invokes it and that the
    canonical payload carries ``content_origin``. Checked structurally because
    the surrounding storage calls are best-effort and swallowed by design, which
    makes the payload unobservable from outside without a live store.
    """
    src = _src("backend/agent/agent_kernel.py")
    tree = ast.parse(src)

    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_store_document_data":
            target = node
            break
    assert target is not None, "_store_document_data not found"

    calls = {
        n.func.attr
        for n in ast.walk(target)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert "_apply_trust_ceiling" in calls, (
        "_store_document_data does not apply the trust ceiling — vision content "
        "can be persisted at whatever trust the caller claims (REQ-18 AC3)"
    )

    # The canonical payload must carry provenance, or nothing downstream can
    # distinguish vision-derived text from DOM text (REQ-18 AC2).
    keys: set[str] = set()
    for n in ast.walk(target):
        if isinstance(n, ast.Dict):
            keys |= {
                k.value for k in n.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
    assert "content_origin" in keys, (
        "the canonical document payload has no content_origin field (REQ-18 AC2)"
    )
