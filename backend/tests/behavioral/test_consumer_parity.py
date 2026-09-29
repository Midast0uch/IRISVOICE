"""Behavioral test: no enforcement below the bar (REQ-22 AC22.4).

A consumer below its bar stays shadow — the fail-closed threshold semantics:
no threshold entry for the active backend, or a confidence below the resolved
threshold, means the legacy path decides.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import backend.agent.decision_engine as de_mod
from backend.agent.decision_engine import (
    CandidateScore,
    DecisionScore,
    EngineCounters,
)


class _StubEngine:
    def __init__(self, chosen="speak", confidence=0.95, threshold=0.40):
        self.model_id = "stub"
        self.counters = EngineCounters()
        self._cfg = SimpleNamespace(
            backend_id="stub-backend",
            candidate_cap=6,
            threshold_for=lambda c: threshold,
        )
        self._chosen = chosen
        self._conf = confidence

    def decide(self, consumer_id, options, frame):
        return DecisionScore(
            consumer_id=consumer_id, chosen=self._chosen,
            confidence=self._conf,
            distribution=(CandidateScore(self._chosen, -0.1, self._conf),),
            engine_latency_ms=1,
        )


class TestNoEnforceBelowBar:
    def test_no_enforce_below_bar(self):
        """AC22.4: a confidence below the resolved threshold never enforces —
        the box escalates (the legacy ladder decides)."""
        from backend.agent.tool_decision import ToolDecisionBox

        engine = _StubEngine(chosen="read_file", confidence=0.30, threshold=0.40)
        box = ToolDecisionBox(
            router=SimpleNamespace(),
            tool_bridge=SimpleNamespace(),
            get_available_tools=lambda: [
                {"name": "read_file", "description": "d", "category": "file"}
            ],
            validate_tool_call=lambda t, p: (True, None),
            decision_engine=engine,
        )
        decision = box.resolve(
            {"description": "read the file", "task_class": "full"},
            session_id="s1", conversation_id="c1",
        )
        # The engine's pick was below threshold → the box escalates: the
        # decision comes from the legacy ladder, not the engine.
        meta = decision.meta or {}
        assert meta.get("route") == "escalated" or decision.source != "engine", (
            "a below-threshold pick must not enforce"
        )

    def test_fail_closed_no_threshold_entry(self):
        """AC25.8: no entry for the active backend → threshold_for returns
        None → the consumer stays shadow (fail-closed)."""
        from backend.agent.decision_engine import EngineConfig

        cfg = EngineConfig(backend_id="unknown-backend", backend_thresholds={})
        assert cfg.threshold_for("tool_choice") is None
        assert cfg.threshold_for("presentation") is None
        assert cfg.threshold_for("narration") is None


# ── REQ-19 AC19.4 (T25): tool_choice is unchanged by the Task refactor ─────


class TestToolChoiceUnchangedByTaskRefactor:
    def test_tool_choice_unchanged_by_task_refactor(self):
        """AC19.4: the Task used for `tool_choice` is byte-identical to the
        measured bench shape, and the frame's option descriptions are NOT
        rendered into it — the 0.40 threshold is only valid for the exact
        distribution it was measured on."""
        from backend.agent.decision_backend_onnx import (
            _TASK_INSTRUCTION,
            build_task,
        )

        opts = ["read_file", "list_directory", "NONE", "DELEGATE"]
        task = build_task("tool_choice", opts)

        assert task.name == "tool"
        assert task.instruction == _TASK_INSTRUCTION
        assert task.exclusive is True
        assert list(task.labels) == opts
        assert all(v is None for v in task.labels.values()), (
            "descriptions leaked into the tool_choice Task — the threshold "
            "curve no longer applies"
        )

        # The refactor must not have changed what `decide` produces either:
        # one exclusive Task, menu-wide softmax over exactly these labels.
        from backend.agent.decision_backend_onnx import GlinerOnnx

        class _Runner:
            def __init__(self):
                self.seen = None

            def logits(self, text, tasks):
                self.seen = tasks
                return {t.name: {l: float(i) for i, l in enumerate(t.labels)}
                        for t in tasks}

        runner = _Runner()
        backend = GlinerOnnx(model_dir="unused")
        backend._runner = runner
        ds = backend.decide("tool_choice", opts, {"goal": "read the readme"})

        assert ds is not None
        assert len(runner.seen) == 1
        assert runner.seen[0].instruction == _TASK_INSTRUCTION
        assert {c.name for c in ds.distribution} == set(opts)
        assert abs(sum(c.prob for c in ds.distribution) - 1.0) < 1e-9


# ── REQ-31 AC31.5/AC31.6 + REQ-29 AC29.6 (T52) ─────────────────────────────


class TestFlipOnlyOnTheMeasuredBar:
    def test_no_enforce_below_bar(self):
        """AC22.4: NO enforcement below the bar — every clause must hold."""
        from backend.agent.consumer_bar import derive_status

        # rows short
        assert derive_status(99, 0.99, 0.01)[0] == "shadow"
        # precision short
        assert derive_status(200, 0.89, 0.01)[0] == "shadow"
        # ECE over bound
        assert derive_status(200, 0.99, 0.20)[0] == "shadow"
        # ECE NOT MEASURED: precision alone cannot flip (AC18.4)
        status, gap = derive_status(200, 0.99, None)
        assert status == "shadow" and "ECE" in gap
        # every clause holds
        assert derive_status(200, 0.99, 0.01) == ("enforced", "")

    def test_flip_only_on_tg13_bar(self):
        """AC29.6: a consumer flips only on the measured bar, and its gap is
        recorded when it does not."""
        from backend.agent.consumer_bar import build_bar

        flipped = build_bar("has_gaps", {"rows": 150, "precision": 0.94,
                                        "ece": 0.02})
        assert flipped.status == "enforced" and flipped.gap == ""

        shadow = build_bar("use_thinking", {"rows": 40, "precision": 0.97,
                                            "ece": 0.01})
        assert shadow.status == "shadow"
        assert "rows 40" in shadow.gap, (
            "the missing clause must be recorded, not rounded up into a flip"
        )

    def test_tg7_stands_when_config_unchanged(self):
        """AC31.6 (Decision C): an UNCHANGED configuration re-validates
        nothing — no settled flip is re-litigated."""
        from backend.agent.consumer_bar import ConsumerBar, superseded_flips

        record = {"tool_choice": ConsumerBar(
            consumer_id="tool_choice", rows=500, precision=0.95, ece=0.01,
            status="enforced",
            config={"candidate_cap": 6, "backend_id": "gliner25-decide-onnx-int8"},
        )}
        deployed = {"candidate_cap": 6,
                    "backend_id": "gliner25-decide-onnx-int8"}

        assert superseded_flips(record, deployed) == [], (
            "a flip was invalidated although the configuration never moved — "
            "TG-7 remains authoritative (AC31.6)"
        )

    def test_a_superseded_configuration_invalidates_the_flip(self):
        """AC31.6: WHEN the configuration differs, the flip does NOT stand."""
        from backend.agent.consumer_bar import ConsumerBar, superseded_flips

        record = {"tool_choice": ConsumerBar(
            consumer_id="tool_choice", rows=500, precision=0.95, ece=0.01,
            status="enforced", config={"candidate_cap": 6},
        )}

        assert superseded_flips(record, {"candidate_cap": 10}) == [
            "tool_choice"
        ], "a flip measured at cap 6 survived a move to cap 10"


# ── REQ-14 AC14.2/AC14.3 (T22, BT-DEI-9): the Brain-skip saving ──────────────


class TestBoolSkipPositivePath:
    """The measured Brain spend of an ENFORCED monitor consumer.

    AC14.1 (shadow, the only shipped default) keeps the Brain in charge of the
    bool AND the text. AC14.3 spends nothing on a confident POSITIVE; AC14.2
    still pays for the TEXT on a negative branch — the engine never writes an
    assessment. AC14.4: a below-margin Noul leaves the Brain in charge.
    """

    class _Engine:
        model_id = "stub"

        def __init__(self, probability):
            self._p = probability

        def noul(self, consumer_id, statement, frame,
                 true_label="yes", false_label="no"):
            from backend.agent.decision_engine import Noul
            return Noul(consumer_id=consumer_id, probability=self._p,
                        engine_latency_ms=1)

    @staticmethod
    def _spend(engine, enforced, threshold=0.8):
        from backend.agent import monitor_shadow as ms

        calls = []

        def _brain_bool():
            calls.append("bool")
            return False  # the Brain would have disagreed with a confident engine

        def _brain_text():
            calls.append("text")
            return "evidence is missing"

        value, text, row = ms.monitor_bool(
            "sufficient", "is the evidence sufficient",
            brain_bool_fn=_brain_bool, brain_text_fn=_brain_text,
            engine=engine, enforced=enforced, threshold=threshold,
        )
        return calls, value, text, row

    def test_bool_skip_positive_path(self):
        """AC14.3: enforced + confident TRUE -> ZERO Brain calls."""
        calls, value, text, row = self._spend(self._Engine(0.97), enforced=True)
        assert calls == [], (
            "a confident positive branch spent a Brain call — the skip rate "
            "TG-7 reports would be zero"
        )
        assert value is True
        assert text == ""
        assert row is not None and row["shadow"] is True, (
            "the row is still recorded, so the saving is measurable"
        )

    def test_shadow_default_always_pays_the_brain(self):
        """AC14.1: the shipped default (enforced=False) is byte-identical to
        the legacy behavior — the Brain decides AND writes."""
        calls, value, text, row = self._spend(self._Engine(0.99), enforced=False)
        assert calls == ["bool", "text"]
        assert value is False  # the Brain's answer, not the engine's
        assert text == "evidence is missing"

    def test_negative_branch_still_pays_only_for_the_text(self):
        """AC14.2: a confident FALSE skips the bool call but the Brain still
        writes the text — the engine never authors an assessment."""
        calls, value, text, row = self._spend(self._Engine(0.03), enforced=True)
        assert calls == ["text"], (
            "the negative branch must not pay for the bool the engine supplied"
        )
        assert value is False
        assert text == "evidence is missing"

    def test_below_margin_leaves_the_brain_in_charge(self):
        """AC14.4: an unconfident Noul enforces nothing (fail-closed)."""
        calls, value, text, row = self._spend(self._Engine(0.55), enforced=True)
        assert calls == ["bool", "text"], (
            "a 0.55 probability is not decisive at a 0.8 margin — the Brain "
            "must still answer"
        )
        assert value is False
