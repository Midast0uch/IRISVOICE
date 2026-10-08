"""Contract tests: per-consumer scoring specs (REQ-19 AC19.3, T25).

CT-DEI-9 — Consumer Head Binding: a consumer is scored under its OWN
registered specification, so another consumer's labels or instruction can
never be silently reused.

Wave 5 (specs/phonon2-d1-model-swap T5.3): the GLiNER build_task/Task shape
this test pinned died with the ONNX backend. The INTENT transfers to the
d1 backend unchanged: the registered ConsumerSpec's INSTRUCTION is what
the model is asked (the Decision Index `instructions` field), and an
unregistered consumer gets the generic AUTO_INSTRUCTION — never another
consumer's question.

Run: python -m pytest backend/tests/contract/test_consumer_tasks_contract.py -q
"""
from __future__ import annotations

from backend.agent.decision_engine import (
    AUTO_INSTRUCTION,
    CONSUMER_TASKS,
    ConsumerSpec,
    get_consumer_spec,
    register_consumer_spec,
)


def _spec(cid: str, **kw) -> ConsumerSpec:
    base = dict(consumer_id=cid, task_name=cid,
                instruction=f"Question for {cid}?")
    base.update(kw)
    return ConsumerSpec(**base)


class TestScoringUsesRegisteredSpec:
    def test_registered_instruction_is_what_the_backend_asks(self):
        """AC19.3 on the d1 backend: the registered spec's instruction is
        the question the model sees — resolve_consumer_instruction returns
        it, never another consumer's."""
        from backend.agent.decision_backend_d1 import D1Backend

        register_consumer_spec(_spec("tst_review", task_name="tst_review"))
        try:
            got = D1Backend._spec_instruction("tst_review", "FALLBACK")
            assert got == "Question for tst_review?", got
        finally:
            CONSUMER_TASKS.pop("tst_review", None)

    def test_unregistered_consumer_gets_the_generic_question(self):
        """No registered spec -> the honest generic AUTO_INSTRUCTION (the
        consumer is still MEASURED), never a borrowed question. The path is
        decide()'s: ensure_consumer_spec registers with AUTO_INSTRUCTION,
        then the spec reader finds it."""
        from backend.agent.decision_backend_d1 import D1Backend
        from backend.agent.decision_engine import ensure_consumer_spec

        CONSUMER_TASKS.pop("tst_never_registered", None)
        ensure_consumer_spec("tst_never_registered", ["a", "b"], None)
        got = D1Backend._spec_instruction("tst_never_registered", "FALLBACK")
        assert got == AUTO_INSTRUCTION, got

    def test_explicit_fallback_only_when_registry_unreadable(self):
        """The caller's fallback is the LAST resort (registry failure)."""
        from backend.agent.decision_backend_d1 import D1Backend

        got = D1Backend._spec_instruction("tool_choice", "FALLBACK")
        assert got != "FALLBACK"
        assert got == CONSUMER_TASKS["tool_choice"].instruction

    def test_registry_is_shared_not_per_backend(self):
        """The registry lives on decision_engine (ONE home since Wave 5):
        registering through it is visible to every backend and site."""
        register_consumer_spec(_spec("tst_shared"))
        try:
            assert get_consumer_spec("tst_shared") is not None
            from backend.agent.decision_backend_d1 import D1Backend

            assert D1Backend._spec_instruction("tst_shared", "F") == "Question for tst_shared?"
        finally:
            CONSUMER_TASKS.pop("tst_shared", None)
