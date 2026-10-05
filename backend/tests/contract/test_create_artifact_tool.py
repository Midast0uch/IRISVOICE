"""Contract (reply-surface audit, Phase A): the create_artifact TOOL door.

Replaces test_render_as_tool.py, test_render_tool_one_card_per_turn.py and
test_render_tool_real_store_signature.py (render_document is deleted).

The bridge handler, the kernel method and the store are all REAL here, on an
in-memory ``DocumentDataStore``. The old tests stubbed ``_store_document_data``
with ``**_kw`` (accepts anything), which is how a TypeError on the real
signature went unseen until a live run (execution audit R1, 2026-09-29): a real
kernel makes that class of break impossible to hide.

Retired with render_document: the "one card per turn" rule (AC11.4). It read
``kernel._render_doc_for_turn``, which the real kernel never had, so it never
ran live; and a turn may now make several artifacts (a report AND a code file).
A new VERSION of one artifact goes through ``artifact_id`` instead.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.document_store import DocumentDataStore
from backend.agent.event_bus import IRISStreamEvent
from backend.agent.node_executor import NODE_TOOLS
from backend.agent.permissions import PermissionTier, classify_tool
from backend.agent.tool_bridge import AgentToolBridge
from backend.agent.tool_registry import resolve_tool, to_function_schema


class _Bus:
    def __init__(self):
        self.renders = []

    def emit(self, event, data=None, **kw):
        if event == IRISStreamEvent.DOCUMENT_RENDER:
            self.renders.append(data)


class _Episodic:
    def __init__(self, conn):
        self.db = conn

    def fragment_and_store(self, *a, **k):
        pass


@pytest.fixture
def rig():
    # check_same_thread=False like the production connection (memory/db.py): the
    # handler runs the kernel call off the event loop.
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    mi = SimpleNamespace(episodic=_Episodic(conn))
    kernel = AgentKernel.__new__(AgentKernel)
    kernel._memory_interface = mi
    kernel._pacman_zone_for_turn = lambda: "chat"
    kernel._current_turn_id = "turn-live"
    kernel._observe_surface_async = lambda *a, **kw: None
    bridge = AgentToolBridge.__new__(AgentToolBridge)
    bridge._active_conversation_id = {}
    bridge._logger = logging.getLogger("test_create_artifact_tool")
    bus = _Bus()
    with patch("backend.agent.event_bus.get_event_bus", return_value=bus), \
         patch("backend.agent.caducean_trajectory.get_trajectory_recorder") as gtr, \
         patch("backend.utils.durability_queue.submit"), \
         patch("backend.agent.agent_kernel.get_agent_kernel", return_value=kernel):
        gtr.return_value.get_latest_coordinate.return_value = None
        yield SimpleNamespace(
            kernel=kernel, bridge=bridge, bus=bus,
            store=DocumentDataStore.get_for(mi),
        )


def _call(rig, params):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(rig.bridge._execute_create_artifact(params, "sess"))
    finally:
        loop.close()


_GOOD = {
    "title": "Launch plan",
    "kind": "document",
    "summary": "Steps and owners for the launch.",
    "content": "# Launch plan\n\nStep one.",
    "conversation_id": "c1",
}


def test_the_tool_stores_and_emits_on_the_live_turn(rig):
    result = _call(rig, dict(_GOOD))
    assert result["success"] is True, result
    assert result["version"] == 1
    assert len(rig.bus.renders) == 1
    data = rig.bus.renders[0]
    assert data["document_id"] == result["artifact_id"]
    assert data["card_id"] == result["card_id"]
    assert data["turn_id"] == "turn-live", (
        "the tool layer is not given the turn id: the kernel that owns the turn "
        "supplies it, so the card joins the live turn"
    )
    assert data["partial"] is False
    assert rig.store.get(result["artifact_id"])["title"] == "Launch plan"


def test_the_tool_refuses_a_tool_result_envelope_and_missing_fields(rig):
    """Owner report 2026-09-25: "prism cards are rendering with just json
    output" - a tool result must never become a card."""
    receipt = '{"success": true, "message": "Written to tts_check.md", "bytes": 189}'
    assert _call(rig, {**_GOOD, "content": receipt})["success"] is False
    bare = _call(rig, {"conversation_id": "c1"})
    assert bare["success"] is False
    for name in ("title", "summary", "content"):
        assert name in bare["error"]
    assert rig.bus.renders == []
    assert rig.store.list_for_conversation("c1", metadata_only=False) == []


def test_a_json_body_without_a_success_key_is_a_real_artifact(rig):
    result = _call(rig, {
        **_GOOD, "kind": "data", "language": "json", "title": "Config",
        "content": '{"note": "a JSON artifact the user asked to keep"}',
    })
    assert result["success"] is True
    assert rig.bus.renders[0]["format"] == "json"


def test_two_artifacts_in_one_turn_are_two_cards(rig):
    a = _call(rig, dict(_GOOD))
    b = _call(rig, {**_GOOD, "title": "Launch script", "kind": "code",
                    "language": "python", "content": "print('go')"})
    assert a["card_id"] != b["card_id"]
    assert len(rig.bus.renders) == 2


# ── the schema the model sees, in every place a tool menu is built ───────────

def test_create_artifact_is_registered_and_render_document_is_gone():
    spec = resolve_tool("create_artifact")
    assert spec is not None, "create_artifact missing from the tool registry"
    assert resolve_tool("render_document") is None
    assert spec.executor == "internal"
    assert set(spec.parameters) == {
        "title", "kind", "summary", "content", "language", "artifact_id",
    }
    assert spec.parameters["kind"]["enum"] == [
        "document", "code", "data", "diagram", "page", "image",
    ]


def test_the_chat_tool_list_and_the_node_menu_both_offer_it(rig):
    chat = {t["name"]: t for t in rig.bridge.get_available_tools()}
    assert "create_artifact" in chat and "render_document" not in chat
    assert "create_artifact" in NODE_TOOLS
    fn = to_function_schema([chat["create_artifact"]])[0]["function"]
    assert set(fn["parameters"]["required"]) == {"title", "kind", "summary", "content"}
    assert fn["parameters"]["properties"]["kind"]["enum"] == [
        "document", "code", "data", "diagram", "page", "image",
    ]
    # Same menu in the registry (DER) and the chat list (direct reply).
    assert set(chat["create_artifact"]["parameters"]) == set(
        resolve_tool("create_artifact").parameters
    )


def test_create_artifact_never_raises_a_permission_card():
    """It writes only the app's own document store. A title such as "Format of
    the report" must not read as the destructive pattern "format "."""
    params = {"title": "Format of the report", "kind": "document",
              "summary": "How to format it", "content": "overwrite nothing"}
    assert classify_tool("create_artifact", params) == PermissionTier.READ_ONLY


def test_the_crawler_description_points_at_create_artifact():
    text = resolve_tool("crawler_query").description
    assert "'show' field" not in text and "create_artifact" in text
