"""tool_choice class decision: a tool the class map does not cover is never removed.

Found 2026-11-09 (audit of the d1-2b class/shortlist role). The class map
(`tool_choice_action_class.TOOL_CLASS`) covers the CODING tools only, and the
93.7% class accuracy was measured on coding menus: of 1581 stored decided rows,
ONE offered the web/browser tools. Two defects followed on a web-toggle menu:

  * the margin was READ/WRITE/RUN mass only, so a research step whose top-1 was
    read_file at 0.45 against `search` at 0.30 read a 0.45 READ margin and took
    the class;
  * the class list was "every offered tool of that class", so `search` and the
    browser tools were stripped from the model's menu for that call.

The guard drives the real `choose_node_tool` with a stub engine. On the old
code the research step loses `search`; on the fix the unmapped tools ride
along and the margin is measured against them.
"""
from __future__ import annotations

from backend.agent.tool_choice_action_class import READ, class_masses


def _dist(pairs):
    from backend.agent.decision_engine import CandidateScore

    return tuple(CandidateScore(n, 0.0, p) for n, p in pairs)


def _box(pairs):
    from backend.agent.decision_engine import DecisionScore
    from backend.agent.tool_decision import ToolDecisionBox

    dist = _dist(pairs)
    top = max(pairs, key=lambda t: t[1])

    class _Eng:
        model_id = "stub"

        def decide(self, consumer_id, options, frame):
            return DecisionScore(consumer_id=consumer_id, chosen=top[0],
                                 confidence=top[1], distribution=dist,
                                 engine_latency_ms=1)

    class _Bridge:
        def record_decision(self, *a, **k):
            pass

    class _Router:
        def generate(self, *a, **k):
            return ("", "", [])

    return ToolDecisionBox(router=_Router(), tool_bridge=_Bridge(),
                           get_available_tools=lambda: [],
                           validate_tool_call=lambda t, p: (True, None),
                           decision_engine=_Eng())


_WEB_MENU = ["read_file", "grep_files", "edit_file", "run_command",
             "search", "crawler_query", "browser_open", "browser_observe"]


def _class_env(monkeypatch):
    monkeypatch.setenv("IRIS_ORACLE_TOOL_CHOICE_CLASS_DECISION", "1")
    monkeypatch.setenv("IRIS_ORACLE_TOOL_CHOICE_SHORTLIST_K", "5")
    monkeypatch.setenv("IRIS_ORACLE_TOOL_CHOICE_ALWAYS", "0")


def test_a_class_decision_keeps_the_unmapped_tools(monkeypatch):
    """A clear READ class still narrows the coding tools, never the web ones."""
    _class_env(monkeypatch)
    pairs = [("read_file", 0.70), ("grep_files", 0.10), ("edit_file", 0.05),
             ("run_command", 0.05), ("search", 0.04), ("crawler_query", 0.02),
             ("browser_open", 0.02), ("browser_observe", 0.02)]
    got = _box(pairs).choose_node_tool(
        goal="Find the release date of the library", candidates=_WEB_MENU,
        scope_key="s")
    assert got is not None
    tools, row = got
    assert row["route"] == "class" and row["class_decided"] == READ
    assert "edit_file" not in tools and "run_command" not in tools
    for web in ("search", "crawler_query", "browser_open", "browser_observe"):
        assert web in tools, f"{web} was stripped by a class it is not in"


def test_the_margin_counts_the_unmapped_mass(monkeypatch):
    """read_file 0.45 vs search 0.30: no READ class (margin 0.15 < 0.30)."""
    _class_env(monkeypatch)
    pairs = [("read_file", 0.45), ("search", 0.30), ("crawler_query", 0.10),
             ("browser_open", 0.10), ("edit_file", 0.03), ("run_command", 0.02)]
    got = _box(pairs).choose_node_tool(
        goal="Look up the current version of the package", candidates=_WEB_MENU,
        scope_key="s")
    assert got is not None
    tools, row = got
    assert row["route"] == "shortlist", row
    assert "search" in tools
    assert row["class_margin"] < 0.30


def test_the_margin_is_about_the_top1_class():
    """The class taken is the top-1 tool's; its margin is measured for it.

    read_file 0.30 is the top-1, but WRITE holds 0.65 over three tools. The
    old runner-up margin read WRITE - READ = 0.35 and took READ."""
    pairs = [("read_file", 0.30), ("edit_file", 0.25), ("write_file", 0.20),
             ("append_file", 0.20), ("run_command", 0.05)]
    masses, margin = class_masses(_dist(pairs), READ)
    assert margin < 0, (masses, margin)
    # the measurement form (no top class) is unchanged
    _, runner_up = class_masses(_dist(pairs))
    assert round(runner_up, 6) == 0.35
