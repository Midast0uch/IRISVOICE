"""Contract: a spoken memory deletion needs a tool event that performed it (D3).

Measured 2026-10-30: with no delete tool available the agent said

    "Done - I've wiped your locker code from memory"

while the pin was still in the store and nothing had run. `forget` exists now,
but nothing checked the claim against what ran, so a reply could still report a
deletion that never happened.

The contract has three layers:

  * the tool chokepoint (`AgentToolBridge.execute_tool`) records what RAN;
  * the reply exit (`AgentKernel._finalize_response`) rewrites a memory-deletion
    claim when the turn has no successful `forget` event;
  * the policy is NARROW: a file deletion, or a denial ("I have not deleted
    anything from memory"), is not a claim and must pass through untouched.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.agent import agent_kernel as kernel_module
from backend.agent.artifact_policy import enforce_memory_deletion_claims
from backend.agent.agent_kernel import AgentKernel
from backend.agent.tool_bridge import AgentToolBridge

CLAIM = "Done - I've wiped your locker code from memory"
HONEST_FRAGMENT = "did not delete anything from memory"


def _bridge() -> AgentToolBridge:
    """A bridge without __init__: no TTS load, and only the event table is
    needed. execute_tool's other dependencies are module level."""
    bridge = AgentToolBridge.__new__(AgentToolBridge)
    bridge._turn_tool_events = {}
    return bridge


def _kernel(bridge: AgentToolBridge, session_id: str = "sess-1") -> AgentKernel:
    kernel = AgentKernel.__new__(AgentKernel)
    kernel.session_id = session_id
    kernel._turn_session_id = session_id
    kernel._turn_started_monotonic = 0.0
    kernel._last_spoken_text = ""
    kernel._tool_bridge = bridge
    return kernel


# ── the policy ──────────────────────────────────────────────────────────────

def test_claim_without_a_delete_event_is_rewritten():
    display, spoken, hits = enforce_memory_deletion_claims(
        CLAIM, None, delete_ran=False
    )
    assert hits == 1
    assert "wiped" not in display
    assert HONEST_FRAGMENT in display


def test_claim_with_a_delete_event_is_left_alone():
    display, spoken, hits = enforce_memory_deletion_claims(
        CLAIM, CLAIM, delete_ran=True
    )
    assert hits == 0
    assert display == CLAIM
    assert spoken == CLAIM


def test_file_deletion_is_not_a_memory_claim():
    text = "I deleted the temp file."
    display, _, hits = enforce_memory_deletion_claims(text, None, delete_ran=False)
    assert hits == 0
    assert display == text


def test_denial_is_not_a_claim():
    text = "I have not deleted anything from memory."
    display, _, hits = enforce_memory_deletion_claims(text, None, delete_ran=False)
    assert hits == 0
    assert display == text


def test_spoken_line_is_corrected_too():
    _, spoken, hits = enforce_memory_deletion_claims(
        "", CLAIM, delete_ran=False
    )
    assert hits == 1
    assert HONEST_FRAGMENT in spoken


def test_only_the_claiming_sentence_is_replaced():
    text = "Here is the plan. I removed that fact from my memory. Next step is done."
    display, _, hits = enforce_memory_deletion_claims(text, None, delete_ran=False)
    assert hits == 1
    assert display.startswith("Here is the plan. ")
    assert display.endswith(" Next step is done.")
    assert HONEST_FRAGMENT in display


# ── the tool chokepoint records what ran ────────────────────────────────────

def test_execute_tool_records_a_successful_delete():
    bridge = _bridge()

    async def _dispatch(tool_name, params, session_id="unknown",
                        plan_title="", _skip_resilience=False,
                        decision_meta=None):
        return {"success": True, "deleted": True}

    bridge._execute_tool_dispatch = _dispatch
    asyncio.run(bridge.execute_tool("forget", {"attribute": "locker"},
                                    session_id="sess-1"))
    assert bridge.forget_ran_since("sess-1", 0.0) is True
    # Another session's turn cannot borrow the evidence.
    assert bridge.forget_ran_since("sess-2", 0.0) is False


def test_execute_tool_does_not_count_a_no_op_delete():
    bridge = _bridge()

    async def _dispatch(tool_name, params, session_id="unknown",
                        plan_title="", _skip_resilience=False,
                        decision_meta=None):
        return {"success": True, "deleted": False}

    bridge._execute_tool_dispatch = _dispatch
    asyncio.run(bridge.execute_tool("forget", {"attribute": "unknown"},
                                    session_id="sess-1"))
    assert bridge.forget_ran_since("sess-1", 0.0) is False


# ── the reply exit ──────────────────────────────────────────────────────────

@pytest.fixture
def quiet_events(monkeypatch):
    monkeypatch.setattr(kernel_module, "_emit_event", lambda *a, **k: None)


def test_finalize_rewrites_a_claim_with_no_delete(quiet_events):
    kernel = _kernel(_bridge())
    display = kernel._finalize_response(CLAIM, CLAIM)
    assert "wiped" not in display
    assert HONEST_FRAGMENT in display
    assert HONEST_FRAGMENT in kernel._last_spoken_text


def test_finalize_keeps_a_claim_the_turn_performed(quiet_events):
    bridge = _bridge()
    bridge._note_turn_tool("sess-1", "forget", {"success": True, "deleted": True})
    kernel = _kernel(bridge)
    display = kernel._finalize_response(CLAIM, CLAIM)
    assert display == CLAIM


def test_finalize_ignores_an_earlier_turns_delete(quiet_events):
    bridge = _bridge()
    bridge._note_turn_tool("sess-1", "forget", {"success": True, "deleted": True})
    kernel = _kernel(bridge)
    # The turn started AFTER that delete: its evidence does not carry over.
    kernel._turn_started_monotonic = 10 ** 9
    display = kernel._finalize_response(CLAIM, None)
    assert HONEST_FRAGMENT in display
