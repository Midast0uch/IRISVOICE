"""Contract: the MCP ``file_manager`` server — the LIVE path for file tools.

``tool_bridge`` maps ``"write_file": ("file_manager", "write_file")``, so THIS
server serves the agent's file calls. The audit log proves the defect these
tests pin:

    "arguments": {"path": "ww_a.md", "contents": "- Tea"}
    "result": "{'success': True, 'message': 'Written to ww_a.md', 'bytes': 0}"

The user was told the file had been written, the file was empty, and the agent
then read nothing back. ``tool_executor``'s own handler had the same defect and
is covered by test_write_file_body_key_contract.py; both now share
``backend/tool_args.py`` so the accepted names cannot drift apart.
"""
import asyncio

from backend.mcp.builtin_servers import FileManagerServer


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_contents_key_is_written(tmp_path):
    srv = FileManagerServer()
    p = tmp_path / "a.md"
    res = _run(srv.execute_tool("write_file", {"path": str(p), "contents": "- Tea"}))
    assert res["success"] is True, res
    assert res["bytes"] == 5
    assert res["bytes_on_disk"] == 5
    assert p.read_text(encoding="utf-8") == "- Tea"


def test_file_path_key_is_accepted(tmp_path):
    srv = FileManagerServer()
    p = tmp_path / "b.md"
    res = _run(srv.execute_tool("write_file", {"file_path": str(p), "content": "# hi"}))
    assert res["success"] is True, res
    assert p.read_text(encoding="utf-8") == "# hi"


def test_missing_body_is_an_error_and_writes_nothing(tmp_path):
    srv = FileManagerServer()
    p = tmp_path / "c.md"
    res = _run(srv.execute_tool("write_file", {"path": str(p)}))
    assert res["success"] is False
    assert "content" in res["error"] and "Keys received" in res["error"]
    assert not p.exists(), "a missing body must not create a file"


def test_missing_path_is_an_explicit_error(tmp_path):
    srv = FileManagerServer()
    res = _run(srv.execute_tool("write_file", {"content": "x"}))
    assert res["success"] is False
    assert "path" in res["error"]


def test_read_file_resolves_the_same_names(tmp_path):
    srv = FileManagerServer()
    p = tmp_path / "d.md"
    p.write_text("- Tea", encoding="utf-8")
    res = _run(srv.execute_tool("read_file", {"file_path": str(p)}))
    assert res["success"] is True and res["content"] == "- Tea"
