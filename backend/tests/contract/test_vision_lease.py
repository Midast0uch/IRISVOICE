"""Contract tests for the vision lease (T9, REQ-7/REQ-9).

The lease is pure bookkeeping (no server calls). We manipulate the module's
PID/use-time globals directly to prove: an active lease blocks idle-stop,
leases hard-expire, and the context manager releases on exception.
"""

import time

import pytest

from backend.tools import lfm_vl_provider as vl


@pytest.fixture(autouse=True)
def _clean_leases():
    """Start every test with a clean lease registry + no owned server."""
    with vl._LEASE_LOCK:
        vl._VISION_LEASES.clear()
    vl._VISION_SERVER_PID = None
    yield
    vl._VISION_SERVER_PID = None
    with vl._LEASE_LOCK:
        vl._VISION_LEASES.clear()


def test_acquire_returns_none_when_no_server():
    """No owned server -> acquire_vision_lease returns None (nothing to protect)."""
    assert vl._VISION_SERVER_PID is None
    assert vl.acquire_vision_lease(5000) is None
    assert vl.has_active_lease() is False


def test_acquire_blocks_idle_stop():
    """Active lease -> should_idle_stop() is False even past idle timeout."""
    vl._VISION_SERVER_PID = 12345
    vl._last_vision_use = time.monotonic() - vl._IDLE_TIMEOUT - 10
    lease = vl.acquire_vision_lease(max_ms=60_000)
    assert lease is not None
    assert vl.has_active_lease() is True
    assert vl.should_idle_stop() is False  # lease overrides idle timeout
    lease.release()
    assert vl.should_idle_stop() is True


def test_hard_expiry():
    """Lease self-expires at deadline; watchdog may then stop."""
    vl._VISION_SERVER_PID = 12345
    vl._last_vision_use = time.monotonic() - vl._IDLE_TIMEOUT - 10
    lease = vl.acquire_vision_lease(max_ms=1)  # 1 ms hard expiry
    assert lease is not None
    assert vl.has_active_lease() is True
    time.sleep(0.05)
    assert lease.expired is True
    assert vl.has_active_lease() is False  # lazily pruned
    assert vl.should_idle_stop() is True


def test_release_on_exception():
    """Context manager releases the lease when the body raises (REQ-9 AC3)."""
    vl._VISION_SERVER_PID = 12345
    with pytest.raises(RuntimeError):
        with vl.acquire_vision_lease(max_ms=60_000) as lease:
            assert lease is not None
            assert vl.has_active_lease() is True
            raise RuntimeError("boom")
    assert vl.has_active_lease() is False


def test_release_on_normal_exit():
    """Context manager releases the lease on clean exit too."""
    vl._VISION_SERVER_PID = 12345
    with vl.acquire_vision_lease(max_ms=60_000) as lease:
        assert lease is not None
        assert vl.has_active_lease() is True
    assert vl.has_active_lease() is False


def test_multiple_leases_counted():
    """Two concurrent leases; releasing one keeps the other active."""
    vl._VISION_SERVER_PID = 12345
    a = vl.acquire_vision_lease(max_ms=60_000)
    b = vl.acquire_vision_lease(max_ms=60_000)
    assert a is not None and b is not None
    assert vl.has_active_lease() is True
    a.release()
    assert vl.has_active_lease() is True  # b still held
    b.release()
    assert vl.has_active_lease() is False


def test_release_idempotent():
    """Double release is safe."""
    vl._VISION_SERVER_PID = 12345
    lease = vl.acquire_vision_lease(max_ms=60_000)
    assert lease is not None
    lease.release()
    lease.release()  # no raise
    assert vl.has_active_lease() is False
