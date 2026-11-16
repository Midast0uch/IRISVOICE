"""CLM-11 / T7.2 contract: run_python is registered like run_command, offered in both
modes (T7.11: it is not in CapabilitySet._TERMINAL_TOOLS; personal mode's scope is the session folder), never on
the fine-grained node menu, and the Workbench package has exactly the allowed importers."""
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
def mode(monkeypatch):
    from backend.capabilities import CapabilitySet

    def set_mode(name):
        monkeypatch.setattr(CapabilitySet, "get_mode", classmethod(lambda cls: name))

    return set_mode


def test_run_python_listed_in_developer_mode_and_in_personal_mode(mode):
    from backend.agent.tool_bridge import AgentToolBridge

    mode("developer")
    dev = {t["name"]: t for t in AgentToolBridge().get_available_tools()}
    assert "run_python" in dev and dev["run_python"]["category"] == "shell"
    assert set(dev["run_python"]["parameters"]) == {"code", "purpose", "timeout_s", "fresh", "close"}  # T7.10
    mode("personal")
    assert "run_python" in {t["name"] for t in AgentToolBridge().get_available_tools()}
    from backend.capabilities import CapabilitySet

    assert CapabilitySet.is_tool_allowed("run_python")
    mode("developer")
    assert CapabilitySet.is_tool_allowed("run_python")


def test_registry_spec_matches_run_command_registration():
    from backend.agent.tool_registry import resolve_tool

    py, cmd = resolve_tool("run_python"), resolve_tool("run_command")
    assert py is not None
    assert (py.category, py.executor, py.permission_tier, py.parallel_safe) == (
        cmd.category, cmd.executor, cmd.permission_tier, cmd.parallel_safe) == ("shell", "dev", "side_effect", False)
    assert set(py.parameters) == {"code", "purpose", "timeout_s", "fresh", "close"}  # T7.10
    assert "keep(" not in py.description


def test_run_python_is_not_on_the_node_menu():
    from backend.agent import node_executor

    assert "run_python" not in node_executor.NODE_TOOLS


def test_the_mode_rule_is_one_constant():
    src = (BACKEND / "capabilities.py").read_text(encoding="utf-8")
    assert len(re.findall(r'"run_python"', src)) == 1


def test_only_the_allowed_files_import_the_workbench_package():
    allowed = {"agent/tool_bridge.py", "agent/kernel/der/node.py"}
    pat = re.compile(r"^\s*(from\s+backend\.agent\.workbench|import\s+backend\.agent\.workbench|"
                     r"from\s+backend\.agent\s+import\s+workbench|from\s+\.+workbench)", re.M)
    offenders = []
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).as_posix()
        if rel.startswith(("agent/workbench/", "tests/", ".venv", "node_modules")) or "/tests/" in rel:
            continue
        if rel in allowed:
            continue
        try:
            if pat.search(path.read_text(encoding="utf-8", errors="replace")):
                offenders.append(rel)
        except OSError:
            continue
    assert offenders == []
    # node_executor.py never imports it, not even lazily inside a function
    lines = (BACKEND / "agent" / "node_executor.py").read_text(encoding="utf-8").splitlines()
    assert [l for l in lines if "workbench" in l.lower() and l.strip().startswith(("import", "from"))] == []
