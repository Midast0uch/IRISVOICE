"""Contract (reply-surface-contract REQ-16 edge / AC11.4; audit 2026-09-22,
F3): one card per turn holds on the TOOL path too.

A second render intent in the SAME turn — whether from a repeated
render_document call or from the model's trailing `show` envelope after a
tool render — revises the existing card in place. It must never mint a
second card with a second card_id.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from types import SimpleNamespace

from unittest.mock import patch

from backend.agent.document_store import DocumentDataStore
from backend.agent.event_bus import (
    IRISStreamEvent,
    get_event_bus,
    reset_event_bus_for_testing,
)
from backend.agent.tool_bridge import AgentToolBridge

import pytest


@pytest.fixture(autouse=True)
def _reset_bus():
    reset_event_bus_for_testing()
    yield
    reset_event_bus_for_testing()


class _Kernel:
    """Minimal stand-in: mapping pre-populated with the turn's first card."""

    def __init__(self, store: DocumentDataStore):
        self._store = store
        self._current_turn_id = "turn-abc"
        self._render_doc_for_turn = {"turn-abc": "doc-first"}
        self.revisions = []

    def _get_document_store(self):
        return self._store

    def _prism_card_id_for(self, document_id: str) -> str:
        return f"card_doc_{document_id}"

    @staticmethod
    def _store_document_data(**_kw):
        return None

    def _record_turn_render(self, turn_id, document_id):
        self._render_doc_for_turn[turn_id] = document_id

    def update_document(self, document_id, **kw):
        self.revisions.append((document_id, kw))
        return document_id


def _bridge() -> AgentToolBridge:
    bridge = AgentToolBridge.__new__(AgentToolBridge)
    bridge._active_conversation_id = {}
    bridge._logger = logging.getLogger("test_render_tool_one_card")
    return bridge


def _render(bridge, params, session="sess"):
    async def run():
        with patch(
            "backend.agent.agent_kernel.get_agent_kernel",
            return_value=_KERNEL,
        ):
            return await bridge._execute_render_document(params, session)

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(run())
    finally:
        loop.close()


_KERNEL = None  # bound per-test via _bind()


def _bind(kernel):
    global _KERNEL
    _KERNEL = kernel


class TestOneCardPerTurnOnTheToolPath:
    def test_second_tool_render_revises_the_first_card(self):
        store = DocumentDataStore(sqlite3.connect(":memory:"))
        kernel = _Kernel(store)
        _bind(kernel)
        bridge = _bridge()

        captured = []
        get_event_bus().subscribe(
            IRISStreamEvent.DOCUMENT_RENDER,
            lambda payload, **kw: captured.append(payload.data),
        )

        result = _render(
            bridge,
            {
                "format": "markdown",
                "content": "# Second intent",
                "conversation_id": "c1",
            },
        )

        assert result["success"] is True
        assert result.get("revised") is True
        assert result["document_id"] == "doc-first", (
            "a second render intent in one turn must revise, not mint"
        )
        # The revision path went through update_document, so no NEW whole-card
        # emit came from this block.
        assert captured == []
        assert kernel.revisions and kernel.revisions[0][0] == "doc-first"

    def test_without_prior_render_id_the_fresh_path_is_used(self):
        store = DocumentDataStore(sqlite3.connect(":memory:"))
        kernel = _Kernel(store)
        kernel._render_doc_for_turn = {}  # turn has no card yet
        _bind(kernel)
        bridge = _bridge()

        captured = []
        get_event_bus().subscribe(
            IRISStreamEvent.DOCUMENT_RENDER,
            lambda payload, **kw: captured.append(payload.data),
        )

        result = _render(
            bridge,
            {"format": "markdown", "content": "# First", "conversation_id": "c1"},
        )
        assert result["success"] is True
        assert len(captured) == 1
        # The fresh render took the kernel's live turn id, so the card joins
        # the running turn in the UI.
        assert captured[0]["turn_id"] == "turn-abc"
        assert kernel._render_doc_for_turn["turn-abc"] == result["document_id"]
