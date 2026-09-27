"""Contract tests: CT-DEI-15 — the engine is read-only w.r.t. the graph
(REQ-28 AC28.4, T44).

AC28.4 — THE ENGINE SHALL NEVER WRITE to the memory/graph store, and a contract
test SHALL assert zero writes on every decision path.

Owner decision (2026-09-25): the engine must never feed the pheromone loop. The
`tool_choice` edge writes belong to the EXECUTION layer
(`EdgeScorer.record_region_mediator_outcome`, `agent_kernel.py:16227`), derived
from the executed item — not from the engine's choice. This suite is the guard
that keeps it that way.
"""

from __future__ import annotations

from types import SimpleNamespace

import backend.agent.decision_backend_onnx as _onnx
import backend.agent.decision_engine as _de
import backend.agent.tool_decision as _td
from backend.agent.decision_engine import EngineConfig
from backend.memory.mycelium import interface as _iface
from backend.memory.mycelium import scorer as _scorer

# The graph-store write surface. Every one of these mutates persistent state.
_WRITE_SURFACE = (
    (_scorer.EdgeScorer, ("record_outcome", "record_region_mediator_outcome")),
    (_iface.MyceliumInterface, ("record_outcome", "crystallize_landmark")),
)

MENU = [
    {"name": "search", "description": "instant lookup", "category": "web"},
    {"name": "crawler_query", "description": "deep crawl", "category": "web"},
    {"name": "speak", "description": "speak", "category": "system"},
]


def _spy(name: str, sink: list):
    def _fn(self, *args, **kwargs):
        sink.append(name)
        return None
    return _fn


def _install_spies(monkeypatch, sink: list) -> None:
    for cls, names in _WRITE_SURFACE:
        for name in names:
            if hasattr(cls, name):
                monkeypatch.setattr(cls, name, _spy(name, sink), raising=False)


class TestZeroGraphWrites:
    def test_zero_graph_writes_all_paths(self, monkeypatch, onnx_backend):
        """AC28.4: drive every decision path; the graph store is never written."""
        writes: list = []
        _install_spies(monkeypatch, writes)

        # ── path 1: the ONNX backend directly ──────────────────────────────
        onnx_backend.decide("tool_choice", ["alpha", "beta"], {"goal": "pick"})
        # The batched path (`decide_many`) was removed 2026-09-26 by owner
        # decision — it was measured to change verdicts. The solo path above
        # and below is the only scoring path now, and this test's subject
        # (zero graph writes) is unchanged.

        # ── path 2: the engine (real backend, real config) ─────────────────
        eng = _de.DecisionEngine(EngineConfig())
        eng.decide("tool_choice", ["alpha", "beta"], {"goal": "pick"})
        eng.generate_args("tool_choice", "alpha", {}, {"goal": "pick"})
        eng.shutdown()

        # ── path 3: the box, including the new shadow + triage seams ───────
        class _Engine:
            model_id = "ro-stub"
            counters = _de.EngineCounters()
            _cfg = EngineConfig()

            def decide(self, consumer_id, options, frame):
                return _de.DecisionScore(
                    consumer_id=consumer_id, chosen=options[0], confidence=0.9,
                    distribution=tuple(
                        _de.CandidateScore(o, -0.1, 1.0 / len(options))
                        for o in options
                    ),
                    engine_latency_ms=1,
                )

        bridge = SimpleNamespace()
        box = _td.ToolDecisionBox(
            router=SimpleNamespace(generate=lambda *a, **kw: ("", "", [])),
            tool_bridge=bridge,
            get_available_tools=lambda: MENU,
            validate_tool_call=lambda t, p: (True, None),
            decision_engine=_Engine(),
        )
        box.resolve({"description": "find the price", "task_class": "full"},
                    evidence={"prior": {"crawler_query": {
                        "lower_bound": 0.4, "observations": 5,
                        "region": "web", "mediator": "crawl",
                        "freshness_s": 1.0}}},
                    session_id="s1", conversation_id="c1")
        box.recovery_strategy(failed_tool="crawler_query", objective="OBJ-1")
        box.record_shadow_tool_choice(
            goal="find the price", observed_tool="crawler_query")

        assert writes == [], (
            f"the engine wrote to the memory/graph store on a decision path: "
            f"{writes} — AC28.4 forbids it (the edge write belongs to the "
            "EXECUTION layer)"
        )

    def test_the_engine_modules_import_no_memory_layer(self):
        """AC28.4 by construction: the engine cannot write what it never
        imports. A future edit that adds a store dependency fails here."""
        for mod in (_de, _onnx):
            src = _read_module(mod)
            assert "backend.memory" not in src, (
                f"{mod.__name__} now imports the memory layer — the engine "
                "must stay read-only by construction (AC28.4)"
            )

    def test_the_engine_names_no_graph_write_api(self):
        """A write could also arrive via a duck-typed handle; name-check it."""
        forbidden = (
            "record_region_mediator_outcome", "crystallize_landmark",
            "record_outcome(", "add_edge(", "pin_add(",
        )
        for mod in (_de, _onnx):
            src = _read_module(mod)
            for token in forbidden:
                assert token not in src, (
                    f"{mod.__name__} names the graph write API {token!r} "
                    "(AC28.4)"
                )


def _read_module(mod) -> str:
    from pathlib import Path

    return Path(mod.__file__).read_text(encoding="utf-8", errors="replace")
