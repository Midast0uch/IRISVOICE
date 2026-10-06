"""Contract tests: the review_verdict consumer's envelope (REQ-13 AC13.1, T17).

CT-DEI-6 — Verdict/Bool Consumer Shapes: `review_verdict` decisions carry the
standard consumer envelope (chosen, confidence, candidates, latency) so
calibration joins work uniformly.

AC13.1 is FOUNDATION (shadow): rows are recorded, the Brain verdict still
decides. AC13.2: the engine never writes step text.
"""

from __future__ import annotations

from backend.agent.decision_engine import (
    CandidateScore,
    DecisionScore,
    EngineCounters,
)
from backend.agent.der_loop import Reviewer, ReviewVerdict


class _VerdictEngine:
    def __init__(self, chosen="pass", confidence=0.93):
        self._chosen = chosen
        self._conf = confidence
        self.model_id = "verdict-stub"
        self.counters = EngineCounters()
        self.calls: list = []

    def decide(self, consumer_id, options, frame):
        self.calls.append((consumer_id, list(options)))
        return DecisionScore(
            consumer_id=consumer_id, chosen=self._chosen,
            confidence=self._conf,
            distribution=tuple(
                CandidateScore(o, -0.1, 0.9 if o == self._chosen else 0.05)
                for o in options
            ),
            engine_latency_ms=2,
        )


class _Adapter:
    """Brain stand-in returning a fixed verdict JSON."""

    def __init__(self, raw='{"verdict": "refine", "refined": "tighten step 2"}'):
        self._raw = raw
        self.calls = 0

    def infer(self, prompt, role="EXECUTION", max_tokens=200, temperature=0.0):
        self.calls += 1
        from types import SimpleNamespace
        return SimpleNamespace(raw_text=self._raw)


class _Ctx:
    gradient_warnings = ""
    active_contracts = ""


def _reviewer(engine, raw=None):
    r = Reviewer(_Adapter(raw) if raw else _Adapter(), None)
    r.set_review_engine(engine)
    return r


def _item(desc="read the readme", objective="OBJ-1"):
    from backend.agent.der_loop import QueueItem
    return QueueItem(step_id="s1", step_number=1, description=desc,
                     objective_anchor=objective)


class TestReviewVerdictShadowRow:
    def test_review_verdict_shadow_row(self):
        """AC13.1 / CT-DEI-6: a well-formed shadow row is produced, and the
        BRAIN verdict still decides (shadow never steers)."""
        engine = _VerdictEngine(chosen="pass", confidence=0.93)
        reviewer = _reviewer(engine)

        verdict, out = reviewer.review(_item(), [], _Ctx(), is_mature=True)

        # ── the Brain still decides (shadow) ──
        assert verdict == ReviewVerdict.REFINE, (
            "the engine verdict steered the loop — AC13.1 is shadow-only"
        )
        assert out == "tighten step 2"

        # ── the row exists with the standard consumer envelope ──
        row = reviewer.last_shadow_verdict
        assert row is not None, "no shadow row was produced"
        assert row["consumer_id"] == "review_verdict"
        assert row["chosen"] == "pass"
        assert 0.0 <= row["confidence"] <= 1.0
        assert {c["name"] for c in row["candidates"]} == {"pass", "refine", "veto"}
        assert all(0.0 <= c["prob"] <= 1.0 for c in row["candidates"])
        assert row["engine_latency_ms"] >= 0
        assert row["shadow"] is True
        # the shadow PAIR: what the engine said vs what actually ran
        assert row["brain_verdict"] == "refine"

    def test_shadow_row_records_the_consumer_and_its_own_labels(self):
        """AC13.1/AC19.3: the consumer is scored under its OWN labels."""
        engine = _VerdictEngine()
        reviewer = _reviewer(engine)
        reviewer.review(_item(), [], _Ctx(), is_mature=True)

        assert engine.calls, "the engine was never consulted"
        consumer_id, labels = engine.calls[0]
        assert consumer_id == "review_verdict"
        assert labels == ["pass", "refine", "veto"]

    def test_no_engine_means_no_row_and_no_behaviour_change(self):
        """A missing engine adds no row and changes nothing (shadow must never
        fabricate a row)."""
        reviewer = _reviewer(None)  # set_review_engine(None) = explicitly off

        verdict, out = reviewer.review(_item(), [], _Ctx(), is_mature=True)

        assert verdict == ReviewVerdict.REFINE
        assert reviewer.last_shadow_verdict is None

    def test_immature_step_is_also_shadow_scored(self):
        """The heuristic branch (immature / no context package) is shadow-scored
        too, so the parity metric covers every verdict the loop takes."""
        engine = _VerdictEngine(chosen="veto")
        reviewer = _reviewer(engine)

        verdict, _ = reviewer.review(_item(), [], object(), is_mature=False)

        assert verdict in (ReviewVerdict.PASS, ReviewVerdict.VETO,
                           ReviewVerdict.REFINE)
        assert reviewer.last_shadow_verdict is not None
        assert reviewer.last_shadow_verdict["chosen"] == "veto"


# ── REQ-14 AC14.1 (T18): the three loop-monitor bool consumers ─────────────


class TestMonitorBoolShadowRows:
    def test_monitor_bool_shadow_rows(self):
        """AC14.1 / CT-DEI-6: each of the three bool consumers emits a
        well-formed shadow row while the Brain call stays unchanged."""
        from backend.agent import monitor_shadow as ms
        from backend.agent.decision_engine import Noul

        class _Eng:
            def __init__(self, p):
                self._p = p
                self.seen: list = []

            def noul(self, consumer_id, statement, frame, *,
                     true_label="yes", false_label="no"):
                self.seen.append(consumer_id)
                return Noul(consumer_id=consumer_id, probability=self._p,
                            engine_latency_ms=2)

        # `on_track` removed 2026-10-05 (Oracle Stage B, owner-approved).
        for cid in ("sufficient", "done"):
            eng = _Eng(p=0.91)
            calls = {"bool": 0, "text": 0}

            def _bool():
                calls["bool"] += 1
                return True

            def _text():
                calls["text"] += 1
                return "n/a"

            value, text, row = ms.monitor_bool(
                cid, ms.MONITOR_CONSUMERS[cid],
                brain_bool_fn=_bool, brain_text_fn=_text, engine=eng,
            )

            # the Brain still decides in shadow (AC14.1)
            assert value is True and calls["bool"] == 1
            assert text == "" and calls["text"] == 0
            # and a well-formed row was produced under this consumer's id
            assert row is not None, cid
            assert row["consumer_id"] == cid
            assert row["shadow"] is True
            assert 0.0 <= row["probability"] <= 1.0
            assert row["brain_bool"] is True
            assert eng.seen == [cid]


# ── REQ-15 AC15.2 (T19): the mode consumer's measured confidence ───────────


class TestModeConfidenceMeasured:
    def test_mode_confidence_measured(self, oracle_decides):
        """AC15.2: the inference branch reports the ENGINE's measured
        probability for the chosen mode, not the hand-set keyword float.

        Stage B (2026-10-05) setup change, assertions unchanged: the engine's
        probability replaces the keyword confidence only when `mode` decides
        through the enforcement chokepoint (the stand-in's 0.72 clears a fitted
        threshold of 0.70)."""
        from backend.agent.mode_detector import AgentMode, ModeDetector

        oracle_decides("mode", threshold=0.70)

        class _Eng:
            def decide(self, consumer_id, options, frame):
                probs = {"implement": 0.72, "research": 0.11, "spec": 0.04,
                         "debug": 0.05, "test": 0.04, "review": 0.04}
                return DecisionScore(
                    consumer_id=consumer_id, chosen="implement",
                    confidence=0.72,
                    distribution=tuple(
                        CandidateScore(n, -0.1, probs.get(n, 0.0))
                        for n in options
                    ),
                    engine_latency_ms=2,
                )

        detector = ModeDetector()
        detector.set_mode_engine(_Eng())

        result = detector.detect("please write the code for the uploader")

        assert result.mode == AgentMode.IMPLEMENT   # keyword still decides
        assert abs(result.confidence - 0.72) < 1e-9, (
            f"the confidence is still the hand-set keyword float "
            f"({result.confidence}) instead of the engine's measurement"
        )

    def test_mode_consumer_scored_under_its_own_labels(self):
        """AC19.3: the mode consumer is scored with the six mode labels and
        its own instruction — never another consumer's head."""
        from backend.agent.decision_backend_onnx import get_consumer_spec
        from backend.agent.mode_detector import ModeDetector

        class _Eng:
            def __init__(self):
                self.calls: list = []

            def decide(self, consumer_id, options, frame):
                self.calls.append((consumer_id, list(options), frame))
                return DecisionScore(
                    consumer_id=consumer_id, chosen=options[0], confidence=0.5,
                    distribution=tuple(
                        CandidateScore(o, -0.1, 1.0 / len(options))
                        for o in options
                    ),
                    engine_latency_ms=1,
                )

        eng = _Eng()
        detector = ModeDetector()
        detector.set_mode_engine(eng)
        detector.detect("write the code")
        # Stage B (2026-10-05): a mode that does not decide is scored on the
        # oracle_shadow lane; the call is observable once the lane drains.
        from backend.utils.durability_queue import lane

        assert lane("oracle_shadow").flush(10.0)

        assert eng.calls, "the mode consumer was never scored"
        consumer_id, labels, frame = eng.calls[0]
        assert consumer_id == "review_verdict" or consumer_id == "mode"
        assert set(labels) == set(ModeDetector.MODE_LABELS)
        spec = get_consumer_spec("mode")
        assert spec is not None
        assert spec.instruction == ModeDetector.MODE_INSTRUCTION


# ── REQ-17 AC17.1/AC17.2 (T21): the failure-triage shadow row ──────────────


class TestTriageShadowRow:
    def test_triage_shadow_row(self):
        """AC17.1 / CT-DEI-6: the triage consumer offers `retry_same` and emits
        a well-formed shadow row pairing the engine's verdict with the counters'
        decision — while the counters keep deciding (AC17.2)."""
        from backend.agent.tool_decision import ToolDecisionBox

        class _TriageEngine:
            def __init__(self, chosen, conf):
                self._chosen, self._conf = chosen, conf
                self.model_id = "triage-stub"
                self.counters = EngineCounters()
                self.menus: list = []

            def decide(self, consumer_id, options, frame):
                self.menus.append((consumer_id, list(options), dict(frame)))
                return DecisionScore(
                    consumer_id=consumer_id, chosen=self._chosen,
                    confidence=self._conf,
                    distribution=tuple(
                        CandidateScore(o, -0.1,
                                       0.9 if o == self._chosen else 0.02)
                        for o in options
                    ),
                    engine_latency_ms=2,
                )

        rows: list = []

        class _Bridge:
            def record_decision(self, meta, kind, error=None,
                                session_id="unknown"):
                rows.append((dict(meta), kind))

        engine = _TriageEngine("retry_same", 0.97)
        box = ToolDecisionBox(
            router=_Adapter(),
            tool_bridge=_Bridge(),
            get_available_tools=lambda: [],
            validate_tool_call=lambda t, p: (True, None),
            decision_engine=engine,
        )

        out = box.recovery_strategy(
            failed_tool="crawler_query", error_snippet="upstream timeout",
            objective="OBJ-T21",
        )
        # Stage B (2026-10-05): the triage does not decide (the counters do), so
        # its Oracle score and row are produced on the oracle_shadow lane.
        from backend.utils.durability_queue import lane

        assert lane("oracle_shadow").flush(10.0)

        # AC17.2: the counters decide — a confident `retry_same` never steers.
        assert out["strategy"] != "retry_same"
        assert out["delegate"] is True

        # AC17.1: `retry_same` was OFFERED to the consumer.
        assert engine.menus, "the triage consumer was never consulted"
        assert engine.menus[0][0] == "recovery_strategy"
        assert "retry_same" in engine.menus[0][1]

        # CT-DEI-6: a well-formed shadow row exists.
        row = box.last_triage_shadow
        assert row is not None, "no triage shadow row was produced"
        assert row["consumer_id"] == "recovery_strategy"
        assert row["chosen"] == "retry_same"
        assert 0.0 <= row["confidence"] <= 1.0
        assert {c["name"] for c in row["candidates"]} >= {
            "retry_same", "retry_different_tool", "decompose", "escalate"}
        assert all(0.0 <= c["prob"] <= 1.0 for c in row["candidates"])
        assert row["engine_latency_ms"] >= 0
        assert row["shadow"] is True
        # the shadow PAIR: the engine said retry_same; the counters said delegate
        assert row["counter_choice"] == "delegate"
        # and it reached the ledger's single writer
        assert rows and rows[0][1] == "shadow"
