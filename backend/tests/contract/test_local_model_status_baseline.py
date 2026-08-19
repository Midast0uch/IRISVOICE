"""Wave 0 baseline (T0e, pins T10/REQ-7, CT-4): characterize the MODEL STATUS
badge path AS IT IS TODAY, before T10 touches it.

Reported symptom: the badge reads UNLOADED after a page reload even when a
local model is demonstrably resident (GPU memory up, server answering). This
file pins the BACKEND half only (a separate agent owns the frontend half —
__tests__/components/model-status-badge.test.tsx).

Findings this file pins, one test class per finding:

  1. `inference.local_model_status` DOES exist on the persisted config today
     (`InferenceConfig.local_model_status`, iris_config.py:275, default
     "unloaded") — it is not greenfield. What IS greenfield is seeding a WS
     message from it on reconnect: nothing does that (class 4 below).
  2. The load/unload WS handlers DO write "loaded"/"unloaded" into that
     config field (iris_gateway.py:8423, :8606) — driven for real, not
     inferred from reading the source.
  3. The status VALUE "error" is NEVER persisted to config by any code path
     in iris_gateway.py — only "loaded" and "unloaded" literals are ever
     assigned to `cfg.inference.local_model_status`. A failed load leaves the
     config field exactly as it was (usually "unloaded"), so on reload a
     model that errored is indistinguishable from a model that was never
     loaded — REQ-7 AC3 ("ERROR distinguishable from UNLOADED") does NOT
     hold today at the persisted-config layer.
  4. Neither `_handle_request_state` (fires on every WS open/reconnect) nor
     `_hydrate_local_provider_on_startup` (fires once at backend startup)
     ever emits a `local_model_status` WS message or reads
     `cfg.inference.local_model_status` — this is the "nothing" T0e's
     BASELINE GAP refers to, and exactly what T10 AC1 must add.
  5. The `local_model_status` payload shape differs by emission site (pinned
     field-by-field): the load-success and load-error broadcasts carry a
     `status` string; the unload broadcast and the `get_local_model_status`
     WS response (mgr.get_status()) do NOT — the frontend's fallback chain
     (useIRISWebSocket.ts:1264-1276) exists because of this inconsistency.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

import pytest

from backend.iris_config import IRISConfig, ProviderEntry
from backend.iris_gateway import IRISGateway


# ---------------------------------------------------------------------------
# Shared fakes (house style — see test_request_state_pushes_inference_snapshot.py)
# ---------------------------------------------------------------------------


class _FakeWSManager:
    """Records send_to_client / broadcast_to_session / broadcast calls."""

    def __init__(self):
        self.sent: List[Tuple[str, Dict[str, Any]]] = []
        self.broadcasts: List[Tuple[Optional[str], Dict[str, Any]]] = []

    async def send_to_client(self, client_id, msg):
        self.sent.append((client_id, msg))

    async def broadcast_to_session(self, session_id, msg, exclude_clients=None):
        self.broadcasts.append((session_id, msg))

    async def broadcast(self, msg):
        self.broadcasts.append((None, msg))

    async def flush_pending(self, session_id, client_id):
        pass


class _FakeState:
    def __init__(self, field_values: Optional[Dict[str, Dict[str, Any]]] = None):
        self.field_values: Dict[str, Dict[str, Any]] = field_values or {}

    def model_dump(self) -> Dict[str, Any]:
        return {"field_values": self.field_values}


class _FakeStateManager:
    def __init__(self, state: Optional[_FakeState] = None):
        self._state = state or _FakeState()

    async def get_state(self, session_id):
        return self._state


class _FakeKernel:
    """Router is None -> every registration/broadcast block the handlers
    gate on `_router is not None` is skipped, isolating the test to the
    local_model_status path specifically."""

    _router = None

    def configure_openai_compat(self, *a, **k):
        pass

    def configure_inprocess_local(self, *a, **k):
        pass


class _FakeLocalModelManager:
    """Stand-in for LocalModelManager — no subprocess, no GPU, no network."""

    ENDPOINT = "http://127.0.0.1:8091/v1"

    def __init__(self, load_result: bool = True, status: Optional[Dict[str, Any]] = None):
        self._load_result = load_result
        self._llm = None
        self._status = status or {
            "loaded": False,
            "model_path": None,
            "profile": None,
            "n_ctx": None,
            "purpose": None,
            "endpoint": None,
            "pid": None,
            "inprocess": False,
            "rotorquant": False,
        }

    def is_loaded(self) -> bool:
        return bool(self._status.get("loaded"))

    def get_status(self) -> Dict[str, Any]:
        return self._status

    async def load_model(self, model_path, profile, custom_params, *, purpose=None,
                          progress_cb=None, crash_cb=None) -> bool:
        return self._load_result

    async def unload_model(self) -> None:
        return None


@pytest.fixture
def loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def gw(loop):
    ws = _FakeWSManager()
    gateway = IRISGateway(ws_manager=ws, state_manager=_FakeStateManager())
    gateway._main_loop = loop
    return gateway, ws


def _patch_kernel_and_config(monkeypatch, mgr, captured: Dict[str, Any]):
    """Wire the local-model manager, kernel, and config dependencies the
    load/unload handlers resolve via LOCAL `from .x import y` at call time
    (so the patch target is the real module attribute, not iris_gateway's
    namespace)."""
    monkeypatch.setattr(
        "backend.agent.local_model_manager.get_local_model_manager", lambda: mgr
    )
    monkeypatch.setattr("backend.agent.get_agent_kernel", lambda session_id: _FakeKernel())

    def fake_save_config(cfg):
        captured["cfg"] = cfg

    monkeypatch.setattr("backend.iris_config.load_config", lambda: IRISConfig())
    monkeypatch.setattr("backend.iris_config.save_config", fake_save_config)


class TestPersistedStatusFieldExistsButIsNarrow:
    """Finding 1/3: the field exists; only two of its four documented values
    are ever written to it."""

    def test_default_value_is_unloaded(self):
        cfg = IRISConfig()
        assert cfg.inference.local_model_status == "unloaded"

    def test_field_accepts_the_four_documented_values_as_a_bare_string(self):
        """The field is an untyped `str` (iris_config.py:275 comment lists
        unloaded|loaded|loading|error) — nothing on the config layer itself
        rejects "error"; the gap is that nothing ever WRITES it there
        (see TestLoadAndUnloadPersistTwoOfFourValues)."""
        cfg = IRISConfig()
        cfg.inference.local_model_status = "error"
        assert cfg.inference.local_model_status == "error"
        assert cfg.to_dict()["inference"]["local_model_status"] == "error"

    def test_error_literal_is_now_assigned_to_the_config_field_in_the_gateway(self):
        """Source-level backstop for finding 3, covering every call path in
        the file at once (the two driven tests below only cover the paths
        this file explicitly exercises). T10a (REQ-7 AC3/AC4) landed: the
        failed-load path now persists status="error", so it survives a
        reload instead of being indistinguishable from "never loaded"."""
        import inspect
        import backend.iris_gateway as gw_module

        src = inspect.getsource(gw_module)
        assert 'local_model_status = "loaded"' in src
        assert 'local_model_status = "unloaded"' in src
        assert 'local_model_status = "error"' in src, (
            "the failed-load path no longer persists status=\"error\" — "
            "REQ-7 AC3 (ERROR distinguishable from UNLOADED) no longer "
            "holds at the persisted-config layer; T10a's fix regressed"
        )


class TestLoadAndUnloadPersistTwoOfFourValues:
    """Finding 2/3, driven through the REAL handlers (not just read from
    source): a successful load persists "loaded"; unload persists
    "unloaded". T10a (REQ-7 AC3/AC4) landed: a FAILED load now also persists
    "error" (see the last test in this class) — REQ-7 AC3 now holds at the
    persisted-config layer. Class name kept as-is; it documents the
    ORIGINAL (pre-T10a) finding this file characterizes."""

    def test_successful_load_persists_loaded_to_config(self, gw, monkeypatch):
        gateway, ws = gw
        mgr = _FakeLocalModelManager(load_result=True)
        captured: Dict[str, Any] = {}
        _patch_kernel_and_config(monkeypatch, mgr, captured)

        async def _noop_available_models(*a, **k):
            return None

        monkeypatch.setattr(gateway, "_handle_get_available_models", _noop_available_models)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                gateway._handle_load_local_model(
                    "session_iris",
                    "client_iris",
                    {"payload": {"model_path": "C:/models/x.gguf", "profile": "balanced",
                                 "purpose": "chat"}},
                )
            )
        finally:
            loop.close()

        assert captured["cfg"].inference.local_model_status == "loaded"
        assert captured["cfg"].inference.local_model_path == "C:/models/x.gguf"
        assert isinstance(
            captured["cfg"].inference.providers.get("local:x"), ProviderEntry
        )

    def test_failed_load_persists_error_to_config(self, gw, monkeypatch):
        """T10a (REQ-7 AC3/AC4): the failure branch now calls save_config too,
        writing status="error" so it survives a reload instead of being
        indistinguishable from "never loaded" (previously the config field
        was left exactly as it was — see the class docstring)."""
        gateway, ws = gw
        mgr = _FakeLocalModelManager(load_result=False)
        captured: Dict[str, Any] = {}
        _patch_kernel_and_config(monkeypatch, mgr, captured)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                gateway._handle_load_local_model(
                    "session_iris",
                    "client_iris",
                    {"payload": {"model_path": "C:/models/x.gguf", "profile": "balanced",
                                 "purpose": "chat"}},
                )
            )
        finally:
            loop.close()

        assert "cfg" in captured, (
            "a failed load must persist status='error' to config (REQ-7 "
            "AC3/AC4) — save_config was never called"
        )
        assert captured["cfg"].inference.local_model_status == "error"

    def test_unload_persists_unloaded_to_config(self, gw, monkeypatch):
        gateway, ws = gw
        mgr = _FakeLocalModelManager(
            status={"loaded": True, "model_path": "C:/models/x.gguf", "profile": "balanced",
                    "n_ctx": None, "purpose": None, "endpoint": None, "pid": None,
                    "inprocess": False, "rotorquant": False}
        )
        captured: Dict[str, Any] = {}
        _patch_kernel_and_config(monkeypatch, mgr, captured)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                gateway._handle_unload_local_model("session_iris", "client_iris", {})
            )
        finally:
            loop.close()

        assert captured["cfg"].inference.local_model_status == "unloaded"


class TestWSPayloadShapeDiffersBySite:
    """Finding 5: field-by-field shape of `local_model_status`, driven for
    real per emission site."""

    def test_get_local_model_status_response_has_no_status_key(self, gw, monkeypatch):
        """The ONLY handler for the frontend's `get_local_model_status`
        request type (iris_gateway.py:685-687) — but grep shows no frontend
        call site sends that message today, so this path is currently dead
        from the UI's perspective. Its payload IS `mgr.get_status()`
        verbatim: booleans/None, no `status` string field at all."""
        gateway, ws = gw
        status = {
            "loaded": True, "model_path": "C:/models/x.gguf", "profile": "balanced",
            "n_ctx": 8192, "purpose": "chat", "endpoint": None, "pid": None,
            "inprocess": True, "rotorquant": False,
        }
        mgr = _FakeLocalModelManager(status=status)
        monkeypatch.setattr(
            "backend.agent.local_model_manager.get_local_model_manager", lambda: mgr
        )

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                gateway._handle_get_local_model_status("session_iris", "client_iris", {})
            )
        finally:
            loop.close()

        msgs = [m for (_, m) in ws.sent if m.get("type") == "local_model_status"]
        assert len(msgs) == 1
        payload = msgs[0]["payload"]
        assert payload == status
        assert "status" not in payload, (
            "get_local_model_status's payload carries no top-level `status` "
            "string — only `loaded` — the frontend's fallback chain "
            "(useIRISWebSocket.ts:1264-1276) exists BECAUSE of this"
        )

    def test_load_success_broadcast_has_status_and_profile(self, gw, monkeypatch):
        gateway, ws = gw
        mgr = _FakeLocalModelManager(load_result=True)
        captured: Dict[str, Any] = {}
        _patch_kernel_and_config(monkeypatch, mgr, captured)

        async def _noop_available_models(*a, **k):
            return None

        monkeypatch.setattr(gateway, "_handle_get_available_models", _noop_available_models)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                gateway._handle_load_local_model(
                    "session_iris", "client_iris",
                    {"payload": {"model_path": "C:/models/x.gguf", "profile": "balanced",
                                 "purpose": "chat"}},
                )
            )
        finally:
            loop.close()

        msgs = [m for (_, m) in ws.sent if m.get("type") == "local_model_status"]
        assert len(msgs) == 1
        payload = msgs[0]["payload"]
        assert payload == {
            "loaded": True, "status": "loaded",
            "model_path": "C:/models/x.gguf", "profile": "balanced",
        }

    def test_load_error_broadcast_has_status_but_no_profile_key(self, gw, monkeypatch):
        """Pins an inconsistency: the error broadcast carries `status` (like
        the success one) but drops `profile` entirely — the success payload
        has it, the error payload does not."""
        gateway, ws = gw
        mgr = _FakeLocalModelManager(load_result=False)
        captured: Dict[str, Any] = {}
        _patch_kernel_and_config(monkeypatch, mgr, captured)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                gateway._handle_load_local_model(
                    "session_iris", "client_iris",
                    {"payload": {"model_path": "C:/models/x.gguf", "profile": "balanced",
                                 "purpose": "chat"}},
                )
            )
        finally:
            loop.close()

        msgs = [m for (_, m) in ws.sent if m.get("type") == "local_model_status"]
        assert len(msgs) == 1
        payload = msgs[0]["payload"]
        assert payload["status"] == "error"
        assert payload["loaded"] is False
        assert "profile" not in payload
        assert payload["model_path"] == "C:/models/x.gguf"

    def test_unload_broadcast_has_no_status_key_either(self, gw, monkeypatch):
        gateway, ws = gw
        mgr = _FakeLocalModelManager(
            status={"loaded": True, "model_path": "C:/models/x.gguf", "profile": "balanced",
                    "n_ctx": None, "purpose": None, "endpoint": None, "pid": None,
                    "inprocess": False, "rotorquant": False}
        )
        captured: Dict[str, Any] = {}
        _patch_kernel_and_config(monkeypatch, mgr, captured)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                gateway._handle_unload_local_model("session_iris", "client_iris", {})
            )
        finally:
            loop.close()

        msgs = [m for (_, m) in ws.sent if m.get("type") == "local_model_status"]
        assert len(msgs) == 1
        payload = msgs[0]["payload"]
        assert payload == {"loaded": False, "model_path": None, "profile": None}
        assert "status" not in payload


class TestNothingSeedsTheStatusOnReloadOrReconnect:
    """Finding 4 — the BASELINE GAP T0e named, now PARTIALLY CLOSED.

    T10c (REQ-7 AC3) landed: `_handle_request_state` — the seam that fires on
    every WS open AND reconnect — now reads the PERSISTED
    `cfg.inference.local_model_status` and pushes it on the `local_model_status`
    channel. The first test below was inverted to that new truth.

    The startup-rehydrate half (`_hydrate_local_provider_on_startup`) is
    UNCHANGED and still tells the badge nothing — the remaining two tests keep
    pinning that, because T10c deliberately did not touch it.
    """

    def _drive_request_state(self, gateway, monkeypatch, persisted_status):
        """Drive _handle_request_state with a KNOWN persisted status.

        T10c imports `load_config` INSIDE the handler, so it resolves from
        `backend.iris_config` at call time and this patch takes effect.
        """
        monkeypatch.setattr(
            "backend.agent.agent_kernel.peek_active_kernel", lambda session_id: None
        )
        monkeypatch.setattr("backend.iris_config.load_field_values", lambda: {})
        cfg = IRISConfig()
        cfg.inference.local_model_status = persisted_status
        monkeypatch.setattr("backend.iris_config.load_config", lambda: cfg)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                gateway._handle_request_state("session_iris", "client_iris")
            )
        finally:
            loop.close()

    def test_request_state_emits_the_persisted_local_model_status(
        self, gw, monkeypatch
    ):
        """T10c CHANGED this. request_state is the seam that fires on every
        page load, remount and reconnect (useIRISWebSocket.ts, per the
        docstring of _handle_request_state). It now pushes the PERSISTED
        status alongside `initial_state` / `role_bindings_updated`.

        Was: asserted local_model_status was NEVER among the emitted types.
        """
        gateway, ws = gw
        self._drive_request_state(gateway, monkeypatch, "loaded")

        types = [m.get("type") for (_, m) in ws.sent]
        assert "local_model_status" in types, (
            "request_state must emit local_model_status — REQ-7 AC1/AC3 "
            "depend on this seam covering reconnect, not just first mount"
        )
        msg = next(m for (_, m) in ws.sent if m.get("type") == "local_model_status")
        assert msg["payload"]["status"] == "loaded"

        # UNCHANGED and still true: T10c chose the separate-message seam
        # rather than folding the value into initial_state.field_values.
        # This assertion documents WHICH seam was taken.
        initial = next(m for (_, m) in ws.sent if m.get("type") == "initial_state")
        assert "local_model_status" not in initial["payload"].get("state", {}).get(
            "field_values", {}
        ).get("local-model-card", {})

    def test_request_state_carries_persisted_error_so_ac3_survives_a_reload(
        self, gw, monkeypatch
    ):
        """REQ-7 AC3, end to end at this seam: T10a persists "error" on a
        failed load, and this is the channel that carries it back after a
        reload. Before T10c, "error" reached no channel the frontend could
        read and a failed load decayed to UNLOADED."""
        gateway, ws = gw
        self._drive_request_state(gateway, monkeypatch, "error")

        msg = next(m for (_, m) in ws.sent if m.get("type") == "local_model_status")
        assert msg["payload"]["status"] == "error", (
            "a failed load must still read ERROR after a reload, not UNLOADED"
        )

    def test_startup_rehydrate_with_config_loaded_but_server_unreachable_emits_nothing(
        self, monkeypatch
    ):
        """Realistic post-restart case: config says a model was loaded before
        the restart, but the subprocess/manager is fresh (the common cold
        case, since LocalModelManager tracks the subprocess it spawned, not
        one from a prior process). `_hydrate_local_provider_on_startup`
        probes the server over HTTP and, on failure, returns without ever
        touching `local_model_status` — the badge is simply never told."""
        ws = _FakeWSManager()
        gateway = IRISGateway(ws_manager=ws, state_manager=_FakeStateManager())

        cfg = IRISConfig()
        cfg.inference.local_model_status = "loaded"
        cfg.inference.local_model_path = "C:/models/x.gguf"
        monkeypatch.setattr("backend.iris_config.load_config", lambda: cfg)

        mgr = _FakeLocalModelManager(status={"loaded": False})
        monkeypatch.setattr(
            "backend.agent.local_model_manager.get_local_model_manager", lambda: mgr
        )

        class _RaisingAsyncClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                raise ConnectionError("server not up yet (fresh process)")

            async def __aexit__(self, *a):
                return False

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", _RaisingAsyncClient)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(gateway._hydrate_local_provider_on_startup())
        finally:
            loop.close()

        all_msgs = [m for (_, m) in ws.sent] + [m for (_, m) in ws.broadcasts]
        types = {m.get("type") for m in all_msgs}
        assert "local_model_status" not in types
        assert "provider_added" not in types, (
            "the startup rehydrate never restores the badge OR the dropdown "
            "when the server is unreachable — config still says 'loaded'"
        )

    def test_startup_rehydrate_when_config_says_unloaded_returns_immediately(
        self, monkeypatch
    ):
        """The other half of finding 4: even when the config value IS
        readable, the ONLY thing this function ever does with it is decide
        whether to probe — it never turns that value into a WS message."""
        ws = _FakeWSManager()
        gateway = IRISGateway(ws_manager=ws, state_manager=_FakeStateManager())

        cfg = IRISConfig()
        cfg.inference.local_model_status = "unloaded"
        monkeypatch.setattr("backend.iris_config.load_config", lambda: cfg)

        probed = {"called": False}

        class _ShouldNotBeCalledAsyncClient:
            def __init__(self, *a, **k):
                probed["called"] = True

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", _ShouldNotBeCalledAsyncClient)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(gateway._hydrate_local_provider_on_startup())
        finally:
            loop.close()

        assert probed["called"] is False
        assert ws.sent == []
        assert ws.broadcasts == []
