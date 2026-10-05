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

def test_card_requires_more_than_four_tool_steps():
    """Owner bound 2026-09-25, final: "keep it >4 steps"."""
    assert MIN_TOOL_STEPS_FOR_CARD == 5
    assert card_warranted([_Step("web_search"), _Step("write_file"), _Step("read_file"),
                           _Step("edit_file"), _Step("list_directory")])
    # Four tool steps is still a conversation, not a project.
    assert not card_warranted([_Step("web_search"), _Step("write_file"),
                               _Step("read_file"), _Step("edit_file")])
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
    steps = [{"tool": "web_search"}, {"tool_name": "write_file"},
             {"tool": "read_file"}, {"tool": "edit_file"}, {"tool": "list_directory"}]
    assert tool_step_count(steps) == 5
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
    assert "suppress_card_for_conversation(self.conversation_id, _turn_id)" in src, (
        "the DER entry must register a card-free turn (and its conversation) on "
        "the gate"
    )
    assert "card_suppressed(_suppressed_turn)" in src, (
        "_persist_card_snapshot must honour the gate, or a card-free turn comes "
        "back as a card after a reload"
    )


def test_the_gate_is_decided_before_the_first_task_start_emit():
    """LIVE 2026-09-25: order matters, and it was wrong.

    The DER-internal decision ran AFTER the earlier task:start emit, so a
    card-free turn still showed a card — and because the terminal events were
    withheld, that card never reached DONE. The decision must come first.
    """
    import inspect

    from backend.agent import agent_kernel as _mod

    src = inspect.getsource(_mod)
    gate_at = src.find("card_warranted(")
    first_emit_at = src.find("IRISStreamEvent.TASK_START")
    assert gate_at != -1, "no card decision found in the kernel"
    assert first_emit_at != -1, "no task:start emit found in the kernel"
    assert gate_at < first_emit_at, (
        "the card decision must be taken BEFORE the first task:start emit, or a "
        "card-free turn shows a card that can never reach DONE"
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


def test_internal_narration_is_recognised_but_an_answer_is_not():
    """Live 2026-09-25: two strings reached the user that are the agent's own
    thinking, not answers."""
    from backend.agent.artifact_policy import looks_like_internal_narration

    # The failed three-file turn, verbatim.
    assert looks_like_internal_narration(
        "We haven't performed the read yet. Need to call read_file for the three "
        "files.Let's run read_file."
    )
    # The report card's opening line, verbatim.
    assert looks_like_internal_narration(
        "The tool only returned a partial draft; it omitted full sections on "
        "condensation, precipitation and collection."
    )
    # Real answers are untouched.
    assert not looks_like_internal_narration(
        "Here are the three bullet points about tea you asked for."
    )
    assert not looks_like_internal_narration(
        "# Water cycle\n\nWater moves between land, sea and sky."
    )
    assert not looks_like_internal_narration("")


def test_a_leading_narration_paragraph_is_dropped_when_an_answer_follows():
    """The report that opened with meta-commentary keeps its report."""
    from backend.agent.artifact_policy import strip_leading_narration

    body = (
        "The tool only returned a partial draft; it omitted full sections.\n\n"
        "# The water cycle\n\nWater evaporates, condenses and precipitates."
    )
    out = strip_leading_narration(body)
    assert out.startswith("# The water cycle")
    # A real answer that merely mentions "let me" keeps its first paragraph,
    # and a single-paragraph text is never touched.
    single = "Let me explain the water cycle: water moves between land and sky."
    assert strip_leading_narration(single) == single
    lead_only = "Need to call read_file for the three files."
    assert strip_leading_narration(lead_only) == lead_only


def test_a_conversation_scoped_frame_is_withheld_too():
    """LIVE 2026-09-25: the live action frames name only their conversation.

    {"type":"task:progress","payload":{"description":"Editing x.md",
    "conversation_id":"conv-151"}} set the frontend's phase/status
    ("SYNTHESIZING ANSWER") while the matching clear (task:done) was withheld for
    a card-free turn, so the status stayed lit after the answer arrived.
    Withholding by conversation removes that too.
    """
    from backend.agent.artifact_policy import (
        clear_card_free_conversation,
        suppress_card_for_conversation,
    )

    suppress_card_for_conversation("conv-151", "turn-free")
    frame = _Payload(None, {"description": "Editing x.md", "conversation_id": "conv-151"})
    assert WSEventBridge._card_event_withheld(IRISStreamEvent.TASK_PROGRESS, frame)
    # Another conversation in the same process is untouched.
    other = _Payload(None, {"description": "Editing y.md", "conversation_id": "conv-9"})
    assert not WSEventBridge._card_event_withheld(IRISStreamEvent.TASK_PROGRESS, other)
    # A turn that EARNS a card clears the conversation gate again.
    clear_card_free_conversation("conv-151")
    assert not WSEventBridge._card_event_withheld(IRISStreamEvent.TASK_PROGRESS, frame)

