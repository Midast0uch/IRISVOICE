"""Contract (OQ-2 resolution, 2026-09-24): a confident NONE can stop the step.

Live finding (turn b0da0d28-8ba, provider gpt-oss:120b-cloud): after a failed
``read_file`` the recovery step got ``decision_engine decide consumer=tool_choice
chosen=NONE conf=0.936`` — and again NONE@0.918. Both times the ladder escalated,
the model was asked a second time with the tool schemas bound, and it named
``list_directory``: a full workspace browse for a file that does not exist. A
correct "no tool needed" answer could not stop the step.

The rule this pins (specs/tool-decision-engine OQ-2, AC3.2):
  * NONE at or above threshold AND a goal with no gather/action signal -> REASON;
  * NONE below threshold -> escalate (unchanged);
  * NONE on a goal that carries an action/gather signal -> escalate (unchanged,
    this is the session-345 conv-128 regression guard);
  * DELEGATE -> escalate (unchanged);
  * a memory suggestion still outranks the engine (unchanged).
"""

from __future__ import annotations

import time

from backend.agent.tool_decision import (
    DecisionKind,
    ToolDecisionBox,
    _goal_needs_action,
    _goal_needs_gather,
    _goal_records_terminal_failure,
)

import pytest

# Oracle Stage B (2026-10-05): the stand-in engine decides only through the
# real enforcement chokepoint; see conftest.oracle_decides_module.
ORACLE_DECIDES = ('tool_choice',)
pytestmark = pytest.mark.usefixtures("oracle_decides_module")


class _EngineDecision:
    """The attribute shape _engine_try reads from an engine decision."""

    def __init__(self, chosen, confidence):
        self.chosen = chosen
        self.confidence = confidence
        self.engine_latency_ms = 1
        self.stage_detail = None
        # REQ-28 (T43/T45): the evidence-prior applier reads `distribution`
        # (tool_decision.py:153/240). The real DecisionScore always carries it,
        # so the stub must too or the engine path raises AttributeError and the
        # box silently falls back to the legacy ladder. Fixture drift, added
        # 2026-09-26; no assertion in this file was touched. An empty tuple is
        # the honest "no per-candidate probabilities" case the code already
        # guards with `ds.distribution or ()`.
        self.distribution = ()


class _FakeEngine:
    model_id = "fake-350m"

    class _Cfg:
        candidate_cap = 8

    _cfg = _Cfg()

    def __init__(self, chosen, confidence):
        self._d = _EngineDecision(chosen, confidence)
        self.counters = None

    def decide(self, consumer, options, frame):
        return self._d


def _box():
    tools = ("list_directory", "read_file", "speak")
    return ToolDecisionBox(
        router=object(),
        tool_bridge=object(),
        get_available_tools=lambda: [
            {"name": n, "description": n, "category": "file"} for n in tools
        ],
        validate_tool_call=lambda name, params: (True, None),
        memory_lookup_fn=lambda _goal: None,
        decision_engine=None,
        use_decision_engine=False,
        decision_threshold=0.85,
    )


def _try(goal, chosen="NONE", conf=0.936):
    return _box()._engine_try(
        engine=_FakeEngine(chosen, conf),
        step={"description": goal, "task_class": "full"},
        goal=goal,
        evidence=None,
        start=time.perf_counter(),
        session_id="s",
        conversation_id="c",
    )


class TestGoalNeedsAction:
    def test_action_and_gather_signals_fire(self):
        for goal in (
            "search the web for the latest news",
            "read the file notes.txt",
            "list files in the project folder",
            "send an email to bob",
            "open C:/dev/IRISVOICE",
        ):
            assert _goal_needs_action(goal) is True, goal

    def test_a_pure_reasoning_goal_does_not(self):
        for goal in (
            "answer the question about recursion",
            "explain the difference between two ideas",
            "provide a concise summary",
            "",
        ):
            assert _goal_needs_action(goal) is False, goal

    def test_gather_signals_are_their_own_group(self):
        for goal in (
            "search the web for the latest news",
            "look up the release notes",
            "research the topic",
        ):
            assert _goal_needs_gather(goal) is True, goal
        for goal in (
            "answer the question about recursion",
            "write the summary to disk",
            "",
        ):
            assert _goal_needs_gather(goal) is False, goal

    def test_a_recorded_terminal_failure_is_recognised(self):
        # The exact live goal from turn b0da0d28-8ba.
        assert _goal_records_terminal_failure(
            "RESOLVE: result was not verified against the expected output: "
            "[Errno 2] No such file or directory: 'C:/dev/IRISVOICE/does_not_exist_42.txt'"
        ) is True
        assert _goal_records_terminal_failure(
            "explain the difference between two ideas"
        ) is False


class TestConfidentNoneCommits:
    def test_a_reasoning_goal_commits_as_reason(self):
        d = _try("answer the question about recursion")
        assert d is not None, (
            "the engine's confident NONE must commit, not escalate to a second "
            "model pass that names a tool anyway"
        )
        assert d.kind == DecisionKind.REASON
        assert d.source == "engine-none"
        assert (d.meta or {}).get("route") == "engine-none"

    def test_a_websearch_goal_still_escalates(self):
        # session-345 / conv-128 regression guard.
        assert _try("search the web for the latest NASA news") is None

    def test_a_file_goal_still_escalates(self):
        assert _try("read the file C:/dev/IRISVOICE/notes.txt") is None

    def test_a_recorded_terminal_failure_commits(self):
        # The exact live recovery goal and confidence from turn b0da0d28-8ba.
        d = _try(
            "RESOLVE: result was not verified against the expected output: "
            "[Errno 2] No such file or directory: "
            "'C:/dev/IRISVOICE/does_not_exist_42.txt'",
            conf=0.936,
        )
        assert d is not None, (
            "a recorded terminal failure must not re-enter the tool ladder — "
            "the file system already answered"
        )
        assert d.kind == DecisionKind.REASON

    def test_a_terminal_failure_plus_a_gather_signal_still_escalates(self):
        assert _try(
            "the file was not found; search the web for the correct name",
            conf=0.99,
        ) is None

    def test_a_low_confidence_terminal_failure_still_escalates(self):
        # Live turn 00677fe0-de0: the engine said NONE@0.601 for the recovery
        # step. Below threshold, so the escalation stayed correct.
        assert _try(
            "RESOLVE: [Errno 2] No such file or directory: "
            "'C:/dev/IRISVOICE/does_not_exist_42.txt'",
            conf=0.601,
        ) is None

    def test_a_low_confidence_none_still_escalates(self):
        assert _try("answer the question about recursion", conf=0.40) is None

    def test_delegate_still_escalates(self):
        assert _try(
            "answer the question about recursion", chosen="DELEGATE", conf=0.99
        ) is None
