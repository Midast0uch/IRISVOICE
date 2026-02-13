"""
OmniConversationManager — Vision-aware conversation system.

Extends the existing AIConversationManager with visual context:
when available, screenshots are sent alongside text to MiniCPM-o 4.5
so IRIS can "see" what the user sees and give contextually relevant responses.

Falls back gracefully to text-only LM Studio when vision is unavailable.
"""
import os
from typing import Any, Dict, List, Optional

from .personality import get_personality_engine
from .memory import get_conversation_memory


class OmniConversationManager:
    """
    Multimodal conversation manager — text + vision via MiniCPM-o (Ollama).

    Pipeline:
        1. User speaks → STT gives transcript
        2. Screen is captured → base64 screenshot
        3. transcript + screenshot → MiniCPM-o → response
        4. Response → TTS → audio output

    Graceful fallback:
        - If MiniCPM-o is unavailable → falls back to LM Studio (text-only)
        - If screenshot is unavailable → sends text-only to MiniCPM-o
    """

    DEFAULT_OLLAMA_ENDPOINT = "http://localhost:11434"
    DEFAULT_MODEL = "minicpm-o4.5"

    def __init__(self):
        self.config: Dict[str, Any] = {
            "ollama_endpoint": os.getenv(
                "OLLAMA_ENDPOINT", self.DEFAULT_OLLAMA_ENDPOINT
            ),
            "model": os.getenv("MINICPM_MODEL", self.DEFAULT_MODEL),
            "vision_enabled": True,
            "screen_context_enabled": True,  # Auto-capture screen during conversation
            "timeout": 120,
            "max_context_messages": 10,
            "temperature": 0.7,
            # Fallback to LM Studio
            "fallback_endpoint": os.getenv(
                "LM_STUDIO_ENDPOINT",
                "http://192.168.0.32:1234/v1/chat/completions",
            ),
            "fallback_model": os.getenv("LM_STUDIO_MODEL", "default"),
        }

        self.personality = get_personality_engine()
        self.memory = get_conversation_memory()

        # Lazy-loaded clients
        self._minicpm_client = None
        self._screen_capture = None

    def _get_minicpm_client(self):
        """Lazy-load MiniCPMClient."""
        if self._minicpm_client is None:
            try:
                from backend.vision import MiniCPMClient

                self._minicpm_client = MiniCPMClient(
                    endpoint=self.config.get("ollama_endpoint"),
                    model=self.config.get("model"),
                )
            except Exception as e:
                print(f"[OmniConversation] Failed to create MiniCPM client: {e}")
        return self._minicpm_client

    def _get_screen_capture(self):
        """Lazy-load ScreenCapture."""
        if self._screen_capture is None:
            try:
                from backend.vision import ScreenCapture

                self._screen_capture = ScreenCapture()
            except Exception as e:
                print(f"[OmniConversation] Failed to create screen capture: {e}")
        return self._screen_capture

    def generate_response(
        self,
        user_text: str,
        screenshot_b64: Optional[str] = None,
        force_text_only: bool = False,
    ) -> Optional[str]:
        """
        Generate a response, optionally with visual context.

        Args:
            user_text: The user's text input (from STT or typed)
            screenshot_b64: Pre-captured screenshot (base64). If None and
                            screen_context_enabled is True, will auto-capture.
            force_text_only: Skip vision even if available

        Returns:
            Response text or None on failure
        """
        if not user_text:
            return None

        # --- Try MiniCPM-o with vision ---
        if not force_text_only and self.config.get("vision_enabled", True):
            minicpm = self._get_minicpm_client()
            if minicpm and minicpm.check_availability():
                return self._generate_with_vision(user_text, screenshot_b64)

        # --- Fallback: LM Studio (text-only) ---
        print("[OmniConversation] Falling back to LM Studio text-only")
        return self._generate_with_lm_studio(user_text)

    def _generate_with_vision(
        self,
        user_text: str,
        screenshot_b64: Optional[str] = None,
    ) -> Optional[str]:
        """Generate response via MiniCPM-o with optional screen context."""
        minicpm = self._get_minicpm_client()
        if not minicpm:
            return None

        # Auto-capture screenshot if enabled and not provided
        if screenshot_b64 is None and self.config.get("screen_context_enabled", True):
            capture = self._get_screen_capture()
            if capture:
                try:
                    screenshot_b64, _ = capture.capture_base64()
                except Exception as e:
                    print(f"[OmniConversation] Screen capture failed: {e}")

        # Build conversation history
        history = self.memory.get_context_window(
            self.config.get("max_context_messages", 10)
        )

        # Add personality to system prompt
        system_prompt = self.personality.get_system_prompt()
        if screenshot_b64:
            system_prompt += (
                "\n\nYou can currently see the user's screen. "
                "If their question relates to what's visible, reference it naturally. "
                "If it's not relevant, just answer normally without forcing screen references."
            )

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})

        try:
            if screenshot_b64:
                result = minicpm.chat(
                    messages=messages,
                    images=[screenshot_b64],
                    temperature=self.config.get("temperature", 0.7),
                )
            else:
                result = minicpm.chat(
                    messages=messages,
                    temperature=self.config.get("temperature", 0.7),
                )

            response_text = result.get("response", "").strip()

            if response_text:
                # Store in memory
                self.memory.add_message(
                    "user", user_text, text_tokens=len(user_text)
                )
                self.memory.add_message(
                    "assistant", response_text, text_tokens=len(response_text)
                )
                return response_text

            print("[OmniConversation] MiniCPM returned empty response")
            return None

        except Exception as e:
            print(f"[OmniConversation] MiniCPM inference error: {e}")
            return None

    def _generate_with_lm_studio(self, user_text: str) -> Optional[str]:
        """Fallback: generate response via LM Studio (text-only)."""
        import requests as req

        system_prompt = self.personality.get_system_prompt()
        history = self.memory.get_context_window(
            self.config.get("max_context_messages", 10)
        )

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})

        endpoint = self.config.get("fallback_endpoint")
        if not endpoint:
            print("[OmniConversation] No fallback endpoint configured")
            return None

        # Ensure endpoint has the completions path
        if not endpoint.endswith("/v1/chat/completions"):
            if endpoint.endswith("/"):
                endpoint += "v1/chat/completions"
            else:
                endpoint += "/v1/chat/completions"

        payload = {
            "model": self.config.get("fallback_model", "default"),
            "messages": messages,
            "temperature": self.config.get("temperature", 0.7),
        }

        try:
            r = req.post(
                endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.config.get("timeout", 60),
            )
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"]["content"].strip()

            self.memory.add_message("user", user_text, text_tokens=len(user_text))
            self.memory.add_message("assistant", text, text_tokens=len(text))

            return text

        except Exception as e:
            print(f"[OmniConversation] LM Studio fallback error: {e}")
            return None

    def update_config(self, **kwargs):
        """Update configuration."""
        for key, value in kwargs.items():
            if key in self.config and value is not None:
                self.config[key] = value

        # Update MiniCPM client if relevant settings changed
        if self._minicpm_client:
            minicpm_updates = {}
            if "ollama_endpoint" in kwargs:
                minicpm_updates["endpoint"] = kwargs["ollama_endpoint"]
            if "model" in kwargs:
                minicpm_updates["model"] = kwargs["model"]
            if minicpm_updates:
                self._minicpm_client.update_config(**minicpm_updates)

        print(f"[OmniConversation] Config updated: {list(kwargs.keys())}")

    def get_status(self) -> Dict[str, Any]:
        """Get conversation manager status."""
        minicpm = self._get_minicpm_client()
        return {
            "vision_enabled": self.config.get("vision_enabled", False),
            "screen_context_enabled": self.config.get("screen_context_enabled", False),
            "minicpm_available": minicpm.check_availability() if minicpm else False,
            "minicpm_status": minicpm.get_status() if minicpm else None,
            "model": self.config.get("model"),
            "fallback_endpoint": self.config.get("fallback_endpoint"),
        }


# ────────────────────────────────────────────────────────────
# Singleton accessor
# ────────────────────────────────────────────────────────────

_omni_conversation_manager: Optional[OmniConversationManager] = None


def get_omni_conversation_manager() -> OmniConversationManager:
    """Get the singleton OmniConversationManager instance."""
    global _omni_conversation_manager
    if _omni_conversation_manager is None:
        _omni_conversation_manager = OmniConversationManager()
    return _omni_conversation_manager
