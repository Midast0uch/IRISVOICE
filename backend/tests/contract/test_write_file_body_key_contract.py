"""Contract: write_file accepts its body as 'content' OR 'contents'.

LIVE DEFECT 2026-09-25. The model sent

    {"path": "tts_check6.md", "contents": "- Snow is frozen precipitation ..."}

and the handler read only ``content``, so the missing key silently became "".
The file was created EMPTY, the tool answered ``success: True, bytes: 0``, the
agent read nothing back, and the user was told the file had been written. The
security audit log is what proved the body existed. These tests pin both
spellings, and pin that a missing body is an ERROR rather than an empty write.
"""
from backend.agent.tool_executor import ToolExecutor


def _executor():
    return ToolExecutor.__new__(ToolExecutor)  # no __init__: pure handler test


def test_contents_spelling_is_accepted(tmp_path):
    p = tmp_path / "note.md"
    res = _executor()._write_file({"path": str(p), "contents": "- one\n- two"}, {})
    assert res["success"] is True
    assert res["bytes"] > 0
    assert p.read_text(encoding="utf-8") == "- one\n- two"


def test_content_spelling_still_works(tmp_path):
    p = tmp_path / "note2.md"
    res = _executor()._write_file({"path": str(p), "content": "# Title\nbody"}, {})
    assert res["success"] is True
    assert p.read_text(encoding="utf-8") == "# Title\nbody"


def test_file_path_spelling_is_accepted(tmp_path):
    """LIVE 2026-09-25: the model sent `file_path`, the handler read `path`, and
    write_file crashed with "[Errno 2] No such file or directory: ''"."""
    p = tmp_path / "note4.md"
    res = _executor()._write_file({"file_path": str(p), "content": "# hi\nbody"}, {})
    assert res["success"] is True
    assert p.read_text(encoding="utf-8") == "# hi\nbody"
    # read_file resolves the same spellings.
    read = _executor()._read_file({"file_path": str(p)}, {})
    assert read["success"] is True and read["content"] == "# hi\nbody"


def test_a_missing_path_is_an_explicit_error(tmp_path):
    for handler, name in ((_executor()._write_file, "write_file"),
                          (_executor()._read_file, "read_file")):
        res = handler({"content": "x"}, {})
        assert res["success"] is False
        assert name in res["error"] and "path" in res["error"]


def test_missing_body_is_an_error_not_an_empty_write(tmp_path):
    """The whole defect was silence: no error, success reported, no content."""
    p = tmp_path / "note3.md"
    res = _executor()._write_file({"path": str(p)}, {})
    assert res["success"] is False
    assert "content" in res["error"]
    assert "Keys received" in res["error"]
