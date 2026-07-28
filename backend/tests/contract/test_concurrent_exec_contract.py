"""
Contract test: CT-2 concurrent executor isolation (REQ-8 AC3 / T2.13 / F13).

THE CONTRACT:
  The scheduler's internal shared state (phase registry, rate meter)
  MUST be safe for concurrent access from multiple executors/threads.

  - CT-2a: Two concurrent ``acquire()`` calls on the same quota do NOT
    corrupt internal data structures or produce negative wait times.
  - CT-2b: Concurrent ``advance_all()`` on different quotas does not
    cross-pollute state.

  This test DOES NOT use the actual DER executor — it tests the scheduler
  components directly from separate threads.
"""
import math
import threading
import time

import pytest

from backend.agent.phase_manager import (
    PhaseRegistry,
    get_registry,
    get_rate_meter,
    reset_registry_for_testing,
)
from backend.agent.call_context import CallClass, set_call_class, call_class, priority_index


@pytest.fixture(autouse=True)
def clean():
    get_rate_meter().reset_for_testing()
    get_rate_meter().record_request("ct2_q", tokens=10, priority=5, estimated=True)
    reset_registry_for_testing()
    yield


class TestConcurrentExecContract:
    """CT-2: scheduler shared-state isolation."""

    def test_ct2a_concurrent_acquire_same_quota(self):
        """Two threads calling acquire() on the same quota do not corrupt state."""
        _rm = get_rate_meter()
        _rm.record_request("ct2_q", tokens=10, priority=5, estimated=True)

        _reg = get_registry()
        _oid_a = "ct2_a"
        _oid_b = "ct2_b"
        _reg.register(_oid_a, "ct2_q", natural_period_s=1.0)
        _reg.register(_oid_b, "ct2_q", natural_period_s=1.0)

        _results = []
        _errors = []
        _lock = threading.Lock()

        def _acquire_loop(_oid, _qid, _n=20):
            try:
                for _i in range(_n):
                    from backend.agent.phase_manager import acquire
                    # Each thread uses its own call_class
                    set_call_class(CallClass.REASON)
                    _wait = acquire(_oid, _qid)
                    with _lock:
                        _results.append((_oid, _wait))
                    time.sleep(0.001)
            except Exception as _e:
                with _lock:
                    _errors.append(str(_e))

        _t1 = threading.Thread(target=_acquire_loop, args=("ct2_a", "ct2_q", 30))
        _t2 = threading.Thread(target=_acquire_loop, args=("ct2_b", "ct2_q", 30))
        _t1.start()
        _t2.start()
        _t1.join(timeout=10)
        _t2.join(timeout=10)

        assert not _errors, "Concurrent acquire produced errors: %s" % _errors
        assert len(_results) >= 58, (
            "Expected ~60 results from concurrent acquire; got %d" % len(_results)
        )
        # All wait times must be non-negative
        for _oid, _wait in _results:
            assert _wait >= 0.0, (
                "Wait time must be >= 0; oscillator %s wait=%s" % (_oid, _wait)
            )

    def test_ct2b_concurrent_advance_different_quotas(self):
        """Concurrent advance_all on different quotas does not cross-pollute."""
        _reg = get_registry()
        _reg.register("a1", "q_a", natural_period_s=1.0)
        _reg.register("a2", "q_a", natural_period_s=1.0)
        _reg.register("b1", "q_b", natural_period_s=0.5)
        _reg.register("b2", "q_b", natural_period_s=0.5)

        _errors = []

        def _advance_q(_qid, _n=50):
            try:
                for _i in range(_n):
                    _reg = get_registry()
                    _reg.advance_all(_qid)
                    time.sleep(0.002)
            except Exception as _e:
                _errors.append(str(_e))

        _t_a = threading.Thread(target=_advance_q, args=("q_a", 40))
        _t_b = threading.Thread(target=_advance_q, args=("q_b", 40))
        _t_a.start()
        _t_b.start()
        _t_a.join(timeout=10)
        _t_b.join(timeout=10)

        assert not _errors, "Concurrent advance_all produced errors: %s" % _errors

        # Snapshot final state — both quotas must have coherent oscillators
        _snap = _reg.snapshot()
        assert len(_snap) == 4, (
            "Should have 4 oscillators after concurrent advance; got %s" % len(_snap)
        )
        for _o in _snap:
            assert 0 <= _o.theta < 2 * math.pi
            assert 0.1 <= _o.amplitude <= 1.0

    def test_ct2c_contextvar_isolation_per_thread(self):
        """CallClass context var is per-thread — no cross-leak."""
        _results = []
        _errors = []

        def _set_and_read(_tid, _cls):
            try:
                set_call_class(_cls)
                time.sleep(0.01)  # let other thread set theirs
                _cc = call_class()
                with threading.Lock():
                    _results.append((_tid, _cc))
            except Exception as _e:
                _errors.append(str(_e))

        _t1 = threading.Thread(target=_set_and_read, args=(1, CallClass.USER_TURN))
        _t2 = threading.Thread(target=_set_and_read, args=(2, CallClass.GRAFT))
        _t1.start()
        _t2.start()
        _t1.join(timeout=5)
        _t2.join(timeout=5)

        assert not _errors, "ContextVar errors: %s" % _errors
        _map = dict(_results)
        assert _map.get(1) == CallClass.USER_TURN, (
            "Thread 1 should read USER_TURN; got %s" % _map.get(1)
        )
        assert _map.get(2) == CallClass.GRAFT, (
            "Thread 2 should read GRAFT; got %s" % _map.get(2)
        )
