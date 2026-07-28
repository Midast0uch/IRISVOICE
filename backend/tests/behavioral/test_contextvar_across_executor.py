"""
Behavioral test: call_class context variable propagates across executor boundaries
(T2.12 / F13).

The call_class is a ``ContextVar`` set via ``set_call_class()``.  When the
backend dispatches work to a thread/process executor (e.g., for inference),
the context variable must propagate so that downstream code (transport.py's
``record_request``) can read the correct priority at record time.

This test verifies that ``call_class()`` returns the value set in the parent
thread *before* the executor call, NOT a stale or default value.

NOTE: ``ContextVar`` does NOT automatically propagate across raw
``ThreadPoolExecutor`` boundaries in all runtime versions — the test uses
``contextvars.copy_context().run()`` to explicitly pass the parent context
where needed.
"""
import os
import pytest
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

from backend.agent.call_context import (
    CallClass,
    call_class,
    set_call_class,
    priority_index,
)


def _read_call_class() -> int:
    """Return the numeric index of the current call class, as transport.py
    does via ``priority_index(call_class())``."""
    return priority_index(call_class())


class TestContextVarPropagation:
    """Context variable MUST propagate across thread executor boundaries."""

    def test_call_context_thread_pool(self):
        """set_call_class before submit → executor reads correct value via copy_context()."""
        set_call_class(CallClass.USER_TURN)
        _ctx = copy_context()
        with ThreadPoolExecutor(max_workers=1) as pool:
            _future = pool.submit(_ctx.run, _read_call_class)
            _idx = _future.result(timeout=5)
        assert _idx == priority_index(CallClass.USER_TURN), (
            "executor should read USER_TURN priority; got %s" % _idx
        )

    def test_call_context_thread_pool_graft(self):
        """GRAFT call class propagates correctly across threads."""
        set_call_class(CallClass.GRAFT)
        _ctx = copy_context()
        with ThreadPoolExecutor(max_workers=1) as pool:
            _future = pool.submit(_ctx.run, _read_call_class)
            _idx = _future.result(timeout=5)
        assert _idx == priority_index(CallClass.GRAFT), (
            "executor should read GRAFT priority; got %s" % _idx
        )

    def test_default_is_background(self):
        """Unset call_class defaults to BACKGROUND (lowest priority)."""
        from contextvars import Context
        _fresh_ctx = Context()
        _idx = _fresh_ctx.run(lambda: priority_index(call_class()))
        assert _idx == priority_index(CallClass.BACKGROUND), (
            "default call_class should be BACKGROUND; got %s" % _idx
        )

    def test_contextvar_isolation_between_threads(self):
        """Each thread has its OWN call_class contextvar — they do NOT leak."""
        _results = []

        def _set_and_read(_cls):
            set_call_class(_cls)
            return _read_call_class()

        with ThreadPoolExecutor(max_workers=4) as pool:
            _futures = [
                pool.submit(_set_and_read, CallClass.USER_TURN),
                pool.submit(_set_and_read, CallClass.GRAFT),
                pool.submit(_set_and_read, CallClass.TOOL),
                pool.submit(_set_and_read, CallClass.SPEAK),
            ]
            _results = [f.result(timeout=5) for f in _futures]

        assert _results == [
            priority_index(CallClass.USER_TURN),
            priority_index(CallClass.GRAFT),
            priority_index(CallClass.TOOL),
            priority_index(CallClass.SPEAK),
        ], "Each thread should have isolated call_class; got %s" % _results
