"""Execution audit B10 (2026-09-29): while IRIS edits itself, reads, searches
and commands see the sandbox worktree its writes go to.

Writes were routed into .iris-worktree, but read_file / run_command / grep
used the live repo: the agent could not see its own edit, and its tests ran
against the old code.
"""

import os

from backend.agent.tool_bridge import AgentToolBridge


def _bridge(repo, workdir):
    b = AgentToolBridge.__new__(AgentToolBridge)
    b._DEFAULT_REPO = str(repo)
    b._session_workdirs = {"s": str(workdir)}
    return b


def test_live_repo_paths_map_into_the_worktree(tmp_path):
    (tmp_path / ".iris-worktree" / "backend").mkdir(parents=True)
    b = _bridge(tmp_path, tmp_path)
    live = os.path.join(str(tmp_path), "backend", "x.py")
    assert b._self_edit_view(live, "s") == os.path.join(str(tmp_path), ".iris-worktree", "backend", "x.py")
    assert b._self_edit_view(str(tmp_path), "s") == os.path.join(str(tmp_path), ".iris-worktree")


def test_other_paths_and_sessions_are_unchanged(tmp_path):
    (tmp_path / ".iris-worktree").mkdir()
    in_wt = os.path.join(str(tmp_path), ".iris-worktree", "a.py")
    b = _bridge(tmp_path, tmp_path)
    assert b._self_edit_view(in_wt, "s") == in_wt
    outside = str(tmp_path.parent / "elsewhere.py")
    assert b._self_edit_view(outside, "s") == os.path.normpath(outside)
    other_project = _bridge(tmp_path, tmp_path.parent)
    live = os.path.join(str(tmp_path), "a.py")
    assert other_project._self_edit_view(live, "s") == live


def test_no_worktree_yet_means_the_live_repo(tmp_path):
    b = _bridge(tmp_path, tmp_path)
    live = os.path.join(str(tmp_path), "a.py")
    assert b._self_edit_view(live, "s") == os.path.normpath(live)
