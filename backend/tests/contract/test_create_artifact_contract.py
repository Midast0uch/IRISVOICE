"""Contract (reply-surface audit, Phase A): ONE trigger for a card.

``create_artifact(title, kind, summary, content, language=None,
artifact_id=None)`` is the only way a card appears. The older `{speak, show}`
JSON converts to the same call, and a plain text reply never becomes a card.

Every test here runs the REAL kernel methods (``create_artifact``,
``_store_document_data``, ``_process_structured_response``) on a REAL
``DocumentDataStore`` (an in-memory sqlite connection). Nothing stubs the store:
the render-tool tests this file replaces stubbed ``_store_document_data(**_kw)``,
which accepts anything, and so hid a TypeError that made every call fail live
(execution audit R1, 2026-09-29).

Which tests fail on the code before this change (HEAD):
  * a, b, d, e, f, h, i, k  - no ``create_artifact`` on the kernel (AttributeError),
    and a `show` event carried no title/kind/summary;
  * c  - a long markdown reply to a "write a report" ask was turned into a card
    by the fallback mint (``_mint_artifact_card``);
  * d2 - a heading-less `show` body, and a `show` that read "I was not able to
    pull any usable pages", were demoted to plain text (markdown demotion and
    the backend failed-search phrase test);
  * g  - the presentation observer ran only on the plain exit;
  * j  - ``_maybe_escalate_web_format`` existed.
"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.document_store import DocumentDataStore
from backend.agent.event_bus import IRISStreamEvent

# Every key the card needs, on the wire. Frontend and rehydration read these.
EVENT_KEYS = {
    "title", "kind", "summary", "language", "format", "content", "document_id",
    "turn_id", "card_id", "conversation_id", "trust",
}


class _Bus:
    def __init__(self):
        self.events = []

    def emit(self, event, data=None, turn_id=None, conversation_id=None, **kw):
        self.events.append((event, data))

    def renders(self):
        return [d for (e, d) in self.events if e == IRISStreamEvent.DOCUMENT_RENDER]

    def questions(self):
        return [d for (e, d) in self.events if e == IRISStreamEvent.QUESTION_ASK]


class _Episodic:
    def __init__(self, conn):
        self.db = conn

    def fragment_and_store(self, *a, **k):
        pass


@pytest.fixture
def world():
    """A real kernel on a real in-memory DocumentDataStore."""
    conn = sqlite3.connect(":memory:")
    mi = SimpleNamespace(episodic=_Episodic(conn))
    k = AgentKernel.__new__(AgentKernel)
    k._memory_interface = mi
    k._pacman_zone_for_turn = lambda: "chat"
    k._last_render_emitted = False
    k._last_spoken_text = ""
    observed = []
    k._observe_surface_async = lambda response, turn_id=None, live_surface="plain": (
        observed.append(live_surface)
    )
    bus = _Bus()
    with patch("backend.agent.event_bus.get_event_bus", return_value=bus), \
         patch("backend.agent.caducean_trajectory.get_trajectory_recorder") as gtr, \
         patch("backend.utils.durability_queue.submit"):
        gtr.return_value.get_latest_coordinate.return_value = None
        yield SimpleNamespace(
            k=k, bus=bus, store=DocumentDataStore.get_for(mi), observed=observed
        )


def _make(w, **over):
    args = dict(
        title="Q3 revenue model",
        kind="document",
        summary="Revenue by region with the three growth cases.",
        content="# Model\n\nRegion tables follow.",
    )
    args.update(over)
    turn_id = args.pop("turn_id", "turn-1")
    return w.k.create_artifact(
        args.pop("title"), args.pop("kind"), args.pop("summary"), args.pop("content"),
        turn_id=turn_id, conversation_id=args.pop("conversation_id", "c1"), **args,
    )


# ── (a) the tool call stores on the real store and emits the full event ──────

def test_a_create_artifact_stores_and_emits_title_kind_summary_turn(world):
    result = _make(world)
    assert result["success"] is True, result
    assert result["version"] == 1
    renders = world.bus.renders()
    assert len(renders) == 1
    data = renders[0]
    assert EVENT_KEYS <= set(data), EVENT_KEYS - set(data)
    assert data["title"] == "Q3 revenue model"
    assert data["kind"] == "document"
    assert data["summary"].startswith("Revenue by region")
    assert data["turn_id"] == "turn-1"
    assert data["conversation_id"] == "c1"
    assert data["card_id"].startswith("card_doc_")
    assert data["trust"] == "trusted"
    assert data["document_id"] == result["artifact_id"]
    row = world.store.get(result["artifact_id"])
    assert row is not None, "the artifact must be stored on the real store"
    assert (row["title"], row["kind"], row["card_id"], row["turn_id"]) == (
        "Q3 revenue model", "document", data["card_id"], "turn-1",
    )
    assert row["summary"] == data["summary"]


# ── (b) a card never appears without a title, a summary and a body ───────────

@pytest.mark.parametrize("missing", ["title", "summary", "content"])
def test_b_missing_title_summary_or_content_is_refused(world, missing):
    result = _make(world, **{missing: "   "})
    assert result["success"] is False
    assert missing in result["error"]
    assert world.bus.renders() == [], "a refused artifact must emit nothing"
    assert world.store.list_for_conversation("c1", metadata_only=False) == []


def test_b_a_tool_result_envelope_and_an_unknown_kind_are_refused(world):
    receipt = '{"success": true, "message": "Written to tts_check.md"}'
    assert _make(world, content=receipt)["success"] is False
    assert _make(world, kind="poster")["success"] is False
    assert world.bus.renders() == []
    assert world.store.list_for_conversation("c1", metadata_only=False) == []


# ── (c) a plain reply never becomes a card ───────────────────────────────────

def test_c_plain_markdown_reply_to_a_build_ask_is_never_a_card(world):
    """The exact shape the deleted fallback mint turned into a card: a build
    verb + a document noun in the ask, and a long markdown body with headings
    in the reply, with no `show` and no create_artifact call."""
    world.k._current_task_text = "write a detailed report on the water cycle"
    body = (
        "# The water cycle\n\n## Evaporation\n\n"
        + "Water rises as vapour from oceans and lakes. " * 12
        + "\n\n## Condensation\n\n- Clouds form.\n- Droplets grow.\n\n"
        + "| stage | driver |\n| --- | --- |\n| rain | gravity |\n"
    )
    out = world.k._process_structured_response(body, turn_id="t-c", conversation_id="c1")
    assert world.bus.renders() == [], "a plain reply must never become a card"
    assert out == body.strip() or out == body, "the reply is shown in full"
    assert world.k._last_render_emitted is False
    assert world.store.list_for_conversation("c1", metadata_only=False) == []


# ── (d) a `show` converts to the same call, so the same event shape ──────────

def test_d_show_converts_to_the_same_event_shape(world):
    _make(world, turn_id="turn-tool")
    tool_event = world.bus.renders()[0]
    world.k._process_structured_response(
        json.dumps({
            "speak": "The report is on the card. It covers three regions.",
            "show": {"format": "markdown", "content": "# Regional report\n\nBody."},
        }),
        turn_id="turn-show",
        conversation_id="c1",
    )
    show_event = world.bus.renders()[1]
    assert EVENT_KEYS <= set(show_event), EVENT_KEYS - set(show_event)
    assert set(tool_event) == set(show_event), "one door means one event shape"
    assert show_event["title"] == "Regional report"
    assert show_event["kind"] == "document"
    # No summary in the `show`: the first sentence of `speak` stands in.
    assert show_event["summary"] == "The report is on the card."
    assert show_event["turn_id"] == "turn-show"
    row = world.store.get(show_event["document_id"])
    assert (row["title"], row["kind"]) == ("Regional report", "document")


@pytest.mark.parametrize("show", [
    {"format": "markdown", "content": "- one\n- two"},
    {"format": "markdown", "content": "body"},
    {"format": "markdown", "content": (
        "I wasn't able to pull any usable pages for this query.\n\n"
        "What was attempted: a crawl.\nWhat failed: no usable content."
    )},
])
def test_d2_a_show_is_a_card_whatever_the_shape_of_its_body(world, show):
    """`show` is the model choosing to keep something. The old body-shape
    demotion and the failed-search phrase test second-guessed it."""
    out = world.k._process_structured_response(
        json.dumps({"speak": "Saved it.", "show": show}),
        turn_id="t-d2", conversation_id="c1",
    )
    renders = world.bus.renders()
    assert len(renders) == 1
    assert renders[0]["title"] and renders[0]["summary"]
    assert out == "Saved it.", "the bubble is the speak line while a card holds the body"


# ── (e) a reload shows the card the live turn showed ─────────────────────────

def test_e_reload_returns_the_stored_title_kind_and_summary(world):
    result = _make(
        world, title="Q3 revenue model",
        content="# Draft heading that is not the title\n\nBody.",
    )
    docs = world.store.list_for_conversation("c1", metadata_only=True)
    assert len(docs) == 1
    assert docs[0]["document_id"] == result["artifact_id"]
    assert docs[0]["title"] == "Q3 revenue model", (
        "a reload must show the title the card was made with, not one derived "
        "from the body"
    )
    assert docs[0]["kind"] == "document"
    assert docs[0]["summary"].startswith("Revenue by region")
    assert docs[0]["card_id"] == world.bus.renders()[0]["card_id"]
    assert "content" not in docs[0], "hydration stays metadata-only (CT-DOC-1)"


# ── (f) kinds map to formats; code is a fenced block with its language ───────

def test_f_code_kind_wraps_a_fence_with_the_language(world):
    result = _make(
        world, title="fizzbuzz.py", kind="code", language="python",
        summary="A fizzbuzz in python.", content="for i in range(3):\n    print(i)",
    )
    assert result["success"] is True
    data = world.bus.renders()[0]
    assert data["format"] == "markdown"
    assert data["language"] == "python"
    assert data["content"] == "```python\nfor i in range(3):\n    print(i)\n```"
    assert world.store.get(result["artifact_id"])["content"] == data["content"]


def test_f_code_that_contains_a_fence_cannot_close_the_block_early(world):
    _make(world, kind="code", language="md", title="notes.md",
          content="```py\nx = 1\n```")  # already ONE fenced block: kept as is
    _make(world, kind="code", language="md", title="doc.md",
          content="intro\n```py\nx = 1\n```\noutro")
    first, second = world.bus.renders()
    assert first["content"] == "```py\nx = 1\n```"
    assert second["content"].startswith("````md\n") and second["content"].endswith("\n````")


@pytest.mark.parametrize("kind,language,fmt", [
    ("data", "json", "json"),
    ("data", "csv", "markdown"),
    ("diagram", None, "diagram"),
    ("page", None, "html"),
    ("image", None, "image"),
    ("document", None, "markdown"),
])
def test_f_each_kind_maps_to_its_render_format(world, kind, language, fmt):
    _make(world, kind=kind, language=language, content="a,b\n1,2")
    assert world.bus.renders()[-1]["format"] == fmt


# ── (g) the Oracle's presentation observer sees BOTH exits ───────────────────

def test_g_presentation_observer_runs_on_the_artifact_path(world):
    _make(world)
    assert world.observed == ["card"], (
        "the artifact path must feed the presentation shadow observer with the "
        "live surface 'card'"
    )
    world.k._process_structured_response(
        "A plain answer.", turn_id="t-g", conversation_id="c1"
    )
    assert world.observed == ["card", "plain"]


# ── (h) a new version of an artifact keeps its card ──────────────────────────

def test_h_artifact_id_publishes_a_new_version_on_the_same_card(world):
    first = _make(world)
    second = _make(
        world, title="Q3 revenue model v2", content="# Model\n\nRevised.",
        artifact_id=first["artifact_id"], turn_id="turn-2",
    )
    assert second["success"] is True, second
    assert second["artifact_id"] == first["artifact_id"]
    assert second["version"] == 2
    created, revised = world.bus.renders()
    assert revised["updated"] is True and revised["revision"] == 1
    assert revised["card_id"] == created["card_id"], "same card, new version"
    assert revised["title"] == "Q3 revenue model v2"
    assert revised["kind"] == "document"
    row = world.store.get(first["artifact_id"])
    assert row["content"].endswith("Revised.")
    assert row["title"] == "Q3 revenue model v2"
    assert len(world.store.list_for_conversation("c1", metadata_only=True)) == 1


# ── (i) a long title is cut, not refused ─────────────────────────────────────

def test_i_a_title_over_sixty_chars_is_cut(world):
    result = _make(world, title="A" * 90)
    assert result["success"] is True
    assert len(world.bus.renders()[0]["title"]) == 60


# ── (j) the web-format question is gone ──────────────────────────────────────

def test_j_a_web_result_answered_in_plain_text_raises_no_question_and_no_card(world):
    assert not hasattr(AgentKernel, "_maybe_escalate_web_format")
    doc_id = world.k._capture_tool_result(
        "crawler_query",
        {"content": "# Research\n\n- Found A\n- Found B " * 4, "pages": []},
        "c1", "t-j",
    )
    assert doc_id is not None, "capture itself stays: the result is stored"
    world.k._process_structured_response(
        "Here is what I found: A and B.", turn_id="t-j", conversation_id="c1"
    )
    assert world.bus.questions() == []
    assert world.bus.renders() == []


# ── (k) the presentation of `show` keeps its own format ──────────────────────

def test_k_a_show_keeps_the_format_it_names(world):
    world.k._process_structured_response(
        json.dumps({"speak": "Chart ready.", "show": {
            "format": "html", "content": "<h1>Chart</h1>", "title": "Sales chart",
        }}),
        turn_id="t-k", conversation_id="c1",
    )
    data = world.bus.renders()[0]
    assert (data["format"], data["kind"], data["title"]) == ("html", "page", "Sales chart")
    assert data["content"] == "<h1>Chart</h1>"
