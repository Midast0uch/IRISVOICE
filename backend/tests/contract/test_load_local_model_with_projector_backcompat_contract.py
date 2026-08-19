"""CT-5 (specs/unified-vision-routing/design.md Testing Strategy):
`load_local_model` accepts a payload WITHOUT `with_projector` — an existing
sender written before this field existed must still work, and the absent
key must mean "attach" (the default), never "opt out".

Two layers:

  1. WS boundary (`IRISGateway._handle_load_local_model`): a payload that
     omits `with_projector` entirely must drive `LocalModelManager.load_model`
     exactly as a pre-T8 caller would have — no unexpected kwarg forwarded,
     and the manager's own default (attach) is what decides. An explicit
     `with_projector: False` must still reach the manager (the opt-out path
     is not silently swallowed).
  2. Manager signature (`LocalModelManager.load_model`): `with_projector`
     defaults to `True` — pinned directly off the real signature so a
     default-value change is caught even if no caller test exercises it.

No subprocess, no GPU, no real model load — `load_model` itself is faked;
only the ARGUMENTS it receives are inspected.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict, List, Optional, Tuple

from backend.agent.local_model_manager import LocalModelManager
from backend.iris_config import IRISConfig
from backend.iris_gateway import IRISGateway


class _FakeWSManager:
    def __init__(self):
        self.sent: List[Tuple[str, Dict[str, Any]]] = []

    async def send_to_client(self, client_id, msg):
        self.sent.append((client_id, msg))

    async def broadcast_to_session(self, session_id, msg, exclude_clients=None):
        pass

    async def broadcast(self, msg):
        pass

    async def flush_pending(self, session_id, client_id):
        pass


class _FakeState:
    def model_dump(self) -> Dict[str, Any]:
        return {"field_values": {}}


class _FakeStateManager:
    async def get_state(self, session_id):
        return _FakeState()


class _FakeKernel:
    _router = None

    def configure_openai_compat(self, *a, **k):
        pass

    def configure_inprocess_local(self, *a, **k):
        pass


class _RecordingLocalModelManager:
    """Captures exactly the args/kwargs `load_model` was called with,
    without doing any real work — the ARGUMENT SHAPE is the contract."""

    ENDPOINT = "http://127.0.0.1:8091/v1"

    def __init__(self):
        self.calls: List[Tuple[tuple, dict]] = []

    def is_loaded(self) -> bool:
        return False

    def get_status(self) -> Dict[str, Any]:
        return {
            "loaded": True, "model_path": "C:/models/x.gguf", "profile": "balanced",
            "n_ctx": None, "purpose": None, "endpoint": None, "pid": None,
            "inprocess": False, "rotorquant": False,
        }

    async def load_model(self, *args, **kwargs) -> bool:
        self.calls.append((args, kwargs))
        return True


def _gateway_and_mgr(monkeypatch):
    ws = _FakeWSManager()
    gateway = IRISGateway(ws_manager=ws, state_manager=_FakeStateManager())
    mgr = _RecordingLocalModelManager()

    monkeypatch.setattr(
        "backend.agent.local_model_manager.get_local_model_manager", lambda: mgr
    )
    monkeypatch.setattr("backend.agent.get_agent_kernel", lambda session_id: _FakeKernel())
    monkeypatch.setattr("backend.iris_config.load_config", lambda: IRISConfig())
    monkeypatch.setattr("backend.iris_config.save_config", lambda cfg: None)
    return gateway, mgr


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestWSHandlerBackCompat:
    def test_payload_without_with_projector_forwards_no_opt_out_kwarg(self, monkeypatch):
        """A sender written before `with_projector` existed sends a payload
        with no such key at all. The handler must default to `True`
        (attach) internally and must NOT forward `with_projector=False` to
        the manager — the manager's own default already means attach, so a
        pre-existing caller's behavior is unchanged (REQ-4 AC1/AC2, CT-5)."""
        gateway, mgr = _gateway_and_mgr(monkeypatch)

        async def _noop(*a, **k):
            return None

        monkeypatch.setattr(gateway, "_handle_get_available_models", _noop)

        _run(gateway._handle_load_local_model(
            "session_iris", "client_iris",
            {"payload": {"model_path": "C:/models/x.gguf", "profile": "balanced"}},
        ))

        assert len(mgr.calls) == 1
        _, kwargs = mgr.calls[0]
        assert "with_projector" not in kwargs, (
            "absent with_projector in the payload must not translate into "
            "an explicit with_projector=False forwarded to the manager — "
            "that would silently break vision attach for every pre-T8 "
            "sender (CT-5)"
        )

    def test_explicit_opt_out_still_reaches_the_manager(self, monkeypatch):
        """The opt-out path (REQ-4 AC2) must not be swallowed by the
        back-compat default — an explicit `with_projector: false` in the
        payload must still forward `with_projector=False`."""
        gateway, mgr = _gateway_and_mgr(monkeypatch)

        async def _noop(*a, **k):
            return None

        monkeypatch.setattr(gateway, "_handle_get_available_models", _noop)

        _run(gateway._handle_load_local_model(
            "session_iris", "client_iris",
            {"payload": {
                "model_path": "C:/models/x.gguf", "profile": "balanced",
                "with_projector": False,
            }},
        ))

        assert len(mgr.calls) == 1
        _, kwargs = mgr.calls[0]
        assert kwargs.get("with_projector") is False

    def test_explicit_attach_true_also_omits_the_kwarg(self, monkeypatch):
        """An UPDATED sender that explicitly opts IN (`with_projector: true`)
        takes the exact same code path as an old sender that never knew the
        field existed — both mean "attach", and the handler only forwards
        the kwarg on the OPT-OUT branch."""
        gateway, mgr = _gateway_and_mgr(monkeypatch)

        async def _noop(*a, **k):
            return None

        monkeypatch.setattr(gateway, "_handle_get_available_models", _noop)

        _run(gateway._handle_load_local_model(
            "session_iris", "client_iris",
            {"payload": {
                "model_path": "C:/models/x.gguf", "profile": "balanced",
                "with_projector": True,
            }},
        ))

        assert len(mgr.calls) == 1
        _, kwargs = mgr.calls[0]
        assert "with_projector" not in kwargs


class TestManagerSignatureDefaultsToAttach:
    def test_with_projector_param_defaults_true(self):
        sig = inspect.signature(LocalModelManager.load_model)
        assert "with_projector" in sig.parameters, (
            "LocalModelManager.load_model lost its with_projector parameter"
        )
        default = sig.parameters["with_projector"].default
        assert default is True, (
            f"with_projector must default to True (attach) so an absent "
            f"key means attach — found default={default!r}"
        )
