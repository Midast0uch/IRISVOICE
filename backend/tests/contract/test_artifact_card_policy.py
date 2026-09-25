"""Contract: the artifact + task-card bound (owner decision, 2026-09-25).

The owner moved two lines on 2026-09-25:

  * a task card is for THREE OR MORE tool steps — "task cards should only appear
    for 3 more steps with tools ... its genuinely long multi tool work";
  * an artifact is a markdown document or a report — "artifacts are really only
    for mds and reports, notes and lists dont need to be an artifact thats not a
    lot of content".

These tests pin the shared policy (``backend/agent/artifact_policy.py``), the
turn-scoped gate the WS bridge honours, and the two properties that keep the
surface honest: the artifact still reaches the UI on a card-free turn, and a
card-bearing turn is never affected.
"""
from __future__ import annotations

import pytest

from backend.agent.artifact_policy import (
    MIN_TOOL_STEPS_FOR_CARD,
    card_suppressed,
    card_warranted,
    clear_card_gate_for_testing,
    is_artifact_ask,
    is_artifact_document,
    suppress_card_for_turn,
    tool_step_count,
)
from backend.agent.event_bus import IRISStreamEvent
from backend.agent.ws_event_bridge import WSEventBridge


class _Step:
    def __init__(self, tool: str, description: str = ""):
        self.tool = tool
        self.description = description


class _Payload:
    def __init__(self, turn_id=None, data=None):
        self.turn_id = turn_id
        self.data = data or {}


@pytest.fixture(autouse=True)
def _clean_gate():
    clear_card_gate_for_testing()
    yield
    clear_card_gate_for_testing()


# ── the card bound: three or more TOOL steps ───────────────────────────────

def test_card_requires_three_tool_steps():
    assert MIN_TOOL_STEPS_FOR_CARD == 3
    assert card_warranted([_Step("web_search"), _Step("write_file"), _Step("read_file")])
    assert not card_warranted([_Step("write_file"), _Step("read_file")])
    assert not card_warranted([_Step("write_file")])


def test_speak_steps_are_not_work_but_unresolved_tools_are():
    """Explicit speak/tts steps are not work.

    An EMPTY tool field is work-in-waiting, not a speaking step: the planner
    resolves tools at execution time, so the decision must not read "no tool
    name yet" as "not a tool step". Live 2026-09-25 proved it — the gate saw
    tool_steps=0 on a turn that then dispatched write_file and read_file.
    """
    assert tool_step_count([_Step("speak"), _Step("speak_tool"), _Step("tts")]) == 0
    assert tool_step_count([_Step(""), _Step("")]) == 2
    # The live two-step write+read turn: two work steps, so no card.
    assert not card_warranted([_Step(""), _Step("")])
    # ...and a five-step turn keeps its card even before tools are resolved.
    assert card_warranted([_Step("")] * 5)


def test_dict_shaped_steps_count_too():
    steps = [{"tool": "web_search"}, {"tool_name": "write_file"}, {"tool": "read_file"}]
    assert tool_step_count(steps) == 3
    assert card_warranted(steps)



def test_the_live_turn_that_prompted_the_bound_earns_no_card():
    """The exact prompt the owner judged: a three-bullet file, written and read.

    Two tool steps (write_file + read_file) and a list — no card, and no
    artifact either (a list is not a document).
    """
    task = ("create a file tts_check.md in the repo root with three bullets "
            "about sleep, then read it back to me")
    steps = [_Step("write_file"), _Step("read_file")]
    assert not card_warranted(steps, task)
    assert not is_artifact_ask(task)
    assert not is_artifact_document("- one\n- two\n- three")


# ── the artifact bound: markdown documents and reports only ────────────────

def test_note_and_list_asks_are_not_artifact_asks():
    assert not is_artifact_ask("write me a short markdown note listing three benefits")
    assert not is_artifact_ask("make a markdown checklist for a weekend trip")
    assert not is_artifact_ask("list three benefits of walking")
    assert not is_artifact_ask("explain how a bicycle stays upright")


def test_report_and_document_asks_are_artifact_asks():
    assert is_artifact_ask("write a detailed report on the top 5 AI chip startups")
    assert is_artifact_ask("draft a markdown document about sleep hygiene")
    assert is_artifact_ask("create a readme guide for this repo")
    # A document ask NEVER earns a card, however many tools it takes.
    many = [_Step("web_search"), _Step("write_file"), _Step("read_file"), _Step("edit_file")]
    assert not card_warranted(many, "write a detailed report on the top 5 AI chip startups")


def test_artifact_document_needs_a_document_shape():
    assert is_artifact_document("# Sleep hygiene\n\nBody paragraph.")
    assert is_artifact_document("| a | b |\n| - | - |\n| 1 | 2 |")
    assert is_artifact_document("```python\nprint('hi')\n```")
    # Notes and lists are conversation, not artifacts (owner bound).
    assert not is_artifact_document("- Sleep helps memory.\n- Keep a schedule.")
    assert not is_artifact_document("1. one\n2. two")
    assert not is_artifact_document("## A subheading alone\n\nprose that is not a document")
    assert not is_artifact_document("Just a sentence.")
    assert not is_artifact_document("")



# ── the turn-scoped gate ───────────────────────────────────────────────────

def test_gate_is_per_turn():
    suppress_card_for_turn("turn-a")
    assert card_suppressed("turn-a")
    assert not card_suppressed("turn-b")
    assert not card_suppressed(None)
    assert not card_suppressed("")


def test_gate_is_bounded():
    """Memory footprint stays bounded: the gate keeps the newest turns only."""
    for n in range(200):
        suppress_card_for_turn("turn-%d" % n)
    assert card_suppressed("turn-199")
    assert not card_suppressed("turn-0")


def test_bridge_withholds_the_whole_card_lifecycle():
    """task:start, progress and done are all withheld — not just task:start.

    A trailing progress frame with no card is what fabricated a phantom card in
    an earlier session, so the gate covers the entire lifecycle.
    """
    suppress_card_for_turn("turn-free")
    for evt in (
        IRISStreamEvent.TASK_START,
        IRISStreamEvent.TASK_PROGRESS,
        IRISStreamEvent.TASK_MILESTONE,
        IRISStreamEvent.TASK_DONE,
        IRISStreamEvent.TASK_FAIL,
    ):
        assert WSEventBridge._card_event_withheld(evt, _Payload("turn-free", {})), evt.value
        assert not WSEventBridge._card_event_withheld(evt, _Payload("turn-other", {})), evt.value
    # The turn id may ride the payload data instead of the envelope.
    assert WSEventBridge._card_event_withheld(
        IRISStreamEvent.TASK_START, _Payload(None, {"turn_id": "turn-free"})
    )


def test_bridge_still_forwards_the_artifact_on_a_card_free_turn():
    """The artifact IS the visible result of a short turn — it must reach the UI."""
    suppress_card_for_turn("turn-free")
    assert not WSEventBridge._card_event_withheld(
        IRISStreamEvent.DOCUMENT_RENDER, _Payload("turn-free", {})
    )


def test_der_entry_consults_the_gate_before_it_emits_a_card():
    """Source contract: the DER entry must decide the card BEFORE task:start.

    Without this, a future edit could re-emit card events for a two-step turn
    and nothing in the pure tests would notice.
    """
    import inspect

    from backend.agent import agent_kernel as _mod

    src = inspect.getsource(_mod)
    assert "card_warranted(items" in src, (
        "the DER entry must call artifact_policy.card_warranted on the plan's "
        "items before emitting task:start"
    )
    assert "suppress_card_for_turn(_turn_id)" in src, (
        "the DER entry must register a card-free turn on the gate"
    )
    assert "card_suppressed(_suppressed_turn)" in src, (
        "_persist_card_snapshot must honour the gate, or a card-free turn comes "
        "back as a card after a reload"
    )


# ── the frames that slipped through live (2026-09-25) ──────────────────────

def test_card_event_turn_id_reads_every_naming():
    """task:progress carries no turn_id, so the turn is read from its card_id.

    This is the exact gap that let the card appear: the gate resolved nothing
    from the envelope, so a progress frame with `card_id` rebuilt the card.
    """
    from backend.agent.artifact_policy import card_event_turn_id

    assert card_event_turn_id(_Payload("turn-1", {})) == "turn-1"
    assert card_event_turn_id(_Payload(None, {"turn_id": "turn-2"})) == "turn-2"
    assert card_event_turn_id(_Payload(None, {"task_id": "turn-3"})) == "turn-3"
    assert card_event_turn_id(_Payload(None, {"card_id": "card_turn-4"})) == "turn-4"
    assert card_event_turn_id(None) is None
    assert card_event_turn_id(_Payload(None, {})) is None


def test_bridge_withholds_a_progress_frame_that_carries_only_a_card_id():
    """The captured frame: {"type":"task:progress", ..., "card_id":"card_..."}"""
    suppress_card_for_turn("turn-free")
    payload = _Payload(None, {"step_done": True, "card_id": "card_turn-free"})
    assert WSEventBridge._card_event_withheld(IRISStreamEvent.TASK_PROGRESS, payload)
    # The tool frames carry card identity too, so they are covered as well.
    for evt in (IRISStreamEvent.TOOL_CALL, IRISStreamEvent.TOOL_RESULT,
                IRISStreamEvent.TOOL_ERROR):
        assert WSEventBridge._card_event_withheld(evt, payload), evt.value
    # A card-free turn must still get its ARTIFACT (only card frames are gated).
    assert not WSEventBridge._card_event_withheld(
        IRISStreamEvent.DOCUMENT_RENDER, payload
    )


def test_store_does_not_offer_a_tool_receipt_for_rehydration():
    """A stored tool receipt is not an artifact: not offered, so not rendered."""
    import sqlite3

    from backend.agent.document_store import DocumentDataStore

    store = DocumentDataStore(sqlite3.connect(":memory:"))
    store.store("receipt", "c1", "json",
                '{"success": true, "message": "Written to note.md"}', {}, [], "trusted")
    store.store("real", "c1", "markdown", "# Weekly plan\n\n- one\n- two", {}, [], "trusted")
    docs = store.list_for_conversation("c1", metadata_only=True)
    assert [d["document_id"] for d in docs] == ["real"]
    assert docs[0]["title"] == "Weekly plan"

