"""
MiniCPM-o 4.5 Client — Local multimodal inference via Ollama API.

Provides vision understanding, screen analysis, and GUI element detection
using the MiniCPM-o 4.5 model running locally through Ollama.

Supports:
  - Single image analysis (screenshots, photos)
  - Multi-image comparison
  - GUI element detection for automation
  - Screen-aware conversation (text + image → response)
  - Structured action planning for GUI agent
"""
import json
import time
from typing import Any, Dict, List, Optional

import requests


class MiniCPMClient:
    """
    Client for MiniCPM-o 4.5 running on Ollama.

    Uses the Ollama REST API (/api/generate, /api/chat) to send
    text + image inputs and receive text responses.
    """

    _instance: Optional["MiniCPMClient"] = None
    _initialized: bool = False

    # Ollama defaults
    DEFAULT_ENDPOINT = "http://localhost:11434"
    DEFAULT_MODEL = "minicpm-o4.5"

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        endpoint: Optional[str] = None,
        model: Optional[str] = None,
    ):
        if MiniCPMClient._initialized:
            return

        self.endpoint = endpoint or self.DEFAULT_ENDPOINT
        self.model = model or self.DEFAULT_MODEL
        self.timeout = 120  # Vision inference can be slow on first call
        self._is_available: Optional[bool] = None
        self._last_check: float = 0
        self._check_interval: float = 30  # re-check availability every 30s

        # Performance tracking
        self._total_requests = 0
        self._total_latency = 0.0

        MiniCPMClient._initialized = True

    # ────────────────────────────────────────────────────────────
    # Health & Connection
    # ────────────────────────────────────────────────────────────

    def check_availability(self, force: bool = False) -> bool:
        """
        Check if Ollama is running and the model is pulled.
        Caches result for `_check_interval` seconds.
        """
        now = time.time()
        if not force and self._is_available is not None:
            if (now - self._last_check) < self._check_interval:
                return self._is_available

        try:
            # Check Ollama is running
            r = requests.get(f"{self.endpoint}/api/tags", timeout=5)
            r.raise_for_status()
            data = r.json()

            # Check if our model is available
            models = [m.get("name", "") for m in data.get("models", [])]
            # Ollama model names may include tag, e.g. "minicpm-o4.5:latest"
            available = any(
                self.model in name or name.startswith(self.model)
                for name in models
            )

            if not available:
                # Also check with openbmb/ prefix
                available = any(
                    f"openbmb/{self.model}" in name
                    for name in models
                )

            self._is_available = available
            self._last_check = now

            if not available:
                print(
                    f"[MiniCPM] Model '{self.model}' not found. "
                    f"Available: {models}. "
                    f"Run: ollama pull openbmb/minicpm-o4.5"
                )

            return available

        except requests.ConnectionError:
            print(f"[MiniCPM] Ollama not reachable at {self.endpoint}")
            self._is_available = False
            self._last_check = now
            return False
        except Exception as e:
            print(f"[MiniCPM] Health check error: {e}")
            self._is_available = False
            self._last_check = now
            return False

    # ────────────────────────────────────────────────────────────
    # Core API Methods
    # ────────────────────────────────────────────────────────────

    def generate(
        self,
        prompt: str,
        images: Optional[List[str]] = None,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """
        Send a generate request to Ollama with optional images.

        Args:
            prompt: Text prompt
            images: List of base64-encoded image strings
            system: System prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            stream: Whether to stream the response

        Returns:
            Dict with 'response' text and metadata
        """
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        if images:
            payload["images"] = images

        if system:
            payload["system"] = system

        t0 = time.time()
        try:
            r = requests.post(
                f"{self.endpoint}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            result = r.json()
            elapsed = time.time() - t0

            self._total_requests += 1
            self._total_latency += elapsed

            print(
                f"[MiniCPM] Generate completed in {elapsed:.1f}s "
                f"({result.get('eval_count', '?')} tokens)"
            )

            return {
                "response": result.get("response", ""),
                "done": result.get("done", True),
                "total_duration": result.get("total_duration"),
                "eval_count": result.get("eval_count"),
                "latency_s": elapsed,
            }

        except requests.Timeout:
            print(f"[MiniCPM] Request timed out after {self.timeout}s")
            return {"response": "", "error": "timeout"}
        except requests.ConnectionError:
            print(f"[MiniCPM] Cannot connect to {self.endpoint}")
            self._is_available = False
            return {"response": "", "error": "connection_error"}
        except Exception as e:
            print(f"[MiniCPM] Generate error: {e}")
            return {"response": "", "error": str(e)}

    def chat(
        self,
        messages: List[Dict[str, Any]],
        images: Optional[List[str]] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> Dict[str, Any]:
        """
        Send a chat request (multi-turn conversation) to Ollama.

        Args:
            messages: List of {role, content} dicts
            images: Images to attach to the last user message
            temperature: Sampling temperature
            max_tokens: Max generation tokens

        Returns:
            Dict with assistant response and metadata
        """
        # Inject images into the last user message if provided
        formatted_messages = []
        for i, msg in enumerate(messages):
            entry: Dict[str, Any] = {
                "role": msg["role"],
                "content": msg["content"],
            }
            # Attach images to the last user message
            if images and msg["role"] == "user" and i == len(messages) - 1:
                entry["images"] = images
            formatted_messages.append(entry)

        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        t0 = time.time()
        try:
            r = requests.post(
                f"{self.endpoint}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            result = r.json()
            elapsed = time.time() - t0

            self._total_requests += 1
            self._total_latency += elapsed

            response_text = (
                result.get("message", {}).get("content", "")
            )

            return {
                "response": response_text,
                "done": result.get("done", True),
                "latency_s": elapsed,
            }

        except Exception as e:
            print(f"[MiniCPM] Chat error: {e}")
            return {"response": "", "error": str(e)}

    # ────────────────────────────────────────────────────────────
    # High-Level Vision Methods
    # ────────────────────────────────────────────────────────────

    def describe_screen(
        self,
        screenshot_b64: str,
        question: Optional[str] = None,
    ) -> str:
        """
        Describe what's on the screen.

        Args:
            screenshot_b64: Base64-encoded screenshot PNG
            question: Optional specific question about the screen

        Returns:
            Text description of the screen contents
        """
        prompt = question or (
            "Describe what you see on this screen. Be concise but thorough. "
            "Mention any important UI elements, text, notifications, or content."
        )

        result = self.generate(
            prompt=prompt,
            images=[screenshot_b64],
            system=(
                "You are IRIS, an intelligent AI assistant with vision capabilities. "
                "You can see the user's screen and describe what's happening. "
                "Be helpful, concise, and natural in your descriptions."
            ),
            temperature=0.5,
        )

        return result.get("response", "I couldn't analyze the screen.")

    def detect_gui_element(
        self,
        screenshot_b64: str,
        description: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Find a specific GUI element in a screenshot.

        Args:
            screenshot_b64: Base64-encoded screenshot
            description: Natural language description of the element to find

        Returns:
            Dict with {found, x, y, width, height, confidence, element_type}
            or None if not found
        """
        prompt = (
            f'Find the UI element described as "{description}" in this screenshot.\n'
            "Return ONLY a JSON object with these fields:\n"
            "- found: boolean\n"
            "- x: center x coordinate (pixels)\n"
            "- y: center y coordinate (pixels)\n"
            "- width: element width\n"
            "- height: element height\n"
            "- confidence: 0.0 to 1.0\n"
            "- element_type: button/input/text/icon/link/menu/etc\n\n"
            "If you cannot find the element, return: {\"found\": false}\n"
            "Return ONLY valid JSON, no markdown, no explanation."
        )

        result = self.generate(
            prompt=prompt,
            images=[screenshot_b64],
            temperature=0.1,  # Low temperature for structured output
            max_tokens=256,
        )

        response_text = result.get("response", "")
        return self._parse_json_response(response_text)

    def analyze_screen_for_action(
        self,
        screenshot_b64: str,
        instruction: str,
        history: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        Analyze screen and determine the next action for GUI automation.

        Args:
            screenshot_b64: Current screenshot
            instruction: What the user wants to accomplish
            history: Previous actions taken (for context)

        Returns:
            Dict with action plan: {action, target, coordinates, text, reason}
        """
        history_context = ""
        if history:
            steps = [
                f"  Step {h['step']}: {h.get('action', {}).get('action', '?')} "
                f"- {h.get('action', {}).get('reason', '?')}"
                for h in history[-5:]  # Last 5 steps
            ]
            history_context = (
                "\nPrevious actions taken:\n" + "\n".join(steps) + "\n"
            )

        prompt = (
            f'Task: "{instruction}"\n'
            f"{history_context}\n"
            "Looking at the current screenshot, what should be the next action?\n"
            "Return ONLY a JSON object with:\n"
            '- action: "click" | "type" | "scroll" | "press_key" | "wait" | "complete"\n'
            "- target: description of what to interact with\n"
            "- text: text to type (if action is type)\n"
            "- key: key to press (if action is press_key)\n"
            '- coordinates: {"x": int, "y": int} (if action is click)\n'
            "- reason: brief explanation of why this action\n\n"
            'If the task is already done, use action "complete".\n'
            "Return ONLY valid JSON."
        )

        result = self.generate(
            prompt=prompt,
            images=[screenshot_b64],
            system=(
                "You are a GUI automation agent. Analyze screenshots and determine "
                "the precise next action to accomplish the user's task. "
                "Be exact with coordinates. Only return JSON."
            ),
            temperature=0.2,
            max_tokens=512,
        )

        parsed = self._parse_json_response(result.get("response", ""))
        if parsed:
            return parsed
        return {"action": "error", "reason": "Failed to parse vision model response"}

    def screen_aware_response(
        self,
        user_text: str,
        screenshot_b64: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """
        Generate a conversational response that's aware of the screen content.

        This is the core method for "IRIS can see" — the user asks something
        and IRIS responds with context from what's on screen.

        Args:
            user_text: What the user said/asked
            screenshot_b64: Current screen state
            conversation_history: Previous conversation turns

        Returns:
            AI response text
        """
        messages = []

        # System prompt
        messages.append({
            "role": "system",
            "content": (
                "You are IRIS, an intelligent AI desktop assistant with vision. "
                "You can see the user's screen in real-time. "
                "When the user asks questions, consider both their words AND "
                "what you can see on their screen to give the most helpful response. "
                "Be conversational, concise, and helpful. "
                "If the user's question relates to what's on screen, reference it naturally. "
                "If the screen context isn't relevant to their question, just answer normally."
            ),
        })

        # Add conversation history
        if conversation_history:
            for msg in conversation_history[-6:]:  # Last 6 turns
                messages.append(msg)

        # Add current user message
        messages.append({
            "role": "user",
            "content": user_text,
        })

        result = self.chat(
            messages=messages,
            images=[screenshot_b64],
            temperature=0.7,
            max_tokens=1024,
        )

        return result.get("response", "I'm having trouble responding right now.")

    def detect_screen_context(
        self,
        screenshot_b64: str,
    ) -> Dict[str, Any]:
        """
        Analyze the current screen to understand context for proactive assistance.

        Returns structured information about:
        - Active application
        - What the user appears to be doing
        - Any notable items (errors, notifications, dialogs)
        - Suggested help topics
        """
        prompt = (
            "Analyze this screenshot and provide a brief JSON summary:\n"
            "{\n"
            '  "active_app": "name of the active application",\n'
            '  "activity": "what the user appears to be doing",\n'
            '  "notable_items": ["list of any errors, notifications, dialogs"],\n'
            '  "needs_help": true/false (does the user seem stuck or confused?),\n'
            '  "suggestion": "optional suggestion for how to help"\n'
            "}\n"
            "Return ONLY valid JSON."
        )

        result = self.generate(
            prompt=prompt,
            images=[screenshot_b64],
            temperature=0.3,
            max_tokens=512,
        )

        parsed = self._parse_json_response(result.get("response", ""))
        return parsed or {
            "active_app": "unknown",
            "activity": "unknown",
            "notable_items": [],
            "needs_help": False,
        }

    # ────────────────────────────────────────────────────────────
    # Utilities
    # ────────────────────────────────────────────────────────────

    def _parse_json_response(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse JSON from model response, handling markdown code blocks."""
        if not text:
            return None

        # Strip markdown code fences
        cleaned = text.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0].strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to find JSON object in the text
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(cleaned[start:end])
                except json.JSONDecodeError:
                    pass

        print(f"[MiniCPM] Failed to parse JSON from response: {text[:200]}")
        return None

    def update_config(self, **kwargs):
        """Update client configuration."""
        if "endpoint" in kwargs:
            self.endpoint = kwargs["endpoint"]
        if "model" in kwargs:
            self.model = kwargs["model"]
        if "timeout" in kwargs:
            self.timeout = kwargs["timeout"]
        # Reset availability cache on config change
        self._is_available = None
        self._last_check = 0

    def get_status(self) -> Dict[str, Any]:
        """Get client status and performance statistics."""
        avg_latency = (
            self._total_latency / self._total_requests
            if self._total_requests > 0
            else 0
        )
        return {
            "endpoint": self.endpoint,
            "model": self.model,
            "available": self._is_available,
            "total_requests": self._total_requests,
            "avg_latency_s": round(avg_latency, 2),
        }


def get_minicpm_client() -> MiniCPMClient:
    """Get the singleton MiniCPMClient instance."""
    return MiniCPMClient()
