"""Behavioral tests — T15 (REQ-6): click, voice, and free-text answers all
resolve through the SAME answer funnel (first-wins + parked-source resume).

specs/task-card-v2-liquid-ink. Drives the REAL `AskUserTool`:

  - click/option-select  -> the gateway's `question_response` branch calls
                            `tool.resolve_answer(question_id, answer)`
                            (iris_gateway.py:5410 — pinned by
                            test_answer_funnel_baseline.py);
  - voice transcript     -> `tool.resolve_via_voice(transcript, session)`
                            -> `fuzzy_match_answer` -> `resolve_answer`;
  - free text            -> the gateway's `question_response` branch calls
                            `tool.resolve_answer(question_id, answer)`.

All three converge on `resolve_answer` — the SINGLE resolution funnel
(ask_user_tool.py:323). No input path gets special treatment: the resolved
answer value is identical across paths, first-wins holds (a second answer to
an already-answered question is ignored), and a parked source is resumed the
same way regardless of which path supplied the answer.
"""

from __future__ import annotations

import pytest

from backend.agent.tools import ask_user_tool as _aut
from backend.agent.tools.ask_user_tool import QuestionSpec


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset the AskUserTool + ParkedSourceRegistry singletons per test so
    pending questions / parked sources never leak across tests."""
    _aut.reset_ask_user_tool_for_testing()
    _aut.reset_parked_source_registry_for_testing()
    yield
    _aut.reset_ask_user_tool_for_testing()
    _aut.reset_parked_source_registry_for_testing()


class TestAllInputPathsShareOneFunnel:
    """REQ-6: click, voice, and free text resolve to the SAME answer through
    the single funnel — no input path gets special treatment."""

    def test_click_voice_free_text_resolve_to_same_answer(self):
        """A question set of three questions, one answered per input path.
        All three resolve to the same answer value ("yes") via the funnel."""
        tool = _aut.get_ask_user_tool()
        qset = tool.ask_set(
            [
                QuestionSpec(text="Proceed?", options=["yes", "no"]),  # (a) click
                QuestionSpec(text="Proceed?", options=["yes", "no"]),  # (b) voice
                QuestionSpec(text="Proceed?", options=["yes", "no"]),  # (c) free text
            ],
            turn_id="sess-funnel",
        )
        q_click, q_voice, q_text = qset.questions

        # (a) click/option-select — the gateway's question_response branch.
        click_resolved = tool.resolve_answer(q_click.question_id, "yes")
        # (c) free text — the gateway's question_response branch.
        text_resolved = tool.resolve_answer(q_text.question_id, "yes")
        # (b) voice — resolve_via_voice picks the most-recent still-pending
        # question for the session (q_voice: click and free text are already
        # answered), fuzzy-matches, then resolves through the same funnel.
        voice_result = tool.resolve_via_voice("yes", "sess-funnel")

        assert click_resolved is not None
        assert text_resolved is not None
        assert click_resolved.answer == "yes"
        assert text_resolved.answer == "yes"
        assert voice_result == {"handled": True, "resolved": "yes"}
        # The resolved answer value is IDENTICAL across all three input paths.
        assert click_resolved.answer == voice_result["resolved"] == text_resolved.answer == "yes"
        # All three questions resolved through the funnel (status answered).
        assert all(q.status == "answered" for q in (q_click, q_voice, q_text))

    def test_click_voice_free_text_all_resume_parked_source(self):
        """A parked source is resumed the same way no matter which input path
        supplied the answer (REQ-13 AC3 + REQ-6: no special treatment)."""
        tool = _aut.get_ask_user_tool()
        registry = _aut.get_parked_source_registry()

        # (a) click.
        q_click = tool.ask_non_blocking(
            "Wall?", options=["Skip", "Retry"],
            parked_url="https://click.example/x", run_id="run-click", turn_id="s-click",
        )
        click_resolved = tool.resolve_answer(q_click.question_id, "Skip")
        assert click_resolved is not None
        assert registry.get(q_click.question_id) is None  # resumed

        # (b) voice.
        q_voice = tool.ask_non_blocking(
            "Wall?", options=["Skip", "Retry"],
            parked_url="https://voice.example/x", run_id="run-voice", turn_id="s-voice",
        )
        voice_result = tool.resolve_via_voice("skip", "s-voice")
        assert voice_result == {"handled": True, "resolved": "Skip"}
        assert registry.get(q_voice.question_id) is None  # resumed

        # (c) free text.
        q_text = tool.ask_non_blocking(
            "Wall?", options=["Skip", "Retry"],
            parked_url="https://text.example/x", run_id="run-text", turn_id="s-text",
        )
        text_resolved = tool.resolve_answer(q_text.question_id, "Skip")
        assert text_resolved is not None
        assert registry.get(q_text.question_id) is None  # resumed

        # Same resolved answer value across all three paths.
        assert click_resolved.answer == voice_result["resolved"] == text_resolved.answer == "Skip"


class TestFirstWinsAcrossInputPaths:
    """REQ-6 AC3 / CT-4: first-wins holds across input paths — a second answer
    to an already-answered question is ignored, whatever path it arrives on."""

    def test_click_first_then_voice_ignored(self):
        tool = _aut.get_ask_user_tool()
        q = tool.ask("Proceed?", options=["yes", "no"], turn_id="sess-cv")

        first = tool.resolve_answer(q.question_id, "yes")  # click
        assert first is not None
        assert first.answer == "yes"

        # Voice arrives after the card resolved -> question gone -> normal path.
        late = tool.resolve_via_voice("no", "sess-cv")
        assert late == {"handled": False}
        assert q.answer == "yes"  # unchanged by the late voice answer

    def test_voice_first_then_click_ignored(self):
        tool = _aut.get_ask_user_tool()
        q = tool.ask("Proceed?", options=["yes", "no"], turn_id="sess-vc")

        voice = tool.resolve_via_voice("yes", "sess-vc")
        assert voice == {"handled": True, "resolved": "yes"}

        # Late card click -> no-op (question already resolved by voice).
        late = tool.resolve_answer(q.question_id, "no")
        assert late is None
        assert q.answer == "yes"

    def test_free_text_first_then_second_answer_ignored(self):
        tool = _aut.get_ask_user_tool()
        q = tool.ask("Proceed?", options=["yes", "no"], turn_id="sess-ft")

        first = tool.resolve_answer(q.question_id, "yes")  # free text
        assert first is not None
        assert first.answer == "yes"

        # A second answer to the same question -> ignored (first-wins).
        second = tool.resolve_answer(q.question_id, "no")
        assert second is None
        assert q.answer == "yes"

    def test_click_first_then_free_text_ignored(self):
        tool = _aut.get_ask_user_tool()
        q = tool.ask("Proceed?", options=["yes", "no"], turn_id="sess-cf")

        first = tool.resolve_answer(q.question_id, "yes")  # click
        assert first is not None

        late = tool.resolve_answer(q.question_id, "no")  # free text after
        assert late is None
        assert q.answer == "yes"