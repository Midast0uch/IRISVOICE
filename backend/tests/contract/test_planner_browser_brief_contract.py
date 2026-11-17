"""Round 6 C9: the flag-on planner rules say when a BROWSER step gets a brief (entry rule C3).

A browser code step needs a brief whose `tools` names a browser tool. The rule fits inside the
Round 5 budget (<= 1,400 chars) by replacing wording, not by raising the bound.
"""
import json

from backend.agent.kernel import planning

_BROWSER_TOOLS = ("browser_open", "browser_read", "browser_observe", "browser_act",
                  "browser_explore")


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
