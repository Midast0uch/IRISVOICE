"""Round 6 C9: the flag-on planner rules say when a BROWSER step gets a brief (entry rule C3).

A browser code step needs a brief whose `tools` names a browser tool. The rule fits inside the
Round 5 budget (<= 1,400 chars) by replacing wording, not by raising the bound.
"""
import json

import pytest

from backend.agent.kernel import planning

_BROWSER_TOOLS = ("browser_open", "browser_read", "browser_observe", "browser_act",
                  "browser_explore")

_D01 = ("On https://quotes.toscrape.com, look at pages 1, 2 and 3 of the quote list "
        "(/page/1/, /page/2/, /page/3/) and tell me how many quotes in total are by "
        "Albert Einstein on those three pages.")
_G01 = ("On https://quotes.toscrape.com, go to the author page of whoever wrote the "
        "quote that begins 'The world as we have created it' and tell me the birth "
        "date it shows.")


def test_c9_the_brief_rules_say_when_a_browser_step_gets_a_brief():
    rules = planning._PLANNER_BRIEF_RULES
    i = rules.index("BROWSER")
    rule = rules[i:rules.index(chr(10), i)]
    assert "named" in rule and "brief" in rule
    for tool in _BROWSER_TOOLS:
        assert tool in rule, tool
    low = rule.lower()
    assert "login" in low and "credentials" in low and "captcha" in low and "look" in low
    assert rules.index(rule) < rules.index('{"step_id"')


def test_c9_the_rules_stay_within_budget_with_the_three_markers_and_a_parseable_example():
    rules = planning._PLANNER_BRIEF_RULES
    assert len(rules) <= 1400, len(rules)
    assert ("use single quotes only and no backslashes; write paths relative with forward "
            "slashes") in rules
    assert "ONE step per data product" in rules
    assert ("'check' must test completeness, not only the type (the expected number of items "
            "or keys)") in rules
    assert rules.count('{"step_id"') == 1
    ex = json.loads(rules[rules.index('{"step_id"'):].strip())
    compile(ex["check"], "<check>", "eval")


def test_computed_browser_brief_names_browser_tools_even_if_planner_named_search(monkeypatch):
    """d01 variance guard: a computed task whose brief names search/crawler_query
    is refused by the entry rule and takes the slow menu path. The backstop must
    force browser tools. Fails on the old code (which returned the brief unchanged)."""
    monkeypatch.setenv("IRIS_WORKBENCH", "1")
    brief = {"outputs": ["answer: str"], "check": "len(answer) > 0",
             "tools": ["search", "crawler_query"]}
    out = planning._ensure_browser_brief(brief, _D01)
    assert {"browser_open", "browser_read"} <= set(out["tools"])
    assert "search" not in out["tools"] and "crawler_query" not in out["tools"]


def test_computed_browser_brief_clears_wb_browser_single(monkeypatch):
    """A computed task mislabelled as a single-page lookup must still reach code mode."""
    monkeypatch.setenv("IRIS_WORKBENCH", "1")
    brief = {"outputs": ["answer: str"], "check": "len(answer) > 0",
             "tools": ["browser_open", "browser_read"], "wb_browser_single": True}
    out = planning._ensure_browser_brief(brief, _D01)
    assert out["wb_browser_single"] is False


def test_lookup_brief_stays_byte_identical(monkeypatch):
    """Lookups (no compute cue) must stay on the menu path, unchanged."""
    monkeypatch.setenv("IRIS_WORKBENCH", "1")
    brief = {"outputs": ["answer: str"], "check": "len(answer) > 0",
             "tools": ["search", "crawler_query"]}
    assert planning._ensure_browser_brief(brief, _G01) == brief


def test_fully_compliant_computed_brief_stays_byte_identical(monkeypatch):
    monkeypatch.setenv("IRIS_WORKBENCH", "1")
    brief = {"outputs": ["answer: str"], "check": "len(answer) > 0",
             "tools": ["browser_open", "browser_read"]}
    assert planning._ensure_browser_brief(brief, _D01) == brief
