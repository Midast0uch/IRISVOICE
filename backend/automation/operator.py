"""
Native GUI Operator - Phase 2 Implementation
Direct Python control using pyautogui and mss
"""
import asyncio
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime


@dataclass
class OperatorResult:
    """Result of an operator action"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    timestamp: str = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "data": self.data,
            "timestamp": self.timestamp
        }


class NativeGUIOperator:
    """
    Native GUI automation operator using pyautogui and mss
    Provides direct control without CLI dependency
    """
    
    def __init__(self, fail_safe: bool = True):
        self.fail_safe = fail_safe
        self._pyautogui = None
        self._mss = None
        self._initialized = False
        self._screen_size: Optional[Tuple[int, int]] = None
    
    async def initialize(self) -> OperatorResult:
        """Initialize the operator, import dependencies"""
        try:
            import pyautogui
            import mss
            
            self._pyautogui = pyautogui
            self._mss = mss.mss()
            self._initialized = True
            
            # Configure pyautogui
            self._pyautogui.FAILSAFE = self.fail_safe
            
            # Get screen size
            self._screen_size = self._pyautogui.size()
            
            return OperatorResult(
                success=True,
                message=f"Native operator initialized. Screen: {self._screen_size[0]}x{self._screen_size[1]}",
                data={"screen_size": self._screen_size}
            )
            
        except ImportError as e:
            return OperatorResult(
                success=False,
                message=f"Missing dependency: {e}. Install with: pip install pyautogui mss",
                data={"error": str(e)}
            )
        except Exception as e:
            return OperatorResult(
                success=False,
                message=f"Initialization failed: {e}",
                data={"error": str(e)}
            )
    
    async def click(self, x: Optional[int] = None, y: Optional[int] = None, 
                   description: Optional[str] = None, button: str = "left") -> OperatorResult:
        """
        Click at coordinates or find element by description
        """
        if not self._initialized:
            return OperatorResult(
                success=False,
                message="Operator not initialized"
            )
        
        try:
            if x is not None and y is not None:
                # Click at specific coordinates
                self._pyautogui.click(x, y, button=button)
                return OperatorResult(
                    success=True,
                    message=f"Clicked at ({x}, {y}) with {button} button",
                    data={"x": x, "y": y, "button": button}
                )
            elif description:
                # Try to find and click by description (requires vision in Phase 3)
                return OperatorResult(
                    success=False,
                    message=f"Element detection by description requires Phase 3 (vision model). Description: '{description}'",
                    data={"description": description}
                )
            else:
                return OperatorResult(
                    success=False,
                    message="Click requires either coordinates (x,y) or description"
                )
                
        except Exception as e:
            return OperatorResult(
                success=False,
                message=f"Click failed: {e}",
                data={"error": str(e)}
            )
    
    async def type_text(self, text: str, interval: float = 0.01) -> OperatorResult:
        """
        Type text at current cursor position
        """
        if not self._initialized:
            return OperatorResult(
                success=False,
                message="Operator not initialized"
            )
        
        try:
            self._pyautogui.typewrite(text, interval=interval)
            return OperatorResult(
                success=True,
                message=f"Typed {len(text)} characters",
                data={"text_length": len(text), "interval": interval}
            )
            
        except Exception as e:
            return OperatorResult(
                success=False,
                message=f"Type failed: {e}",
                data={"error": str(e)}
            )
    
    async def take_screenshot(self, save_path: Optional[str] = None) -> OperatorResult:
        """
        Capture screen using mss
        """
        if not self._initialized:
            return OperatorResult(
                success=False,
                message="Operator not initialized"
            )
        
        try:
            import numpy as np
            from PIL import Image
            
            # Capture with mss
            monitor = self._mss.monitors[0]  # Full screen
            screenshot = self._mss.grab(monitor)
            
            # Convert to PIL Image
            img = Image.frombytes(
                "RGB", 
                (screenshot.width, screenshot.height), 
                screenshot.rgb
            )
            
            # Save if path provided
            if save_path:
                img.save(save_path)
                return OperatorResult(
                    success=True,
                    message=f"Screenshot saved to {save_path}",
                    data={
                        "path": save_path,
                        "size": (screenshot.width, screenshot.height)
                    }
                )
            else:
                # Return as base64 for API use
                import io
                import base64
                buffer = io.BytesIO()
                img.save(buffer, format="PNG")
                img_base64 = base64.b64encode(buffer.getvalue()).decode()
                
                return OperatorResult(
                    success=True,
                    message="Screenshot captured (base64)",
                    data={
                        "base64": img_base64[:100] + "...",  # Truncated for display
                        "size": (screenshot.width, screenshot.height),
                        "format": "PNG"
                    }
                )
                
        except ImportError as e:
            return OperatorResult(
                success=False,
                message=f"Missing dependency: {e}. Install with: pip install Pillow numpy",
                data={"error": str(e)}
            )
        except Exception as e:
            return OperatorResult(
                success=False,
                message=f"Screenshot failed: {e}",
                data={"error": str(e)}
            )
    
    async def press_key(self, key: str) -> OperatorResult:
        """Press a single key"""
        if not self._initialized:
            return OperatorResult(
                success=False,
                message="Operator not initialized"
            )
        
        try:
            self._pyautogui.press(key)
            return OperatorResult(
                success=True,
                message=f"Pressed key: {key}",
                data={"key": key}
            )
        except Exception as e:
            return OperatorResult(
                success=False,
                message=f"Key press failed: {e}",
                data={"error": str(e)}
            )
    
    async def hotkey(self, *keys: str) -> OperatorResult:
        """Press key combination (e.g., ctrl+c)"""
        if not self._initialized:
            return OperatorResult(
                success=False,
                message="Operator not initialized"
            )
        
        try:
            self._pyautogui.hotkey(*keys)
            return OperatorResult(
                success=True,
                message=f"Pressed hotkey: {'+'.join(keys)}",
                data={"keys": list(keys)}
            )
        except Exception as e:
            return OperatorResult(
                success=False,
                message=f"Hotkey failed: {e}",
                data={"error": str(e)}
            )
    
    async def move_to(self, x: int, y: int, duration: float = 0.5) -> OperatorResult:
        """Move mouse to coordinates"""
        if not self._initialized:
            return OperatorResult(
                success=False,
                message="Operator not initialized"
            )
        
        try:
            self._pyautogui.moveTo(x, y, duration=duration)
            return OperatorResult(
                success=True,
                message=f"Moved mouse to ({x}, {y})",
                data={"x": x, "y": y, "duration": duration}
            )
        except Exception as e:
            return OperatorResult(
                success=False,
                message=f"Move failed: {e}",
                data={"error": str(e)}
            )
    
    async def get_mouse_position(self) -> OperatorResult:
        """Get current mouse position"""
        if not self._initialized:
            return OperatorResult(
                success=False,
                message="Operator not initialized"
            )
        
        try:
            x, y = self._pyautogui.position()
            return OperatorResult(
                success=True,
                message=f"Mouse position: ({x}, {y})",
                data={"x": x, "y": y}
            )
        except Exception as e:
            return OperatorResult(
                success=False,
                message=f"Failed to get position: {e}",
                data={"error": str(e)}
            )
    
    def is_initialized(self) -> bool:
        return self._initialized
    
    async def shutdown(self):
        """Cleanup resources"""
        if self._mss:
            self._mss.close()
        self._initialized = False
