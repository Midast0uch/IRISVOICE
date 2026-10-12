"""Behavioral tests: mode routing (REQ-15 AC15.1, T19).

Slash-command overrides are DETERMINISTIC and always win. The `mode` Oracle
consumer was REMOVED 2026-10-10 (owner): its incumbent is this free keyword
classifier, so enforcing it could never pay, and its reference was the keyword
list itself. The tests below pin the classifier that REMAINS; the shadow
machinery tests (set_mode_engine / last_mode_shadow) were removed with the
consumer — STALE-BY-SPEC.
"""

from __future__ import annotations

from backend.agent.mode_detector import AgentMode, ModeDetector


class TestSlashOverridesWin:
    def test_slash_overrides_win(self):
        """AC15.1: a slash command routes deterministically."""
        d = ModeDetector()

        for text, expected in [
            ("/spec design the ingest pipeline", AgentMode.SPEC),
            ("/implement build the endpoint", AgentMode.IMPLEMENT),
            ("/debug the collector crashes", AgentMode.DEBUG),
            ("/test the queue", AgentMode.TEST),
            ("/review the diff", AgentMode.REVIEW),
            ("/ask what should we build", AgentMode.IMPLEMENT),
        ]:
            result = d.detect(text)
            assert result.mode == expected, (text, result.mode)
            assert result.trigger == "slash_command"
            assert result.confidence == 1.0
            assert result.needs_clarification == (expected == AgentMode.IMPLEMENT
                                                  and text.startswith("/ask"))

    def test_inference_branch_is_keyword_decided(self):
        """The keyword branch decides the mode on its own keywords ("write",
        "code" -> IMPLEMENT). This was the shadow half of the old test; the
        keyword half is the behavior that remains after the consumer removal."""
        d = ModeDetector()
        result = d.detect("please write the code for the upload handler")
        assert result.mode == AgentMode.IMPLEMENT
        assert result.trigger == "inference"

    def test_no_engine_leaves_routing_untouched(self):
        """Edge case: the keyword branch is the only decider (there is no
        engine any more); the confidence is the rule's own."""
        d = ModeDetector()
        result = d.detect("fix the broken collector")
        assert result.mode == AgentMode.DEBUG
        assert result.trigger == "inference"
        assert result.confidence == d._infer_mode(
            "fix the broken collector")[1]
