"""Regression (Phase 0 eval, 2026-09-29): file tools resolve a relative path
against the session workdir, the same folder run_command already uses.

Before the fix, execute_mcp_tool passed params["path"] unchanged, so
"test_mathutils.py" was read from the backend's cwd (the IRIS repo) and every
coding task in another project failed with Errno 2. The first test fails on
that code.
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

from backend.agent.tool_bridge import AgentToolBridge


class _RecordingFileServer:
    def __init__(self):
        self.arguments = []

    async def handle_request(self, request):
        self.arguments.append(request.params["arguments"])
        return SimpleNamespace(result={"success": True}, error=None)


def _bridge(workdir=None):
    bridge = AgentToolBridge.__new__(AgentToolBridge)
    server = _RecordingFileServer()
    bridge._mcp_servers = {"file_manager": server}
    bridge._security_filter = None
    bridge._audit_logger = None
    bridge._session_workdirs = {"sess": workdir} if workdir else {}
    return bridge, server


def _call(bridge, tool, params):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(bridge.execute_mcp_tool("file_manager", tool, params, "sess"))
    finally:
        loop.close()


def test_relative_path_resolves_against_session_workdir(tmp_path):
    bridge, server = _bridge(str(tmp_path))
    _call(bridge, "read_file", {"path": "test_mathutils.py"})
    _call(bridge, "write_file", {"file_path": os.path.join("pkg", "mod.py"), "content": "x"})
    assert server.arguments[0]["path"] == os.path.join(str(tmp_path), "test_mathutils.py")
    assert server.arguments[1]["file_path"] == os.path.join(str(tmp_path), "pkg", "mod.py")
    assert server.arguments[1]["content"] == "x"


def test_absolute_path_is_untouched(tmp_path):
    bridge, server = _bridge(str(tmp_path))
    absolute = os.path.join(str(tmp_path.parent), "elsewhere.txt")
    _call(bridge, "read_file", {"path": absolute})
    assert server.arguments[0]["path"] == absolute


def test_no_bound_workdir_keeps_old_behaviour():
    bridge, server = _bridge(None)
    _call(bridge, "list_directory", {"path": "scripts"})
    assert server.arguments[0]["path"] == "scripts"
