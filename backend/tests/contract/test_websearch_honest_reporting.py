"""
CT-5 (T5, REQ-15): honest reporting of fetch outcomes.

Spec: specs/vision-browser-websearch/requirements.md REQ-15, design.md CT-5.

  AC1  WHEN a research call produces no usable page THEN THE SYSTEM SHALL
       report the tool result as a failure (success=False) — never success=True.
  AC2  THE SYSTEM SHALL NOT report a tool result as both successful and
       permanently failed (success=True AND error_type="permanent" must be
       impossible at TOOL_DISPATCH).

Pins BOTH layers of the contradiction traced in production
(`[TOOL_DISPATCH] tool=crawler_query success=True error_type=permanent` on a
run that retrieved zero usable content):

  - tool_bridge._execute_crawler_query: a research result whose pages are all
    zero-usable (error=None but empty markdown — the reference "Palworld"
    shape the old gate counted as usable) must come back success=False; a
    result carrying an explicit error must stay success=False with the
    permanent envelope (honest failure), never flipped to success.
  - ToolDecisionBox.dispatch: the `_classify_error(None) == "permanent"` trap
    — a HEALTHY crawl with no error string — must not produce
    success=True + error_type="permanent", whether the permanent label comes
    from the heuristic or from an explicit envelope.

Run: python -m pytest backend/tests/contract/test_websearch_honest_reporting.py -v
"""

import asyncio

import pytest

from backend.agent.agent_kernel import (
    set_global_internet_access,
    get_global_internet_access,
)
from backend.agent.tool_bridge import AgentToolBridge
from backend.agent.tool_decision import ToolDecisionBox, Decision, DecisionKind
from backend.crawler.crawler_engine import CrawlResult, PageData


@pytest.fixture(autouse=True)
def _reset_internet_flag():
    """Web-mode flag is a process-wide global; each test here flips it ON and
    must restore it, or the capability gate (_internet_provider is wired to
    it) leaks into later tests (observed: capability_allowed(web_tool) came
    back True in the batch after this file ran). Default state is OFF."""
    set_global_internet_access(False)
    yield
    set_global_internet_access(False)


# ─────────────────────────────────────────────
# REQ-15 AC1 — tool-boundary honesty
# ─────────────────────────────────────────────

def test_zero_usable_content_is_never_success():
    """REQ-15 AC1 at the tool boundary: pages with error=None but EMPTY
    markdown (the old gate's counted-as-usable shape) must come back
    success=False — the orchestrator may have judged them "no error", but
    the content collector must not surface them as a successful crawl."""
    set_global_internet_access(True)

    class _FakeOrchestrator:
        async def research(self, query, **kwargs):
            return CrawlResult(
                query=query,
                pages=[
                    PageData(url="https://x.gov/a", title="A", markdown="", html="", metadata={}),
                    PageData(url="https://x.gov/b", title="B", markdown="   ", html="", metadata={}),
                ],
                duration_ms=10,
                crawled_at="2026-01-01T00:00:00+00:00",
            )

    from unittest.mock import patch

    with patch(
        "backend.crawler.orchestrator.get_crawl_orchestrator",
        return_value=_FakeOrchestrator(),
    ):
        result = asyncio.run(
            AgentToolBridge()._execute_crawler_query({"query": "x"}, "ct5-a")
        )

    assert result.get("success") is False
    assert result.get("error"), "zero usable content must carry an honest error"
    assert result.get("error_type") == "empty_result"


def test_explicit_research_error_stays_failure():
    """REQ-15 AC1: a research call that returns an explicit error must stay
    success=False with the permanent envelope — the fallback-note path must
    not flip it into a success."""
    set_global_internet_access(True)

    class _FakeOrchestrator:
        async def research(self, query, **kwargs):
            return CrawlResult(
                query=query,
                pages=[],
                duration_ms=10,
                crawled_at="2026-01-01T00:00:00+00:00",
                error="content below rerank threshold",
            )

    from unittest.mock import patch

    with patch(
        "backend.crawler.orchestrator.get_crawl_orchestrator",
        return_value=_FakeOrchestrator(),
    ):
        result = asyncio.run(
            AgentToolBridge()._execute_crawler_query({"query": "x"}, "ct5-b")
        )

    assert result.get("success") is False
    assert "below rerank" in result.get("error", "")
    assert result.get("error_type") == "permanent"


# ─────────────────────────────────────────────
# REQ-15 AC2 — TOOL_DISPATCH contradiction
# ─────────────────────────────────────────────

def _dispatch(fake_result):
    from unittest.mock import MagicMock, AsyncMock

    fake_bridge = MagicMock()
    fake_bridge.execute_tool = AsyncMock(return_value=fake_result)
    box = ToolDecisionBox(
        router=MagicMock(),
        tool_bridge=fake_bridge,
        get_available_tools=MagicMock(return_value=[]),
        validate_tool_call=MagicMock(return_value=(True, "")),
    )
    decision = Decision(kind=DecisionKind.TOOL, tool="crawler_query", params={"query": "x"})
    return box.dispatch(decision, session_id="s1", conversation_id="c1")


def test_dispatch_never_reports_success_true_with_permanent():
    """REQ-15 AC2: the traced contradiction — a HEALTHY crawl (success=True,
    no error string) whose None error the heuristic would classify as
    "permanent" — must NOT come out of TOOL_DISPATCH as success=True +
    error_type="permanent"."""
    dr = _dispatch({
        "success": True,
        "content": "# Example Domain\n\nReal content retrieved.",
    })
    assert dr.success is True
    assert dr.error_type != "permanent", (
        f"success=True with error_type=permanent is forbidden (got {dr.error_type!r})"
    )


def test_dispatch_neutralizes_explicit_permanent_on_success():
    """REQ-15 AC2: even an EXPLICIT error_type='permanent' in a successful
    tool envelope must be neutralized — the invariant holds regardless of
    where the permanent label came from."""
    dr = _dispatch({
        "success": True,
        "content": "x",
        "error_type": "permanent",  # buggy tool envelope — must not survive
    })
    assert dr.success is True
    assert dr.error_type != "permanent"


def test_dispatch_keeps_permanent_on_honest_failure():
    """REQ-15 AC2 sanity: success=False + permanent is the honest failure
    envelope and stays intact — only the success/permanent COMBINATION is
    forbidden."""
    dr = _dispatch({
        "success": False,
        "error": "no candidate urls",
        "error_type": "permanent",
    })
    assert dr.success is False
    assert dr.error_type == "permanent"
