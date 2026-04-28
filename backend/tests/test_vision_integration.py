"""
Vision integration tests — requires llama-server running with LFM2.5-VL on port 8081.

The backend auto-starts the vision server on first use (lazy load).
To start manually for testing:
  python -c "from backend.tools.lfm_vl_provider import _ensure_vision_server_running; _ensure_vision_server_running()"

Download models if needed (one-time) — place in ~/.lmstudio/models/LiquidAI/LFM2.5-VL-450M-GGUF/:
  python -c "
  from huggingface_hub import hf_hub_download
  import os
  base = os.path.expanduser('~/.lmstudio/models/LiquidAI/LFM2.5-VL-450M-GGUF/')
  os.makedirs(base, exist_ok=True)
  hf_hub_download('LiquidAI/LFM2.5-VL-450M-GGUF','LFM2.5-VL-450M-Q8_0.gguf',local_dir=base)
  hf_hub_download('LiquidAI/LFM2.5-VL-450M-GGUF','mmproj-LFM2.5-VL-450m-F32.gguf',local_dir=base)
  "

Run: python -m pytest backend/tests/test_vision_integration.py -v
"""

import pytest
import asyncio


# ── Pre-flight: skip entire file if server is not reachable ───────────────────

def _server_running() -> bool:
    try:
        import httpx
        r = httpx.get("http://localhost:8081/v1/models", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _server_running(),
    reason="llama-server not running on port 8081 — vision server auto-starts on first use, or start manually via _ensure_vision_server_running()"
)


# ── Provider-level tests ──────────────────────────────────────────────────────

def test_provider_health_check_true():
    from backend.tools.lfm_vl_provider import LFMVLProvider
    provider = LFMVLProvider()
    assert provider.health_check() is True, (
        "health_check() returned False — llama-server is unreachable. "
        "Vision server auto-starts on first use; ensure the model files are present."
    )


def test_screenshot_captures_valid_png():
    from backend.tools.lfm_vl_provider import screenshot_to_bytes
    img = screenshot_to_bytes()
    assert isinstance(img, bytes)
    assert len(img) > 1000, "Screenshot too small — possible capture failure"
    assert img[:4] == b'\x89PNG', (
        "screenshot_to_bytes() did not return PNG bytes. "
        f"First 4 bytes: {img[:4]!r}"
    )


def test_analyze_screen_returns_non_empty_description():
    """
    Critical test: if mmproj file is not loaded, LFM2.5-VL returns blank.
    This test guards against that silent failure.
    """
    from backend.tools.lfm_vl_provider import LFMVLProvider, screenshot_to_bytes
    provider = LFMVLProvider()
    img = screenshot_to_bytes()
    result = provider.analyze_screen(img, "Describe what you see on screen in one sentence.")
    assert isinstance(result, str)
    assert len(result) > 10, (
        "analyze_screen returned blank or very short result. "
        "CRITICAL: Check that mmproj file is loaded "
        f"(llama-server --mmproj flag). Got: {repr(result)}"
    )


def test_read_text_returns_string():
    from backend.tools.lfm_vl_provider import LFMVLProvider, screenshot_to_bytes
    provider = LFMVLProvider()
    img = screenshot_to_bytes()
    result = provider.read_text(img)
    assert isinstance(result, str)


def test_describe_live_frame_returns_non_empty():
    from backend.tools.lfm_vl_provider import LFMVLProvider, screenshot_to_bytes
    provider = LFMVLProvider()
    img = screenshot_to_bytes()
    result = provider.describe_live_frame(img)
    assert isinstance(result, str)
    assert len(result) > 5, (
        "describe_live_frame returned blank — check mmproj is loaded. "
        f"Got: {repr(result)}"
    )


def test_find_ui_element_returns_dict_with_found_key():
    from backend.tools.lfm_vl_provider import LFMVLProvider, screenshot_to_bytes
    provider = LFMVLProvider()
    img = screenshot_to_bytes()
    result = provider.find_ui_element(img, "taskbar or desktop area")
    assert isinstance(result, dict)
    assert "found" in result
    assert isinstance(result["found"], bool)


def test_suggest_action_returns_dict_with_action_key():
    from backend.tools.lfm_vl_provider import LFMVLProvider, screenshot_to_bytes
    provider = LFMVLProvider()
    img = screenshot_to_bytes()
    result = provider.suggest_action(img, "Open a text editor")
    assert isinstance(result, dict)
    assert "action" in result


# ── MCP server with real server ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_vision_mcp_analyze_screen_with_live_server():
    from backend.tools.vision_mcp_server import VisionMCPServer
    server = VisionMCPServer()
    result = await server.execute_tool(
        "vision.analyze_screen", {"question": "What is visible on screen?"}
    )
    assert isinstance(result, dict)
    text = result["content"][0]["text"]
    assert isinstance(text, str)
    assert len(text) > 10, (
        "vision.analyze_screen returned blank with server running. "
        "Check mmproj file is loaded in llama-server."

    )


@pytest.mark.asyncio
async def test_vision_mcp_describe_live_frame_with_live_server():
    from backend.tools.vision_mcp_server import VisionMCPServer
    server = VisionMCPServer()
    result = await server.execute_tool("vision.describe_live_frame", {})
    text = result["content"][0]["text"]
    assert len(text) > 5, f"describe_live_frame blank — check mmproj. Got: {repr(text)}"


# ── Agent kernel end-to-end ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_kernel_vision_get_context_with_live_server():
    """
    Full path: AgentToolBridge.execute_vision_tool('vision_get_context')
    → VisionMCPServer.execute_tool('vision.describe_live_frame')
    → LFMVLProvider.describe_live_frame()
    → llama-server port 8081
    """
    from backend.agent.tool_bridge import AgentToolBridge
    bridge = AgentToolBridge()
    await bridge.initialize()
    result = await bridge.execute_vision_tool("vision_get_context", {})
    assert isinstance(result, dict)
    assert result.get("success") is True, (
        f"vision_get_context returned non-success with live server: {result}"
    )
    description = result.get("result", {}).get("description", "")
    assert len(description) > 10, (
        "vision_get_context returned blank description with live server. "
        "Check mmproj is loaded in llama-server. "
        f"Got: {repr(description)}"
    )
