"""Execution audit B9 (2026-09-29): there was no edit tool, and read_file had
no line range. A change meant rewriting the whole file, which the small tool
model never attempted (eval re-runs: no step resolved to a write tool).

edit_file(path, old, new) replaces exactly one exact occurrence; read_file
takes start_line/end_line; write_file writes atomically.
"""

from __future__ import annotations

import asyncio

from backend.mcp.builtin_servers import FileManagerServer


def _run(name, args):
    return asyncio.run(FileManagerServer().execute_tool(name, args))


def test_edit_replaces_the_single_match(tmp_path):
    f = tmp_path / "mathutils.py"
    f.write_text("def f(a, b):\n    return range(a, b)\n", encoding="utf-8")
    r = _run("edit_file", {"path": str(f), "old": "range(a, b)", "new": "range(a, b + 1)"})
    assert r["success"] is True and r["line"] == 2
    assert f.read_text(encoding="utf-8") == "def f(a, b):\n    return range(a, b + 1)\n"


def test_edit_refuses_missing_and_ambiguous_text(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("x = 1\nx = 1\n", encoding="utf-8")
    missing = _run("edit_file", {"path": str(f), "old": "y = 2", "new": "y = 3"})
    twice = _run("edit_file", {"path": str(f), "old": "x = 1", "new": "x = 2"})
    assert missing["success"] is False and "not found" in missing["error"]
    assert twice["success"] is False and "2 times" in twice["error"]
    assert f.read_text(encoding="utf-8") == "x = 1\nx = 1\n"


def test_edit_keeps_crlf_endings_for_an_lf_quote(tmp_path):
    f = tmp_path / "w.py"
    f.write_bytes(b"a = 1\r\nb = 2\r\n")
    r = _run("edit_file", {"path": str(f), "old": "a = 1\nb = 2", "new": "a = 1\nb = 3"})
    assert r["success"] is True
    assert f.read_bytes() == b"a = 1\r\nb = 3\r\n"


def test_edit_accepts_old_string_new_string_names(tmp_path):
    f = tmp_path / "n.py"
    f.write_text("v = 0\n", encoding="utf-8")
    r = _run("edit_file", {"file_path": str(f), "old_string": "v = 0", "new_string": "v = 9"})
    assert r["success"] is True and f.read_text(encoding="utf-8") == "v = 9\n"


def test_read_file_line_range(tmp_path):
    f = tmp_path / "r.txt"
    f.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    r = _run("read_file", {"path": str(f), "start_line": "2", "end_line": 3})
    assert r["content"] == "two\nthree\n"
    assert (r["start_line"], r["end_line"], r["total_lines"]) == (2, 3, 4)


def test_write_file_leaves_no_temp_file(tmp_path):
    f = tmp_path / "out.txt"
    r = _run("write_file", {"path": str(f), "content": "hello"})
    assert r["success"] is True and f.read_text(encoding="utf-8") == "hello"
    assert [p.name for p in tmp_path.iterdir()] == ["out.txt"]
