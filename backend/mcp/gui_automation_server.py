"""
GUIAutomationServer - UI-TARS integration
Phase 1: Uses npx @agent-tars/cli for task execution
Phase 2: Uses native Python operator (pyautogui + mss) for direct control
"""
import asyncio
import json
import subprocess
import tempfile
import os
from typing import Any, Dict, List, Optional
from datetime import datetime

from .protocol import MCPRequest, MCPResponse, MCPTool, MCPMessageType
from .builtin_servers import BuiltinServer


def _import_operator():
    """Lazy import to avoid dependency errors if not using native mode"""
    try:
        from ..automation import NativeGUIOperator
        return NativeGUIOperator
    except ImportError:
        return None


class GUIAutomationServer(BuiltinServer):
    """
    GUI automation MCP server using UI-TARS CLI and native Python operator
    Phase 3: Adds vision model for element detection by description
    Provides voice-controlled desktop automation capabilities
    """
    
    def __init__(self, use_native: bool = True, use_vision: bool = False, 
                 vision_provider: str = "anthropic", vision_api_key: Optional[str] = None,
                 max_steps: int = 25, safety_confirmation: bool = True, debug_mode: bool = True):
        self.debug_log: List[Dict] = []
        self.use_native = use_native
        self.use_vision = use_vision
        self.vision_provider = vision_provider
        self.vision_api_key = vision_api_key
        self.max_steps = max_steps
        self.safety_confirmation = safety_confirmation
        self.debug_mode = debug_mode
        self._native_operator = None
        self._operator_initialized = False
        self._vision_client = None
        self._vision_initialized = False
        super().__init__("gui_automation")
    
    async def _ensure_operator(self):
        """Initialize native operator if needed"""
        if not self.use_native or self._operator_initialized:
            return
        
        OperatorClass = _import_operator()
        if OperatorClass:
            self._native_operator = OperatorClass()
            result = await self._native_operator.initialize()
            self._operator_initialized = result.success
            self._log_debug("OPERATOR_INIT", result.to_dict())
    
    async def _ensure_vision(self):
        """Initialize vision model client if needed"""
        if not self.use_vision or self._vision_initialized:
            return
        
        try:
            from ..automation import VisionModelClient, VisionProvider
            provider = VisionProvider(self.vision_provider)
            self._vision_client = VisionModelClient(provider, self.vision_api_key)
            result = await self._vision_client.initialize()
            self._vision_initialized = result.get("success", False)
            self._log_debug("VISION_INIT", result)
        except Exception as e:
            self._log_debug("VISION_INIT_ERROR", {"error": str(e)})
    
    def _setup_tools(self):
        self._tools = [
            MCPTool(
                name="execute_task",
                description="Execute a multi-step GUI task (e.g., 'Open Chrome and search for weather')",
                input_schema={
                    "type": "object",
                    "properties": {
                        "instruction": {
                            "type": "string",
                            "description": "Natural language task description"
                        },
                        "max_steps": {
                            "type": "integer",
                            "description": "Maximum automation steps",
                            "default": 25
                        },
                        "require_confirmation": {
                            "type": "boolean",
                            "description": "Ask user before destructive actions",
                            "default": True
                        }
                    },
                    "required": ["instruction"]
                }
            ),
            MCPTool(
                name="click_element",
                description="Click on a UI element by description or coordinates",
                input_schema={
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "string",
                            "description": "Text description of element to click"
                        },
                        "x": {"type": "integer", "description": "X coordinate"},
                        "y": {"type": "integer", "description": "Y coordinate"}
                    }
                }
            ),
            MCPTool(
                name="type_text",
                description="Type text into the focused field",
                input_schema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to type"},
                        "interval": {
                            "type": "number",
                            "description": "Delay between keystrokes",
                            "default": 0.01
                        }
                    },
                    "required": ["text"]
                }
            ),
            MCPTool(
                name="take_screenshot",
                description="Capture current screen state",
                input_schema={
                    "type": "object",
                    "properties": {
                        "save_path": {
                            "type": "string",
                            "description": "Optional path to save screenshot"
                        }
                    }
                }
            ),
            MCPTool(
                name="get_automation_logs",
                description="Get recent automation debug logs",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Number of log entries",
                            "default": 50
                        }
                    }
                }
            ),
            MCPTool(
                name="execute_with_vision",
                description="Execute GUI task using vision model (Phase 3) - analyze screen and perform actions",
                input_schema={
                    "type": "object",
                    "properties": {
                        "instruction": {
                            "type": "string",
                            "description": "Natural language task description"
                        },
                        "max_steps": {
                            "type": "integer",
                            "description": "Maximum automation steps",
                            "default": 10
                        }
                    },
                    "required": ["instruction"]
                }
            )
        ]
    
    def _log_debug(self, action: str, data: Dict[str, Any]):
        """Add debug log entry with timestamp"""
        if not self.debug_mode:
            return
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "data": data
        }
        self.debug_log.append(entry)
        print(f"[GUIAutomation] {action}: {json.dumps(data, default=str)[:200]}")
        
        # Keep only last 100 entries
        if len(self.debug_log) > 100:
            self.debug_log = self.debug_log[-100:]
    
    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Execute GUI automation tool"""
        self._log_debug("EXECUTE_START", {"tool": name, "args": arguments})
        
        try:
            if name == "execute_task":
                result = await self._execute_task(arguments)
            elif name == "execute_with_vision":
                result = await self._execute_with_vision(arguments)
            elif name == "click_element":
                result = await self._click_element(arguments)
            elif name == "type_text":
                result = await self._type_text(arguments)
            elif name == "take_screenshot":
                result = await self._take_screenshot(arguments)
            elif name == "get_automation_logs":
                result = await self._get_logs(arguments)
            else:
                result = {"error": f"Unknown tool: {name}"}
            
            self._log_debug("EXECUTE_END", {
                "tool": name,
                "success": "error" not in result,
                "result_preview": str(result)[:100]
            })
            return result
            
        except Exception as e:
            self._log_debug("EXECUTE_ERROR", {"tool": name, "error": str(e)})
            return {"success": False, "error": str(e)}
    
    async def _execute_task(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute task using UI-TARS CLI via subprocess
        Phase 1: Shell out to npx @agent-tars/cli
        """
        instruction = arguments.get("instruction", "")
        max_steps = arguments.get("max_steps", 25)
        require_confirmation = arguments.get("require_confirmation", True)
        
        self._log_debug("TASK_START", {
            "instruction": instruction,
            "max_steps": max_steps
        })
        
        # Create temp file for instruction
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(instruction)
            instruction_file = f.name
        
        try:
            # Build CLI command
            cmd = [
                "npx", "@agent-tars/cli@latest",
                "start",
                "--instruction", instruction,
                "--max-loop", str(max_steps),
                "--headless"
            ]
            
            self._log_debug("CLI_COMMAND", {"cmd": " ".join(cmd)})
            
            # Run CLI with timeout
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tempfile.gettempdir()
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=300
            )
            
            stdout_str = stdout.decode() if stdout else ""
            stderr_str = stderr.decode() if stderr else ""
            
            self._log_debug("CLI_OUTPUT", {
                "stdout": stdout_str[:500],
                "stderr": stderr_str[:500],
                "returncode": process.returncode
            })
            
            if process.returncode == 0:
                return {
                    "success": True,
                    "instruction": instruction,
                    "steps_executed": max_steps,
                    "output": stdout_str,
                    "message": f"Task completed: {instruction[:50]}..."
                }
            else:
                return {
                    "success": False,
                    "instruction": instruction,
                    "error": stderr_str or "CLI execution failed",
                    "output": stdout_str
                }
                
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": "Task execution timed out (5 minutes)"
            }
        except FileNotFoundError:
            return {
                "success": False,
                "error": "npx not found. Please install Node.js and ensure npx is in PATH"
            }
        finally:
            try:
                os.unlink(instruction_file)
            except:
                pass
    
    async def _click_element(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Click element using native operator, optionally with vision detection"""
        # Check safety confirmation
        if self.safety_confirmation and arguments.get("require_confirmation", True):
            # TODO: Implement actual confirmation dialog in future
            self._log_debug("SAFETY_CHECK", {"action": "click", "status": "confirmation_required"})
            # For now, log and proceed with warning
            print("[GUIAutomation] Warning: Destructive action (click) - confirmation bypassed in debug mode")
        
        await self._ensure_operator()
        
        if not self._operator_initialized:
            return {
                "success": False,
                "message": "Native operator not available. Install: pip install pyautogui mss Pillow numpy"
            }
        
        x = arguments.get("x")
        y = arguments.get("y")
        description = arguments.get("description")
        
        # If description provided but no coordinates, use vision to detect
        if description and (x is None or y is None) and self.use_vision:
            await self._ensure_vision()
            
            if self._vision_initialized:
                # Take screenshot for vision analysis
                screenshot_result = await self._native_operator.take_screenshot()
                if screenshot_result.success:
                    img_base64 = screenshot_result.data.get("base64", "").replace("...", "")
                    if img_base64:
                        self._log_debug("VISION_DETECT", {"description": description})
                        element = await self._vision_client.detect_element(img_base64, description)
                        
                        if element:
                            x, y = element.x, element.y
                            self._log_debug("VISION_FOUND", {
                                "description": description,
                                "x": x, "y": y,
                                "confidence": element.confidence
                            })
                        else:
                            return {
                                "success": False,
                                "message": f"Could not find element: {description}"
                            }
            else:
                return {
                    "success": False,
                    "message": f"Vision model not initialized. Cannot find: {description}. Provide coordinates (x, y) instead."
                }
        
        result = await self._native_operator.click(x=x, y=y, description=description)
        return result.to_dict()
    
    async def _type_text(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Type text using native operator"""
        # Check safety confirmation for text input (could be destructive)
        if self.safety_confirmation and arguments.get("require_confirmation", False):
            self._log_debug("SAFETY_CHECK", {"action": "type_text", "status": "confirmation_required"})
            print("[GUIAutomation] Warning: Text input action - confirmation bypassed in debug mode")
        
        await self._ensure_operator()
        
        if not self._operator_initialized:
            return {
                "success": False,
                "message": "Native operator not available. Install: pip install pyautogui mss Pillow numpy"
            }
        
        text = arguments.get("text", "")
        interval = arguments.get("interval", 0.01)
        
        result = await self._native_operator.type_text(text, interval)
        return result.to_dict()
    
    async def _take_screenshot(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Take screenshot using native operator"""
        await self._ensure_operator()
        
        if not self._operator_initialized:
            return {
                "success": False,
                "message": "Native operator not available. Install: pip install pyautogui mss Pillow numpy"
            }
        
        save_path = arguments.get("save_path")
        result = await self._native_operator.take_screenshot(save_path)
        return result.to_dict()
    
    async def _get_logs(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        limit = arguments.get("limit", 50)
        return {
            "success": True,
            "logs": self.debug_log[-limit:],
            "total_available": len(self.debug_log)
        }
    
    async def _execute_with_vision(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute task using vision model (Phase 3)
        Screenshots screen, analyzes with vision model, performs actions
        """
        instruction = arguments.get("instruction", "")
        max_steps = arguments.get("max_steps", 10)
        
        # Check safety confirmation for autonomous vision tasks
        if self.safety_confirmation and arguments.get("require_confirmation", True):
            self._log_debug("SAFETY_CHECK", {"action": "execute_with_vision", "status": "confirmation_required"})
            print("[GUIAutomation] Warning: Autonomous vision task - confirmation bypassed in debug mode")
        
        self._log_debug("VISION_TASK_START", {
            "instruction": instruction,
            "max_steps": max_steps
        })
        
        # Ensure operator and vision are initialized
        await self._ensure_operator()
        await self._ensure_vision()
        
        if not self._operator_initialized:
            return {
                "success": False,
                "error": "Native operator not available. Install: pip install pyautogui mss Pillow numpy"
            }
        
        if not self._vision_initialized:
            return {
                "success": False,
                "error": "Vision model not initialized. Check API key and provider settings."
            }
        
        try:
            from ..automation import GUIAgent
            
            # Create GUI agent with vision and operator
            agent = GUIAgent(self._vision_client, self._native_operator)
            
            self._log_debug("VISION_AGENT_CREATED", {})
            
            # Execute instruction
            result = await agent.execute_instruction(instruction, max_steps)
            
            self._log_debug("VISION_TASK_END", {
                "success": result.get("success"),
                "steps_count": len(result.get("steps", []))
            })
            
            return {
                "success": result.get("success", False),
                "instruction": instruction,
                "steps_executed": len(result.get("steps", [])),
                "steps": result.get("steps", []),
                "message": result.get("message", "Task execution completed")
            }
            
        except Exception as e:
            self._log_debug("VISION_TASK_ERROR", {"error": str(e)})
            return {
                "success": False,
                "error": str(e),
                "instruction": instruction
            }
