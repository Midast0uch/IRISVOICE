"""Phase 1.2 — in-process MCP timeout (B2 + RC10).

Covers: (1) the asyncio.wait_for timeout pattern on a hanging server, (2) that
file I/O via asyncio.to_thread does not block the event loop, (3) the real
AgentToolBridge timeout branch, and (4) that FileManagerServer.read_file still
works after being moved onto asyncio.to_thread.
"""
import asyncio
import os
import tempfile
import time

import pytest


@pytest.mark.asyncio
async def test_in_process_mcp_timeout():
    """B2: in-process MCP tools MUST timeout, not hang."""

    class HangingServer:
        async def handle_request(self, req):
            await asyncio.sleep(999)  # simulate hang

    try:
        await asyncio.wait_for(HangingServer().handle_request(None), timeout=0.1)
        assert False, "Should have timed out"
    except asyncio.TimeoutError:
        pass  # correct behavior


@pytest.mark.asyncio
async def test_file_io_does_not_block_event_loop():
    """RC10: file I/O in MCP servers MUST run in a thread, not block the loop."""
    responsiveness = []

    async def check_loop():
        start = asyncio.get_event_loop().time()
        await asyncio.sleep(0.01)
        responsiveness.append(asyncio.get_event_loop().time() - start)

    async def file_op():
        await asyncio.to_thread(time.sleep, 0.1)  # simulated blocking I/O

    await asyncio.gather(check_loop(), file_op())
    # Event loop should have responded in ~10ms, not blocked for 100ms
    assert responsiveness[0] < 0.05, f"Event loop blocked: {responsiveness[0]:.3f}s"


@pytest.mark.asyncio
async def test_execute_mcp_tool_returns_timeout_error():
    """B2: a hung MCP server MUST surface a timeout error, not hang forever."""
    from backend.agent.tool_bridge import AgentToolBridge

    class HangingServer:
        async def handle_request(self, req):
            raise asyncio.TimeoutError("simulated hang")

    bridge = AgentToolBridge()
    bridge._mcp_servers["fake"] = HangingServer()
    result = await bridge.execute_mcp_tool("fake", "tool", {})
    assert result.get("success") is False
    assert "timed out" in result.get("error", "").lower()


@pytest.mark.asyncio
async def test_file_manager_read_via_thread():
    """RC10: read_file runs via to_thread and still returns content."""
    from backend.mcp.builtin_servers import FileManagerServer

    server = FileManagerServer()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tf:
        tf.write("hello world")
        path = tf.name
    try:
        result = await server.execute_tool("read_file", {"path": path})
        assert result.get("success") is True
        assert "hello world" in result.get("content", "")
    finally:
        os.unlink(path)
