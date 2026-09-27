"""Behavioral test: no heuristic overrides a confident engine choice.

REQ-3 AC3.3 (T3): a factual "what's" question routes the candidate menu to the
web tools and does NOT force the vision tools to the front — the twin of the
unit-level vocabulary pin in ``tests/unit/test_vision_tokens.py``.

REQ-9 AC9.3 (T12): when a goal matches research-class intent the
``_is_web_intent``-family heuristics must NOT force-downgrade ``search`` where
the engine confidently chose it — and the mirror case (an instant-lookup goal
where the engine confidently chose ``crawler_query``) must hold too.

The heuristics that DO steer web goals live in the graft-recovery resolver
(`agent_kernel.py:14777-14810`), where the step arrives with ``tool=None`` and
there is no engine choice to respect. This test pins the boundary: a step the
engine resolved confidently is returned as-is.
"""

from __future__ import annotations

from backend.agent.decision_engine import (
    CandidateScore,
    DecisionScore,
    EngineCounters,
)
from backend.agent.explorer import _is_web_intent
from backend.agent.tool_decision import DecisionKind, ToolDecisionBox


RESEARCH_GOAL = "research everything about the ai hardware market and gather sources"
INSTANT_GOAL = "what is the current price of the rtx 5090"
# AC3.3's query: starts with "what's" and is FACTUAL — the token the pre-T3
# vocabulary matched, which force-fronted a vision menu onto a web question.
FACTUAL_WHATS_GOAL = "what's the stock price of Apple"
VISION_PHRASE_GOAL = "what's on my screen"

WEB_MENU = [
    {"name": "search", "description": "INSTANT web lookup", "category": "web"},
    {"name": "crawler_query", "description": "DEEP MULTI-PAGE RESEARCH CRAWL",
     "category": "web"},
    {"name": "speak", "description": "Speak text", "category": "system"},
]

# Mixed registry with the vision tools LAST, so "vision fronted" is an
# observable reordering rather than the registry's own order.
MIXED_MENU = WEB_MENU + [
    {"name": "vision_analyze_screen", "description": "Analyze the screen",
     "category": "vision"},
    {"name": "vision_detect_element", "description": "Detect a UI element",
     "category": "vision"},
]
MIXED_NAMES = [t["name"] for t in MIXED_MENU]


class _FixedEngine:
    def __init__(self, chosen, confidence=0.99):
        self._chosen = chosen
        self._conf = confidence
        self.model_id = "stub"
        self.counters = EngineCounters()
        self.seen_options: list = []

    def decide(self, consumer_id, options, frame):
        self.seen_options = list(options)
        assert self._chosen in options, (
            f"{self._chosen!r} never reached the scorer; menu={options}"
        )
        return DecisionScore(
            consumer_id=consumer_id, chosen=self._chosen, confidence=self._conf,
            distribution=(CandidateScore(self._chosen, -0.05, self._conf),),
            engine_latency_ms=3,
        )

    def generate_args(self, consumer_id, option, schema, frame):
        class _R:
            retried = False
            args: dict = {}
        return _R()


class _BrainRouter:
    def __init__(self):
        self.calls = 0

    def generate(self, role, messages, **kw):
        self.calls += 1
        return ("", "", [])

    def resolve(self, role):
        class _R:
            id = "same"
            model = "same"
        return _R()


class _Bridge:
    async def execute_tool(self, tool, params, session_id="unknown",
                           decision_meta=None, **kw):
        return {"success": True}

    def record_decision(self, meta, kind, error=None, session_id="unknown"):
        pass


def _box(engine, menu=None):
    return ToolDecisionBox(
        router=_BrainRouter(),
        tool_bridge=_Bridge(),
        get_available_tools=lambda: menu if menu is not None else WEB_MENU,
        validate_tool_call=lambda n, p: (True, None),
        infer_fn=lambda prompt, **kw: "done",
        memory_lookup_fn=lambda _g: None,
        decision_engine=engine,
    )


class TestNoHeuristicOverrideAboveThreshold:
    def test_no_heuristic_override_above_threshold(self):
        """AC9.3: a confident `search` pick survives a research-class goal."""
        # The heuristic really does fire on this goal — otherwise the pin
        # would be vacuous.
        assert _is_web_intent(RESEARCH_GOAL) is True

        engine = _FixedEngine("search")
        box = _box(engine)
        router = box._router

        decision = box.resolve(step={"description": RESEARCH_GOAL})

        assert decision.kind == DecisionKind.TOOL
        assert decision.tool == "search", (
            "a research-class heuristic overrode the engine's confident pick"
        )
        assert router.calls == 0, "the Brain was consulted despite a confident pick"

    def test_instant_goal_does_not_downgrade_a_research_pick(self):
        """AC9.3 (mirror): the engine's confident `crawler_query` on an
        instant-lookup goal is respected too — the rule is symmetric."""
        engine = _FixedEngine("crawler_query")
        box = _box(engine)

        decision = box.resolve(step={"description": INSTANT_GOAL})

        assert decision.kind == DecisionKind.TOOL
        assert decision.tool == "crawler_query"


class TestFactualWhatsQueryRoutesToWeb:
    """REQ-3 AC3.3 (T3). The unit pin (``test_vision_tokens.py``) proves the
    vocabulary; this proves the BEHAVIOR the vocabulary exists for — the menu
    that reaches the scorer for a factual "what's" question is the web menu in
    registry order, with the vision tools neither fronted nor injected.
    """

    def test_whats_query_routes_to_web(self):
        """AC3.3: "what's the stock price of Apple" routes to a web tool and
        does NOT force the vision tools to the front."""
        engine = _FixedEngine("search")
        box = _box(engine, menu=MIXED_MENU)

        decision = box.resolve(step={"description": FACTUAL_WHATS_GOAL})

        assert decision.kind == DecisionKind.TOOL
        assert decision.tool == "search"
        # The menu reaches the scorer in registry order: nothing was floated
        # ahead of the web tools (the pre-T3 defect fronted the vision names).
        assert engine.seen_options[:len(MIXED_NAMES)] == MIXED_NAMES, (
            f"the candidate menu was reordered: {engine.seen_options}"
        )

    def test_vision_phrase_still_fronts_vision(self):
        """The control that makes AC3.3 non-vacuous: the SAME registry with a
        real multi-word vision phrase DOES float the vision names to the
        front — so the assertion above is testing the phrase rule, not an
        ordering accident."""
        engine = _FixedEngine("vision_analyze_screen")
        box = _box(engine, menu=MIXED_MENU)

        decision = box.resolve(step={"description": VISION_PHRASE_GOAL})

        assert decision.kind == DecisionKind.TOOL
        assert decision.tool == "vision_analyze_screen"
        assert engine.seen_options[0] == "vision_analyze_screen", (
            f"a vision phrase did not front the vision tools: {engine.seen_options}"
        )
        assert engine.seen_options[1] == "vision_detect_element"
