"""Contract (specs/reply-surface-contract REQ-16, task T26): render-as-tool.

`render_document` is a registered first-class tool; the `show` envelope stays
the wire transport (CT-1 is unaffected — its suite must stay green); a tool
render emits THE SAME DOCUMENT_RENDER event shape the seam produces,
including the stable card_id (REQ-10).
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3

from unittest.mock import patch

from backend.agent.document_store import DocumentDataStore
from backend.agent.event_bus import (
    IRISStreamEvent,
    get_event_bus,
    reset_event_bus_for_testing,
)
from backend.agent.tool_bridge import AgentToolBridge
from backend.agent.tool_registry import resolve_tool

import pytest


@pytest.fixture(autouse=True)
def _reset_bus():
    reset_event_bus_for_testing()
    yield
    reset_event_bus_for_testing()


class _Kernel:
    def __init__(self, store: DocumentDataStore):
        self._store = store
        self._prism_map: dict = {}

    def _get_document_store(self):
        return self._store

    def _prism_card_id_for(self, document_id: str) -> str:
        existing = self._prism_map.get(document_id)
        if existing:
            return existing
        card_id = f"card_doc_{len(self._prism_map):08d}"
        self._prism_map[document_id] = card_id
        return card_id

    @staticmethod
    def _store_document_data(**_kw):
        return None


def _bridge() -> AgentToolBridge:
    bridge = AgentToolBridge.__new__(AgentToolBridge)
    bridge._active_conversation_id = {}
    bridge._logger = logging.getLogger("test_render_as_tool")
    return bridge


def test_render_document_is_a_registered_tool():
    spec = resolve_tool("render_document")
    assert spec is not None, "render_document missing from the tool registry"
    assert "content" in spec.parameters
    assert spec.executor == "internal"


def test_render_document_emits_the_same_document_render_shape():
    store = DocumentDataStore(sqlite3.connect(":memory:"))
    kernel = _Kernel(store)
    bridge = _bridge()

    captured = []
    get_event_bus().subscribe(
        IRISStreamEvent.DOCUMENT_RENDER, lambda payload, **kw: captured.append(payload.data)
    )

    async def run():
        with patch(
            "backend.agent.agent_kernel.get_agent_kernel", return_value=kernel
        ):
            return await bridge._execute_render_document(
                {
                    "format": "markdown",
                    "content": "# Plan\n\nBody text",
                    "conversation_id": "c1",
                },
                "sess",
            )

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(run())
    finally:
        loop.close()

    assert result["success"] is True
    assert len(captured) == 1
    data = captured[0]
    assert data["content"].startswith("# Plan")
    assert data["format"] == "markdown"
    assert data["document_id"] == result["document_id"]
    assert data["card_id"] == result["card_id"]
    # Same additive channel flags the seam sets (partial channel, REQ-13 AC5).
    assert data["partial"] is False


def test_render_document_refuses_a_tool_result_envelope():
    """Owner report 2026-09-25: "prism cards are rendering with just json output".

    The model called ``render_document`` with the PREVIOUS tool's JSON result as
    the body, so every write/read step minted a prism card whose content was
    ``{"success": true, "message": "Written to X"}`` — conv-151 held four such
    rows (two per turn, format=json). A tool result belongs to the step lane; a
    card is for an artifact. The refusal must mint nothing and emit nothing.
    """
    store = DocumentDataStore(sqlite3.connect(":memory:"))
    kernel = _Kernel(store)
    bridge = _bridge()

    captured = []
    get_event_bus().subscribe(
        IRISStreamEvent.DOCUMENT_RENDER, lambda payload, **kw: captured.append(payload.data)
    )
    envelope = '{"success": true, "message": "Written to tts_check.md", "bytes": 189}'

    async def run():
        with patch(
            "backend.agent.agent_kernel.get_agent_kernel", return_value=kernel
        ):
            return await bridge._execute_render_document(
                {"format": "json", "content": envelope, "conversation_id": "c1"},
                "sess",
            )

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(run())
    finally:
        loop.close()

    assert result["success"] is False
    assert captured == [], "a tool result must never become a prism card"
    assert store.list_for_conversation("c1", metadata_only=False) == []


def test_render_document_still_accepts_a_real_artifact():
    """The refusal is narrow: a real artifact renders exactly as before."""
    store = DocumentDataStore(sqlite3.connect(":memory:"))
    kernel = _Kernel(store)
    bridge = _bridge()
    captured = []
    get_event_bus().subscribe(
        IRISStreamEvent.DOCUMENT_RENDER, lambda payload, **kw: captured.append(payload.data)
    )

    async def run():
        with patch(
            "backend.agent.agent_kernel.get_agent_kernel", return_value=kernel
        ):
            return await bridge._execute_render_document(
                {
                    "format": "markdown",
                    "content": "{\"note\": \"a JSON artifact the user asked to keep\"}",
                    "conversation_id": "c2",
                },
                "sess",
            )

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(run())
    finally:
        loop.close()

    # A JSON body WITHOUT a tool-result 'success' key is a legitimate artifact.
    assert result["success"] is True
    assert len(captured) == 1


def test_render_document_requires_content():
    bridge = _bridge()

    async def run():
        return await bridge._execute_render_document({"format": "markdown"}, "sess")

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(run())
    finally:
        loop.close()
    assert result["success"] is False
    assert "content" in result["error"]
