#!/usr/bin/env python3
"""Standalone unit test for REQ-12 (Wave 9): _emit_context_usage.

Run:  python backend/tests/test_context_usage_emit.py
NOT collected by pytest (no test_ prefix) to avoid the full-backend
memory spike — mirrors test_agent_kernel_turn_zone.py.

Covers:
  T29: helper emits IRISStreamEvent.CONTEXT_USAGE with
       used_tokens = self._tokens_used (real per-thread) and
       max_tokens = resolve_context_window().
  T31 (AC3 "never 0"): an ACTIVE / SWITCHED thread (self._tokens_used
       restored to a real count) emits that non-zero count; only a fresh
       thread with no history may emit 0.
  T32 (AC4): same helper/shape used for DER + non-DER (no drift).
"""
import sys

REPO_ROOT = r"C:\dev\IRISVOICE"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.agent.agent_kernel import AgentKernel
from backend.agent.event_bus import get_event_bus, IRISStreamEvent

results = []


def check(name, cond, detail=""):
    results.append((name, cond, detail))
    print(("PASS" if cond else "FAIL"), name, ("- " + detail) if detail else "")


def make_kernel():
    """Build an AgentKernel without running __init__ (avoids heavy setup)."""
    k = AgentKernel.__new__(AgentKernel)
    k._tokens_used = 0
    k.conversation_id = "conv_test"
    k.session_id = "sess_test"
    k._current_turn_id = "turn_1"
    # Stub resolve_context_window so the test is deterministic + offline.
    k.resolve_context_window = lambda: 200_000
    return k


def main():
    bus = get_event_bus()
    captured = []

    def _capture(payload):
        if payload.event == IRISStreamEvent.CONTEXT_USAGE:
            _d = dict(payload.data or {})
            _d["_conversation_id"] = payload.conversation_id
            captured.append(_d)

    bus.subscribe(IRISStreamEvent.CONTEXT_USAGE, _capture)

    # ── T29: helper emits with real used + resolved max ───────────────
    k = make_kernel()
    k._tokens_used = 12_400
    captured.clear()
    k._emit_context_usage()
    check("T29 emits CONTEXT_USAGE", len(captured) == 1, str(captured))
    if captured:
        d = captured[0]
        check("T29 used_tokens = self._tokens_used (12400)",
              d.get("used_tokens") == 12_400, str(d.get("used_tokens")))
        check("T29 max_tokens = resolve_context_window (200000)",
              d.get("max_tokens") == 200_000, str(d.get("max_tokens")))
        check("T29 conversation_id forwarded",
              d.get("_conversation_id") == "conv_test", str(d.get("_conversation_id")))

    # ── T31 AC3: active/switched thread NEVER emits 0 ──────────────
    # Simulate a thread SWITCH: restore_context_from_store set a real count.
    k2 = make_kernel()
    k2._tokens_used = 53_210  # restored from store for an active thread
    captured.clear()
    k2._emit_context_usage()
    check("T31 active/switched thread emits real non-zero used_tokens",
          len(captured) == 1 and captured[0].get("used_tokens") == 53_210,
          str(captured[0].get("used_tokens") if captured else "none"))

    # ── T31 AC3: only a FRESH thread (no history) may emit 0 ────────
    k3 = make_kernel()
    k3._tokens_used = 0  # genuinely brand-new, nothing happened
    captured.clear()
    k3._emit_context_usage()
    check("T31 fresh thread may emit 0 (honest)",
          len(captured) == 1 and captured[0].get("used_tokens") == 0,
          str(captured[0].get("used_tokens") if captured else "none"))

    # ── T32 AC4: DER-style call (step_number/total_steps) same shape ──
    k4 = make_kernel()
    k4._tokens_used = 8_000
    captured.clear()
    k4._emit_context_usage(step_number=3, total_steps=5)
    check("T32 DER call emits same shape with step metadata",
          len(captured) == 1
          and captured[0].get("step_number") == 3
          and captured[0].get("total_steps") == 5
          and captured[0].get("max_tokens") == 200_000,
          str(captured[0] if captured else "none"))

    bus.unsubscribe(IRISStreamEvent.CONTEXT_USAGE, _capture)

    passed = sum(1 for _, c, _ in results if c)
    total = len(results)
    print(f"\n{passed}/{total} checks passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
