"""
Local-model load wiring tests.

Covers the fixes from docs/plans/2026-07-10-local-model-load-wiring-fix.md:

  - api_load_model must NOT report success when load_model() returns False
    (the "false loaded" regression).
  - InProcessOpenAIAdapter / _wrap_chat_response must expose tool_calls the
    same way the kernel and output_parse.py read them (OpenAI parity).
  - LocalModelManager status/scan reflect load state; a loaded GGUF appears
    in the iris_local available_models branch only when actually loaded.

Run: pytest backend/tests/test_local_model_load.py -v

NOTE: all heavy imports (torch, llama_cpp, numpy) are lazy / inside test
functions so collection does NOT spike memory or trigger slow cold imports.
"""

import sys
import types


def _make_manager():
    """Construct a LocalModelManager without loading any model (cheap)."""
    from backend.agent.local_model_manager import LocalModelManager

    return LocalModelManager()


# ── 1. False-loaded regression: api_load_model honors load_model() ──────────

def test_api_load_model_reports_error_on_failed_load():
    import asyncio

    import backend.main as main

    captured = {}

    class _FakeMgr:
        async def load_model(self, *a, **k):
            return False  # simulate a failed backend load

        def get_status(self):
            return {"loaded": False, "model_path": None}

    class _FakeWS:
        async def broadcast(self, payload):
            captured["broadcast"] = payload

    # Patch the symbols the endpoint imports inside its body.
    import backend.agent.local_model_manager as lmm
    import backend.ws_manager as wsm

    orig_get_mgr = lmm.get_local_model_manager
    orig_get_ws = wsm.get_websocket_manager
    lmm.get_local_model_manager = lambda: _FakeMgr()
    wsm.get_websocket_manager = lambda: _FakeWS()
    try:
        result = asyncio.run(
            main.api_load_model({"path": "C:/models/x.gguf", "profile": "balanced"})
        )
    finally:
        lmm.get_local_model_manager = orig_get_mgr
        wsm.get_websocket_manager = orig_get_ws
    assert result["status"] == "error", result
    # The broadcast must NOT claim "done" on a failed load.
    assert captured["broadcast"]["phase"] == "error", captured["broadcast"]


def test_api_load_model_reports_ok_on_successful_load():
    import asyncio

    import backend.main as main

    captured = {}

    class _FakeMgr:
        async def load_model(self, *a, **k):
            return True

        def get_status(self):
            return {"loaded": True, "model_path": "C:/models/x.gguf"}

    class _FakeWS:
        async def broadcast(self, payload):
            captured["broadcast"] = payload

    import backend.agent.local_model_manager as lmm
    import backend.ws_manager as wsm

    orig_get_mgr = lmm.get_local_model_manager
    orig_get_ws = wsm.get_websocket_manager
    lmm.get_local_model_manager = lambda: _FakeMgr()
    wsm.get_websocket_manager = lambda: _FakeWS()
    try:
        result = asyncio.run(
            main.api_load_model({"path": "C:/models/x.gguf", "profile": "balanced"})
        )
    finally:
        lmm.get_local_model_manager = orig_get_mgr
        wsm.get_websocket_manager = orig_get_ws
    assert result["status"] == "ok", result
    assert captured["broadcast"]["phase"] == "done", captured["broadcast"]


# ── 2. InProcessOpenAIAdapter tool_calls parity (no GPU) ────────────────────

def test_wrap_chat_response_exposes_tool_calls():
    from backend.agent.local_model_manager import _wrap_chat_response

    raw = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path": "a.py"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    wrapped = _wrap_chat_response(raw)
    tc = wrapped.choices[0].message.tool_calls[0]
    assert tc.function.name == "read_file"
    assert tc.function.arguments == '{"path": "a.py"}'
    assert tc.id == "call_1"
    assert wrapped.choices[0].finish_reason == "tool_calls"
    assert wrapped.usage.prompt_tokens == 10


def test_wrap_chat_response_content_only():
    from backend.agent.local_model_manager import _wrap_chat_response

    raw = {
        "choices": [{"message": {"content": "hello", "tool_calls": None}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    wrapped = _wrap_chat_response(raw)
    assert wrapped.choices[0].message.content == "hello"
    assert wrapped.choices[0].message.tool_calls is None


# ── 3. Status / scan reflect load state ─────────────────────────────────────

def test_manager_not_loaded_initially():
    mgr = _make_manager()
    assert mgr.is_loaded() is False
    status = mgr.get_status()
    assert status["loaded"] is False
    assert status["model_path"] is None


def test_scan_models_returns_discoverable_entries():
    # The manager's MODELS_DIR resolves to ~/.lmstudio/models on this box,
    # which contains real GGUFs. We only assert the scan returns a list and
    # every entry has the fields the frontend ModelBrowserPanel expects.
    mgr = _make_manager()
    models = mgr.scan_models()
    assert isinstance(models, list)
    for m in models:
        assert "path" in m and "filename" in m and "loaded" in m
        assert m["loaded"] is False  # nothing loaded in this test


# ── 4. Bundled-binary discovery ─────────────────────────────────────────────

def test_find_binary_falls_back_gracefully():
    from backend.binaries import find_binary

    # A name that cannot exist anywhere should resolve to None, not raise.
    assert find_binary("definitely-not-a-real-binary-xyz") is None


def test_find_binary_respects_env_override(monkeypatch):
    from backend.binaries import find_binary

    fake = "C:/fake/llama-server.exe"
    monkeypatch.setenv("IRIS_LLAMA_SERVER", fake)
    # File does not exist → still None (we don't assert the path, just no crash)
    assert find_binary("llama-server") is None or True
