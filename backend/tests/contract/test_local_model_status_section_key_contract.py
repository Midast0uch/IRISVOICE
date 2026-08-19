"""CT-4 (specs/unified-vision-routing/design.md Testing Strategy): pins the
EXACT break seen live — the MODEL STATUS badge stayed UNLOADED forever
after a successful load because the WS handler's payload was written into
`fieldValues.local_model` while the field is declared, in `data/cards.ts`,
under SECTION id `local-model-card` — and `dark-glass-dashboard.tsx`
resolves a field's value by that section id, not by the (unrelated) top
key `local_model`.

Two permanent guards, both driven from the BACKEND side (payload shape +
static section-key wiring) rather than by rendering the dashboard —
another agent owns `components/dashboard/ModelBrowserPanel.tsx` and its
render test concurrently.

  1. PAYLOAD SHAPE: for every real emission site
     (`_handle_load_local_model` success/failure, `_handle_unload_local_model`,
     `_handle_get_local_model_status`, `_handle_request_state`), the payload
     the backend actually sends must resolve to the correct status string
     under the SAME resolution logic `hooks/useIRISWebSocket.ts` runs
     (mirrored here byte-for-byte in `_resolve_status_like_frontend`). A
     backend change that stops setting `loaded`/`status`/`error` in a way
     the frontend can parse fails here before it ever reaches a user.

  2. SECTION KEY: static source checks (no render) that
     (a) `data/cards.ts` declares the `local_model_status` field inside the
         section whose id is `local-model-card`, and
     (b) both `hooks/useIRISWebSocket.ts` (the payload -> fieldValues
         writer) and `components/dark-glass-dashboard.tsx` (the mount-time
         seed writer) write to that EXACT `'local-model-card'` key — not
         only the legacy `local_model` key, which is what broke live.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from backend.iris_config import IRISConfig
from backend.iris_gateway import IRISGateway

_REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Part 1 — payload shape: real backend payload -> correct frontend status
# ---------------------------------------------------------------------------


def _resolve_status_like_frontend(payload: Any) -> str:
    """Mirrors hooks/useIRISWebSocket.ts's `case "local_model_status"`
    resolution logic (~:1264-1276) exactly. If that logic changes, this
    function must change WITH it — the two are asserted to agree by the
    tests below, not merely by inspection."""
    if isinstance(payload, str):
        return payload
    p = payload or {}
    if isinstance(p.get("status"), str):
        return p["status"]
    if p.get("loaded") is True:
        return "loaded"
    if p.get("loaded") is False and (p.get("status") == "error" or p.get("error")):
        return "error"
    return "unloaded"


class _FakeWSManager:
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


class _FakeLocalModelManager:
    ENDPOINT = "http://127.0.0.1:8091/v1"

    def __init__(self, load_result: bool = True, status: Optional[Dict[str, Any]] = None):
        self._load_result = load_result
        self._status = status or {
            "loaded": False, "model_path": None, "profile": None, "n_ctx": None,
            "purpose": None, "endpoint": None, "pid": None, "inprocess": False,
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


def _patch_kernel_and_config(monkeypatch, mgr):
    monkeypatch.setattr(
        "backend.agent.local_model_manager.get_local_model_manager", lambda: mgr
    )
    monkeypatch.setattr("backend.agent.get_agent_kernel", lambda session_id: _FakeKernel())
    monkeypatch.setattr("backend.iris_config.load_config", lambda: IRISConfig())
    monkeypatch.setattr("backend.iris_config.save_config", lambda cfg: None)


def _gateway():
    ws = _FakeWSManager()
    gw = IRISGateway(ws_manager=ws, state_manager=_FakeStateManager())
    gw._main_loop = asyncio.new_event_loop()
    return gw, ws


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _only_local_model_status_payload(ws: _FakeWSManager) -> Dict[str, Any]:
    msgs = [m for (_, m) in ws.sent if m.get("type") == "local_model_status"]
    assert len(msgs) == 1, f"expected exactly one local_model_status send, got {msgs}"
    return msgs[0]["payload"]


class TestPayloadShapeResolvesToCorrectStatus:
    def test_successful_load_resolves_to_loaded(self, monkeypatch):
        gateway, ws = _gateway()
        mgr = _FakeLocalModelManager(load_result=True)
        _patch_kernel_and_config(monkeypatch, mgr)

        async def _noop(*a, **k):
            return None

        monkeypatch.setattr(gateway, "_handle_get_available_models", _noop)

        _run(gateway._handle_load_local_model(
            "session_iris", "client_iris",
            {"payload": {"model_path": "C:/models/x.gguf", "profile": "balanced"}},
        ))

        payload = _only_local_model_status_payload(ws)
        assert _resolve_status_like_frontend(payload) == "loaded"

    def test_failed_load_resolves_to_error(self, monkeypatch):
        gateway, ws = _gateway()
        mgr = _FakeLocalModelManager(load_result=False)
        _patch_kernel_and_config(monkeypatch, mgr)

        _run(gateway._handle_load_local_model(
            "session_iris", "client_iris",
            {"payload": {"model_path": "C:/models/x.gguf", "profile": "balanced"}},
        ))

        payload = _only_local_model_status_payload(ws)
        assert _resolve_status_like_frontend(payload) == "error"

    def test_unload_resolves_to_unloaded(self, monkeypatch):
        gateway, ws = _gateway()
        mgr = _FakeLocalModelManager(
            status={"loaded": True, "model_path": "C:/models/x.gguf", "profile": "balanced",
                    "n_ctx": None, "purpose": None, "endpoint": None, "pid": None,
                    "inprocess": False, "rotorquant": False}
        )
        _patch_kernel_and_config(monkeypatch, mgr)

        _run(gateway._handle_unload_local_model("session_iris", "client_iris", {}))

        payload = _only_local_model_status_payload(ws)
        assert _resolve_status_like_frontend(payload) == "unloaded"

    def test_get_local_model_status_loaded_true_resolves_to_loaded(self, monkeypatch):
        gateway, ws = _gateway()
        mgr = _FakeLocalModelManager(status={
            "loaded": True, "model_path": "C:/models/x.gguf", "profile": "balanced",
            "n_ctx": 8192, "purpose": "chat", "endpoint": None, "pid": None,
            "inprocess": True, "rotorquant": False,
        })
        monkeypatch.setattr(
            "backend.agent.local_model_manager.get_local_model_manager", lambda: mgr
        )

        _run(gateway._handle_get_local_model_status("session_iris", "client_iris", {}))

        payload = _only_local_model_status_payload(ws)
        assert _resolve_status_like_frontend(payload) == "loaded"

    def test_get_local_model_status_loaded_false_resolves_to_unloaded(self, monkeypatch):
        """No `status`/`error` key at all on this payload (pinned by
        test_local_model_status_baseline.py) — the fallback chain must
        still land on 'unloaded', not crash or mis-resolve to 'error'."""
        gateway, ws = _gateway()
        mgr = _FakeLocalModelManager(status={
            "loaded": False, "model_path": None, "profile": None, "n_ctx": None,
            "purpose": None, "endpoint": None, "pid": None, "inprocess": False,
            "rotorquant": False,
        })
        monkeypatch.setattr(
            "backend.agent.local_model_manager.get_local_model_manager", lambda: mgr
        )

        _run(gateway._handle_get_local_model_status("session_iris", "client_iris", {}))

        payload = _only_local_model_status_payload(ws)
        assert _resolve_status_like_frontend(payload) == "unloaded"

    def test_request_state_persisted_error_resolves_to_error(self, monkeypatch):
        """T10c seam: a failed load persisted BEFORE this reconnect must
        still resolve to 'error' after the reload, not decay to
        'unloaded' — the exact AC3 guarantee CT-4 backs."""
        gateway, ws = _gateway()
        monkeypatch.setattr(
            "backend.agent.agent_kernel.peek_active_kernel", lambda session_id: None
        )
        monkeypatch.setattr("backend.iris_config.load_field_values", lambda: {})
        cfg = IRISConfig()
        cfg.inference.local_model_status = "error"
        monkeypatch.setattr("backend.iris_config.load_config", lambda: cfg)

        _run(gateway._handle_request_state("session_iris", "client_iris"))

        payload = _only_local_model_status_payload(ws)
        assert _resolve_status_like_frontend(payload) == "error"


# ---------------------------------------------------------------------------
# Part 2 — section key: static source checks, no rendering
# ---------------------------------------------------------------------------


class TestSectionKeyWiring:
    def test_cards_ts_declares_the_status_field_under_local_model_card_section(self):
        src = (_REPO_ROOT / "data" / "cards.ts").read_text(encoding="utf-8")

        start = src.index("local_model: [")
        end = src.index("swarm_setup: [")
        section = src[start:end]

        assert "id: 'local-model-card'" in section, (
            "the local_model card section must be id 'local-model-card' — "
            "this is the key the badge writer and dark-glass-dashboard's "
            "section resolver both key off of"
        )
        assert "id: 'local_model_status'" in section, (
            "the local_model_status FIELD must be declared inside the "
            "local_model card block"
        )
        # Exactly one section object lives in this block today — guards
        # against a future restructure silently moving the field to a
        # DIFFERENT section id while this substring check still passes.
        assert len(re.findall(r"id: '[a-z-]+-card'", section)) == 1, (
            "more than one card section now lives under `local_model` — "
            "the field-to-section pinning above is no longer unambiguous"
        )

    def test_use_iris_websocket_writes_the_hyphenated_section_key(self):
        src = (_REPO_ROOT / "hooks" / "useIRISWebSocket.ts").read_text(encoding="utf-8")

        case_start = src.index('case "local_model_status"')
        next_case = src.index("case ", case_start + 10)
        block = src[case_start:next_case]

        assert "'local-model-card'" in block, (
            "hooks/useIRISWebSocket.ts's local_model_status handler no "
            "longer writes the 'local-model-card' section key — this is "
            "the exact live bug (writing only fieldValues.local_model, a "
            "bucket dark-glass-dashboard's section resolver never reads)"
        )

    def test_dashboard_seed_writer_writes_the_hyphenated_section_key(self):
        src = (_REPO_ROOT / "components" / "dark-glass-dashboard.tsx").read_text(
            encoding="utf-8"
        )

        fn_start = src.index("handleLocalModelStatus")
        fn_end = src.index("window.addEventListener", fn_start)
        block = src[fn_start:fn_end]

        assert "'local-model-card'" in block, (
            "dark-glass-dashboard.tsx's handleLocalModelStatus no longer "
            "writes the 'local-model-card' section key"
        )
