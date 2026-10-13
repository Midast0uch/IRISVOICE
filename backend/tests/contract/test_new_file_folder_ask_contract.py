"""Contract: a new file or folder with no folder chosen asks the user first
(personal mode, owner rule 2026-10-13).

Live symptom (2026-10-12): a browsing task wrote temp/einstein_info.txt into
the IRIS repo, because a relative file path resolved against the backend's
cwd. The bridge now asks where to save, offers a new folder in the user's
Documents, and writes nothing when the user declines or does not answer.

Boundaries pinned here, producer-side only (no dialog, no disk outside tmp_path):
  * execute_mcp_tool -> _folder_for_new_file runs BEFORE the path is anchored.
  * the question goes to the live question card, with the live turn id.
  * the question wait runs on a worker thread, never on the event loop.
"""
from __future__ import annotations

import inspect
import os
import pathlib
from types import SimpleNamespace

import pytest

from backend.agent.tool_bridge import AgentToolBridge
from backend.capabilities import CapabilitySet

_DECLINE = "Don't save it"


class _FakeAskTool:
    """Records ask() kwargs; wait_for_answer() returns the scripted resolution."""

    def __init__(self, status="answered", answer=None):
        self.status = status
        self.answer = answer
        self.ask_calls = []

    def ask(self, **kw):
        self.ask_calls.append(kw)
        return SimpleNamespace(question_id="q_new_file")

    def wait_for_answer(self, question):
        return SimpleNamespace(
            status=self.status, answer=self.answer, question_id=question.question_id
        )


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake user home. Path.home() never reaches the real Documents folder."""
    home_dir = (tmp_path / "home").resolve()
    home_dir.mkdir()
    monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: home_dir))
    return home_dir


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A fake IRIS repo: the bridge's default root, and the cwd."""
    repo_dir = (tmp_path / "repo").resolve()
    repo_dir.mkdir()
    monkeypatch.chdir(repo_dir)
    return repo_dir


@pytest.fixture
def personal(monkeypatch):
    monkeypatch.setattr(CapabilitySet, "is_developer", staticmethod(lambda: False))


def _bridge(repo_dir, monkeypatch, tool) -> AgentToolBridge:
    bridge = AgentToolBridge.__new__(AgentToolBridge)
    bridge._session_workdirs = {}
    bridge._active_conversation_id = {}
    bridge._DEFAULT_REPO = str(repo_dir)
    bridge._live_turn_id = lambda session_id: "t1"
    monkeypatch.setattr(
        "backend.agent.tools.ask_user_tool.get_ask_user_tool", lambda: tool
    )
    return bridge


async def test_new_folder_answer_saves_under_documents_iris(repo, home, personal, monkeypatch):
    """Live 2026-10-12: temp/einstein_info.txt was written into the IRIS repo.
    The user picks "New folder": the file goes to <home>/Documents/IRIS and the
    folder is bound for the session. The question carries the live turn id."""
    suggested = str(home / "Documents" / "IRIS")
    tool = _FakeAskTool(answer=f"New folder: {suggested}")
    bridge = _bridge(repo, monkeypatch, tool)

    params, not_saved = await bridge._folder_for_new_file(
        {"path": "notes/a.txt"}, "s1", "write_file")

    assert not_saved is None
    assert params["path"] == os.path.join(suggested, "notes", "a.txt")
    assert os.path.isdir(suggested)
    assert bridge._session_workdirs["s1"] == suggested
    assert len(tool.ask_calls) == 1
    kw = tool.ask_calls[0]
    assert kw["options"] == [f"New folder: {suggested}", _DECLINE]
    assert kw["allow_other"] is True
    assert kw["turn_id"] == "t1"


async def test_decline_answer_writes_nothing(repo, home, personal, monkeypatch):
    """Live 2026-10-12: temp/einstein_info.txt was written into the IRIS repo.
    The user picks "Don't save it": the write is refused and no folder appears."""
    tool = _FakeAskTool(answer=_DECLINE)
    bridge = _bridge(repo, monkeypatch, tool)

    params, result = await bridge._folder_for_new_file(
        {"path": "notes/a.txt"}, "s1", "write_file")

    assert params is None
    assert result["success"] is False
    assert "Not saved" in result["error"]
    assert not (home / "Documents").exists()
    assert "s1" not in bridge._session_workdirs


async def test_a_no_holds_for_the_rest_of_the_turn(repo, home, personal, monkeypatch):
    """Live 2026-10-13: after "Don't save it" the next step asked again for the
    same file and waited out the full 120 s question window. In the same turn
    a second write is refused at once, without a second question; a new turn
    asks again."""
    tool = _FakeAskTool(answer=_DECLINE)
    bridge = _bridge(repo, monkeypatch, tool)

    await bridge._folder_for_new_file({"path": "a.txt"}, "s1", "write_file")
    params, result = await bridge._folder_for_new_file({"path": "a.txt"}, "s1", "write_file")

    assert params is None and "already chose not to save" in result["error"]
    assert len(tool.ask_calls) == 1
    bridge._live_turn_id = lambda session_id: "t2"
    await bridge._folder_for_new_file({"path": "a.txt"}, "s1", "write_file")
    assert len(tool.ask_calls) == 2


async def test_unanswered_question_writes_nothing(repo, home, personal, monkeypatch):
    """Live 2026-10-12: temp/einstein_info.txt was written into the IRIS repo.
    The question times out: the write is refused and says the user did not answer."""
    tool = _FakeAskTool(status="timed_out")
    bridge = _bridge(repo, monkeypatch, tool)

    params, result = await bridge._folder_for_new_file(
        {"path": "notes/a.txt"}, "s1", "write_file")

    assert params is None
    assert result["success"] is False
    assert "did not answer" in result["error"]
    assert not (home / "Documents").exists()


async def test_path_outside_the_repo_is_written_without_asking(
        repo, home, personal, monkeypatch, tmp_path):
    """Live 2026-10-12: temp/einstein_info.txt was written into the IRIS repo.
    A path the user owns, outside the repo, is written as given with no question."""
    target = str(tmp_path / "elsewhere" / "a.txt")
    tool = _FakeAskTool()
    bridge = _bridge(repo, monkeypatch, tool)

    params, result = await bridge._folder_for_new_file(
        {"path": target}, "s1", "write_file")

    assert result is None
    assert params == {"path": target}
    assert tool.ask_calls == []


async def test_developer_mode_writes_without_asking(repo, home, monkeypatch):
    """Live 2026-10-12: temp/einstein_info.txt was written into the IRIS repo.
    Developer mode edits IRIS itself, so a repo path is written with no question."""
    monkeypatch.setattr(CapabilitySet, "is_developer", staticmethod(lambda: True))
    tool = _FakeAskTool()
    bridge = _bridge(repo, monkeypatch, tool)

    params, result = await bridge._folder_for_new_file(
        {"path": "notes/a.txt"}, "s1", "write_file")

    assert result is None
    assert params == {"path": "notes/a.txt"}
    assert tool.ask_calls == []


async def test_bound_session_workdir_writes_without_asking(repo, home, personal, monkeypatch):
    """Live 2026-10-12: temp/einstein_info.txt was written into the IRIS repo.
    A session whose folder is already bound writes there with no question."""
    tool = _FakeAskTool()
    bridge = _bridge(repo, monkeypatch, tool)
    bridge._session_workdirs["s1"] = str(home / "Projects")

    params, result = await bridge._folder_for_new_file(
        {"path": "notes/a.txt"}, "s1", "write_file")

    assert result is None
    assert params == {"path": "notes/a.txt"}
    assert tool.ask_calls == []


async def test_typed_folder_answer_is_used_and_bound(
        repo, home, personal, monkeypatch, tmp_path):
    """Live 2026-10-12: temp/einstein_info.txt was written into the IRIS repo.
    The user types an absolute folder ("C:/..." style): the file goes there and
    the folder is bound for the session. Nothing lands in the default folder."""
    chosen = (tmp_path / "chosen").as_posix()
    tool = _FakeAskTool(answer=chosen)
    bridge = _bridge(repo, monkeypatch, tool)

    params, result = await bridge._folder_for_new_file(
        {"path": "notes/a.txt"}, "s1", "write_file")

    assert result is None
    assert params["path"] == os.path.join(chosen, "notes", "a.txt")
    assert os.path.isdir(chosen)
    assert bridge._session_workdirs["s1"] == chosen
    assert not (home / "Documents").exists()


def test_create_tools_pass_through_the_gate_in_execute_mcp_tool():
    """Live 2026-10-12: temp/einstein_info.txt was written into the IRIS repo.
    The gate must run before the path is anchored, or the anchor hides the repo path."""
    src = inspect.getsource(AgentToolBridge.execute_mcp_tool)
    assert "_folder_for_new_file(" in src
    assert src.index("_folder_for_new_file(") < src.index("_anchor_file_paths(")


def test_ask_handler_does_not_block_the_loop():
    """Live 2026-10-12: temp/einstein_info.txt was written into the IRIS repo.
    The question wait must run on a worker thread, not hold the event loop."""
    src = inspect.getsource(AgentToolBridge._handle_ask_user_question)
    assert "asyncio.to_thread(tool.wait_for_answer" in src
