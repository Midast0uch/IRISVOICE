"""Contract test CT-S3 (specs/phase-5-switcher/design.md).

"`context:usage` shape parity: DER-path and direct-path events have the same
shape and the same denominator (REQ-6 AC2)."

Both paths in `backend/agent/agent_kernel.py` (the direct non-DER reply at
`process_text_message` and the DER per-step/final emit) call the SAME
`_emit_context_usage()` helper (see its docstring: "Single emitter so DER and
non-DER paths share the SAME event contract"). This test drives that helper
directly, the way `backend/tests/test_context_usage_emit.py` does for the
underlying REQ-12/Wave-9 behavior, and additionally pins the STRUCTURAL fact
that both call sites route through it — so a future change that adds a
second, drifting emitter is caught here even before any event is inspected.
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.agent.event_bus import get_event_bus, IRISStreamEvent
from backend.agent.agent_kernel import AgentKernel

ROOT = Path(__file__).resolve().parent.parent.parent.parent
AGENT_KERNEL_PATH = ROOT / "backend" / "agent" / "agent_kernel.py"


def _make_kernel(tokens_used: int, max_tokens: int) -> AgentKernel:
    k = AgentKernel.__new__(AgentKernel)
    k._tokens_used = tokens_used
    k.conversation_id = "conv_ct_s3"
    k.session_id = "sess_ct_s3"
    k._current_turn_id = "turn_ct_s3"
    k.resolve_context_window = lambda: max_tokens
    return k


class TestCTS3ContextUsageShapeParity:
    def test_direct_path_and_der_path_both_call_the_single_shared_emitter(self):
        """Structural pin: neither call site may grow its own emit logic —
        both must route through `self._emit_context_usage(...)`."""
        src = AGENT_KERNEL_PATH.read_text(encoding="utf-8")

        # The non-DER direct-reply path (process_text_message).
        direct_call = re.search(
            r"# REQ-12 \(Wave 9\): emit live context usage on every non-DER\s*"
            r"(?:#.*\n\s*){0,4}self\._emit_context_usage\(\)",
            src,
        )
        assert direct_call is not None, (
            "direct (non-DER) reply path no longer calls the shared "
            "_emit_context_usage() helper — CT-S3 parity is at risk"
        )

        # The DER final-emit path.
        der_call = re.search(
            r"self\._emit_context_usage\(\s*"
            r"step_number=len\(completed_items\),\s*"
            r"total_steps=len\(queue\.items\),\s*\)",
            src,
        )
        assert der_call is not None, (
            "DER path no longer calls the shared _emit_context_usage() "
            "helper with step metadata — CT-S3 parity is at risk"
        )

    def test_direct_style_and_der_style_calls_emit_identical_shape(self):
        """Behavioral pin: call the ONE real helper both ways (no
        step metadata == direct path; with step metadata == DER path) and
        assert the emitted event has the same keys and the same
        resolve_context_window() denominator either way."""
        bus = get_event_bus()
        captured = []

        def _capture(payload):
            if payload.event == IRISStreamEvent.CONTEXT_USAGE:
                captured.append(dict(payload.data or {}))

        bus.subscribe(IRISStreamEvent.CONTEXT_USAGE, _capture)
        try:
            k = _make_kernel(tokens_used=9_001, max_tokens=64_000)

            captured.clear()
            k._emit_context_usage()  # direct-path style (no step metadata)
            direct_event = captured[0]

            captured.clear()
            k._emit_context_usage(step_number=2, total_steps=4)  # DER-path style
            der_event = captured[0]
        finally:
            bus.unsubscribe(IRISStreamEvent.CONTEXT_USAGE, _capture)

        # Same denominator either way — REQ-6 AC2's core guarantee.
        assert direct_event["max_tokens"] == 64_000
        assert der_event["max_tokens"] == 64_000
        # Same numerator source (self._tokens_used) either way.
        assert direct_event["used_tokens"] == 9_001
        assert der_event["used_tokens"] == 9_001
        # Same base shape — DER only ADDS step metadata, never changes the
        # shared fields' names or types.
        shared_keys = {"used_tokens", "max_tokens"}
        assert shared_keys.issubset(direct_event.keys())
        assert shared_keys.issubset(der_event.keys())
