"""Contract tests — T3 (REQ-5 multi-question, REQ-6 one answer funnel).

specs/task-card-v2-liquid-ink. Covers:
  - REQ-5 AC1/AC2: a question set of N questions is rendered/pending together.
  - REQ-5 AC5 / REQ-6 edge case: each question resolves INDEPENDENTLY through
    the same funnel — answering one leaves the others pending.
  - REQ-5 AC6 / CT-2: single-question sets stay backward compatible — the
    emitted payload also carries the legacy top-level keys.
  - REQ-6 AC3/AC5: first-wins, and an unknown question_id logs and never
    raises.
  - T3 design point 6: a multi_select answer round-trips as a list; a
    non-multi-select answer stays a string.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.agent.tools import ask_user_tool as _aut
from backend.agent.tools.ask_user_tool import QuestionSpec


@pytest.fixture(autouse=True)
def _reset_singletons():
    _aut.reset_ask_user_tool_for_testing()
    _aut.reset_parked_source_registry_for_testing()
    yield
    _aut.reset_ask_user_tool_for_testing()
    _aut.reset_parked_source_registry_for_testing()


# ── REQ-5 AC1/AC2: a set of 3 questions, all pending ────────────────────

def test_ask_set_of_three_questions_all_pending():
    tool = _aut.get_ask_user_tool()
    specs = [
        QuestionSpec(text="Which repo?", options=["a", "b"], header="Repo"),
        QuestionSpec(text="Which branch?", options=["main", "dev"], header="Branch"),
        QuestionSpec(text="Deploy now?", options=["yes", "no"], header="Deploy"),
    ]
    qset = tool.ask_set(specs, turn_id="sess-3q")

    assert len(qset.questions) == 3
    # Each question has its own id, and all start pending.
    ids = {q.question_id for q in qset.questions}
    assert len(ids) == 3
    assert all(q.status == "pending" for q in qset.questions)
    # All three are tracked in _pending, individually addressable.
    for q in qset.questions:
        assert tool._pending[q.question_id] is q
    # set_id links them back to the same set.
    assert all(q.set_id == qset.set_id for q in qset.questions)


def test_ask_set_emits_one_question_ask_event_with_all_questions():
    tool = _aut.get_ask_user_tool()
    specs = [
        QuestionSpec(text="Q1?", options=["a", "b"]),
        QuestionSpec(text="Q2?", options=["c", "d"]),
        QuestionSpec(text="Q3?", options=["e", "f"]),
    ]
    with patch.object(tool._bus, "emit") as mock_emit:
        qset = tool.ask_set(specs, turn_id="sess-emit")

    ask_events = [
        call for call in mock_emit.call_args_list
        if call[0][0].value == "question:ask"
    ]
    assert len(ask_events) == 1
    data = ask_events[0].kwargs.get("data") or ask_events[0][1].get("data")
    assert data["set_id"] == qset.set_id
    assert len(data["questions"]) == 3
    texts = {q["text"] for q in data["questions"]}
    assert texts == {"Q1?", "Q2?", "Q3?"}
    # N > 1 -> no legacy top-level mirror keys.
    assert "question_id" not in data
    assert "text" not in data


# ── REQ-5 AC5: independent resolution ───────────────────────────────────

def test_answering_one_question_in_a_set_leaves_others_pending():
    tool = _aut.get_ask_user_tool()
    specs = [
        QuestionSpec(text="Q1?", options=["a", "b"]),
        QuestionSpec(text="Q2?", options=["c", "d"]),
        QuestionSpec(text="Q3?", options=["e", "f"]),
    ]
    qset = tool.ask_set(specs, turn_id="sess-independent")
    q1, q2, q3 = qset.questions

    resolved = tool.resolve_answer(q2.question_id, "d")

    assert resolved is not None
    assert resolved.status == "answered"
    assert resolved.answer == "d"
    # The other two questions are untouched — still pending in _pending.
    assert q1.status == "pending"
    assert q3.status == "pending"
    assert q1.question_id in tool._pending
    assert q3.question_id in tool._pending
    assert q2.question_id not in tool._pending


# ── REQ-5 AC6 / CT-2: single-question back-compat payload ──────────────

def test_ask_set_with_one_question_mirrors_legacy_top_level_keys():
    tool = _aut.get_ask_user_tool()
    specs = [QuestionSpec(text="Continue?", options=["yes", "no"], allow_other=True)]
    with patch.object(tool._bus, "emit") as mock_emit:
        qset = tool.ask_set(specs, turn_id="sess-single")

    ask_events = [
        call for call in mock_emit.call_args_list
        if call[0][0].value == "question:ask"
    ]
    assert len(ask_events) == 1
    data = ask_events[0].kwargs.get("data") or ask_events[0][1].get("data")

    only = qset.questions[0]
    # New shape always present.
    assert data["set_id"] == qset.set_id
    assert len(data["questions"]) == 1
    # Legacy top-level mirror keys present because the set has exactly 1
    # question — this is what keeps an unmodified (pre-T10) QuestionCard
    # rendering correctly.
    assert data["question_id"] == only.question_id
    assert data["text"] == "Continue?"
    assert data["options"] == ["yes", "no"]
    assert data["allow_other"] is True


# ── REQ-6 AC3: first-wins ────────────────────────────────────────────────

def test_set_question_first_wins_on_second_answer():
    tool = _aut.get_ask_user_tool()
    qset = tool.ask_set([QuestionSpec(text="Pick", options=["x", "y"])], turn_id="s1")
    q = qset.questions[0]

    first = tool.resolve_answer(q.question_id, "x")
    assert first is not None
    assert first.answer == "x"

    second = tool.resolve_answer(q.question_id, "y")
    assert second is None


# ── REQ-6 AC5: unknown question_id logs, never raises ───────────────────

def test_resolve_answer_unknown_question_id_logs_and_does_not_raise(caplog):
    tool = _aut.get_ask_user_tool()
    import logging
    caplog.set_level(logging.WARNING, logger="backend.agent.tools.ask_user_tool")

    result = tool.resolve_answer("no_such_question", "whatever")

    assert result is None
    assert any("unknown question" in rec.message.lower() for rec in caplog.records)


def test_resolve_answer_already_resolved_question_id_logs_and_does_not_raise(caplog):
    tool = _aut.get_ask_user_tool()
    import logging
    caplog.set_level(logging.WARNING, logger="backend.agent.tools.ask_user_tool")

    q = tool.ask(text="Pick", options=["a", "b"], turn_id="s2")
    tool.resolve_answer(q.question_id, "a")
    caplog.clear()

    # Second resolution of the same, now-gone, question_id.
    result = tool.resolve_answer(q.question_id, "b")

    assert result is None
    assert any("unknown question" in rec.message.lower() for rec in caplog.records)


# ── T3 design point 6: multi_select normalization ───────────────────────

def test_multi_select_answer_round_trips_as_list():
    tool = _aut.get_ask_user_tool()
    qset = tool.ask_set(
        [QuestionSpec(text="Which files?", options=["a.py", "b.py", "c.py"], multi_select=True)],
        turn_id="s-multi",
    )
    q = qset.questions[0]

    resolved = tool.resolve_answer(q.question_id, ["a.py", "c.py"])

    assert resolved is not None
    assert resolved.answer == ["a.py", "c.py"]
    assert isinstance(resolved.answer, list)


def test_multi_select_answer_accepts_bare_string_and_wraps_in_list():
    """A single click on one option of a multi_select question still
    normalizes to a list, so downstream always sees one consistent type."""
    tool = _aut.get_ask_user_tool()
    qset = tool.ask_set(
        [QuestionSpec(text="Which files?", options=["a.py", "b.py"], multi_select=True)],
        turn_id="s-multi-2",
    )
    q = qset.questions[0]

    resolved = tool.resolve_answer(q.question_id, "a.py")

    assert resolved is not None
    assert resolved.answer == ["a.py"]


def test_non_multi_select_answer_stays_a_string():
    tool = _aut.get_ask_user_tool()
    qset = tool.ask_set(
        [QuestionSpec(text="Deploy?", options=["yes", "no"], multi_select=False)],
        turn_id="s-single-type",
    )
    q = qset.questions[0]

    resolved = tool.resolve_answer(q.question_id, "yes")

    assert resolved is not None
    assert resolved.answer == "yes"
    assert isinstance(resolved.answer, str)


# ── REQ-5 AC5 edge case: partial timeout reports mixed statuses ─────────

def test_wait_for_set_reports_answered_and_timed_out_independently():
    tool = _aut.get_ask_user_tool()
    qset = tool.ask_set(
        [
            QuestionSpec(text="Fast?", options=["a", "b"]),
            QuestionSpec(text="Slow?", options=["c", "d"]),
        ],
        timeout_seconds=1,
        turn_id="s-timeout",
    )
    fast, slow = qset.questions
    # Give "fast" a tiny timeout window that has already effectively
    # elapsed for "slow" only — answer fast immediately, let slow expire.
    slow.timeout_seconds = 0  # expires on first poll tick
    tool.resolve_answer(fast.question_id, "a")

    result = tool.wait_for_set(qset, poll_interval=0.01, filler_interval=999)

    assert result.questions[0].status == "answered"
    assert result.questions[0].answer == "a"
    assert result.questions[1].status == "timed_out"
