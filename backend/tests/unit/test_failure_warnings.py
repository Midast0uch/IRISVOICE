"""Unit tests for AgentKernel._get_failure_warnings (REQ-24, T34).

AC24.1  passes a failure DICT to the encoder (not the task string).
AC24.3  absent state returns the documented empty value, no raise.
AC24.5  a non-recoverable error is logged WITH its exception type.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.agent.agent_kernel import AgentKernel


class _FakeEncoder:
    """Records what it was handed — the contract is the DICT, not a str."""

    def __init__(self):
        self.calls = []

    def encode_with_resolution(self, failure, conn=None) -> str:
        self.calls.append((failure, conn))
        assert isinstance(failure, dict), (
            f"encode_with_resolution expects a Dict, got {type(failure).__name__}"
        )
        return "[space:unknown | outcome:miss | tool:x | condition:y | delta:-0.05]"


class _FakeMycelium:
    def __init__(self, conn):
        self.conn = conn


def _kernel_with_mycelium(conn) -> AgentKernel:
    k = AgentKernel.__new__(AgentKernel)
    k.session_id = "sess-fw"
    k._memory_interface = SimpleNamespace(_mycelium=_FakeMycelium(conn=conn))
    return k


class TestPassesFailureDictToEncoder:
    def test_passes_failure_dict_to_encoder(self, monkeypatch):
        """AC24.1: the method builds the failure dict from recorded session
        state and passes a DICT to encode_with_resolution."""
        enc = _FakeEncoder()
        import backend.memory.mycelium.interpreter as interp

        monkeypatch.setattr(interp, "ResolutionEncoder", lambda: enc)
        k = _kernel_with_mycelium(conn=object())
        out = k._get_failure_warnings("read the config file")
        assert out.startswith("[space:")
        failure, conn = enc.calls[0]
        assert isinstance(failure, dict)
        assert failure["task_summary"] == "read the config file"
        assert failure["session_id"] == "sess-fw"


class TestAbsentStateReturnsEmptyNoRaise:
    def test_absent_state_returns_empty_no_raise(self):
        """AC24.3: no failure state (no memory interface) → the documented
        empty value "None", no raise."""
        k = AgentKernel.__new__(AgentKernel)
        k.session_id = "sess-fw"
        k._memory_interface = None
        assert k._get_failure_warnings("any task") == "None"

    def test_absent_mycelium_returns_empty_no_raise(self):
        """AC24.3: the memory interface exists but mycelium is None → "None"."""
        k = AgentKernel.__new__(AgentKernel)
        k.session_id = "sess-fw"
        k._memory_interface = SimpleNamespace(_mycelium=None)
        assert k._get_failure_warnings("any task") == "None"


class TestErrorLoggedWithExceptionType:
    def test_error_logged_with_exception_type(self, caplog):
        """AC24.5: a non-recoverable error is logged WITH its exception type
        instead of silently returning "None"."""
        k = AgentKernel.__new__(AgentKernel)
        k.session_id = "sess-fw"

        class _BoomInterface:
            @property
            def _mycelium(self):
                raise RuntimeError("conn dead")

        k._memory_interface = _BoomInterface()
        with caplog.at_level("ERROR"):
            out = k._get_failure_warnings("any task")
        assert out == "None"
        errs = [
            r for r in caplog.records
            if "_get_failure_warnings failed" in r.message
        ]
        assert errs, "the error was swallowed silently"
        assert "RuntimeError" in errs[0].getMessage(), (
            "the exception type must ride the log line (AC24.5)"
        )
