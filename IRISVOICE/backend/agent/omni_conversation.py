"""
OmniConversationManager — Vision-aware conversation system.

Extends the existing AIConversationManager with visual context:
when available, screenshots are sent alongside text to MiniCPM-o 4.5
so IRIS can "see" what the user sees and give contextually relevant responses.

Falls back gracefully to text-only LM Studio when vision is unavailable.
"""
import os
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from .personality import get_personality_engine
from .memory import get_conversation_memory
from backend.vision.vision_service import get_vision_service, VisionService


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

        # Use shared VisionService (lazy loading, user-controlled)
        self._vision_service: VisionService = get_vision_service()
        
        # Lazy-loaded screen capture
        self._screen_capture = None

    def _get_vision_service(self) -> VisionService:
        """Get the shared VisionService instance."""
        return self._vision_service

    def _is_vision_available(self) -> bool:
        """Check if vision is enabled and available."""
        status = self._vision_service.get_status()
        return status.get("status") == "enabled" and status.get("is_available", False)

    def _get_screen_capture(self):
        """Lazy-load ScreenCapture."""
        if self._screen_capture is None:
            try:
                from backend.vision import ScreenCapture

                self._screen_capture = ScreenCapture()
            except Exception as e:
                logger.error(f"[OmniConversation] Failed to create screen capture: {e}")
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

        # --- Try VisionService with vision (only if user has enabled it) ---
        if not force_text_only and self._is_vision_available():
            return self._generate_with_vision(user_text, screenshot_b64)

        # --- Fallback: LM Studio (text-only) ---
        logger.info("[OmniConversation] Falling back to LM Studio text-only")
        return self._generate_with_lm_studio(user_text)

    def _generate_with_vision(
        self,
        user_text: str,
        screenshot_b64: Optional[str] = None,
    ) -> Optional[str]:
        """Generate response via VisionService with optional screen context."""
        vision_service = self._get_vision_service()
        
        # Auto-capture screenshot if enabled and not provided
        if screenshot_b64 is None and self.config.get("screen_context_enabled", True):
            capture = self._get_screen_capture()
            if capture:
                try:
                    screenshot_b64, _ = capture.capture_base64()
                except Exception as e:
                    logger.error(f"[OmniConversation] Screen capture failed: {e}")

        # Build conversation history
        history = self.memory.get_context(
            max_messages=self.config.get("max_context_messages", 10)
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
            # Use VisionService for multimodal inference
            import asyncio
            loop = asyncio.get_event_loop()
            
            if screenshot_b64:
                response_text = loop.run_until_complete(
                    vision_service.chat(
                        messages=messages,
                        images=[screenshot_b64],
                        temperature=self.config.get("temperature", 0.7),
                    )
                )
            else:
                response_text = loop.run_until_complete(
                    vision_service.chat(
                        messages=messages,
                        temperature=self.config.get("temperature", 0.7),
                    )
                )

            if response_text:
                # Store in memory
                self.memory.add_message(
                    "user", user_text, text_tokens=len(user_text)
                )
                self.memory.add_message(
                    "assistant", response_text, text_tokens=len(response_text)
                )
                return response_text

            logger.warning("[OmniConversation] Vision service returned empty response")
            return None

        except Exception as e:
            logger.error(f"[OmniConversation] Vision service inference error: {e}")
            return None

    def _generate_with_lm_studio(self, user_text: str) -> Optional[str]:
        """Fallback: generate response via LM Studio (text-only)."""
        import requests as req

        system_prompt = self.personality.get_system_prompt()
        history = self.memory.get_context(
            max_messages=self.config.get("max_context_messages", 10)
        )

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})

        endpoint = self.config.get("fallback_endpoint")
        if not endpoint:
            logger.warning("[OmniConversation] No fallback endpoint configured")
            return None

        # Ensure endpoint has the completions path cleanly
        endpoint = endpoint.rstrip("/")
        for suffix in ["/v1/chat/completions", "/v1/completions"]:
            if endpoint.endswith(suffix):
                endpoint = endpoint[:-len(suffix)]
        endpoint = f"{endpoint}/v1/chat/completions"

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
            logger.error(f"[OmniConversation] LM Studio fallback error: {e}")
            return None

    def update_config(self, **kwargs):
        """Update configuration."""
        for key, value in kwargs.items():
            if key in self.config and value is not None:
                self.config[key] = value

        logger.info(f"[OmniConversation] Config updated: {list(kwargs.keys())}")

    def get_status(self) -> Dict[str, Any]:
        """Get conversation manager status."""
        vision_status = self._vision_service.get_status()
        return {
            "vision_enabled": self._is_vision_available(),
            "screen_context_enabled": self.config.get("screen_context_enabled", False),
            "vision_service_status": vision_status.get("status"),
            "vision_available": vision_status.get("is_available", False),
            "model": vision_status.get("model_name"),
            "vram_usage_mb": vision_status.get("vram_usage_mb"),
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
