"""Contract: a model cannot park learned user data in the repo (2026-10-30).

The tool ledger holds six real attempts by the model to write user facts into
the project tree:

    backend/agent/skills/user-preferences.md               library card number
    backend/agent/skills/user-preferences/library-card.md  library card number
    user_preferences.json                                  status colour
    .user_preferences.json                                 status colour

The repo is committed and shared, so a write there publishes the user's data.
Learned memory belongs in the application store (D:/IRIS/store), written by the
``remember`` tool. These tests pin the refusal at the live tool boundary.
"""

import asyncio

import pytest

from backend.mcp.builtin_servers import FileManagerServer
from backend.repo_privacy import _REPO_ROOT, learned_user_data_error

# The exact paths from the ledger, plus the obvious next attempt (.md at the
# top level of the skills directory).
OBSERVED = [
    "backend/agent/skills/user-preferences.md",
    "backend/agent/skills/user-preferences/library-card.md",
    "user_preferences.json",
    ".user_preferences.json",
]
NEXT_ATTEMPT = ["backend/agent/skills/notes.md"]


@pytest.fixture
def repo_cwd(monkeypatch):
    """The live app runs with the repo as cwd; pin that so relative paths mean
    what they meant in the ledger."""
    monkeypatch.chdir(_REPO_ROOT)
    return _REPO_ROOT


@pytest.mark.parametrize("rel", OBSERVED + NEXT_ATTEMPT)
def test_write_file_refuses_and_writes_nothing(repo_cwd, rel):
    target = _REPO_ROOT / rel
    before = target.exists()
    out = asyncio.run(
        FileManagerServer().execute_tool(
            "write_file",
            {"path": rel, "content": "Library card number: 880417\n"},
        )
    )
    assert out["success"] is False, out
    assert out.get("denied") == "learned_user_data_in_repo", out
    assert "D:/IRIS/store" in out["error"], out
    assert target.exists() == before, f"{rel} was written despite the refusal"


def test_edit_file_refuses(repo_cwd):
    out = asyncio.run(
        FileManagerServer().execute_tool(
            "edit_file",
            {"path": "user_preferences.json", "old": "a", "new": "b"},
        )
    )
    assert out["success"] is False, out
    assert out.get("denied") == "learned_user_data_in_repo", out


def test_agent_tool_executor_writer_refuses(repo_cwd):
    """The second writer shares the rule, so the two cannot drift."""
    from backend.agent.tool_executor import ToolExecutor

    target = _REPO_ROOT / "user_preferences.json"
    before = target.exists()
    out = ToolExecutor()._write_file(
        {"path": "user_preferences.json", "content": '{"x": 1}'}, {}
    )
    assert out["success"] is False, out
    assert out.get("denied") == "learned_user_data_in_repo", out
    assert target.exists() == before


def test_relative_path_is_denied_even_when_cwd_is_not_the_repo(monkeypatch, tmp_path):
    """The live backend's cwd is C:/Users/<user>/Documents/IRIS (measured
    2026-10-30), so a relative repo path must still be judged against the repo."""
    monkeypatch.chdir(tmp_path)
    out = asyncio.run(
        FileManagerServer().execute_tool(
            "write_file",
            {"path": "backend/agent/skills/user-preferences.md", "content": "x\n"},
        )
    )
    assert out["success"] is False, out
    assert out.get("denied") == "learned_user_data_in_repo", out


@pytest.mark.parametrize(
    "rel",
    [
        "backend/agent/skills/config.yaml",
        "backend/agent/skills/my-new-skill/SKILL.md",
        "backend/agent/skills/user-docs/readme.md",
        "backend/agent/tool_executor.py",
        "docs/user-profile-design.md",
        "backend/user_preferences_schema.py",
    ],
)
def test_legitimate_paths_stay_allowed(repo_cwd, rel):
    assert learned_user_data_error(rel) is None, rel
