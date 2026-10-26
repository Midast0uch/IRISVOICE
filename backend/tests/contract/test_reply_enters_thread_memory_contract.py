"""IRIS's own reply enters the thread's memory (2026-10-26).

The kernel stores every reply with add_message("assistant", text, sources=...). ConversationMemory.add_message did
not accept `sources`, so the call raised, its caller swallowed it at DEBUG ("conversation_memory.add_message (der)
failed: ... unexpected keyword argument 'sources'", hundreds of times since 2026-10-20) and no reply ever entered the
window: the next turn did not see what IRIS had answered.
"""
from __future__ import annotations

import tempfile

from backend.agent.agent_kernel import AgentKernel
from backend.agent.memory import ConversationMemory


def _mem(tmp):
    return ConversationMemory(session_id="s", conversation_id="conv-reply", max_messages=10,
                              session_storage_path=tmp)


def test_a_reply_with_sources_is_kept_in_the_window():
    with tempfile.TemporaryDirectory() as tmp:
        m = _mem(tmp)
        m.add_message("user", "what is on example.com?")
        m.add_message("assistant", "It is a demo page.", sources=["https://example.com"])
        assert [x.role for x in m.messages] == ["user", "assistant"]
        assert m.messages[-1].sources == ["https://example.com"]


def test_the_direct_reply_path_stores_the_reply_for_the_next_turn():
    with tempfile.TemporaryDirectory() as tmp:
        k = AgentKernel.__new__(AgentKernel)
        k.session_id, k.conversation_id = "s", "conv-reply"
        k._pending_thinking, k._initialization_error = "", None
        k._model_router = object()
        k._conversation_memory = _mem(tmp)
        k._mcm_orch, k._memory_interface = None, None
        k.resolve_context_window = lambda: 32_000
        k._needs_planning = lambda text, context: False
        k._respond_direct = lambda text, context, chunk_callback=None, reasoning_callback=None: "Hello there."
        k._process_structured_response = lambda response, turn_id=None, conversation_id=None: response
        k._maybe_escalate_web_format = lambda task_id, conv_id, response_text="": None
        k.clear_turn_trust_flag = lambda: None
        k._turn_sources = lambda: ["https://example.com"]
        assert k.process_text_message("hi", session_id="s") == "Hello there."
        roles = [(x.role, x.content) for x in k._conversation_memory.messages]
        assert ("assistant", "Hello there.") in roles, roles
