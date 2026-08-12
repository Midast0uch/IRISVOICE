"""The plan prism card is ONE card that fills in — not a card per phase.

The card is emitted at PLAN time carrying the steps the agent intends to take,
is revised in place as the run progresses, and finally carries the answer. Two
properties make that true, and neither is expressible as a unit test on either
half alone:

  1. The plan card claims the turn's document_id, and the final structured
     answer REVISES that document rather than minting a fresh uuid. Without
     this the plan card is left sitting above the answer as a second, stale card
     describing work that has already finished.
  2. The plan card announces itself as ``pending``. The frontend suppresses a
     turn's plain-text response when a document exists for that turn
     (chat-view.tsx handleTextResponse), so a card that did NOT say it was
     merely a plan would claim the turn and SWALLOW any answer that arrived as
     plain text rather than as a structured `show` payload — leaving the user
     looking at a plan for work that was already done. That is the phantom-card
     failure the project's CDD rules name explicitly, and it is the reason the
     flag exists rather than being inferred.
"""
from __future__ import annotations

from backend.agent.agent_kernel import AgentKernel
from backend.agent.event_bus import IRISStreamEvent, get_event_bus


def _bare_kernel(conversation_id: str = "conv-plan") -> AgentKernel:
    """A kernel with only what the plan-card path touches.

    Built via __new__ deliberately: the card must not depend on a fully
    initialised kernel, because it is emitted from the planning path that
    recovery also reaches (pin_54aef09b748c records a bare `self.conversation_id`
    access on exactly such a kernel silently turning a graft into a failure).
    """
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = conversation_id
    k.session_id = "sess-plan"
    k._memory = None
    return k


def _capture(events: list):
    # The bus hands handlers an EventPayload, not the raw dict — its `.data` is
    # what the WS bridge forwards and therefore what the frontend receives.
    def _on(payload):
        events.append(getattr(payload, "data", payload))

    return _on


def _emit_plan(kernel, turn_id="turn-1", steps=None):
    events: list = []
    bus = get_event_bus()
    handler = _capture(events)
    bus.subscribe(IRISStreamEvent.DOCUMENT_RENDER, handler)
    try:
        doc_id = kernel._emit_plan_document(
            plan_title="Research party builds",
            steps=steps if steps is not None else [
                {"description": "search the web", "toolName": "crawler_query"},
                {"description": "summarize the findings", "toolName": "respond"},
            ],
            turn_id=turn_id,
            conversation_id=kernel.conversation_id,
        )
    finally:
        bus.unsubscribe(IRISStreamEvent.DOCUMENT_RENDER, handler)
    return doc_id, events


def test_plan_card_is_emitted_with_the_steps():
    k = _bare_kernel()
    doc_id, events = _emit_plan(k)

    assert doc_id, "no plan card document_id — the card was never created"
    rendered = [e for e in events if isinstance(e, dict)]
    assert rendered, "no DOCUMENT_RENDER emitted for the plan"
    payload = rendered[-1]
    content = payload.get("content") or ""
    assert "search the web" in content and "summarize the findings" in content, (
        f"the card does not list the planned steps: {content!r}"
    )


def test_plan_card_declares_itself_pending():
    """The flag the frontend keys on to avoid swallowing a plain-text answer."""
    k = _bare_kernel()
    _doc_id, events = _emit_plan(k)
    payload = [e for e in events if isinstance(e, dict)][-1]

    assert payload.get("pending") is True, (
        "the plan card did not announce pending=True. The frontend suppresses a "
        "turn's plain-text response once ANY document exists for that turn, so "
        "without this flag the card claims the turn and the answer is never "
        "shown — a plan card standing in for an answer that was produced."
    )
    assert payload.get("kind") == "plan"


def test_plan_card_id_is_remembered_for_the_turn():
    k = _bare_kernel()
    doc_id, _events = _emit_plan(k, turn_id="turn-abc")

    assert k._plan_document_id("turn-abc") == doc_id, (
        "the plan card's id is not retrievable for its turn, so the final answer "
        "cannot fold into it and would mint a second card"
    )
    assert k._plan_document_id("some-other-turn") is None
    assert k._plan_document_id(None) is None


def test_plan_card_ids_are_bounded_per_conversation():
    """The kernel is cached PER CONVERSATION, so an unbounded map grows for that
    conversation's whole life — the same leak shape as router._attempts."""
    k = _bare_kernel()
    for i in range(AgentKernel._PLAN_DOC_MAX_TURNS + 20):
        _emit_plan(k, turn_id=f"turn-{i}")

    assert len(k._plan_doc_ids) <= AgentKernel._PLAN_DOC_MAX_TURNS, (
        f"{len(k._plan_doc_ids)} plan-card ids retained; bound is "
        f"{AgentKernel._PLAN_DOC_MAX_TURNS}"
    )
    # The CURRENT turn must always still resolve — evicting the live turn would
    # split the run across two cards, which is the whole defect.
    last = f"turn-{AgentKernel._PLAN_DOC_MAX_TURNS + 19}"
    assert k._plan_document_id(last) is not None


def test_a_turn_without_a_plan_card_is_unaffected():
    """No plan card => the answer path mints its own id exactly as before. The
    fold must not become a hard dependency on the card having been emitted."""
    k = _bare_kernel()
    assert k._plan_document_id("never-planned") is None


def test_emit_never_raises_even_with_a_crippled_kernel():
    """A card is not worth failing a task over (REQ-9 AC5 discipline)."""
    k = AgentKernel.__new__(AgentKernel)  # no conversation_id, no _memory
    doc_id = k._emit_plan_document(
        plan_title="x", steps=[{"description": "y"}],
        turn_id="t", conversation_id="c",
    )
    # Either it worked or it degraded to None — but it did not propagate.
    assert doc_id is None or isinstance(doc_id, str)
