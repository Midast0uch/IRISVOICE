"""
Tests for planner routing (REQ-4, corrected 2026-07-19).

`_needs_planning` uses a layered, rule-first intent classifier (the "router"
pattern).  Direct path (no DER, 1 Cerebras call) for chat + standalone
questions; DER loop for explicit action/tool requests AND follow-ups that
continue a prior task.  This prevents the multi-stage Cerebras burst from
hitting the rate limit on every prompt while keeping the agent able to engage
dynamically mid-conversation.

Run: python -m pytest backend/tests/test_universal_planning.py -v
"""

from unittest.mock import patch


def _make_kernel():
    from backend.agent.agent_kernel import AgentKernel

    with patch.object(AgentKernel, "__init__", lambda self, *a, **kw: None):
        k = AgentKernel.__new__(AgentKernel)
    k._tool_mode = "auto"
    return k


def test_chitchat_bypasses_planning():
    k = _make_kernel()
    for msg in [
        "hi", "hello", "hey there", "how are you?", "how's it going",
        "thanks", "thank you", "ok", "yes", "no", "bye", "good night",
        "lol", "what's up", "who are you", "nice", "cool", "great",
    ]:
        assert k._needs_planning(msg) is False, f"'{msg}' should be chit-chat"


def test_action_messages_route_to_planner():
    k = _make_kernel()
    for msg in [
        "search for the latest news on AI",
        "create a file called notes.txt",
        "open chrome",
        "remind me to call mom at 5pm",
        "send an email to bob",
        "download the report",
        "list files in the project folder",
    ]:
        assert k._needs_planning(msg) is True, f"'{msg}' should need planning (action)"


def test_standalone_questions_take_direct_path():
    # Simple factual questions have no action verb and no task anchor, so they
    # must NOT enter the DER loop (avoids the rate-limit burst on every query).
    k = _make_kernel()
    for msg in [
        "what time is it in Tokyo?",
        "explain how recursion works",
        "what is the capital of France?",
        "who wrote Romeo and Juliet?",
        "how does a carburetor work?",
    ]:
        assert k._needs_planning(msg) is False, f"'{msg}' should be direct (question)"


def test_followup_to_task_routes_to_planner():
    # A short reply that continues a prior task (anaphora / confirmation) must
    # stay in DER even without an action verb of its own.
    k = _make_kernel()
    task_ctx = [
        {"role": "user", "content": "remind me to call mom at 5pm"},
        {"role": "assistant", "content": "I'll create a reminder to call mom at 5pm."},
    ]
    for msg in ["yes do it", "change that to 6pm", "what about the other one", "ok proceed"]:
        assert k._needs_planning(msg, task_ctx) is True, f"'{msg}' should need planning (followup)"


def test_disabled_mode_never_plans():
    k = _make_kernel()
    k._tool_mode = "disabled"
    assert k._needs_planning("search for cats") is False
    assert k._needs_planning("hi") is False


def test_ask_first_mode_only_prefix():
    k = _make_kernel()
    k._tool_mode = "ask_first"
    assert k._needs_planning("tool: search for cats") is True
    assert k._needs_planning("search for cats") is False
    assert k._needs_planning("hi") is False


def test_is_chitchat_detects_acknowledgements():
    k = _make_kernel()
    for msg in ["got it", "sure thing", "sounds good", "agreed", "of course", "alright"]:
        assert k._is_chitchat(msg) is True
