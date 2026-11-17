"""Contract (Round 5): L1 the user_feedback label call and B1 the planner brief rules.

L1  the 16-token label call was cut by the provider's hidden reasoning and resent at
    max_tokens=1040 (110 times in one log). It now carries reasoning_effort="low" and
    max_tokens=64 (when `infer` accepts the keyword, like call_kind).
B1  the flag-on planner rules cost ~530 tokens per plan on tiny tasks: at most 1,400 chars,
    the three marker rules kept, the example still parses to the end.
"""
import json
from types import SimpleNamespace

from backend.agent import event_oracle
from backend.agent.kernel import planning


def test_l1_the_label_call_carries_low_reasoning_and_64_tokens():
    seen = {}

    def infer(prompt, role="x", max_tokens=1, temperature=0.0, call_kind="other",
              reasoning_effort=None):
        seen.update(max_tokens=max_tokens, call_kind=call_kind, effort=reasoning_effort)
        return SimpleNamespace(raw_text="positive")

    brain = event_oracle.brain_for(SimpleNamespace(infer=infer))
    assert brain("q") == "positive"
    assert seen == {"max_tokens": 64, "call_kind": "label", "effort": "low"}


def test_l1_a_fixed_signature_infer_is_still_called_without_the_keywords():
    seen = {}

    def infer(prompt, role="x", max_tokens=1, temperature=0.0):
        seen["max_tokens"] = max_tokens
        return SimpleNamespace(raw_text="ok")

    assert event_oracle.brain_for(SimpleNamespace(infer=infer))("q") == "ok"
    assert seen["max_tokens"] == 64


def test_b1_the_brief_rules_are_short_and_keep_the_three_markers():
    rules = planning._PLANNER_BRIEF_RULES
    assert len(rules) <= 1400, len(rules)
    assert ("use single quotes only and no backslashes; write paths relative with forward "
            "slashes") in rules
    assert "ONE step per data product" in rules
    assert "'check' must test completeness, not only the type (the expected number of items "\
           "or keys)" in rules


def test_b1_the_example_is_one_json_object_that_parses_to_the_end():
    rules = planning._PLANNER_BRIEF_RULES
    assert rules.count('{"step_id"') == 1
    ex = json.loads(rules[rules.index('{"step_id"'):].strip())
    compile(ex["check"], "<check>", "eval")
    assert isinstance(ex["outputs"], list) and "expected_output" in ex
