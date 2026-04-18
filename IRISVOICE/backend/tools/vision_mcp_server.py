"""
VisionMCPServer — LFM2.5-VL vision tools for the Agent Tool Bridge.

Exposes 5 MCP tools with the vision. prefix:
  vision.analyze_screen     - General screen understanding + question answering
  vision.find_ui_element    - Locate UI elements by natural-language description
  vision.read_text          - OCR / extract text from screen
  vision.suggest_next_action - Suggest the next action toward a goal
  vision.describe_live_frame - Fast single-sentence description (monitoring/streaming)

Pattern: Identical to backend/mcp/builtin_servers.py BuiltinServer subclasses.
All tool handlers capture a screenshot and call LFMVLProvider synchronously
(wrapped in asyncio.run_in_executor to avoid blocking the event loop).
All handlers return graceful error strings on any failure — never raise.
"""
import asyncio
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

from backend.mcp.protocol import MCPTool
from backend.mcp.builtin_servers import BuiltinServer


class VisionMCPServer(BuiltinServer):
    """
    MCP server exposing LFM2.5-VL vision capabilities as agent tools.

    Follows the BuiltinServer pattern so it can be registered directly in
    AgentToolBridge._mcp_servers like all other built-in MCP servers.

    The vision server is optional — if LFM2.5-VL is unavailable, all tools
    return a clear error string without raising exceptions.
    """

    def __init__(self):
        self._provider = None
        super().__init__("vision")

    def _get_provider(self):
        """Lazy-load LFMVLProvider — avoids import cost if vision is unused."""
        if self._provider is None:
            try:
                from backend.tools.lfm_vl_provider import LFMVLProvider
                self._provider = LFMVLProvider()
            except Exception as e:
                logger.error(f"[VisionMCPServer] Cannot load LFMVLProvider: {e}")
        return self._provider

    def _setup_tools(self):
        """Register the 5 vision.* tools."""
        self._tools = [
            MCPTool(
                name="vision.analyze_screen",
                description="Analyze current screen content and answer questions about it",
                input_schema={
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "What to look for or ask about the screen"
                        },
                        "region": {
                            "type": "array",
                            "description": "Optional [left, top, width, height] capture region",
                            "items": {"type": "integer"}
                        }
                    }
                }
            ),
            MCPTool(
                name="vision.find_ui_element",
                description="Locate a UI element on screen by natural-language description",
                input_schema={
                    "type": "object",
                    "properties": {
                        "element_description": {
                            "type": "string",
                            "description": "Natural-language description of the element to find"
                        }
                    },
                    "required": ["element_description"]
                }
            ),
            MCPTool(
                name="vision.read_text",
                description="Extract and return all readable text from the screen or a region",
                input_schema={
                    "type": "object",
                    "properties": {
                        "region_hint": {
                            "type": "string",
                            "description": "Optional hint about which area to focus on (e.g. 'top toolbar', 'center dialog')"
                        }
                    }
                }
            ),
            MCPTool(
                name="vision.suggest_next_action",
                description="Suggest the next UI action to take in order to achieve a goal",
                input_schema={
                    "type": "object",
                    "properties": {
                        "goal": {
                            "type": "string",
                            "description": "The goal to accomplish"
                        }
                    },
                    "required": ["goal"]
                }
            ),
            MCPTool(
                name="vision.describe_live_frame",
                description="Fast single-sentence description of the current screen state (for monitoring/streaming)",
                input_schema={
                    "type": "object",
                    "properties": {}
                }
            ),
        ]

    def _make_content(self, text: str) -> Dict[str, Any]:
        """Wrap text in MCP content format."""
        return {"content": [{"type": "text", "text": text}]}

    async def _capture_screenshot(self, region=None) -> Optional[bytes]:
        """Capture screenshot in executor to avoid blocking."""
        try:
            loop = asyncio.get_event_loop()
            from backend.tools.lfm_vl_provider import screenshot_to_bytes
            img_bytes = await loop.run_in_executor(None, screenshot_to_bytes, region)
            return img_bytes
        except Exception as e:
            logger.warning(f"[VisionMCPServer] Screenshot failed: {e}")
            return None

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """
        Dispatch vision tool calls to LFMVLProvider.
        All handlers: capture screenshot → call provider → return MCP content.
        Never raise — always return content dict.
        """
        provider = self._get_provider()
        loop = asyncio.get_event_loop()

        try:
            if name == "vision.analyze_screen":
                region_raw = arguments.get("region")
                region = tuple(region_raw) if region_raw else None
                img_bytes = await self._capture_screenshot(region)
                if img_bytes is None:
                    return self._make_content("Vision unavailable: screenshot capture failed")
                question = arguments.get("question", "")
                result = await loop.run_in_executor(
                    None, provider.analyze_screen, img_bytes, question
                )
                return self._make_content(result)

            elif name == "vision.find_ui_element":
                img_bytes = await self._capture_screenshot()
                if img_bytes is None:
                    return self._make_content("Vision unavailable: screenshot capture failed")
                description = arguments.get("element_description", "")
                detection = await loop.run_in_executor(
                    None, provider.find_ui_element, img_bytes, description
                )
                found = detection.get("found", False)
                hint = detection.get("location_hint", "")
                text = f"Found: {found}. Location: {hint}" if found else f"Not found. {hint}"
                return self._make_content(text)

            elif name == "vision.read_text":
                img_bytes = await self._capture_screenshot()
                if img_bytes is None:
                    return self._make_content("Vision unavailable: screenshot capture failed")
                region_hint = arguments.get("region_hint")
                result = await loop.run_in_executor(
                    None, provider.read_text, img_bytes, region_hint
                )
                return self._make_content(result)

            elif name == "vision.suggest_next_action":
                img_bytes = await self._capture_screenshot()
                if img_bytes is None:
                    return self._make_content("Vision unavailable: screenshot capture failed")
                goal = arguments.get("goal", "")
                suggestion = await loop.run_in_executor(
                    None, provider.suggest_action, img_bytes, goal
                )
                action = suggestion.get("action", "unknown")
                target = suggestion.get("target", "")
                reasoning = suggestion.get("reasoning", "")
                text = f"Action: {action}. Target: {target}. Reasoning: {reasoning}"
                return self._make_content(text)

            elif name == "vision.describe_live_frame":
                img_bytes = await self._capture_screenshot()
                if img_bytes is None:
                    return self._make_content("Vision unavailable: screenshot capture failed")
                result = await loop.run_in_executor(
                    None, provider.describe_live_frame, img_bytes
                )
                return self._make_content(result)

            else:
                return self._make_content(f"Unknown vision tool: {name}")

        except Exception as e:
            logger.error(f"[VisionMCPServer] Tool '{name}' error: {e}")
            return self._make_content(f"Vision tool error: {e}")
