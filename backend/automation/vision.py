"""
Vision Model Integration — open-source stack only.

LFM2.5-VL screen analysis: backend/tools/vision_mcp_server.py (MCP tools, llama-cpp-python).
GUI element detection: VisionModelClient with LOCAL (llama-cpp-python) or VOLCENGINE providers.
No Anthropic/cloud API key required.
"""
import asyncio
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum


class VisionProvider(Enum):
    LOCAL = "local"             # llama-cpp-python GGUF (LFM2.5-VL or compatible)
    VOLCENGINE = "volcengine"   # Volcengine cloud vision (optional)
    LLAMA_SERVER = "llama_server"  # LFM2.5-VL via llama-cpp-python (primary)


@dataclass
class ElementDetection:
    """Detected GUI element with pixel coordinates."""
    description: str
    x: int
    y: int
    width: int
    height: int
    confidence: float
    element_type: str


class VisionModelClient:
    """
    Vision model client for GUI element detection.

    Primary backend: LFM2.5-VL loaded via llama-cpp-python (LLAMA_SERVER provider).
    Access via vision.* MCP tools through AgentToolBridge for full kernel integration.

    For direct use in automation scripts, instantiate with LOCAL provider once
    LFM25VLChatHandler is registered in llama_cpp.llama_chat_format.
    """

    def __init__(self, provider: VisionProvider = VisionProvider.LLAMA_SERVER):
        self.provider = provider
        self._client = None

    async def initialize(self) -> Dict[str, Any]:
        if self.provider == VisionProvider.LLAMA_SERVER:
            return {
                "success": True,
                "provider": "llama_server",
                "note": "Use vision.* MCP tools via AgentToolBridge for screen analysis"
            }
        elif self.provider == VisionProvider.LOCAL:
            # llama-cpp-python direct — requires LFM25VLChatHandler to be registered
            try:
                from backend.tools.lfm_vl_provider import LFMVLProvider
                self._client = LFMVLProvider()
                return {"success": True, "provider": "local_lfm"}
            except Exception as e:
                return {"success": False, "error": str(e)}
        elif self.provider == VisionProvider.VOLCENGINE:
            return {"success": False, "error": "Volcengine SDK not yet implemented"}
        return {"success": False, "error": f"Unknown provider: {self.provider}"}

    async def detect_element(self, screenshot_bytes: bytes, description: str) -> Optional[ElementDetection]:
        """Detect element by description. Returns pixel coordinates or None."""
        try:
            if self.provider in (VisionProvider.LLAMA_SERVER, VisionProvider.LOCAL):
                return await self._detect_with_lfm(screenshot_bytes, description)
            return None
        except Exception as e:
            print(f"[VisionModel] Detection error: {e}")
            return None

    async def _detect_with_lfm(self, screenshot_bytes: bytes, description: str) -> Optional[ElementDetection]:
        """Use LFM2.5-VL via MCP tools to locate a UI element."""
        try:
            from backend.tools.lfm_vl_provider import LFMVLProvider
            import asyncio
            provider = LFMVLProvider()
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, provider.find_ui_element, screenshot_bytes, description
            )
            # result is a dict: {"found": bool, "location_hint": str, "confidence": float}
            if isinstance(result, dict) and result.get("found"):
                # location_hint is descriptive — coordinate extraction handled by VisionGuidedOperator
                return ElementDetection(
                    description=description,
                    x=result.get("x", 0),
                    y=result.get("y", 0),
                    width=result.get("width", 50),
                    height=result.get("height", 30),
                    confidence=result.get("confidence", 0.7),
                    element_type=result.get("element_type", "unknown"),
                )
            return None
        except Exception as e:
            print(f"[VisionModel] LFM detection error: {e}")
            return None

    async def analyze_screen(self, screenshot_bytes: bytes, instruction: str) -> Dict[str, Any]:
        """Analyze screen and return next action suggestion."""
        if self.provider == VisionProvider.LLAMA_SERVER:
            return {"action": "error", "message": "Use vision.* MCP tools for LFM2.5-VL screen analysis"}
        try:
            from backend.tools.lfm_vl_provider import LFMVLProvider
            import asyncio
            provider = LFMVLProvider()
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, provider.suggest_action, screenshot_bytes, instruction
            )
            return result if isinstance(result, dict) else {"action": "error", "message": str(result)}
        except Exception as e:
            return {"action": "error", "message": str(e)}


class GUIAgent:
    """High-level GUI agent: VisionModelClient sees, operator acts."""

    def __init__(self, vision_client: VisionModelClient, operator=None):
        self.vision = vision_client
        self.operator = operator
        self.action_history: List[Dict] = []

    async def execute_instruction(self, instruction: str, max_steps: int = 25) -> Dict[str, Any]:
        steps = []
        for step_num in range(max_steps):
            if not self.operator:
                return {"success": False, "error": "Operator not available", "steps": steps}

            screenshot_result = await self.operator.take_screenshot()
            if not screenshot_result.success:
                return {"success": False, "error": "Screenshot failed", "steps": steps}

            img_bytes = screenshot_result.data.get("bytes", b"")
            if not img_bytes:
                return {"success": False, "error": "No screenshot data", "steps": steps}

            action = await self.vision.analyze_screen(img_bytes, instruction)

            if action.get("action") == "complete":
                steps.append({"step": step_num, "action": action, "status": "complete"})
                return {"success": True, "steps": steps, "message": "Task completed"}

            if action.get("action") == "error":
                steps.append({"step": step_num, "action": action, "status": "error"})
                return {"success": False, "error": action.get("message"), "steps": steps}

            result = None
            if action.get("action") == "click":
                coords = action.get("coordinates", {})
                result = await self.operator.click(coords.get("x"), coords.get("y"))
            elif action.get("action") == "type":
                result = await self.operator.type_text(action.get("text", ""))

            steps.append({
                "step": step_num,
                "action": action,
                "result": result.to_dict() if result else None,
                "status": "executed"
            })
            await asyncio.sleep(0.5)

        return {"success": False, "error": "Max steps reached", "steps": steps}
