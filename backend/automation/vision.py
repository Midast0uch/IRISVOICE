"""
Vision Model Integration - Phase 3
UI-TARS/Seed-VL vision model for GUI element detection
"""
import asyncio
import base64
import json
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum


class VisionProvider(Enum):
    ANTHROPIC = "anthropic"
    VOLCENGINE = "volcengine"
    LOCAL = "local"
    MINICPM_OLLAMA = "minicpm_ollama"


@dataclass
class ElementDetection:
    """Detected GUI element"""
    description: str
    x: int
    y: int
    width: int
    height: int
    confidence: float
    element_type: str


class VisionModelClient:
    """
    Vision model client for GUI element detection
    Supports multiple providers: Anthropic, Volcengine, Local
    """
    
    def __init__(self, provider: VisionProvider = VisionProvider.MINICPM_OLLAMA, api_key: Optional[str] = None):
        self.provider = provider
        self.api_key = api_key
        self._client = None
        self._minicpm_client = None
    
    async def initialize(self) -> Dict[str, Any]:
        """Initialize vision model client"""
        try:
            if self.provider == VisionProvider.MINICPM_OLLAMA:
                try:
                    from backend.vision import MiniCPMClient
                    self._minicpm_client = MiniCPMClient()
                    if self._minicpm_client.check_availability():
                        return {"success": True, "provider": "minicpm_ollama"}
                    else:
                        return {
                            "success": False,
                            "error": "MiniCPM-o not available. Run: ollama pull openbmb/minicpm-o4.5"
                        }
                except ImportError:
                    return {"success": False, "error": "Vision module not available"}

            elif self.provider == VisionProvider.ANTHROPIC:
                try:
                    import anthropic
                    self._client = anthropic.Anthropic(api_key=self.api_key)
                    return {"success": True, "provider": "anthropic"}
                except ImportError:
                    return {"success": False, "error": "Install anthropic: pip install anthropic"}
            
            elif self.provider == VisionProvider.VOLCENGINE:
                return {"success": False, "error": "Volcengine SDK not yet implemented"}
            
            elif self.provider == VisionProvider.LOCAL:
                return {"success": False, "error": "Local model not yet implemented"}
            
            return {"success": False, "error": f"Unknown provider: {self.provider}"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def detect_element(self, screenshot_base64: str, description: str) -> Optional[ElementDetection]:
        """
        Detect element by description in screenshot
        Returns element coordinates or None if not found
        """
        try:
            if self.provider == VisionProvider.MINICPM_OLLAMA and self._minicpm_client:
                return await self._detect_with_minicpm(screenshot_base64, description)
            elif self.provider == VisionProvider.ANTHROPIC and self._client:
                return await self._detect_with_anthropic(screenshot_base64, description)
            return None
        except Exception as e:
            print(f"[VisionModel] Detection error: {e}")
            return None
    
    async def _detect_with_anthropic(self, screenshot_base64: str, description: str) -> Optional[ElementDetection]:
        """Use Claude Vision to detect element"""
        prompt = f"""Find the UI element described as "{description}" in this screenshot.
        Return ONLY a JSON object with:
        - found: boolean
        - x: center x coordinate
        - y: center y coordinate  
        - width: element width
        - height: element height
        - confidence: 0.0 to 1.0
        - element_type: button/input/text/icon/etc
        
        Example: {{"found": true, "x": 500, "y": 300, "width": 100, "height": 40, "confidence": 0.95, "element_type": "button"}}"""
        
        try:
            response = self._client.messages.create(
                model="claude-3-opus-20240229",
                max_tokens=1000,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": screenshot_base64}},
                        {"type": "text", "text": prompt}
                    ]
                }]
            )
            
            # Parse JSON from response
            text = response.content[0].text
            # Extract JSON from markdown code blocks if present
            if "```json" in text:
                json_str = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                json_str = text.split("```")[1].split("```")[0].strip()
            else:
                json_str = text.strip()
            
            result = json.loads(json_str)
            
            if result.get("found"):
                return ElementDetection(
                    description=description,
                    x=result["x"],
                    y=result["y"],
                    width=result.get("width", 50),
                    height=result.get("height", 30),
                    confidence=result.get("confidence", 0.8),
                    element_type=result.get("element_type", "unknown")
                )
            return None
            
        except Exception as e:
            print(f"[VisionModel] Anthropic error: {e}")
            return None
    
    async def _detect_with_minicpm(self, screenshot_base64: str, description: str) -> Optional[ElementDetection]:
        """Use MiniCPM-o via Ollama for local element detection"""
        try:
            import asyncio
            result = await asyncio.to_thread(
                self._minicpm_client.detect_gui_element,
                screenshot_base64,
                description
            )
            
            if result and result.get("found"):
                return ElementDetection(
                    description=description,
                    x=result.get("x", 0),
                    y=result.get("y", 0),
                    width=result.get("width", 50),
                    height=result.get("height", 30),
                    confidence=result.get("confidence", 0.8),
                    element_type=result.get("element_type", "unknown")
                )
            return None
            
        except Exception as e:
            print(f"[VisionModel] MiniCPM detection error: {e}")
            return None

    async def analyze_screen(self, screenshot_base64: str, instruction: str) -> Dict[str, Any]:
        """
        Analyze screen and suggest next action
        Returns action dict with type and parameters
        """
        # MiniCPM-o provider
        if self.provider == VisionProvider.MINICPM_OLLAMA and self._minicpm_client:
            try:
                import asyncio
                result = await asyncio.to_thread(
                    self._minicpm_client.analyze_screen_for_action,
                    screenshot_base64,
                    instruction
                )
                return result
            except Exception as e:
                return {"action": "error", "message": str(e)}

        # Anthropic provider
        if not self._client:
            return {"action": "error", "message": "Vision client not initialized"}
        
        prompt = f"""Given the current screenshot and instruction "{instruction}", what should be the next action?
        Return a JSON object with:
        - action: "click" | "type" | "scroll" | "wait" | "complete"
        - target: description of what to interact with
        - text: text to type (if action is type)
        - coordinates: {{"x": int, "y": int}} (if action is click)
        - reason: brief explanation
        
        Example: {{"action": "click", "target": "Submit button", "coordinates": {{"x": 500, "y": 400}}, "reason": "Need to submit form"}}"""
        
        try:
            response = self._client.messages.create(
                model="claude-3-opus-20240229",
                max_tokens=1000,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": screenshot_base64}},
                        {"type": "text", "text": prompt}
                    ]
                }]
            )
            
            text = response.content[0].text
            if "```json" in text:
                json_str = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                json_str = text.split("```")[1].split("```")[0].strip()
            else:
                json_str = text.strip()
            
            return json.loads(json_str)
            
        except Exception as e:
            return {"action": "error", "message": str(e)}


class GUIAgent:
    """
    High-level GUI agent combining vision model with native operator
    """
    
    def __init__(self, vision_client: VisionModelClient, operator=None):
        self.vision = vision_client
        self.operator = operator
        self.action_history: List[Dict] = []
    
    async def execute_instruction(self, instruction: str, max_steps: int = 25) -> Dict[str, Any]:
        """
        Execute multi-step instruction using vision + operator
        """
        steps = []
        
        for step_num in range(max_steps):
            # Take screenshot
            if not self.operator:
                return {"success": False, "error": "Operator not available", "steps": steps}
            
            screenshot_result = await self.operator.take_screenshot()
            if not screenshot_result.success:
                return {"success": False, "error": "Screenshot failed", "steps": steps}
            
            # Get base64 image
            img_data = screenshot_result.data.get("base64", "")
            if not img_data:
                return {"success": False, "error": "No screenshot data", "steps": steps}
            
            # Analyze with vision model
            action = await self.vision.analyze_screen(img_data, instruction)
            
            if action.get("action") == "complete":
                steps.append({"step": step_num, "action": action, "status": "complete"})
                return {"success": True, "steps": steps, "message": "Task completed"}
            
            if action.get("action") == "error":
                steps.append({"step": step_num, "action": action, "status": "error"})
                return {"success": False, "error": action.get("message"), "steps": steps}
            
            # Execute action
            if action.get("action") == "click":
                coords = action.get("coordinates", {})
                result = await self.operator.click(coords.get("x"), coords.get("y"))
            elif action.get("action") == "type":
                result = await self.operator.type_text(action.get("text", ""))
            else:
                result = None
            
            steps.append({
                "step": step_num,
                "action": action,
                "result": result.to_dict() if result else None,
                "status": "executed"
            })
            
            await asyncio.sleep(0.5)
        
        return {"success": False, "error": "Max steps reached", "steps": steps}
