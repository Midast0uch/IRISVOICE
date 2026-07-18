"""Contract tests: ToolDecisionBox data shapes and event envelopes.

Pins the public interface of Decision, DecisionKind, DispatchResult, and
ToolDecisionBox so that schema drifts are caught at the boundary.

Spec: specs/der-tool-resolution-blackbox/ REQ-3
"""

from __future__ import annotations

import inspect
from dataclasses import fields

from backend.agent.tool_decision import (
    Decision,
    DecisionKind,
    DispatchResult,
    ToolDecisionBox,
)


class TestDecisionShape:
    """Decision dataclass must have the expected fields and types."""

    def test_fields_present(self):
        """Every Decision field is present and named per spec."""
        names = {f.name for f in fields(Decision)}
        assert "kind" in names
        assert "tool" in names
        assert "params" in names
        assert "rationale" in names
        assert "source" in names
        assert "error" in names
        assert len(names) == 6  # no extra fields

    def test_decision_kind_values(self):
        """DecisionKind has exactly TOOL / REASON / FAIL."""
        values = {m.value for m in DecisionKind}
        assert values == {"tool", "reason", "fail"}
        assert DecisionKind.TOOL.value == "tool"
        assert DecisionKind.REASON.value == "reason"
        assert DecisionKind.FAIL.value == "fail"

    def test_decision_source_compliance(self):
        """source must be one of llm / memory / fail."""
        for valid in ("llm", "memory", "fail"):
            d = Decision(kind=DecisionKind.TOOL, tool="t", source=valid)
            assert d.source == valid

    def test_fail_decision_carries_error(self):
        """FAIL decisions include a non-None error."""
        d = Decision(kind=DecisionKind.FAIL, source="fail", error="test error")
        assert d.error is not None
        assert len(d.error) > 0

    def test_tool_decision_no_error(self):
        """Successful TOOL decisions have error=None."""
        d = Decision(kind=DecisionKind.TOOL, tool="t", source="llm")
        assert d.error is None


class TestDispatchResultShape:
    """DispatchResult dataclass must have the expected fields and types."""

    def test_fields_present(self):
        names = {f.name for f in fields(DispatchResult)}
        assert "success" in names
        assert "result" in names
        assert "error" in names
        assert "duration_ms" in names
        assert "error_type" in names
        assert len(names) == 5

    def test_success_default(self):
        dr = DispatchResult(success=True)
        assert dr.success is True
        assert dr.result is None
        assert dr.error is None
        assert dr.duration_ms == 0


class TestToolDecisionBoxInterface:
    """ToolDecisionBox public API contract."""

    def test_methods_exist(self):
        import inspect

        methods = {m[0] for m in inspect.getmembers(ToolDecisionBox, predicate=inspect.isfunction)}
        assert "resolve" in methods
        assert "dispatch" in methods

    def test_resolve_signature(self):
        sig = inspect.signature(ToolDecisionBox.resolve)
        params = list(sig.parameters.keys())
        assert "step" in params
        assert "self" in params

    def test_dispatch_signature(self):
        sig = inspect.signature(ToolDecisionBox.dispatch)
        params = list(sig.parameters.keys())
        assert "decision" in params
        assert "self" in params
