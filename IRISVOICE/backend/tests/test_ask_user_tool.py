"""
Tests for ask_user_tool.py — AskQuestion, AskPayload, AskUserTool
Source: specs/director_mode_system.md
Gate 1 Step 1.3 acceptance criteria.

Key requirements (from GOALS.md):
  - build_questions() returns None on empty model response
  - ingest_answers() never raises even with broken Mycelium

Run: python -m pytest backend/tests/test_ask_user_tool.py -v
"""

from unittest.mock import MagicMock, patch
import pytest


# ── Import sanity ──────────────────────────────────────────────────────────

def test_imports():
    from backend.agent.ask_user_tool import AskQuestion, AskPayload, AskUserTool
    assert AskQuestion
    assert AskPayload
    assert AskUserTool


# ── AskQuestion dataclass ─────────────────────────────────────────────────

def test_ask_question_defaults():
    from backend.agent.ask_user_tool import AskQuestion
    q = AskQuestion(id="q1", text="Which language?", type="single_select")
    assert q.options == []
    assert q.required is True


def test_ask_question_with_options():
    from backend.agent.ask_user_tool import AskQuestion
    q = AskQuestion(
        id="q1", text="Which db?", type="single_select",
        options=["postgres", "sqlite", "mysql"]
    )
    assert "postgres" in q.options
    assert len(q.options) == 3


# ── AskPayload dataclass ──────────────────────────────────────────────────

def test_ask_payload_fields():
    from backend.agent.ask_user_tool import AskQuestion, AskPayload
    q = AskQuestion(id="q1", text="Stack?", type="single_select",
                    options=["Python", "Go"])
    payload = AskPayload(questions=[q], context="need to choose stack")
    assert len(payload.questions) == 1
    assert payload.context == "need to choose stack"


# ── build_questions() — None on empty model response ──────────────────────

def test_build_questions_returns_none_on_empty_list():
    """Model returns empty questions list → None (no unnecessary asks)."""
    from backend.agent.ask_user_tool import AskUserTool
    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(
        raw_text='{"context":"x","questions":[]}'
    )
    tool = AskUserTool(adapter=adapter, memory_interface=MagicMock())
    result = tool.build_questions(
        task="build a login form",
        mode="implement",
        context_package=MagicMock(),
        is_mature=False,
    )
    assert result is None


def test_build_questions_returns_none_on_no_json():
    """Model returns unparseable text → None."""
    from backend.agent.ask_user_tool import AskUserTool
    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(raw_text="I don't know what to ask")
    tool = AskUserTool(adapter=adapter, memory_interface=MagicMock())
    result = tool.build_questions(
        task="do something", mode="implement",
        context_package=None, is_mature=False,
    )
    assert result is None


def test_build_questions_returns_none_on_adapter_exception():
    """Adapter raises → None, never raise."""
    from backend.agent.ask_user_tool import AskUserTool
    adapter = MagicMock()
    adapter.infer.side_effect = Exception("model down")
    tool = AskUserTool(adapter=adapter, memory_interface=MagicMock())
    result = tool.build_questions(
        task="do something", mode="implement",
        context_package=None, is_mature=False,
    )
    assert result is None


def test_build_questions_returns_payload_on_valid_response():
    """Valid model response → AskPayload with questions."""
    from backend.agent.ask_user_tool import AskUserTool, AskPayload
    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(raw_text=(
        '{"context":"need to know stack",'
        '"questions":['
        '{"id":"q1","text":"Which language?","type":"single_select",'
        '"options":["Python","Go"],"required":true}'
        ']}'
    ))
    tool = AskUserTool(adapter=adapter, memory_interface=MagicMock())
    result = tool.build_questions(
        task="build a service", mode="implement",
        context_package=None, is_mature=False,
    )
    assert isinstance(result, AskPayload)
    assert len(result.questions) == 1
    assert result.questions[0].id == "q1"
    assert "Python" in result.questions[0].options


def test_build_questions_caps_at_three():
    """More than 3 questions in response → hard-capped at 3."""
    from backend.agent.ask_user_tool import AskUserTool
    import json
    questions = [
        {"id": f"q{i}", "text": f"Q{i}?", "type": "free_text",
         "options": [], "required": True}
        for i in range(1, 6)  # 5 questions
    ]
    adapter = MagicMock()
    adapter.infer.return_value = MagicMock(
        raw_text=json.dumps({"context": "many", "questions": questions})
    )
    tool = AskUserTool(adapter=adapter, memory_interface=MagicMock())
    result = tool.build_questions(
        task="big task", mode="spec",
        context_package=None, is_mature=False,
    )
    assert result is not None
    assert len(result.questions) <= 3


# ── ingest_answers() — never raises ──────────────────────────────────────

def test_ingest_answers_never_raises_with_broken_mycelium():
    """Even if memory raises on every call, ingest_answers() must not raise."""
    from backend.agent.ask_user_tool import AskQuestion, AskUserTool
    memory = MagicMock()
    memory.mycelium_ingest_statement.side_effect = Exception("db down")
    tool = AskUserTool(adapter=MagicMock(), memory_interface=memory)
    questions = [
        AskQuestion(id="q1", text="Stack?", type="single_select",
                    options=["Python", "Go"]),
    ]
    # Must not raise
    tool.ingest_answers(
        answers={"q1": "Python"},
        questions=questions,
        session_id="sess_001",
    )


def test_ingest_answers_never_raises_on_empty_answers():
    from backend.agent.ask_user_tool import AskQuestion, AskUserTool
    tool = AskUserTool(adapter=MagicMock(), memory_interface=MagicMock())
    questions = [
        AskQuestion(id="q1", text="Stack?", type="single_select"),
    ]
    # Empty answers dict — must not raise
    tool.ingest_answers(answers={}, questions=questions, session_id="s1")


def test_ingest_answers_calls_memory_for_each_answer():
    """Each answered question gets an ingest call."""
    from backend.agent.ask_user_tool import AskQuestion, AskUserTool
    memory = MagicMock()
    tool = AskUserTool(adapter=MagicMock(), memory_interface=memory)
    questions = [
        AskQuestion(id="q1", text="Language?", type="single_select"),
        AskQuestion(id="q2", text="DB?", type="single_select"),
    ]
    tool.ingest_answers(
        answers={"q1": "Python", "q2": "Postgres"},
        questions=questions,
        session_id="s1",
    )
    assert memory.mycelium_ingest_statement.call_count == 2


def test_ingest_answers_skips_missing_answers():
    """Questions with no answer in the dict are silently skipped."""
    from backend.agent.ask_user_tool import AskQuestion, AskUserTool
    memory = MagicMock()
    tool = AskUserTool(adapter=MagicMock(), memory_interface=memory)
    questions = [
        AskQuestion(id="q1", text="A?", type="free_text"),
        AskQuestion(id="q2", text="B?", type="free_text"),
    ]
    # Only answer q1
    tool.ingest_answers(
        answers={"q1": "yes"},
        questions=questions,
        session_id="s1",
    )
    assert memory.mycelium_ingest_statement.call_count == 1


def test_ingest_answers_never_raises_on_none_memory():
    """Even if memory_interface is None-ish and crashes, no raise."""
    from backend.agent.ask_user_tool import AskQuestion, AskUserTool
    tool = AskUserTool(adapter=MagicMock(), memory_interface=None)
    questions = [AskQuestion(id="q1", text="X?", type="free_text")]
    # Must not raise even with None memory
    tool.ingest_answers(answers={"q1": "yes"}, questions=questions, session_id="s1")


# ── _parse_questions() internal ───────────────────────────────────────────

def test_parse_questions_bad_json_returns_none():
    from backend.agent.ask_user_tool import AskUserTool
    tool = AskUserTool(adapter=MagicMock(), memory_interface=MagicMock())
    result = tool._parse_questions("{not valid json}", "task", "mode")
    assert result is None


def test_parse_questions_missing_id_gets_fallback():
    """Question without id gets a generated fallback id."""
    from backend.agent.ask_user_tool import AskUserTool
    import json
    raw = json.dumps({
        "context": "need info",
        "questions": [{"text": "Which?", "type": "free_text", "options": []}]
    })
    tool = AskUserTool(adapter=MagicMock(), memory_interface=MagicMock())
    result = tool._parse_questions(raw, "t", "m")
    assert result is not None
    assert result.questions[0].id  # not empty
