"""Contract: the SAFETY events and the STRUCTURAL FEEDBACK events of the taxonomy
(docs/Design/EVENT_TAXONOMY.md section 4) come from the REAL chokepoints:

  UNSAFE_REFUSED / ESCALATED_UNSURE + the PIVOT a refusal causes
                       - the click-safety gate on the real browser_act path
  APPROVAL / DENIAL    - the user answers a click-safety question or a permission request
                         (evidence "user")
  NO_RESPONSE          - a question or a permission request times out
  CLARIFY_ASKED / CLARIFY_ANSWERED - an ask_user question and its answer
  ESCALATED            - the agent hands a decision to the user (purpose "decide")
  PERMISSION_DENIED    - the consent / capability gate in the tool bridge

Typing free user messages (CORRECTION ...) is not here: that is the Oracle consumer.
Each test asserts the memory_events ROW; the last one proves a blocked lane never
delays a chokepoint.
"""
from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

import backend.agent.tool_registry as _registry
import backend.memory as _memory_pkg
from backend.agent import agent_kernel, permissions
from backend.agent.event_bus import EventBus
from backend.agent.nodes.outcome import Reason
from backend.agent.tool_bridge import AgentToolBridge
from backend.agent.tools import browser_tools, click_safety
from backend.agent.tools.ask_user_tool import AskUserTool, get_ask_user_tool
from backend.tests.contract._events_fixture import BlockedLane, memory_interface, rows, store  # noqa: F401
from backend.tests.contract.test_click_safety_contract import _btn, gate  # noqa: F401

EPISODE = "sess-fb:turn-fb"


@pytest.fixture()
def live(store, monkeypatch):  # noqa: F811
    """The memory interface the emitters resolve, and a live kernel that owns the turn's episode."""
    mi = memory_interface(store)
    monkeypatch.setattr(_memory_pkg, "_memory_interface", mi)
    kernel = SimpleNamespace(session_id="sess-fb", _event_episode_id=EPISODE, _memory_interface=mi)
    monkeypatch.setattr(agent_kernel, "_agent_kernel_instances", {"conv-fb": kernel})
    return store


def _labels(conn):
    return [r["label"] for r in rows(conn)]


# ── click-safety: SAFETY verdicts, the user's answer, the pivot ────────────────

async def _act(gate, mark, session="sess-fb"):  # noqa: F811
    gate.install(mark)
    token = click_safety.ACT_CONTEXT.set(
        {"goal": "buy nothing", "conversation_id": "conv-fb", "session_id": session})
    try:
        return await browser_tools.browser_act(gate.conv, "click", 1)
    finally:
        click_safety.ACT_CONTEXT.reset(token)


async def test_unsafe_click_is_refused_then_pivots(live, gate):  # noqa: F811
    res = await _act(gate, _btn("Buy now"))
    assert res["pivot"] is True
    evs = rows(live)
    assert [r["label"] for r in evs] == ["UNSAFE_REFUSED", "PIVOT"]
    refused, pivot = evs
    assert (refused["family"], refused["evidence"], refused["episode_id"], refused["thread_id"]) == (
        "safety", "verifier", EPISODE, "sess-fb")
    assert (pivot["family"], pivot["trigger"], pivot["episode_id"]) == (
        "control", Reason.PERMISSION_DENIED.value, EPISODE)
    assert "Buy now" not in json.dumps(evs, default=str), "untrusted element text stays out of the rows"


def test_pivot_trigger_is_a_node_outcome_reason():
    assert click_safety.PIVOT_TRIGGER == Reason.PERMISSION_DENIED.value


async def test_safe_click_emits_nothing(live, gate):  # noqa: F811
    res = await _act(gate, {"id": 1, "role": "link", "name": "Pricing", "tag": "a", "href": "/pricing"})
    assert res["success"] is True
    assert rows(live) == []


async def test_unsure_unanswered_is_escalated_no_response_pivot(live, gate):  # noqa: F811
    res = await _act(gate, _btn("Continue", form={"fields": ["text::note"]}))
    assert res["pivot"] is True  # ASK_TIMEOUT_S is 1 in the gate fixture
    assert _labels(live) == ["ESCALATED_UNSURE", "NO_RESPONSE", "PIVOT"]
    unsure, silent, _pivot = rows(live)
    assert (unsure["family"], unsure["episode_id"]) == ("safety", EPISODE)
    assert (silent["family"], silent["episode_id"]) == ("feedback", EPISODE)
    assert json.loads(silent["payload"])["purpose"] == "safety"
    assert "CLARIFY_ASKED" not in _labels(live), "the gate's own question is not a clarification"


@pytest.mark.parametrize("answer,label,pivots", [("Yes, do it", "APPROVAL", False),
                                                 ("No, find another way", "DENIAL", True)])
async def test_unsure_answered_is_approval_or_denial_from_the_user(live, gate, monkeypatch, answer, label, pivots):  # noqa: F811
    monkeypatch.setattr(click_safety, "ASK_TIMEOUT_S", 20)

    def _answer_when_asked():
        tool = get_ask_user_tool()
        end = time.time() + 5
        while time.time() < end:
            pending = list(tool._pending)
            if pending:
                tool.resolve_answer(pending[0], answer)
                return
            time.sleep(0.02)

    threading.Thread(target=_answer_when_asked, daemon=True).start()
    await _act(gate, _btn("Continue", form={"fields": ["text::note"]}))
    evs = rows(live)
    assert [r["label"] for r in evs] == (
        ["ESCALATED_UNSURE", label, "PIVOT"] if pivots else ["ESCALATED_UNSURE", label])
    user_row = evs[1]
    assert (user_row["family"], user_row["evidence"], user_row["episode_id"]) == ("feedback", "user", EPISODE)


# ── ask_user: clarification, escalation, timeout ──────────────────────────────

@pytest.fixture()
def tool():
    return AskUserTool(event_bus=EventBus())


def test_a_clarification_is_asked_and_answered(live, tool):
    q = tool.ask("Which file did you mean?", options=["a.py", "b.py"], session_id="sess-fb",
                 turn_id="turn-fb")
    tool.resolve_answer(q.question_id, "a.py")
    asked, answered = rows(live)
    assert (asked["family"], asked["label"], asked["evidence"], asked["episode_id"]) == (
        "intent", "CLARIFY_ASKED", "none", EPISODE)
    assert (answered["family"], answered["label"], answered["evidence"], answered["episode_id"]) == (
        "intent", "CLARIFY_ANSWERED", "user", EPISODE)
    assert json.loads(asked["payload"])["question_id"] == q.question_id
    assert "Which file" not in json.dumps([asked, answered], default=str), "the question text stays out"


def test_an_unanswered_question_is_no_response(live, tool):
    q = tool.ask("Which file did you mean?", session_id="sess-fb", timeout_seconds=0)
    assert tool.wait_for_answer(q).status == "timed_out"
    assert _labels(live) == ["CLARIFY_ASKED", "NO_RESPONSE"]
    row = rows(live, "NO_RESPONSE")[0]
    assert (row["family"], row["valence"], row["episode_id"]) == ("feedback", "neutral", EPISODE)


def test_a_decision_handed_to_the_user_is_escalated_not_a_clarification(live, tool):
    tool.ask("How should I present the results?", options=["Table", "Plain text"],
             session_id="sess-fb", purpose="decide")
    (row,) = rows(live)
    assert (row["family"], row["label"], row["episode_id"]) == ("control", "ESCALATED", EPISODE)


def test_a_browser_takeover_is_an_escalation(live, tool):
    tool.ask_browser_takeover(takeover_url="https://x.test", reason="captcha", turn_id="turn-fb",
                              conversation_id="conv-fb")
    (row,) = rows(live)
    assert (row["family"], row["label"], row["episode_id"]) == ("control", "ESCALATED", EPISODE)


def test_a_safety_question_emits_no_clarify_event(live, tool):
    q = tool.ask("Allow it?", session_id="sess-fb", purpose="safety")
    tool.resolve_answer(q.question_id, "Yes, do it")
    assert rows(live) == []  # the gate types APPROVAL / DENIAL itself (tests above)


# ── permissions: the user's answer, expiry, the gate's refusal ───────────────

def _request(system, session="sess-fb"):
    # delete_file is ALWAYS_ASK: no standing or session approval can ever skip the card.
    req = system.request_permission(
        "delete_file", permissions.PermissionTier.DESTRUCTIVE, params={"path": "evtest-none.tmp"},
        description="delete evtest-none.tmp", session_id=session, auto_approve=False, force=True,
    )
    assert req.status == "pending"
    return req


@pytest.mark.parametrize("approved,label", [(True, "APPROVAL"), (False, "DENIAL")])
def test_a_permission_answer_is_approval_or_denial(live, approved, label):
    system = permissions.ToolPermissionSystem(event_bus=EventBus())
    req = _request(system)
    system.respond_to_permission(req.request_id, approved=approved)
    (row,) = rows(live)
    assert (row["family"], row["label"], row["evidence"], row["episode_id"]) == (
        "feedback", label, "user", EPISODE)
    payload = json.loads(row["payload"])
    assert payload["request_id"] == req.request_id and payload["tool"] == "delete_file"


def test_an_expired_permission_request_is_no_response(live):
    system = permissions.ToolPermissionSystem(event_bus=EventBus())
    req = _request(system)
    req.timeout_seconds = 0
    assert system.get_response(req).status == "timed_out"
    (row,) = rows(live)
    assert (row["family"], row["label"], row["evidence"]) == ("feedback", "NO_RESPONSE", "none")


@pytest.fixture()
def bridge_env(monkeypatch):
    monkeypatch.setattr(_registry, "_internet_provider", lambda: True)
    monkeypatch.setattr(_registry, "_desktop_provider", lambda: True)
    import backend.capabilities as caps
    monkeypatch.setattr(caps.CapabilitySet, "is_tool_allowed", staticmethod(lambda name: True))


async def test_a_capability_refusal_is_permission_denied(live, bridge_env, monkeypatch):
    monkeypatch.setattr(_registry, "_internet_provider", lambda: False)
    res = await AgentToolBridge().execute_tool("web_search", {"query": "x"}, session_id="sess-fb")
    assert res["success"] is False
    (row,) = rows(live)
    assert (row["family"], row["label"], row["evidence"], row["episode_id"]) == (
        "safety", "PERMISSION_DENIED", "verifier", EPISODE)
    assert json.loads(row["payload"]) == {"tool": "search", "reason": "capability_internet_disabled"}


async def test_a_denied_consent_card_is_denial_and_permission_denied(live, bridge_env, monkeypatch):
    import backend.agent.tool_bridge as tb

    monkeypatch.setattr(tb, "_approval_ui_attached", lambda _sid: True)
    monkeypatch.setattr(permissions, "get_auto_approve", lambda: False)
    permissions.reset_permission_system_for_testing()
    system = permissions.get_permission_system()

    def _deny_when_asked():
        end = time.time() + 5
        while time.time() < end:
            pending = list(system._pending)
            if pending:
                system.respond_to_permission(pending[0], approved=False)
                return
            time.sleep(0.02)

    threading.Thread(target=_deny_when_asked, daemon=True).start()
    try:
        res = await AgentToolBridge().execute_tool(
            "delete_file", {"path": "evtest-none.tmp"}, session_id="sess-fb")
    finally:
        permissions.reset_permission_system_for_testing()
    assert res.get("permission_response") == "denied", res
    evs = rows(live)
    assert sorted(r["label"] for r in evs) == ["DENIAL", "PERMISSION_DENIED"]
    gate_row = next(r for r in evs if r["label"] == "PERMISSION_DENIED")
    assert (gate_row["family"], gate_row["evidence"]) == ("safety", "user")
    assert json.loads(gate_row["payload"])["reason"] == "consent_denied"


# ── off the answer path ──────────────────────────────────────────────────────

def test_blocked_memory_events_lane_does_not_delay_a_feedback_chokepoint(live, tool):
    system = permissions.ToolPermissionSystem(event_bus=EventBus())
    req = _request(system)
    with BlockedLane():
        t0 = time.monotonic()
        q = tool.ask("Which one?", session_id="sess-fb")
        tool.resolve_answer(q.question_id, "x")
        system.respond_to_permission(req.request_id, approved=True)
        assert time.monotonic() - t0 < 1.0
    assert sorted(_labels(live)) == ["APPROVAL", "CLARIFY_ANSWERED", "CLARIFY_ASKED"]
