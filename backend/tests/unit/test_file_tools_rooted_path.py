"""Regression (eval re-run after Phase 1, 2026-09-29): a rooted path with no
drive stays inside the session workdir.

The tool model wrote "/durations.py" (c04) and "/home/user/mathutils.py" (c01).
On Windows those are not absolute, so the relative branch joined them onto the
workdir and os.path.join kept only the drive: "C:\\durations.py" and
"C:\\home\\user\\mathutils.py". Every write step failed with Errno 2. These
tests use the exact paths from those two turns and fail on that code.
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


def _bridge(workdir):
    bridge = AgentToolBridge.__new__(AgentToolBridge)
    server = _RecordingFileServer()
    bridge._mcp_servers = {"file_manager": server}
    bridge._security_filter = None
    bridge._audit_logger = None
    bridge._session_workdirs = {"sess": workdir}
    return bridge, server


def _call(bridge, tool, params):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(bridge.execute_mcp_tool("file_manager", tool, params, "sess"))
    finally:
        loop.close()


def test_rooted_basename_lands_in_workdir(tmp_path):
    bridge, server = _bridge(str(tmp_path))
    _call(bridge, "write_file", {"path": "/durations.py", "content": "x"})
    assert server.arguments[0]["path"] == os.path.join(str(tmp_path), "durations.py")


def test_invented_home_prefix_is_dropped(tmp_path):
    (tmp_path / "mathutils.py").write_text("")
    bridge, server = _bridge(str(tmp_path))
    _call(bridge, "write_file", {"path": "/home/user/mathutils.py", "content": "x"})
    assert server.arguments[0]["path"] == os.path.join(str(tmp_path), "mathutils.py")


def test_rooted_path_keeps_existing_subfolder(tmp_path):
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    bridge, server = _bridge(str(tmp_path))
    _call(bridge, "write_file", {"file_path": "\\src\\pkg\\new.py", "content": "x"})
    assert server.arguments[0]["file_path"] == os.path.join(str(tmp_path), "src", "pkg", "new.py")


def test_parent_segments_cannot_leave_workdir(tmp_path):
    bridge, server = _bridge(str(tmp_path))
    _call(bridge, "read_file", {"path": "/../../secret.txt"})
    assert server.arguments[0]["path"] == os.path.join(str(tmp_path), "secret.txt")
