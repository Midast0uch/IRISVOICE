"""Contract tests: the evidence seam's frame + row shape (REQ-28, T43/T45).

AC28.1 — the frame carries an `evidence` field and accepts it UNPOPULATED.
AC28.6 — the decision row records whether evidence was PRESENT and USED.

CT-DEI-15's zero-write half lives in `tests/contract/test_readonly_engine.py`.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.agent.decision_engine import (
    CandidateScore,
    DecisionScore,
    EngineCounters,
)
from backend.agent.tool_decision import ToolDecisionBox

MENU = [
    {"name": "search", "description": "instant lookup", "category": "web"},
    {"name": "crawler_query", "description": "deep crawl", "category": "web"},
    {"name": "speak", "description": "speak", "category": "system"},
]


class _RecordingEngine:
    """Records the frame it scored, and returns a fixed verdict."""

    def __init__(self, chosen="search", confidence=0.95):
        self._chosen, self._conf = chosen, confidence
        self.model_id = "evidence-stub"
        self.counters = EngineCounters()
        self.frames: list = []

    def decide(self, consumer_id, options, frame):
        self.frames.append(dict(frame))
        return DecisionScore(
            consumer_id=consumer_id, chosen=self._chosen, confidence=self._conf,
            distribution=tuple(
                CandidateScore(o, -0.1, 0.9 if o == self._chosen else 0.05)
                for o in options
            ),
            engine_latency_ms=2,
        )

    def generate_args(self, consumer_id, option, schema, frame):
        class _R:
            retried = False
            args = {"query": "x"}
        return _R()


def _box(engine, bridge=None):
    return ToolDecisionBox(
        router=SimpleNamespace(generate=lambda *a, **kw: ("", "", [])),
        tool_bridge=bridge or SimpleNamespace(),
        get_available_tools=lambda: MENU,
        validate_tool_call=lambda t, p: (True, None),
        decision_engine=engine,
    )


class _Bridge:
    def __init__(self):
        self.rows: list = []

    def record_decision(self, meta, kind, error=None, session_id="unknown"):
        self.rows.append((dict(meta), kind))


class TestFrameAcceptsUnpopulatedEvidence:
    def test_frame_accepts_unpopulated_evidence(self):
        """AC28.1: the field exists and is `{}` when no caller supplies one."""
        engine = _RecordingEngine()
        box = _box(engine)

        box.resolve({"description": "find the price", "task_class": "full"},
                    session_id="s1", conversation_id="c1")

        assert engine.frames, "the engine was never consulted"
        assert "evidence" in engine.frames[0], (
            "the frame has no `evidence` field (AC28.1)"
        )
        assert engine.frames[0]["evidence"] == {}, (
            "the unpopulated seam must be an EMPTY block, not a placeholder"
        )

    def test_absent_evidence_is_byte_identical(self):
        """AC28.1 edge: no evidence → the same verdict as before the seam."""
        engine = _RecordingEngine()
        box = _box(engine)

        with_nothing = box.resolve(
            {"description": "find the price", "task_class": "full"},
            session_id="s1", conversation_id="c1")
        # A turn-scoped cache would otherwise answer the identical question
        # from memory and hide the frame from this assertion.
        box._engine_cache.clear()
        engine.frames.clear()
        with_empty_dict = box.resolve(
            {"description": "find the price", "task_class": "full"},
            evidence={}, session_id="s1", conversation_id="c1")

        assert with_nothing.tool == with_empty_dict.tool
        assert engine.frames[0]["evidence"] == {}

    def test_a_supplied_prior_rides_the_frame(self):
        """AC28.2: a supplied payload reaches the frame SHAPED."""
        engine = _RecordingEngine()
        box = _box(engine)

        box.resolve(
            {"description": "find the price", "task_class": "full"},
            evidence={"prior": {"crawler_query": {
                "lower_bound": 0.3, "observations": 9,
                "region": "web", "mediator": "crawl", "freshness_s": 1.0,
            }}},
            session_id="s1", conversation_id="c1",
        )

        ev = engine.frames[0]["evidence"]
        assert "crawler_query" in ev
        assert ev["crawler_query"]["lower_bound"] == 0.3
        assert ev["crawler_query"]["observations"] == 9


class TestRowRecordsPresentAndUsed:
    def test_row_records_present_and_used(self):
        """AC28.6/AC28.7: present and used are recorded SEPARATELY.

        A TOOL decision carries its provenance on `Decision.meta` (its ledger
        row is written at dispatch, one row one writer), so the meta channel is
        where these fields must appear.
        """
        # (a) absent evidence → present False, used False
        box = _box(_RecordingEngine())
        d = box.resolve({"description": "find the price", "task_class": "full"},
                        session_id="s1", conversation_id="c1")
        assert d.meta is not None
        assert d.meta["evidence_present"] is False
        assert d.meta["evidence_used"] is False

        # (b) evidence present but reordering nothing → present True, used False
        box = _box(_RecordingEngine())
        d = box.resolve(
            {"description": "find the price", "task_class": "full"},
            evidence={"prior": {"speak": {
                "lower_bound": 0.0, "observations": 1,
                "region": "r", "mediator": "m", "freshness_s": 0.0,
            }}},
            session_id="s1", conversation_id="c1",
        )
        assert d.meta["evidence_present"] is True, (
            "a supplied payload was not recorded as present"
        )
        assert d.meta["evidence_used"] is False, (
            "an unused retrieval was scored as used — AC28.7 forbids it"
        )
