"""Session 268, handoff item 3.9 — pin the TEXT-ONLY load default
(pin_8e40f54a98dc): the local model on 8082 is the BRAIN; vision is served
separately by the 18181 vision server. Loading with the mmproj projector
attached by default caused Bonsai-27B-Q1_0 + mmproj (~5.13GB) to SIGABRT
against ~4.9GB free VRAM — the "stuck at 98%, then signal aborted" failure.

Two layers:

  1. WS boundary (`IRISGateway._handle_load_local_model`): a payload without
     `with_projector` forwards `with_projector=False` to the manager
     (text-only); an explicit `with_projector: True` omits the kwarg so the
     manager's own default (attach) applies.
  2. Command layer (`LocalModelManager._build_server_cmd`): `mmproj_path`
     is the ONLY thing that puts `--mmproj` on the spawned llama-server
     argv — a text-only load must never carry it.

No subprocess, no GPU — load_model is faked; the command builder is driven
directly with `_select_server_binary` stubbed to a fixed path.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple

import pytest

try:
    from backend.agent.local_model_manager import LocalModelManager
    from backend.iris_gateway import IRISGateway
except ImportError:
    import sys

    sys.path.insert(0, "..")
    from backend.agent.local_model_manager import LocalModelManager
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


class _RecordingManager:
    ENDPOINT = "http://127.0.0.1:8091/v1"

    def __init__(self):
        self.calls: List[Tuple[tuple, dict]] = []

    def is_loaded(self) -> bool:
        return False

    def get_status(self) -> Dict[str, Any]:
        return {"loaded": False, "model_path": None, "vision_loaded": False}

    async def load_model(self, *args, **kwargs) -> bool:
        self.calls.append((args, kwargs))
        return True


def _gateway_and_mgr(monkeypatch):
    ws = _FakeWSManager()
    gateway = IRISGateway(ws_manager=ws, state_manager=_FakeStateManager())
    mgr = _RecordingManager()
    monkeypatch.setattr(
        "backend.agent.local_model_manager.get_local_model_manager", lambda: mgr
    )
    monkeypatch.setattr("backend.agent.get_agent_kernel", lambda session_id: _FakeKernel())
    monkeypatch.setattr("backend.iris_gateway.load_config", lambda: _fresh_cfg())
    monkeypatch.setattr("backend.iris_gateway.save_config", lambda cfg: None)
    return gateway, mgr


class _CfgInference:
    local_model_status = "unloaded"
    local_model_path = ""


class _Cfg:
    inference = _CfgInference()
    field_values: Dict[str, Any] = {}


def _fresh_cfg():
    return _Cfg()


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestWSBoundaryTextOnlyDefault:
    def test_absent_with_projector_loads_text_only(self, monkeypatch):
        """The dashboard's Load button sends no with_projector key. The
        brain must load text-only — the manager receives an explicit
        with_projector=False (mirroring pin_8e40f54a98dc)."""
        gateway, mgr = _gateway_and_mgr(monkeypatch)

        async def _noop(*a, **k):
            return None

        monkeypatch.setattr(gateway, "_handle_get_available_models", _noop)

        _run(gateway._handle_load_local_model(
            "session_iris", "client_iris",
            {"payload": {"model_path": "C:/models/Bonsai-27B-Q1_0.gguf"}},
        ))

        assert len(mgr.calls) == 1
        _, kwargs = mgr.calls[0]
        assert kwargs.get("with_projector") is False, (
            "a load without with_projector must be text-only "
            "(with_projector=False forwarded to the manager)"
        )

    def test_explicit_with_projector_true_opts_in(self, monkeypatch):
        """A caller that genuinely wants a multimodal local model opts in
        explicitly; the attach decision is then the manager's default."""
        gateway, mgr = _gateway_and_mgr(monkeypatch)

        async def _noop(*a, **k):
            return None

        monkeypatch.setattr(gateway, "_handle_get_available_models", _noop)

        _run(gateway._handle_load_local_model(
            "session_iris", "client_iris",
            {"payload": {
                "model_path": "C:/models/x.gguf",
                "with_projector": True,
            }},
        ))

        assert len(mgr.calls) == 1
        _, kwargs = mgr.calls[0]
        assert "with_projector" not in kwargs, (
            "explicit opt-in takes the manager's own default (attach) — "
            "the gateway must not force it either way"
        )


class TestServerCommandMmprojArgv:
    """The final authority on text-only: the spawned argv. --mmproj appears
    iff a projector path was resolved, and the gateway now resolves one only
    when the caller opted in."""

    def _mgr_with_binary(self, monkeypatch) -> LocalModelManager:
        mgr = object.__new__(LocalModelManager)  # skip heavy __init__
        monkeypatch.setattr(
            mgr, "_select_server_binary", lambda model_path: "llama-server"
        )
        return mgr

    def _params(self) -> Dict[str, Any]:
        return {"n_gpu_layers": -1, "n_ctx": 4096, "n_batch": 512}

    def test_no_mmproj_flag_without_projector(self, monkeypatch):
        mgr = self._mgr_with_binary(monkeypatch)
        cmd = mgr._build_server_cmd(
            "C:/models/x.gguf", self._params(), mmproj_path=None
        )
        assert "--mmproj" not in cmd, (
            f"text-only load must not carry --mmproj on the argv: {cmd}"
        )
        assert "--model" in cmd and "C:/models/x.gguf" in cmd

    def test_mmproj_flag_present_when_attached(self, monkeypatch):
        mgr = self._mgr_with_binary(monkeypatch)
        cmd = mgr._build_server_cmd(
            "C:/models/x.gguf", self._params(),
            mmproj_path="C:/models/mmproj-x.gguf",
        )
        assert "--mmproj" in cmd, (
            f"an attached projector must appear as --mmproj on the argv: {cmd}"
        )
        i = cmd.index("--mmproj")
        assert cmd[i + 1] == "C:/models/mmproj-x.gguf"
