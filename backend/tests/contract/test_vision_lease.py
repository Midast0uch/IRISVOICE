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


# ---------------------------------------------------------------------------
# T11 — CT-3 missing case: `_stop_owned_vision_server` never kills an
# unowned PID (e.g. a user's own llama-server on the same port).
# ---------------------------------------------------------------------------


class TestStopOwnedNeverKillsAnUnownedPID:
    """`_stop_owned_vision_server` only ever acts on the module-tracked
    `_VISION_SERVER_PID` — it takes no PID argument, so the only way it
    could kill a process IRIS does not own is if it fired despite never
    having adopted one. A user running their OWN llama-server on the vision
    port is exactly that case: IRIS never sets `_VISION_SERVER_PID` for a
    process it did not spawn (see `_resolve_listener_pid` / the spawn path),
    so the stop call must be a true no-op — no taskkill, no os.kill, at all.
    """

    def test_no_owned_pid_never_calls_taskkill_or_kill(self, monkeypatch):
        assert vl._VISION_SERVER_PID is None  # nothing adopted (user's own server)

        run_calls = []
        kill_calls = []
        monkeypatch.setattr(
            vl.subprocess, "run", lambda *a, **k: run_calls.append((a, k))
        )
        monkeypatch.setattr(vl.os, "kill", lambda *a, **k: kill_calls.append((a, k)))

        vl._stop_owned_vision_server()

        assert run_calls == [], "must never taskkill a PID it does not own"
        assert kill_calls == [], "must never os.kill a PID it does not own"
        assert vl._VISION_SERVER_PID is None

    def test_owned_pid_kills_only_the_exact_tracked_pid(self, monkeypatch):
        """When IRIS DOES own a server, the stop path must target exactly
        the tracked PID — never some other PID that might belong to a
        user's separately-running server sharing the same port."""
        vl._VISION_SERVER_PID = 42424
        killed_cmds = []

        class _FakeCompleted:
            returncode = 0

        monkeypatch.setattr(
            vl.subprocess,
            "run",
            lambda cmd, **k: killed_cmds.append(cmd) or _FakeCompleted(),
        )
        monkeypatch.setattr(vl.os, "kill", lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("os.kill should not be used on Windows (os.name == 'nt')")
        ))

        vl._stop_owned_vision_server()

        assert len(killed_cmds) == 1
        assert str(42424) in killed_cmds[0]
        assert vl._VISION_SERVER_PID is None  # cleared after stop, so a
        # second call cannot re-target the same (now-dead) PID either.

        # Second call is a no-op — proves the PID is truly forgotten, not
        # just re-used.
        run_calls_after = []
        monkeypatch.setattr(
            vl.subprocess, "run", lambda *a, **k: run_calls_after.append((a, k))
        )
        vl._stop_owned_vision_server()
        assert run_calls_after == []


# ---------------------------------------------------------------------------
# T11 — CT-3 extension (Decisions Locked 8): `VisionResolution.takes_lease`
# follows LOCAL-takes-a-lease / REMOTE-takes-none at EVERY tier (brain,
# tool, fallback) — not just tier 3. Mirrors the tier-permutation cases
# already exercised at the unit layer (test_vision_capability_resolution.py)
# but pins them here too, since CT-3 (the lease contract) is this file's
# home.
# ---------------------------------------------------------------------------


from backend.agent.inference.provider import ProviderInstance, ProviderKind  # noqa: E402
from backend.agent.inference.registry import ProviderRegistry  # noqa: E402
from backend.agent.inference.roles import RoleBindingTable  # noqa: E402
from backend.agent.inference.router import InferenceRouter  # noqa: E402


def _router_with(*instances):
    reg = ProviderRegistry()
    for inst in instances:
        reg.add(inst)
    router = InferenceRouter.__new__(InferenceRouter)
    object.__setattr__(router, "_registry", reg)
    object.__setattr__(router, "_roles", RoleBindingTable(reg))
    object.__setattr__(router, "_default_role", None)
    object.__setattr__(router, "_transports", {})
    object.__setattr__(router, "_inprocess_mgr", None)
    return router


class TestTakesLeaseFollowsLocalVsRemoteAtEveryTier:
    def test_local_brain_tier1_takes_lease(self, monkeypatch):
        monkeypatch.setattr("backend.agent.inference.router._free_vram_gb", lambda: 4.0)
        brain = ProviderInstance(
            id="local:gemma", label="local", kind=ProviderKind.LOCAL_OPENAI,
            model="gemma-4-E4B", vision_loaded=True,
        )
        router = _router_with(brain)
        router.roles.bind("reasoning", "local:gemma")

        res = router.resolve_vision_provider()

        assert res.tier == "brain"
        assert res.takes_lease is True

    def test_local_tool_tier2_takes_lease(self, monkeypatch):
        monkeypatch.setattr("backend.agent.inference.router._free_vram_gb", lambda: 4.0)
        brain = ProviderInstance(
            id="cohere", label="Cohere", kind=ProviderKind.API, model="command-r-plus"
        )
        tool = ProviderInstance(
            id="local:gemma", label="local", kind=ProviderKind.INPROCESS,
            model="gemma-4-E4B", vision_loaded=True,
        )
        router = _router_with(brain, tool)
        router.roles.bind("reasoning", "cohere")
        router.roles.bind("tool_execution", "local:gemma")

        res = router.resolve_vision_provider()

        assert res.tier == "tool"
        assert res.takes_lease is True

    def test_fallback_tier3_takes_lease(self, monkeypatch):
        monkeypatch.setattr("backend.agent.inference.router._free_vram_gb", lambda: 4.0)
        router = _router_with()
        monkeypatch.setattr(
            "backend.tools.lfm_vl_provider._find_vision_model",
            lambda: ("/models/LFM2.5-VL-450M/model.gguf", "/models/LFM2.5-VL-450M/mmproj.gguf"),
        )

        res = router.resolve_vision_provider()

        assert res.tier == "fallback"
        assert res.takes_lease is True

    def test_remote_brain_tier1_takes_no_lease(self, monkeypatch):
        monkeypatch.setattr("backend.agent.inference.router._free_vram_gb", lambda: 4.0)
        brain = ProviderInstance(
            id="openai", label="OpenAI", kind=ProviderKind.API, model="gpt-4o"
        )
        router = _router_with(brain)
        router.roles.bind("reasoning", "openai")

        res = router.resolve_vision_provider()

        assert res.tier == "brain"
        assert res.takes_lease is False

    def test_remote_tool_tier2_takes_no_lease(self, monkeypatch):
        monkeypatch.setattr("backend.agent.inference.router._free_vram_gb", lambda: 4.0)
        brain = ProviderInstance(
            id="cohere", label="Cohere", kind=ProviderKind.API, model="command-r-plus"
        )
        tool = ProviderInstance(
            id="openai", label="OpenAI", kind=ProviderKind.API, model="gpt-4o"
        )
        router = _router_with(brain, tool)
        router.roles.bind("reasoning", "cohere")
        router.roles.bind("tool_execution", "openai")

        res = router.resolve_vision_provider()

        assert res.tier == "tool"
        assert res.takes_lease is False
