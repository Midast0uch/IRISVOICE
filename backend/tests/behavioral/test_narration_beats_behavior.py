"""Behavioral: planned-beat authoring at task start (REQ-10, T12).

Drives the REAL `_plan_task` with a stubbed inference router (no LLM, no
audio) and asserts emergent planning-time properties:

  * multi-segment plan → beats parsed, stripped, kept (AC10.2)
  * single-segment plan → beats dropped by the duration gate (AC10.10)
  * beats absent/unparseable → [] (backward compatible, never a crash)
  * beat text preserved verbatim (engine never rewrites content, D10)
  * first beat admitted to the narration lane immediately (AC10.10)
  * no scheduler → silent skip, turn never blocked

Proving tests for tasks.md T12 (matrix rows AC10.1/AC10.2/AC10.10/AC10.12).
"""
from __future__ import annotations

import json
import types as _types
from unittest.mock import patch

from backend.agent.agent_kernel import AgentKernel


def _plan_json(steps, beats=None):
    obj = {
        "strategy": "do_it_myself",
        "reasoning": "test approach",
        "plan_title": "test plan",
        "steps": [
            {
                "step_id": f"s{i + 1}",
                "step_number": i + 1,
                "description": s,
                "depends_on": [],
                "critical": True,
            }
            for i, s in enumerate(steps)
        ],
    }
    if beats is not None:
        obj["beats"] = beats
    return json.dumps(obj)


class _StubRouter:
    """Canned planner output; captures the prompt for guidance assertions."""

    def __init__(self, *payloads):
        self._payloads = list(payloads)
        self.prompts: list = []
        self.last_usage = None

    # SETUP 2026-10-05: per-call keywords (the planner's reasoning_effort) are
    # accepted like InferenceRouter.generate(**kwargs); no assertion changed.
    def generate(self, kind, messages, max_tokens=0, temperature=0.0, **_kw):
        self.prompts.append(messages)
        text = self._payloads.pop(0) if self._payloads else ""
        return text, "", None


def _make_kernel(router):
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = "conv_test"
    k.session_id = "sess_test"
    k._current_turn_id = "turn_1"
    k._memory_interface = None
    k._is_mature = False
    k._personality = None
    k._router = router
    k._accrue_tokens = lambda *a, **k_: None
    k._caducean_modulate_temperature = lambda temp, sess: temp
    # REQ-24 AC24.2: the settled return type is str — this stub returned []
    # while the other five stub "None"; aligned 2026-09-25 (T34).
    k._get_failure_warnings = lambda text: "None"
    return k


def _plan(k, text="do the thing"):
    return k._plan_task(
        text=text,
        context=None,
        is_mature=False,
        task_class="full",
        context_package=None,
        mode="default",
        session_id="sess_test",
    )


class TestBeatAuthoring:
    def test_multi_segment_plan_keeps_beats(self):
        router = _StubRouter(
            _plan_json(
                ["Search the web", "Compare results"],
                beats=["  Checking current sources. ", "Comparing options now."],
            )
        )
        plan = _plan(_make_kernel(router))
        assert plan is not None
        assert plan.beats == ["Checking current sources.", "Comparing options now."]

    def test_single_segment_plan_drops_beats_duration_gate(self):
        """AC10.10: narration earns airtime only beyond the reply — a trivial
        plan's beats die at authoring, logged, never spoken."""
        router = _StubRouter(
            _plan_json(["Say hello"], beats=["Greeting you warmly."])
        )
        plan = _plan(_make_kernel(router))
        assert plan is not None
        assert plan.beats == []

    def test_missing_beats_key_is_backward_compatible(self):
        router = _StubRouter(_plan_json(["Step one", "Step two"]))
        plan = _plan(_make_kernel(router))
        assert plan is not None
        assert plan.beats == []

    def test_blank_beats_dropped(self):
        router = _StubRouter(
            _plan_json(["Step one", "Step two"], beats=["  ", "", "Real line."])
        )
        plan = _plan(_make_kernel(router))
        assert plan.beats == ["Real line."]

    def test_beat_text_preserved_verbatim(self):
        """The engine never rewrites content (D10) — even a mechanical line
        passes through untouched; quality is the prompt's job (T16 pins)."""
        router = _StubRouter(
            _plan_json(
                ["Step one", "Step two"],
                beats=["Splitting into subtasks now."],
            )
        )
        plan = _plan(_make_kernel(router))
        assert plan.beats == ["Splitting into subtasks now."]

    def test_prompt_carries_beats_guidance(self):
        router = _StubRouter(_plan_json(["Step one", "Step two"]))
        _plan(_make_kernel(router))
        full_prompt = router.prompts[0][0]["content"]
        assert '"beats"' in full_prompt
        assert "single-step" in full_prompt  # duration gate in the contract


class TestFirstBeatImmediate:
    def _admit(self, k, plan, scheduler):
        fake_kernel = _types.SimpleNamespace(scheduler=scheduler)
        with patch(
            "backend.agent.conversation_kernel.get_conversation_kernel",
            return_value=fake_kernel,
        ):
            k._admit_first_beat(plan, turn_id="t9", session_id="s9")

    def test_first_beat_admitted_to_narration_lane(self):
        from backend.agent.speech_lanes import KIND_PLANNED, NARRATION

        admitted: list = []

        class _FakeScheduler:
            def admit(self, node):
                admitted.append(node)

        k = _make_kernel(_StubRouter())
        plan = _types.SimpleNamespace(beats=["First line.", "Second line."])
        self._admit(k, plan, _FakeScheduler())
        assert len(admitted) == 1
        node = admitted[0]
        assert node.lane == NARRATION
        assert node.kind == KIND_PLANNED
        assert node.content["text"] == "First line."
        assert node.turn_id == "t9"
        assert node.session_id == "s9"

    def test_no_beats_no_admission(self):
        admitted: list = []

        class _FakeScheduler:
            def admit(self, node):
                admitted.append(node)

        k = _make_kernel(_StubRouter())
        self._admit(
            k, _types.SimpleNamespace(beats=[]), _FakeScheduler()
        )
        assert admitted == []

    def test_no_scheduler_silent_skip(self):
        k = _make_kernel(_StubRouter())
        with patch(
            "backend.agent.conversation_kernel.get_conversation_kernel",
            return_value=None,
        ):
            # Must not raise — beats are companion speech, never load-bearing.
            k._admit_first_beat(
                _types.SimpleNamespace(beats=["Hello."]),
                turn_id="t1",
                session_id="s1",
            )
