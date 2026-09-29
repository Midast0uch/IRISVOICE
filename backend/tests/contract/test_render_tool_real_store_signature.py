"""Regression (execution audit R1, 2026-09-29): render_document must call the
kernel's store with arguments the REAL method accepts.

The existing render-tool contract tests stub ``_store_document_data(**_kw)``,
which accepts anything. The live call passed ``card_id=``, which the real
method does not take, so every render_document call raised TypeError, was
caught, and returned a failure with no card. This test binds the call against
the real signature and fails on that code.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from unittest.mock import patch

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.event_bus import (
    IRISStreamEvent,
    get_event_bus,
    reset_event_bus_for_testing,
)
from backend.agent.tool_bridge import AgentToolBridge

_REAL_STORE_SIGNATURE = inspect.signature(AgentKernel._store_document_data)


@pytest.fixture(autouse=True)
def _reset_bus():
    reset_event_bus_for_testing()
    yield
    reset_event_bus_for_testing()


class _KernelWithRealStoreSignature:
    def __init__(self):
        self.stored = []

    def _prism_card_id_for(self, document_id: str) -> str:
        return f"card_doc_{document_id[:8]}"

    def _store_document_data(self, *args, **kwargs):
        # Raises TypeError exactly as the real method would.
        _REAL_STORE_SIGNATURE.bind(self, *args, **kwargs)
        self.stored.append(kwargs)


def test_render_document_store_call_matches_real_signature():
    kernel = _KernelWithRealStoreSignature()
    bridge = AgentToolBridge.__new__(AgentToolBridge)
    bridge._active_conversation_id = {}
    bridge._logger = logging.getLogger("test_render_tool_real_store_signature")
    captured = []
    get_event_bus().subscribe(
        IRISStreamEvent.DOCUMENT_RENDER, lambda payload, **kw: captured.append(payload.data)
    )

    async def run():
        with patch("backend.agent.agent_kernel.get_agent_kernel", return_value=kernel):
            return await bridge._execute_render_document(
                {"format": "markdown", "content": "# Plan\n\nBody", "conversation_id": "c1"},
                "sess",
            )

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(run())
    finally:
        loop.close()

    assert result["success"] is True, result
    assert len(kernel.stored) == 1
    assert len(captured) == 1 and captured[0]["card_id"] == result["card_id"]
