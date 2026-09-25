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
    # ANY heading level counts as a document shape: a report uses H2s. The TITLE
    # rule is separate and still prefers an H1 (card_title_from_content).
    assert is_artifact_document("## A section heading\n\nprose.")
    assert not is_artifact_document("no heading here, just prose\nand more prose")
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


def test_a_report_without_a_heading_is_still_an_artifact():
    """Live 2026-09-25: a 250-word report with bold lead-ins and bullets, NO
    heading, stayed a scrolling bubble. The ask was a report and the body is a
    report, so it must become a card — the rule is about TYPE, not shape."""
    from backend.agent.artifact_policy import is_substantial_markdown

    body = (
        "**Overview** The water cycle moves water between land, sea and sky.\n\n"
        "- Evaporation lifts water as vapour.\n- Condensation forms clouds.\n"
        "- Precipitation returns it to the surface.\n\n" + "More prose here. " * 40
    )
    assert is_substantial_markdown(body)
    # A short answer to the same ask is not a report.
    assert not is_substantial_markdown("Here you go!")
    # A long CHAT answer with no markdown structure is not a report either.
    assert not is_substantial_markdown("word " * 200)


def test_card_title_prefers_heading_then_ask_then_first_line():
    """Owner 2026-09-25: labels must be unique to the artifact."""
    from backend.agent.artifact_policy import card_title_for

    assert card_title_for("# Real Title\nbody", "write a report on X") == "Real Title"
    assert card_title_for(
        "**Overview** The water cycle...",
        "write a markdown report about the water cycle, around 250 words",
    ) == "Markdown Report About The Water Cycle"
    assert card_title_for("The water cycle is a process.", "") == \
        "The water cycle is a process."


def test_title_from_ask_names_the_card_when_the_body_has_no_heading():
    """A report body with no H1 still gets a real label (owner: title labels)."""
    from backend.agent.artifact_policy import title_from_ask

    assert title_from_ask("write a markdown report about the water cycle, around 250 words") == \
        "Markdown Report About The Water Cycle"
    assert title_from_ask("draft a detailed report on the top 5 AI chip startups").startswith(
        "Detailed Report"
    )
    assert title_from_ask("") == "Document"


def test_a_report_without_a_heading_is_still_a_document():
    """The water-cycle report: bold lead-ins and bullets, no heading.

    It stayed a scrolling bubble because the shape test wanted a heading. The
    owner's line is about TYPE: a report is an artifact.
    """
    from backend.agent.artifact_policy import is_substantial_markdown

    report = ("**Evaporation** moves water from lakes and oceans into the air, where it "
              "condenses into clouds.\n\n"
              "- Precipitation returns water to the surface.\n"
              "- Collection gathers it in rivers and aquifers.\n\n"
              "Understanding the cycle matters for managing water resources.")
    assert not is_substantial_markdown(report)  # ~300 chars: under the report floor
    assert is_substantial_markdown(report * 3)  # report length, structured
    # A short conversational answer is never a document, however it is spaced.
    assert not is_substantial_markdown("Sure! Here you go.\n\nEnjoy.")


def test_card_title_prefers_a_heading_then_the_ask():
    from backend.agent.artifact_policy import card_title_for

    ask = "write a markdown report about the water cycle, around 250 words"
    assert card_title_for("# Water cycle\nbody", ask) == "Water cycle"
    assert card_title_for("no heading, just prose", ask) == (
        "Markdown Report About The Water Cycle"
    )


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

