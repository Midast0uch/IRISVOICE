"""Contract: what the USER is shown as step evidence (REQ-2 AC2.3).

Live 2026-09-25, a finished two-step turn showed the user:

  - Create zz_a.md ...: success — proceed, doc b2299b91-2c3 | {"success": true, ...}
  - Read the contents ...: success, [idling] — try_different, doc 43de69cd-343 | - Tea ...

The first part of each line is ``ToolEnvelope.line()`` — a DIAGNOSTIC string
(verdict, stuck shape, doc id) that belongs in the ledger. These tests pin that
the user-facing evidence carries the OUTCOME instead: no verdict tokens, no
stuck shapes, no doc ids, and a JSON envelope unwrapped to its human message.
"""
from backend.agent.agent_kernel import AgentKernel


class _Envelope:
    def __init__(self, status="success", summary="", error_type="", suggestion="proceed",
                 stuck_shape="none"):
        self.status = status
        self.summary = summary
        self.error_type = error_type
        self.suggestion = suggestion
        self.stuck_shape = stuck_shape

    def line(self) -> str:  # the diagnostic form this must NOT surface
        return f"{self.status} [{self.stuck_shape}] — {self.suggestion}, doc ab12ef34 | {self.summary}"


class _Item:
    def __init__(self, envelope):
        self.envelope = envelope
        self.description = "Create zz_a.md"


def test_evidence_is_the_outcome_not_the_ledger_diagnostics():
    env = _Envelope(summary='{"success": true, "message": "Written to zz_a.md", "bytes": 32}')
    out = AgentKernel._der_user_facing_evidence(_Item(env))
    assert out == "Written to zz_a.md"
    for token in ("proceed", "try_different", "retry_same", "doc ", "[idling]", "success:"):
        assert token not in out, f"{token!r} must not reach the user"


def test_evidence_keeps_a_readable_content_summary():
    env = _Envelope(summary="- Tea is a comforting beverage.")
    out = AgentKernel._der_user_facing_evidence(_Item(env))
    assert out == "- Tea is a comforting beverage."


def test_evidence_names_an_error_without_the_verdict():
    env = _Envelope(status="failed", summary="", error_type="timeout", suggestion="stop",
                    stuck_shape="dry_well")
    out = AgentKernel._der_user_facing_evidence(_Item(env))
    assert "failed" in out
    assert "dry_well" not in out and "stop" not in out


def test_humanize_unwraps_a_tool_envelope():
    assert AgentKernel._humanize_evidence(
        '{"success": false, "error": "no such file", "path": "x.md"}'
    ) == '{"success": false, "error": "no such file", "path": "x.md"}'  # no human field: unchanged
    assert AgentKernel._humanize_evidence(
        '{"success": true, "content": "- one\\n- two"}'
    ) == "- one\n- two"
    assert AgentKernel._humanize_evidence("plain text") == "plain text"
