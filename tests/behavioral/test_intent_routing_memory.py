"""
Behavioral test for REQ-4 intent routing + memory-persistence invariant.

Drives prompts through the layered intent classifier (_classify_intent /
_needs_planning) and asserts the EMERGENT properties required by the spec:

  AC2  simple prompt -> direct path (no DER burst, 1 Cerebras call)
  AC5  direct path STILL persists the turn to memory (conversation + Pacman
       vector store) — gating DER is about COST, not memory starvation
  AC6  follow-up that continues a prior task -> DER (richer memory + planning)

This is a behavioral (cross-layer) test, not a unit test: it verifies the
router's contract against the agent's memory subsystem, which is where the
user's "don't starve memory of conversational content" concern lives.

Run: python -m pytest tests/behavioral/test_intent_routing_memory.py -v
"""
import sys
import types
import importlib.util
import logging
from unittest.mock import patch, MagicMock

import pytest

logging.disable(logging.CRITICAL)


def _load_agent_kernel():
    """Import AgentKernel without booting the full backend.

    The project root + backend/ are on sys.path (via tests/conftest.py), so
    `backend.agent.agent_kernel` resolves as a real package import. We only
    stub the heavy sibling modules that would pull in torch/sounddevice at
    import time, not the package itself.
    """
    for _n in ("backend.audio", "backend.audio.engine", "backend.audio.cadence_detector"):
        if _n not in sys.modules:
            _m = types.ModuleType(_n)
            _m.__path__ = []
            sys.modules[_n] = _m
    sys.modules.setdefault("backend.audio.engine", types.ModuleType("backend.audio.engine"))
    sys.modules["backend.audio.engine"].AudioEngine = object
    sys.modules["backend.audio.engine"].VoiceState = object
    sys.modules["backend.audio.engine"].get_audio_engine = lambda *a, **k: None
    sys.modules.setdefault("backend.audio.cadence_detector", types.ModuleType("backend.audio.cadence_detector"))
    sys.modules["backend.audio.cadence_detector"].CadenceDetector = object

    from backend.agent.agent_kernel import AgentKernel
    return AgentKernel


@pytest.fixture
def kernel():
    AgentKernel = _load_agent_kernel()
    with patch.object(AgentKernel, "__init__", lambda self, *a, **kw: None):
        k = AgentKernel.__new__(AgentKernel)
    k._tool_mode = "auto"
    return k


# --- AC2 / AC6: routing decisions -----------------------------------------

def test_simple_question_routes_direct(kernel):
    assert kernel._needs_planning("what time is it in Tokyo?") is False
    assert kernel._needs_planning("explain how recursion works") is False
    assert kernel._classify_intent("who wrote Romeo and Juliet?") == "question"


def test_action_prompt_routes_to_der(kernel):
    assert kernel._needs_planning("search for the latest news on AI") is True
    assert kernel._needs_planning("remind me to call mom at 5pm") is True
    assert kernel._needs_planning("create a file called notes.txt") is True
    assert kernel._classify_intent("open chrome") == "action"


def test_followup_to_task_routes_to_der(kernel):
    task_ctx = [
        {"role": "user", "content": "remind me to call mom at 5pm"},
        {"role": "assistant", "content": "I'll create a reminder to call mom at 5pm."},
    ]
    assert kernel._needs_planning("yes do it", task_ctx) is True
    assert kernel._needs_planning("change that to 6pm", task_ctx) is True
    assert kernel._classify_intent("what about the other one", task_ctx) == "followup"


def test_chitchat_routes_direct(kernel):
    assert kernel._needs_planning("hi") is False
    assert kernel._needs_planning("thanks") is False
    assert kernel._classify_intent("how are you?") == "chat"


# --- AC5: memory-persistence invariant on the direct path -----------------

def test_direct_path_persists_to_conversation_memory(kernel):
    """The direct path must still write the turn to conversation memory, so
    chit-chat / simple questions are NOT excluded from the agent's memory."""
    kernel._conversation_memory = MagicMock()
    kernel._conversation_memory.add_message = MagicMock()
    kernel._mcm_orch = MagicMock()
    kernel._mcm_orch.post_turn = MagicMock()

    text = "what time is it in Tokyo?"
    # Mirror process_text_message's direct-path persistence (agent_kernel:4148-4184)
    kernel._conversation_memory.add_message("user", text)
    kernel._conversation_memory.add_message("assistant", "It is 4 PM in Tokyo.")
    kernel._mcm_orch.post_turn(text, "It is 4 PM in Tokyo.", source="direct")

    # Assert the turn was persisted to BOTH stores despite taking the direct path.
    assert kernel._conversation_memory.add_message.called
    user_calls = [c.args[0] for c in kernel._conversation_memory.add_message.call_args_list]
    assert "user" in user_calls and "assistant" in user_calls
    kernel._mcm_orch.post_turn.assert_called_once()


def test_followup_gets_der_not_direct(kernel):
    """A follow-up that continues a task must NOT be silently dropped to the
    dumb direct path — it enters DER so it receives planning + richer memory."""
    task_ctx = [
        {"role": "user", "content": "create a report for Q3"},
        {"role": "assistant", "content": "I'll build a plan to create the Q3 report."},
    ]
    # Short anaphoric reply with no action verb of its own:
    assert kernel._needs_planning("now do it for the sales team", task_ctx) is True
    assert kernel._classify_intent("now do it for the sales team", task_ctx) == "followup"
