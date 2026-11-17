"""Planner JSON repair contract (TG-7 v2, 2026-11-17).

All three planner parse failures logged in the TG-7 v2 full run (write cohort, conv-8016 /
conv-8078 / conv-8204) had one model typo: a stray quote after a number value,
'"step_number":2","description"'. Each cost a planner retry (~10-17 s). The parser now
repairs exactly that, and only for text that did not parse: valid JSON is never touched,
and other broken JSON still returns None.
"""
from backend.agent.agent_kernel import AgentKernel

_LOGGED = (
    '{"strategy":"do_it_myself","plan_title":"Fix off-by-one in mathutils","steps":['
    '{"step_id":"s1","step_number":1,"description":"Read mathutils.py","expected_output":"the bug",'
    '"depends_on":["start"],"critical":true},'
    '{"step_id":"s2","step_number":2","description":"Apply the corrected range logic",'
    '"expected_output":"patched","depends_on":["s1"],"critical":true}]}'
)


def test_the_logged_stray_quote_after_a_number_parses():
    plan = AgentKernel._parse_planner_json(_LOGGED)
    assert isinstance(plan, dict) and [s["step_number"] for s in plan["steps"]] == [1, 2]
    assert plan["steps"][1]["description"] == "Apply the corrected range logic"


def test_valid_json_with_a_time_like_string_is_untouched():
    raw = '{"plan_title":"Meet at 10:30","steps":[{"step_id":"s1","description":"at 10:30","note":"x:2"}]}'
    plan = AgentKernel._parse_planner_json(raw)
    assert plan["plan_title"] == "Meet at 10:30" and plan["steps"][0]["note"] == "x:2"


def test_other_broken_json_still_returns_none():
    assert AgentKernel._parse_planner_json('{"plan_title":"x","steps":[{"step_id":"s1",}') is None
