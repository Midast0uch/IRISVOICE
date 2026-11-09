"""Contract: file-tool paths are anchored to the session workdir.

Measured 2026-11-07: two c42 rows carried an ABSOLUTE path from an earlier
iris-evals run (Temp/iris-evals/20261102-004139/c42_config_level/settings.ini)
into a 2026-11-07 run. The file existed, so the read succeeded, and the step
failed on the wrong content. A relative path was already anchored; an absolute
path was not. This pins the narrow fix: only an absolute path under a DIFFERENT
iris-evals run is rebased. Other absolute paths (system files, a user path)
stay untouched.
"""
from pathlib import Path

from backend.agent.tool_bridge import AgentToolBridge


def _bridge(workdir):
    b = AgentToolBridge.__new__(AgentToolBridge)
    b._session_workdirs = {"s": str(workdir)}
    return b


def test_relative_path_is_anchored(tmp_path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    out = _bridge(tmp_path)._anchor_file_paths({"path": "a.py"}, "s")
    assert Path(out["path"]) == tmp_path / "a.py"


def test_rooted_path_is_rerooted(tmp_path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    out = _bridge(tmp_path)._anchor_file_paths({"path": "/a.py"}, "s")
    assert Path(out["path"]) == tmp_path / "a.py"


def test_stale_iris_evals_path_is_rebased(tmp_path):
    (tmp_path / "settings.ini").write_text("x", encoding="utf-8")
    stale = str(tmp_path.parent / "iris-evals" / "20261102-004139"
                / "c42_config_level" / "settings.ini")
    out = _bridge(tmp_path)._anchor_file_paths({"path": stale}, "s")
    assert Path(out["path"]) == tmp_path / "settings.ini"


def test_absolute_path_inside_the_workdir_is_untouched(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("x", encoding="utf-8")
    out = _bridge(tmp_path)._anchor_file_paths({"path": str(target)}, "s")
    assert out["path"] == str(target)


def test_other_absolute_path_is_untouched(tmp_path):
    other = str(tmp_path.parent / "elsewhere" / "settings.ini")
    out = _bridge(tmp_path)._anchor_file_paths({"path": other}, "s")
    assert out["path"] == other


def test_no_workdir_is_untouched():
    b = AgentToolBridge.__new__(AgentToolBridge)
    b._session_workdirs = {}
    out = b._anchor_file_paths({"path": "a.py"}, "s")
    assert out["path"] == "a.py"
