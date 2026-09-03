"""Session 268, handoff item 3.7 — pin the IsolatedStateManager.update_field
5-arg + tuple contract.

The StateManager facade (`backend/state_manager.py:64`) forwards
`update_field(section_id, field_id, value, timestamp)` — 5 args — and
returns the result straight to `iris_gateway.py:1194`, which unpacks it:

    success, update_timestamp = await self._state_manager.update_field(...)

Before session 268 the isolated manager took 3 args and returned None, so
EVERY field_update died with "cannot unpack non-iterable NoneType object" —
the root cause of every "stuck loading" / "dropdown empty" symptom.

This pins: 5-arg signature, tuple return shape, explicit-timestamp passthrough,
auto-timestamp fallback, and persistence into field_values.
"""
from __future__ import annotations

import asyncio
import time

try:
    from backend.sessions.state_isolation import IsolatedStateManager
except ImportError:
    import sys

    sys.path.insert(0, "..")
    from backend.sessions.state_isolation import IsolatedStateManager


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_manager() -> IsolatedStateManager:
    # No initialize() call -> _persistence_dir stays None -> no disk I/O.
    return IsolatedStateManager("sess-update-field")


class TestUpdateFieldContract:
    def test_explicit_timestamp_passthrough(self):
        """A caller-supplied timestamp is returned verbatim — the gateway
        logs/echoes this value, so it must not be replaced by now()."""
        mgr = _make_manager()
        result = _run(mgr.update_field("sect", "display_name", "IRIS", 123.0))
        assert isinstance(result, tuple), (
            f"update_field must return a tuple (success, ts) — got {type(result)}"
        )
        assert result == (True, 123.0), (
            f"explicit timestamp must pass through: expected (True, 123.0), "
            f"got {result}"
        )

    def test_implicit_timestamp_is_current_time(self):
        """No timestamp -> the manager stamps it with now(). Returns the SAME
        tuple shape (the facade unpacks it unconditionally)."""
        mgr = _make_manager()
        before = time.time()
        result = _run(mgr.update_field("sect", "display_name", "IRIS"))
        after = time.time()
        assert isinstance(result, tuple) and len(result) == 2
        success, ts = result
        assert success is True
        assert before <= ts <= after, (
            f"auto timestamp must be ~now(): got {ts}, window [{before}, {after}]"
        )

    def test_value_persisted_into_field_values(self):
        """The point of the call: field_values[section][field] is set, so a
        subsequent get_state() serves the persisted value."""
        mgr = _make_manager()
        _run(mgr.update_field("sect", "display_name", "IRIS", 123.0))
        fv = mgr._state.field_values
        assert fv.get("sect", {}).get("display_name") == "IRIS", (
            f"field_values must persist the write — got {fv}"
        )

    def test_five_arg_signature_accepted(self):
        """The facade calls with all 5 positional-ish args — the signature
        must accept (section, field, value, timestamp) without TypeError."""
        mgr = _make_manager()
        result = _run(mgr.update_field("a", "b", "c", 1.0))
        assert result == (True, 1.0)

    def test_return_shape_unpackable_by_gateway(self):
        """The exact unpack the gateway performs (iris_gateway.py:1194):
        `success, update_timestamp = await ...`. Must never raise."""
        mgr = _make_manager()
        success, update_timestamp = _run(mgr.update_field("a", "b", "c"))
        assert success is True
        assert isinstance(update_timestamp, float)
