"""Unit tests: the monitor bool split (REQ-14 AC14.2/AC14.4, T18).

AC14.2  on a NEGATIVE branch the Brain writes the text; the engine never does.
AC14.4  the sufficiency gate keeps its advisory-FAIL-CLOSED shape — any
        inference/parse failure returns (False, "").
"""

from __future__ import annotations

from backend.agent.decision_engine import Noul
from backend.agent import monitor_shadow as ms


class _Engine:
    def __init__(self, p_true=0.9):
        self._p = p_true
        self.calls: list = []

    def noul(self, consumer_id, statement, frame, *, true_label="yes",
             false_label="no"):
        self.calls.append(consumer_id)
        return Noul(consumer_id=consumer_id, probability=self._p,
                    engine_latency_ms=2)


class _Brain:
    """Records which Brain calls were made."""

    def __init__(self, value=True, text="the missing piece"):
        self._value = value
        self._text = text
        self.bool_calls = 0
        self.text_calls = 0

    def bool_fn(self) -> bool:
        self.bool_calls += 1
        return self._value

    def text_fn(self) -> str:
        self.text_calls += 1
        return self._text


class TestBrainTextOnNegativeBranch:
    def test_brain_text_on_negative_branch(self):
        """AC14.2: negative → the Brain writes the text; the engine supplies
        only the bool. Positive → no text at all."""
        brain = _Brain(value=True, text="missing: the price")
        engine = _Engine(p_true=0.05)  # the engine says NOT sufficient

        value, text, row = ms.monitor_bool(
            "sufficient", "Is the evidence sufficient?",
            brain_bool_fn=brain.bool_fn, brain_text_fn=brain.text_fn,
            engine=engine, enforced=True,
        )

        assert value is False, "the confident engine verdict did not decide"
        assert text == "missing: the price", "the engine must not write the text"
        assert brain.text_calls == 1
        assert brain.bool_calls == 0, (
            "an enforced negative branch must not spend the Brain on the bool"
        )
        assert row["probability"] == 0.05
        assert row["brain_bool"] is False

        # positive branch → no text, no Brain at all
        brain2 = _Brain(value=True)
        value2, text2, _ = ms.monitor_bool(
            "sufficient", "Is the evidence sufficient?",
            brain_bool_fn=brain2.bool_fn, brain_text_fn=brain2.text_fn,
            engine=_Engine(p_true=0.95), enforced=True,
        )
        assert value2 is True
        assert text2 == ""
        assert brain2.text_calls == 0 and brain2.bool_calls == 0

    def test_shadow_mode_leaves_the_brain_in_charge(self):
        """AC14.1: shadow (the only shipped mode) — the Brain decides the bool
        AND writes the text, exactly as today; the row is recorded."""
        brain = _Brain(value=True)
        engine = _Engine(p_true=0.10)  # engine disagrees, and must not win

        value, text, row = ms.monitor_bool(
            "done", "Is the objective complete?",
            brain_bool_fn=brain.bool_fn, brain_text_fn=brain.text_fn,
            engine=engine, enforced=False,
        )

        assert value is True, "the engine steered in shadow mode"
        assert brain.bool_calls == 1
        assert row is not None and row["shadow"] is True
        assert row["brain_bool"] is True
        assert row["probability"] == 0.10  # the disagreement is RECORDED


class TestSufficiencyFailClosed:
    def test_sufficiency_fail_closed(self):
        """AC14.4: no engine, a raising Brain, or a below-threshold Noul all
        yield (False, "") — the advisory gate stays closed."""
        # (a) no engine at all -> the Brain decides normally (that IS the
        #     fail-closed fallback: it never fabricates a "true")
        brain = _Brain(value=False)
        value, text = ms.sufficiency_gate(
            "Is the evidence sufficient?",
            brain_bool_fn=brain.bool_fn, brain_text_fn=brain.text_fn,
            engine=None, enforced=True,
        )
        assert (value, text) == (False, "the missing piece"), (value, text)
        assert brain.bool_calls == 1, "the Brain is the fallback when the engine is absent"

        # (b) a raising Brain
        def _boom():
            raise RuntimeError("inference failed")

        value, text = ms.sufficiency_gate(
            "Is the evidence sufficient?",
            brain_bool_fn=_boom, brain_text_fn=_boom, engine=None,
        )
        assert (value, text) == (False, "")

        # (c) a below-threshold Noul does not enforce — the Brain still decides
        brain3 = _Brain(value=True)
        value, text = ms.sufficiency_gate(
            "Is the evidence sufficient?",
            brain_bool_fn=brain3.bool_fn, brain_text_fn=brain3.text_fn,
            engine=_Engine(p_true=0.55), enforced=True, threshold=0.90,
        )
        assert value is True
        assert brain3.bool_calls == 1

    def test_no_noul_means_no_row(self):
        """A missing engine must never fabricate a shadow row."""
        brain = _Brain(value=True)
        _value, _text, row = ms.monitor_bool(
            "on_track", "Is the approach on track?",
            brain_bool_fn=brain.bool_fn, brain_text_fn=brain.text_fn,
            engine=None,
        )
        assert row is None


class TestMonitorConsumersRegistered:
    def test_monitor_consumers_have_criteria(self):
        """AC14.1/AC19.3: each bool consumer is scored under its OWN criteria
        (a consumer without criteria is refused, not borrowed)."""
        from backend.agent.decision_backend_onnx import get_consumer_spec

        added = ms.register_monitor_consumers()
        assert added == 0 or added == len(ms.MONITOR_CONSUMERS)
        for cid, instruction in ms.MONITOR_CONSUMERS.items():
            spec = get_consumer_spec(cid)
            assert spec is not None, cid
            assert spec.instruction == instruction
            assert list(spec.labels) == ["yes", "no"]
