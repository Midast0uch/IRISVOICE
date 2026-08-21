import asyncio
import json
from pathlib import Path

import backend.capabilities as caps
from backend.agent.permissions import get_approvable_tools
from backend.main import get_config


def test_get_approvable_tools_excludes_always_ask():
    tools = get_approvable_tools()
    assert isinstance(tools, list) and tools
    # ALWAYS_ASK (destructive/terminal) tools must never be pre-approvable
    for never in ("delete_file", "delete_directory", "force_delete", "terminal", "destroy"):
        assert never not in tools
    # Side-effect repo tools must be pre-approvable
    for yes in ("write_file", "create_directory", "git_commit", "git_diff", "git_push", "git_status"):
        assert yes in tools


def test_get_config_shape_and_effective_mode(tmp_path, monkeypatch):
    p = tmp_path / "iris_config.json"
    p.write_text(json.dumps({"mode": "developer", "approved_tools": ["write_file"]}))
    monkeypatch.setattr("backend.capabilities._CFG_PATH", str(p))
    caps._CFG_PATH = str(p)

    result = asyncio.run(get_config())
    assert result["mode"] == "developer"
    assert result["effective_mode"] == "developer"  # REQ-16 AC2: truthful mode
    assert result["approved_tools"] == ["write_file"]
    assert isinstance(result["available_tools"], list)
    assert "write_file" in result["available_tools"]
    # ALWAYS_ASK tools are not offered as pre-approvable
    assert "delete_file" not in result["available_tools"]


def test_get_config_falls_back_when_mode_missing(tmp_path, monkeypatch):
    p = tmp_path / "iris_config.json"
    p.write_text(json.dumps({}))  # no mode key
    monkeypatch.setattr("backend.capabilities._CFG_PATH", str(p))
    caps._CFG_PATH = str(p)

    result = asyncio.run(get_config())
    assert result["mode"] is None
    # effective_mode still resolves (defaults to personal via get_mode)
    assert result["effective_mode"] in ("personal", "developer")
    assert isinstance(result["available_tools"], list)
