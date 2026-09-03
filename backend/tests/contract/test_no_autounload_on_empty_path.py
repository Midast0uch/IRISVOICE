"""Session 268, handoff item 3.8 — pin the auto-unload guard in the
local_model confirm_card branch (`backend/iris_gateway.py:2072-2119`).

Before the fix, the check `path != cfg.inference.local_model_path` fired on
EVERY confirm that carried an empty path (card remounts render path=""), so a
loaded model self-unloaded the moment any other card saved. Same bug class:
saving models_directory WIPED local_model_path, destroying the loaded model's
identity.

Three behaviors pinned:
  A. empty path in the confirm -> NO unload, persisted path unchanged
  B. different non-empty path -> unload fires, status -> "unloaded"
  C. same non-empty path -> no-op (no unload)

Config load/save and the model manager are faked at the iris_gateway import
seams; the REAL `_handle_settings` confirm_card branch runs unmodified.
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

try:
    from backend.iris_gateway import IRISGateway
except ImportError:
    import sys

    sys.path.insert(0, "..")
    from backend.iris_gateway import IRISGateway


LOADED_PATH = "C:/models/Bonsai-27B-Q1_0.gguf"
OTHER_PATH = "C:/models/other.gguf"


class _FakeWSManager:
    def __init__(self):
        self.sent: List[tuple] = []

    async def send_to_client(self, client_id, msg):
        self.sent.append((client_id, msg))

    async def broadcast_to_session(self, session_id, msg, exclude_clients=None):
        pass

    def get_session_id_for_client(self, client_id):
        return "sess-autounload"

    async def flush_pending(self, session_id, client_id):
        pass


class _FakeState:
    current_category = None
    field_values: Dict[str, Any] = {}


class _FakeStateManager:
    async def get_state(self, session_id):
        return _FakeState()


class _FakeMgr:
    """Records unload calls; reports loaded so the guard's is_loaded() check
    passes when the branch actually decides to unload."""

    def __init__(self):
        self.unload_calls = 0
        self.set_dir_calls: List[str] = []

    def is_loaded(self) -> bool:
        return True

    async def unload_model(self) -> bool:
        self.unload_calls += 1
        return True

    def set_models_directory(self, d):
        self.set_dir_calls.append(d)


def _make_cfg() -> SimpleNamespace:
    return SimpleNamespace(
        inference=SimpleNamespace(
            local_model_status="loaded",
            local_model_path=LOADED_PATH,
            local_model_profile="balanced",
            local_model_ctx=0,
            local_model_gpu_layers=-1,
            models_directory="C:/models",
        ),
        field_values={},
    )


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _confirm_local_model(monkeypatch, values: Dict[str, Any]):
    """Drive the REAL _handle_settings confirm_card path for section
    local_model. Returns (fake_mgr, saved_cfgs)."""
    ws = _FakeWSManager()
    gw = IRISGateway(ws_manager=ws, state_manager=_FakeStateManager())
    gw._main_loop = asyncio.new_event_loop()
    gw._logger = logging.getLogger("test_no_autounload")

    mgr = _FakeMgr()
    cfg = _make_cfg()
    saved: List[Any] = []

    monkeypatch.setattr("backend.iris_gateway.load_config", lambda: cfg)
    monkeypatch.setattr("backend.iris_gateway.save_config", lambda c: saved.append(c))
    monkeypatch.setattr(
        "backend.agent.local_model_manager.get_local_model_manager", lambda: mgr
    )

    _run(gw._handle_settings(
        "sess-autounload", "client-autounload",
        {
            "type": "confirm_card",
            "payload": {"section_id": "local_model", "values": values},
        },
    ))
    return mgr, saved, cfg


class TestNoAutoUnloadOnEmptyPath:
    def test_empty_path_does_not_unload(self, monkeypatch):
        """Case A: a card remount confirm with path="" must not disturb the
        loaded model (the original self-unload bug)."""
        mgr, saved, cfg = _confirm_local_model(
            monkeypatch, {"local_model_path": ""}
        )
        assert mgr.unload_calls == 0, (
            "an empty path in the confirm must NOT trigger unload_model()"
        )
        assert cfg.inference.local_model_path == LOADED_PATH, (
            "an empty path must NOT wipe the persisted local_model_path"
        )
        assert cfg.inference.local_model_status == "loaded"
        assert saved, "config should still be saved (profile/ctx/gpu fields)"

    def test_different_nonempty_path_unloads(self, monkeypatch):
        """Case B: switching to a genuinely different model unloads the old
        one and marks status unloaded."""
        mgr, saved, cfg = _confirm_local_model(
            monkeypatch, {"local_model_path": OTHER_PATH}
        )
        assert mgr.unload_calls == 1, (
            "a different non-empty path MUST trigger unload of the previous model"
        )
        assert cfg.inference.local_model_status == "unloaded"
        assert cfg.inference.local_model_path == OTHER_PATH

    def test_same_nonempty_path_is_noop(self, monkeypatch):
        """Case C: re-confirming the already-loaded model's path must not
        unload it (idempotent confirm)."""
        mgr, saved, cfg = _confirm_local_model(
            monkeypatch, {"local_model_path": LOADED_PATH}
        )
        assert mgr.unload_calls == 0, (
            "confirming the SAME path must not unload the loaded model"
        )
        assert cfg.inference.local_model_status == "loaded"
        assert cfg.inference.local_model_path == LOADED_PATH

    def test_models_directory_save_does_not_wipe_path(self, monkeypatch):
        """The sibling bug: saving only models_directory must leave
        local_model_path and loaded status untouched."""
        mgr, saved, cfg = _confirm_local_model(
            monkeypatch, {"models_directory": "C:/new_models"}
        )
        assert mgr.unload_calls == 0
        assert cfg.inference.local_model_path == LOADED_PATH, (
            "a models_directory-only save must not wipe local_model_path"
        )
        assert cfg.inference.local_model_status == "loaded"
        assert mgr.set_dir_calls == ["C:/new_models"]
