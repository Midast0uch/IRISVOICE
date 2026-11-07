"""Advisory node-tool narrowing must never remove basic capability.

The node menu was 17 tools (~14k chars) on every model call. The narrowing
keeps the CORE coding tools plus the Oracle's top picks, and returns the FULL
menu whenever the Oracle gives no ranking. MEASURED 2026-11-06.
"""
from backend.agent import agent_kernel as ak


def _tools(names):
    return [{"type": "function", "function": {"name": n, "parameters": {}}} for n in names]


class _Eng:
    def __init__(self, order):
        self._order = order

    def decide(self, consumer, names, frame):
        order = self._order

        class _C:
            def __init__(self, n, p):
                self.name = n
                self.prob = p

        class _D:
            def __init__(self):
                self.distribution = [
                    _C(n, 1.0 - i / 100.0)
                    for i, n in enumerate(order) if n in names
                ]

        return _D()


def test_core_tools_always_survive():
    names = ["read_file", "edit_file", "run_command", "browser_open",
             "search", "crawler_query", "git_status", "open_url"]
    out = ak._narrow_node_tools(
        _tools(names), "add slugify", engine=_Eng(list(reversed(names))), k=5)
    kept = {t["function"]["name"] for t in out}
    assert {"read_file", "edit_file", "run_command"} <= kept
    assert len(kept) <= 5


def test_no_engine_returns_the_full_menu(monkeypatch):
    import backend.agent.decision_engine as de

    monkeypatch.setattr(de, "get_decision_engine", lambda: None)
    names = ["read_file", "edit_file", "run_command", "browser_open",
             "search", "crawler_query"]
    out = ak._narrow_node_tools(_tools(names), "x", engine=None, k=3)
    assert len(out) == len(names)


def test_k_zero_disables():
    names = ["read_file", "edit_file", "run_command", "browser_open", "search"]
    out = ak._narrow_node_tools(_tools(names), "x", engine=_Eng(names), k=0)
    assert out == _tools(names)
