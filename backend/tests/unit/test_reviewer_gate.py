"""Guard (2026-10-19, owner decision): the Brain step review runs only when the
memory gives it something to judge against.

Live: once the memory context package reached the DER loop (is_mature=True), the
Reviewer's Brain branch ran on every step with gradient_warnings and
active_contracts BOTH empty (no producer fills them) - 22 extra model calls, 149 s
in one coding run, no pass gained. With nothing to judge against, the heuristic
review answers, as it always did in production before 2026-10-19.
"""
from types import SimpleNamespace

from backend.agent.der_loop import QueueItem, Reviewer


class _Adapter:
    def __init__(self):
        self.calls = 0

    def infer(self, prompt, role="EXECUTION", max_tokens=200, temperature=0.0):
        self.calls += 1
        return SimpleNamespace(raw_text='{"verdict": "pass"}')


def _item():
    return QueueItem(step_id="s1", step_number=1, description="read the readme",
                     objective_anchor="OBJ-1")


def _ctx(warnings="", contracts=""):
    return SimpleNamespace(gradient_warnings=warnings, active_contracts=contracts)


def test_an_empty_package_makes_no_model_call():
    adapter = _Adapter()
    Reviewer(adapter, None).review(_item(), [], _ctx(), is_mature=True)
    assert adapter.calls == 0


def test_a_warning_brings_the_model_review():
    adapter = _Adapter()
    Reviewer(adapter, None).review(_item(), [], _ctx(warnings="failed like this before"),
                                   is_mature=True)
    assert adapter.calls == 1


def test_a_contract_brings_the_model_review():
    adapter = _Adapter()
    Reviewer(adapter, None).review(_item(), [], _ctx(contracts="tests must stay green"),
                                   is_mature=True)
    assert adapter.calls == 1
