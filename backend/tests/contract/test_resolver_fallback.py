"""Contract tests: REQ-5 resolver fallback — non-research unparseable
does NOT route to the crawler.

Pins the boundary at the interface BEFORE behavior: propose() on an
unparseable, NON-research goal must fall back to kind="reasoning"
(or a pheromone top-1 tool), never crawler_query. A research goal
may resolve to crawler_query. This guards the audit finding that
non-research unparseable output was wrongly routed to the crawler.

Spec: specs/der-loop-integrity-display/requirements.md REQ-5.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.agent.explorer import propose


class _StubInfer:
    def __init__(self, raw):
        self._raw = raw

    def __call__(self, prompt, role=None, max_tokens=0, temperature=0.0):
        return SimpleNamespace(raw_text=self._raw)


class _NoMyc:
    pass


def _unparseable():
    # Garbage the extractor cannot turn into a dict.
    return "this is not json at all <<<"


def _live_tools(names):
    return [{"name": n} for n in names]


class TestResolverFallback:
    def test_non_research_unparseable_to_reasoning(self):
        # A reasoning/text goal that the LLM returned as garbage -> reason,
        # NOT crawler. myc=None so the web fallback cannot fire.
        res = propose(
            goal="explain why the sky is blue",
            evidence="",
            live_tools=_live_tools(["crawler_query", "speak", "reasoning"]),
            infer=_StubInfer(_unparseable()),
            myc=None,
            session_id="s1",
            task_class="reasoning",
            completed_tools=[],
        )
        assert res["kind"] == "reasoning"
        assert res["tool"] is None
        # Explicitly NOT the crawler.
        assert res["tool"] != "crawler_query"

    def test_research_goal_does_not_route_to_crawler_when_unparseable_and_no_web(self):
        # A research goal whose LLM output is garbage AND has no web capability
        # available must NOT silently become a crawler call — it falls back to
        # reasoning (the crawler requires a resolvable crawler_query spec +
        # capability check, which is absent here). The key REQ-5 invariant:
        # non-research-style unparseable output is never auto-crawled.
        res = propose(
            goal="research the history of jazz",
            evidence="",
            live_tools=_live_tools(["crawler_query", "speak"]),
            infer=_StubInfer(_unparseable()),
            myc=None,
            session_id="s1",
            task_class="research",
            completed_tools=[],
        )
        # Without a web capability, the crawler cannot fire -> reasoning.
        assert res["kind"] == "reasoning"
        assert res["tool"] != "crawler_query"

    def test_valid_tool_passthrough(self):
        # speak is a REAL registered tool -> valid JSON passes through.
        good = (
            '{"kind": "tool", "tool": "speak", "params": {"text": "hi"}, '
            '"rationale": "say hi"}'
        )
        res = propose(
            goal="say hello",
            evidence="",
            live_tools=_live_tools(["speak", "crawler_query"]),
            infer=_StubInfer(good),
            myc=None,
            session_id="s1",
            task_class="speak",
            completed_tools=[],
        )
        assert res["kind"] == "tool"
        assert res["tool"] == "speak"
