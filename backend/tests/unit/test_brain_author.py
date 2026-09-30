"""Split roles (owner decision 2026-09-29): the Brain writes file bodies.

Eval re-runs on 2026-09-29 (coding 0/3): the 2.6B tool model resolved
"Implement parse_duration in durations.py" to read_file and never wrote a file.
brain_author turns a chosen edit_file/write_file into Brain-written arguments,
checking every SEARCH block against the current file before any tool call.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.agent.brain_author import author_file_change, author_step

MATHUTILS = (
    "def sum_range(start, end):\n"
    "    total = 0\n"
    "    for n in range(start, end):\n"
    "        total += n\n"
    "    return total\n"
)


def _brain(reply):
    calls = []

    def generate(role, messages, **kw):
        calls.append((role, messages[0]["content"], kw))
        return reply, "", []

    return generate, calls


def test_one_block_becomes_edit_file():
    gen, calls = _brain(
        "<<<<<<< SEARCH\n    for n in range(start, end):\n=======\n"
        "    for n in range(start, end + 1):\n>>>>>>> REPLACE\n"
    )
    tool, params, err = author_file_change(gen, "edit_file", "m.py", "fix off-by-one", MATHUTILS)
    assert err == "" and tool == "edit_file"
    assert params == {"path": "m.py", "old": "    for n in range(start, end):",
                      "new": "    for n in range(start, end + 1):"}
    role, prompt, kw = calls[0]
    assert role == "reasoning" and MATHUTILS in prompt and kw["max_tokens"] >= 4096


def test_several_blocks_become_one_verified_write():
    gen, _ = _brain(
        "```\n<<<<<<< SEARCH\n    total = 0\n=======\n    total = 1\n>>>>>>> REPLACE\n"
        "<<<<<<< SEARCH\n    return total\n=======\n    return total * 2\n>>>>>>> REPLACE\n```"
    )
    tool, params, err = author_file_change(gen, "edit_file", "m.py", "g", MATHUTILS)
    assert tool == "write_file" and err == ""
    assert params["content"] == MATHUTILS.replace("total = 0", "total = 1").replace(
        "return total", "return total * 2")


def test_search_that_does_not_match_fails_before_any_tool_call():
    gen, _ = _brain("<<<<<<< SEARCH\n    for i in range(9):\n=======\n    pass\n>>>>>>> REPLACE\n")
    tool, params, err = author_file_change(gen, "edit_file", "m.py", "g", MATHUTILS)
    assert tool is None and params is None and "matches 0 times" in err


def test_missing_file_is_written_whole():
    gen, _ = _brain("Here it is:\n```python\ndef parse_duration(s):\n    return 0\n```\n")
    tool, params, err = author_file_change(gen, "edit_file", "d.py", "implement", None)
    assert tool == "write_file" and params == {"path": "d.py", "content": "def parse_duration(s):\n    return 0\n"}


def test_crlf_file_is_matched_as_lf():
    gen, _ = _brain("<<<<<<< SEARCH\n    total = 0\n=======\n    total = 5\n>>>>>>> REPLACE\n")
    tool, params, err = author_file_change(gen, "edit_file", "m.py", "g", MATHUTILS.replace("\n", "\r\n"))
    assert tool == "edit_file" and params["old"] == "    total = 0" and err == ""


def test_author_step_reads_the_anchored_file(tmp_path):
    (tmp_path / "mathutils.py").write_text(MATHUTILS, encoding="utf-8")
    bridge = SimpleNamespace(
        _anchor_file_paths=lambda p, s: {"path": str(tmp_path / p["path"].lstrip("/"))})
    gen, calls = _brain("<<<<<<< SEARCH\n    total = 0\n=======\n    total = 5\n>>>>>>> REPLACE\n")
    tool, params, err = author_step(bridge, gen, "sess", "edit_file",
                                    {"path": "/mathutils.py"}, "g")
    assert tool == "edit_file" and params["path"] == str(tmp_path / "mathutils.py")
    assert MATHUTILS in calls[0][1]


def test_brain_failure_is_a_reason_not_a_crash():
    def boom(*a, **k):
        raise RuntimeError("transport down")

    tool, params, err = author_file_change(boom, "edit_file", "m.py", "g", MATHUTILS)
    assert tool is None and "transport down" in err
