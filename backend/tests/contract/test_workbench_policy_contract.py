"""CLM-11 / T7.5 contract: what may enter the Workbench. Every refusal has a name and is counted."""
import pytest

from backend.tests.contract._wb_common import mod

policy = mod("policy")


def delta(before):
    after = policy.refusals()
    return {k: after.get(k, 0) - before.get(k, 0) for k in after if after.get(k, 0) != before.get(k, 0)}


@pytest.mark.parametrize("name,value,reason", [
    ("__builtins__", 1, "bad_name"), ("1x", 1, "bad_name"), ("a b", 1, "bad_name"),
    pytest.param("blob", "x" * 64_001, "too_large", id="too_large"), ("obj", {1, 2}, "not_json"), ("obj", object(), "not_json"),
])
def test_admit_put_refusals_are_named_and_counted(name, value, reason):
    before = policy.refusals()
    assert policy.admit_put(name, value) == (False, reason)
    assert delta(before) == {reason: 1}


def test_admit_put_accepts_json_within_bound():
    before = policy.refusals()
    for name, value in (("task", "fix the bug"), ("steps", [{"n": 1, "result": "ok"}]),
                        ("memory", {"a": [1, 2.5, None, True]}), ("edge", "x" * 63_990)):
        assert policy.admit_put(name, value) == (True, "ok")
    assert delta(before) == {}
