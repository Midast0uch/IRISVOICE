"""Contract (reply-surface-contract REQ-24, AC1 + AC3): a bounded content ask
never silently enters the research lane.

REQ-24 — live finding (conv-green-tea, 2026-09-24): "compare OLED versus LCD
displays for me" is a reasoning ask, yet it reached the tool lane and the DER
announced "We need to invoke web-search". The user never asked for fresh
facts. The rule is deterministic and free: no model call, no I/O, no state.

Pinned here:
  * ``semantic_gate.is_bounded_content_ask`` — the single rule. Freshness
    markers, explicit web phrasing and named evidence OBJECTS all keep the
    crawl lane open (AC3).
  * the kernel-side read of the turn text — the decision ladder sees
    model-rewritten step goals, so the USER's own phrasing is stashed per turn;
  * the veto itself: the hint the kernel returns for a bounded ask removes the
    heavy web gather tools from the decision candidates in BOTH resolution
    paths (engine-first and legacy), because both funnel through
    ``ToolDecisionBox._apply_pre_filter``.
"""

from __future__ import annotations

from pathlib import Path

import backend.agent.agent_kernel as ak
from backend.agent.semantic_gate import is_bounded_content_ask
from backend.agent.tool_decision import ToolDecisionBox

# The ask that produced the live finding, plus REQ-24's own examples.
_BOUNDED = [
    "compare OLED versus LCD displays for me",
    "compare OLED vs LCD",
    "explain how recursion works",
    "explain the ontology to me",
    "summarize this article for me",
    "write me a short note about sleep",
    "can you analyze the pros and cons of monorepos?",
    "calculate the total cost",
    "translate this text to French",
]

# Same verb, but the user WANTS current facts → research ask (AC3).
_NOT_BOUNDED_FRESH = [
    "what are the latest NASA Mars rover discoveries this month?",
    "search for the latest news on AI",
    "compare the current prices of the two cards",
    "what's the weather like today?",
]

# Same verb, but the ask is ABOUT a named object → it needs that object.
_NOT_BOUNDED_OBJECT = [
    "list files in the project folder",
    "write a file called notes.txt",
    "compare notes.txt with report.md",
    "summarize https://example.com/post",
    "explain the error in the backend log",
]

_NOT_BOUNDED_OTHER = [
    "search the web for quantum computing",
    "look up online the best restaurants",
    "hello",
    "",
    "   ",
    "Tool: do the thing",
]


class TestBoundedContentAskPredicate:
    """The rule itself — pure, deterministic, no model call."""

    def test_bounded_asks_are_bounded(self):
        for text in _BOUNDED:
            assert is_bounded_content_ask(text) is True, (
                f"a reasoning ask must not enter the research lane: {text!r}"
            )

    def test_freshness_markers_keep_the_crawl_lane(self):
        for text in _NOT_BOUNDED_FRESH:
            assert is_bounded_content_ask(text) is False, (
                f"a fresh-data ask keeps the crawl lane (AC3): {text!r}"
            )

    def test_named_evidence_objects_keep_the_crawl_lane(self):
        for text in _NOT_BOUNDED_OBJECT:
            assert is_bounded_content_ask(text) is False, (
                f"an ask about a named object needs that object: {text!r}"
            )

    def test_everything_else_is_not_bounded(self):
        for text in _NOT_BOUNDED_OTHER:
            assert is_bounded_content_ask(text) is False, (
                f"not a bounded content ask: {text!r}"
            )


class TestKernelReadsTheStashedTurnText:
    """The ladder sees step goals, not the user's ask — the kernel stashes it."""

    def _kernel(self, turn_text):
        k = ak.AgentKernel.__new__(ak.AgentKernel)
        if turn_text is not None:
            k._current_turn_text = turn_text
        return k

    def test_the_live_finding_is_bounded_on_the_kernel(self):
        k = self._kernel("compare OLED versus LCD displays for me")
        assert k._turn_is_bounded_content_ask() is True

    def test_a_fresh_data_ask_is_not_bounded_on_the_kernel(self):
        k = self._kernel("what are the latest NASA Mars rover discoveries?")
        assert k._turn_is_bounded_content_ask() is False

    def test_an_unknown_turn_applies_no_veto(self):
        # No stashed text (older call sites, direct unit construction) → the
        # crawl lane must behave exactly as it did before REQ-24.
        assert self._kernel(None)._turn_is_bounded_content_ask() is False


class TestBoundedAskVetoesWebGatherTools:
    """The veto reaches the candidate set both resolution paths share."""

    _TOOLS = [
        {"name": "crawler_query", "description": "crawl the web"},
        {"name": "web_search", "description": "search the web"},
        {"name": "get_rendered_documents", "description": "read gathered docs"},
        {"name": "read_file", "description": "read a file"},
        {"name": "speak", "description": "speak"},
    ]

    def _box(self, hint):
        return ToolDecisionBox(
            router=object(),
            tool_bridge=object(),
            get_available_tools=lambda: list(self._TOOLS),
            validate_tool_call=lambda name, params: (True, None),
            memory_lookup_fn=lambda _goal: hint,
            decision_engine=None,
            use_decision_engine=False,
        )

    def test_the_kernel_hint_shape_removes_the_web_gather_tools(self):
        # Exactly the dict the kernel returns for a bounded content ask.
        hint = {
            "tool": None,
            "veto": sorted(ak.AgentKernel._WEB_CONTENT_TOOLS),
            "rationale": "bounded_content_ask",
        }
        kept = [
            t["name"]
            for t in self._box(hint)._apply_pre_filter(
                self._TOOLS, hint, "compare OLED versus LCD displays"
            )
        ]
        for name in ak.AgentKernel._WEB_CONTENT_TOOLS:
            assert name not in kept, f"{name} must not be a candidate (REQ-24)"
        assert "get_rendered_documents" in kept   # reading is still allowed
        assert "read_file" in kept

    def test_without_the_veto_the_web_tools_stay(self):
        kept = [
            t["name"]
            for t in self._box(None)._apply_pre_filter(
                self._TOOLS, None, "compare OLED versus LCD displays"
            )
        ]
        assert "crawler_query" in kept


class TestTheVetoIsWiredIntoTheGatherHint:
    """Source pin: the veto cannot be dropped from the gate silently."""

    def test_kernel_consults_the_bounded_ask_rule(self):
        src = Path(ak.__file__).read_text(encoding="utf-8", errors="replace")
        assert "if self._turn_is_bounded_content_ask():" in src
        assert '"rationale": "bounded_content_ask",' in src
        assert '"veto": sorted(self._WEB_CONTENT_TOOLS),' in src


class TestVetoOrderInTheGatherHint:
    """ORDER pin — live finding 2026-09-24: the veto must come FIRST.

    ``_mem_lookup`` sanctions ``crawler_query`` for a web-phrased goal and
    RETURNS. The planner rewrites a bounded ask into exactly that phrasing
    ("Search the web for recent comparisons of OLED and LCD displays..."), so a
    veto placed AFTER the sanction is unreachable: the live turn resolved
    ``crawler_query`` with ``source=memory`` and read 5 pages of the web for an
    ask whose user never asked for fresh facts. A guard must precede the branch
    it pre-empts — a logic test cannot see that, a source-order test can.
    """

    def test_the_veto_precedes_the_web_intent_sanction(self):
        src = Path(ak.__file__).read_text(encoding="utf-8", errors="replace")
        veto = src.index("if self._turn_is_bounded_content_ask():")
        sanction = src.index('"rationale": "web-intent (memory pre-filter)"')
        assert veto < sanction, (
            "the bounded-ask veto must precede the web-intent sanction, or a "
            "web-phrased step goal crawls anyway (live 2026-09-24)"
        )

    def test_the_veto_precedes_the_synthesis_read_steering(self):
        src = Path(ak.__file__).read_text(encoding="utf-8", errors="replace")
        veto = src.index("if self._turn_is_bounded_content_ask():")
        steering = src.index(
            "REQ-3 AC4 / REQ-5 (specs/long-horizon-der-execution)"
        )
        assert veto < steering, (
            "a bounded turn has no gathered evidence to read, so the veto must "
            "not sit behind the read-steering either"
        )
