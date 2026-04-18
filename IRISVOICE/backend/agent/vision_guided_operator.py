"""
VisionGuidedOperator — Option B desktop automation architecture.

Contract with the agent kernel:
  - Kernel (DER loop) APPROVES what task to run — the safety gate
  - This class EXECUTES it fast: screenshot → LFM2.5-VL → action → repeat
  - Kernel receives full action trace + final screenshot for Mycelium recording

No per-action DER overhead inside the loop.
Nothing executes without the kernel having approved the goal first.
"""
import asyncio
import logging
import re
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)


class VisionGuidedOperator:
    """
    Bridges VisionMCPServer (LFM2.5-VL) + NativeGUIOperator (pyautogui).

    Wired by AgentToolBridge after both MCP servers are initialized:
        bridge._vision_guided_operator = VisionGuidedOperator(
            vision_server=bridge._mcp_servers["vision"],
            native_operator=bridge._mcp_servers["gui_automation"]._native_operator,
        )
    """

    def __init__(self, vision_server=None, native_operator=None):
        self._vision = vision_server       # VisionMCPServer (LFM2.5-VL)
        self._operator = native_operator   # NativeGUIOperator (pyautogui)
        self._trace: List[Dict[str, Any]] = []

    def set_vision_server(self, server):
        self._vision = server

    def set_operator(self, operator):
        self._operator = operator

    # ── Screenshot ────────────────────────────────────────────────────────────

    async def screenshot(self) -> bytes:
        from backend.tools.lfm_vl_provider import screenshot_to_bytes
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, screenshot_to_bytes)

    # ── Vision ────────────────────────────────────────────────────────────────

    async def find_element(self, description: str) -> Optional[Tuple[int, int]]:
        """
        Ask LFM2.5-VL for pixel coordinates of a UI element.
        Prompt enforces strict format: x=NNN y=NNN
        Returns (x, y) or None.
        """
        if self._vision is None:
            return None
        from backend.tools.lfm_vl_provider import LFMVLProvider
        provider = LFMVLProvider()
        loop = asyncio.get_event_loop()
        img = await self.screenshot()
        prompt = (
            f"Find this UI element: {description}\n"
            "Respond ONLY with pixel coordinates in this exact format: x=NNN y=NNN\n"
            "If not visible, respond: NOT_FOUND"
        )
        response = await loop.run_in_executor(None, provider.analyze_screen, img, prompt)
        match = re.search(r'x=(\d+)\s*y=(\d+)', response, re.IGNORECASE)
        if match:
            x, y = int(match.group(1)), int(match.group(2))
            logger.info(f"[VGO] '{description[:50]}' → ({x}, {y})")
            return (x, y)
        logger.warning(f"[VGO] Not found: '{description[:50]}' | response: {response[:80]}")
        return None

    async def verify(self, question: str) -> str:
        """Ask LFM2.5-VL to verify current screen state. Returns plain text."""
        if self._vision is None:
            return "Vision unavailable — server not running"
        result = await self._vision.execute_tool(
            "vision.analyze_screen", {"question": question}
        )
        return result.get("content", [{}])[0].get("text", "")

    # ── Actions ───────────────────────────────────────────────────────────────

    async def click(self, x: int, y: int, label: str = "") -> bool:
        import pyautogui
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, lambda: pyautogui.click(x, y))
            self._log("click", {"x": x, "y": y, "label": label})
            await asyncio.sleep(0.2)
            return True
        except Exception as e:
            logger.warning(f"[VGO] click({x},{y}) failed: {e}")
            return False

    async def click_element(self, description: str, fallback: Optional[Tuple[int, int]] = None) -> bool:
        """Find element via LFM2.5-VL then click. Uses fallback coords if vision fails."""
        coords = await self.find_element(description)
        if coords is None and fallback:
            logger.info(f"[VGO] Vision failed for '{description}', using fallback {fallback}")
            coords = fallback
        if coords:
            return await self.click(coords[0], coords[1], label=description)
        logger.warning(f"[VGO] Cannot click — no coords for: {description}")
        return False

    async def drag(self, x1: int, y1: int, x2: int, y2: int) -> bool:
        import pyautogui
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: pyautogui.drag(x2 - x1, y2 - y1, duration=0.4, button='left')
            )
            self._log("drag", {"from": (x1, y1), "to": (x2, y2)})
            await asyncio.sleep(0.3)
            return True
        except Exception as e:
            logger.warning(f"[VGO] drag failed: {e}")
            return False

    async def click_drag(self, x1: int, y1: int, x2: int, y2: int) -> bool:
        """Click at (x1,y1) and drag to (x2,y2) — for creating text boxes."""
        import pyautogui
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: pyautogui.moveTo(x1, y1)
            )
            await asyncio.sleep(0.1)
            await loop.run_in_executor(
                None,
                lambda: pyautogui.dragTo(x2, y2, duration=0.5, button='left')
            )
            self._log("click_drag", {"from": (x1, y1), "to": (x2, y2)})
            await asyncio.sleep(0.3)
            return True
        except Exception as e:
            logger.warning(f"[VGO] click_drag failed: {e}")
            return False

    async def hotkey(self, *keys) -> bool:
        import pyautogui
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, lambda: pyautogui.hotkey(*keys))
            self._log("hotkey", {"keys": list(keys)})
            await asyncio.sleep(0.2)
            return True
        except Exception as e:
            logger.warning(f"[VGO] hotkey {keys} failed: {e}")
            return False

    async def press(self, key: str) -> bool:
        import pyautogui
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, pyautogui.press, key)
            self._log("press", {"key": key})
            await asyncio.sleep(0.1)
            return True
        except Exception as e:
            logger.warning(f"[VGO] press({key}) failed: {e}")
            return False

    async def type_text(self, text: str, use_clipboard: bool = True) -> bool:
        """
        Type text. Uses clipboard paste by default (handles spaces + special chars).
        Falls back to typewrite for simple ASCII.
        """
        import pyautogui
        loop = asyncio.get_event_loop()
        try:
            if use_clipboard:
                import pyperclip
                await loop.run_in_executor(None, pyperclip.copy, text)
                await asyncio.sleep(0.1)
                await loop.run_in_executor(None, lambda: pyautogui.hotkey('ctrl', 'v'))
            else:
                await loop.run_in_executor(None, lambda: pyautogui.write(text, interval=0.04))
            self._log("type_text", {"text": text[:50]})
            await asyncio.sleep(0.2)
            return True
        except Exception as e:
            logger.warning(f"[VGO] type_text failed: {e}")
            return False

    async def sleep(self, seconds: float):
        await asyncio.sleep(seconds)

    # ── Trace ─────────────────────────────────────────────────────────────────

    def _log(self, action: str, data: Dict):
        import datetime
        self._trace.append({
            "ts": datetime.datetime.now().isoformat(),
            "action": action,
            **data
        })

    def get_trace(self) -> List[Dict]:
        return list(self._trace)

    def clear_trace(self):
        self._trace.clear()
