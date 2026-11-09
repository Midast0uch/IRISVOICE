"""With the class decision on, the node-start menu cut does not run by default.

MEASURED 2026-11-09: the goal-only node-start cut (_narrow_node_tools, k=12)
removes tools for the WHOLE step with no way back - live, it dropped
screenshot_page from a web step - while the class decision already narrows
every call on the step's live state. c14 (3 runs each, same code): reply
64/26/42 s with the cut, 35/29/64 s without. So the class decision is the one
narrowing; an explicit IRIS_NODE_TOOL_MENU_K still turns the cut on.
"""
from backend.agent import agent_kernel as ak


def _tools(names):
    return [{"type": "function", "function": {"name": n, "parameters": {}}} for n in names]


_NAMES = ["read_file", "edit_file", "write_file", "run_command", "grep_files",
          "glob_files", "list_directory", "git_status", "git_diff", "search",
          "crawler_query", "browser_open", "browser_observe", "screenshot_page"]


class _Eng:
    calls = 0

    def decide(self, consumer, names, frame):
        _Eng.calls += 1

        class _C:
            def __init__(self, n, p):
                self.name, self.prob = n, p

        class _D:
            distribution = [_C(n, 1.0 - i / 100.0) for i, n in enumerate(names)]

        return _D()


def test_class_decision_on_keeps_the_full_menu_and_asks_nothing(monkeypatch):
    monkeypatch.setenv("IRIS_ORACLE_TOOL_CHOICE_CLASS_DECISION", "1")
    monkeypatch.delenv("IRIS_NODE_TOOL_MENU_K", raising=False)
    _Eng.calls = 0
    out = ak._narrow_node_tools(_tools(_NAMES), "take a screenshot of the page",
                                engine=_Eng())
    assert [t["function"]["name"] for t in out] == _NAMES
    assert _Eng.calls == 0, "no node-start d1 call when the class decision narrows"


def test_an_explicit_k_still_cuts(monkeypatch):
    monkeypatch.setenv("IRIS_ORACLE_TOOL_CHOICE_CLASS_DECISION", "1")
    monkeypatch.setenv("IRIS_NODE_TOOL_MENU_K", "10")
    out = ak._narrow_node_tools(_tools(_NAMES), "fix m.py", engine=_Eng())
    assert len(out) == 10


def test_class_decision_off_keeps_the_old_default(monkeypatch):
    monkeypatch.delenv("IRIS_ORACLE_TOOL_CHOICE_CLASS_DECISION", raising=False)
    monkeypatch.delenv("IRIS_NODE_TOOL_MENU_K", raising=False)
    out = ak._narrow_node_tools(_tools(_NAMES), "fix m.py", engine=_Eng())
    assert len(out) == 12
