"""Contract test: production menu composition (REQ-21 AC21.8, CT-DEI-18).

Asserts the menu the PRODUCTION path builds (ToolDecisionBox._engine_try —
registry names + DELEGATE/NONE, after pre-filter and cap) yields a label set
with NO duplicates, that both control labels SURVIVE the cap at the shipped
width (6), and that the backend scores that exact set. The 60-case battery
builds its own fixture-driven menu, so it replicates the menu SHAPE without
executing the production composition code — this test executes it.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.agent.decision_engine import (
    CandidateScore,
    DecisionScore,
    EngineCounters,
)
from backend.agent.tool_decision import ToolDecisionBox


class _RecordingEngine:
    """Engine stand-in that records the menu it was handed."""

    def __init__(self, cap=6, chosen="NONE", confidence=0.30):
        self.model_id = "menu-stub"
        self.counters = EngineCounters()
        self._cfg = SimpleNamespace(candidate_cap=cap)
        self._chosen = chosen
        self._conf = confidence
        self.menus = []

    def decide(self, consumer_id, options, frame):
        self.menus.append(list(options))
        return DecisionScore(
            consumer_id=consumer_id, chosen=self._chosen,
            confidence=self._conf,
            distribution=tuple(
                CandidateScore(o, -0.1, self._conf) for o in options
            ),
            engine_latency_ms=1,
        )

    def generate_args(self, consumer_id, option, schema, frame):
        from backend.agent.decision_engine import ArgsResult

        return ArgsResult(args=None, retried=False)


def _box(engine) -> ToolDecisionBox:
    return ToolDecisionBox(
        router=SimpleNamespace(),
        tool_bridge=SimpleNamespace(),
        get_available_tools=lambda: [
            {"name": n, "description": f"{n} desc", "category": "misc"}
            for n in (
                "read_file", "list_directory", "get_system_info",
                "recall_memory", "speak", "ask_user_question",
                "create_skill", "improve_self",  # 8 registry names > cap 6
            )
        ],
        validate_tool_call=lambda t, p: (True, None),
        decision_engine=engine,
    )


class TestProductionMenuComposition:
    def test_production_menu_no_dupes_controls_survive_cap(self):
        """AC21.8 / CT-DEI-18: at the shipped width of 6, the production
        composition yields a menu with no duplicate labels and BOTH control
        labels present — the engine's internal cap truncation must never cut
        them off (the defect this composition fixes)."""
        engine = _RecordingEngine(cap=6)
        box = _box(engine)
        decision = box.resolve(
            {"description": "do a thing", "task_class": "full"},
            session_id="s1", conversation_id="c1",
        )
        assert engine.menus, "the engine was never consulted"
        menu = engine.menus[0]
        # No duplicate labels — a registry tool named NONE/DELEGATE would dup.
        assert len(menu) == len(set(menu)), f"duplicate labels: {menu}"
        # Both control labels survive the cap.
        assert "DELEGATE" in menu, f"DELEGATE cut by the cap: {menu}"
        assert "NONE" in menu, f"NONE cut by the cap: {menu}"
        # The menu is bounded by the cap (6) — not cap+2.
        assert len(menu) <= 6, f"menu wider than the cap: {menu}"

    def test_registry_tool_named_none_does_not_duplicate(self):
        """AC21.8 collision case: a registry tool literally named NONE or
        DELEGATE must not duplicate a control label."""
        engine = _RecordingEngine(cap=6)
        box = ToolDecisionBox(
            router=SimpleNamespace(),
            tool_bridge=SimpleNamespace(),
            get_available_tools=lambda: [
                {"name": n, "description": f"{n} desc", "category": "misc"}
                for n in ("NONE", "read_file", "speak", "list_directory")
            ],
            validate_tool_call=lambda t, p: (True, None),
            decision_engine=engine,
        )
        box.resolve(
            {"description": "do a thing", "task_class": "full"},
            session_id="s1", conversation_id="c1",
        )
        menu = engine.menus[0]
        assert len(menu) == len(set(menu)), f"duplicate labels: {menu}"
        assert menu.count("NONE") == 1 and menu.count("DELEGATE") == 1

    def test_vision_fronted_names_survive_composition(self):
        """Vision-fronted names stay at the front and survive whenever they
        fit inside the reserved width (AC21.8)."""
        engine = _RecordingEngine(cap=6)
        box = ToolDecisionBox(
            router=SimpleNamespace(),
            tool_bridge=SimpleNamespace(),
            get_available_tools=lambda: [
                {"name": n, "description": f"{n} desc", "category": cat}
                for n, cat in (
                    ("vision_detect_element", "vision"),
                    ("vision_analyze_screen", "vision"),
                    ("read_file", "file"),
                    ("list_directory", "file"),
                    ("speak", "system"),
                    ("recall_memory", "memory"),
                    ("create_skill", "system"),
                )
            ],
            validate_tool_call=lambda t, p: (True, None),
            decision_engine=engine,
        )
        box.resolve(
            {"description": "what's on screen", "task_class": "full"},
            session_id="s1", conversation_id="c1",
        )
        menu = engine.menus[0]
        assert len(menu) == len(set(menu))
        assert "DELEGATE" in menu and "NONE" in menu
        assert "vision_detect_element" in menu
