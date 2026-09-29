"""Regression (execution audit B12, 2026-09-29): the destructive-pattern scan
must not read the CONTENT a tool writes.

str(params) included the file body, so writing source code that merely
contained "overwrite", "format " or "purge" escalated write_file to
DESTRUCTIVE and asked for confirmation. The first test fails on that code.
"""

import pytest

from backend.agent.permissions import PermissionTier, classify_tool


@pytest.mark.parametrize("body", [
    "def save(path, overwrite=False):\n    pass\n",
    "msg = 'format {}'.format(x)\n",
    "# purge the cache nightly\n",
    "DROP TABLE users;  -- migration text, not executed\n",
])
def test_file_content_does_not_escalate(body):
    tier = classify_tool("write_file", {"path": "app/module.py", "content": body})
    assert tier != PermissionTier.DESTRUCTIVE


def test_commit_message_does_not_escalate():
    assert classify_tool("git_commit", {"message": "overwrite stale config"}) != PermissionTier.DESTRUCTIVE


@pytest.mark.parametrize("tool,params", [
    ("run_command", {"command": "rm -rf build"}),
    ("run_command", {"command": "del /s old"}),
    ("delete_file", {"path": "notes.txt"}),
])
def test_real_destructive_actions_stay_gated(tool, params):
    assert classify_tool(tool, params) == PermissionTier.DESTRUCTIVE
