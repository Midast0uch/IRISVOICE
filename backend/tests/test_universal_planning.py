"""
Tests for Phase 1.1 — universal planner routing.

`_needs_planning` is now universal: every inbound message routes through the
planner EXCEPT pure chit-chat, which keeps the fast direct path.

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


def test_task_messages_route_to_planner():
    k = _make_kernel()
    for msg in [
        "search for the latest news on AI",
        "create a file called notes.txt",
        "open chrome",
        "remind me to call mom at 5pm",
        "what time is it in Tokyo?",
        "explain how recursion works",
        "summarize the document I just opened",
        "send an email to bob",
        "download the report",
        "list files in the project folder",
    ]:
        assert k._needs_planning(msg) is True, f"'{msg}' should need planning"


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
