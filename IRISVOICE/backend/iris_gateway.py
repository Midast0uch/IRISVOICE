"""
IRIS Gateway - WebSocket Message Router
Routes incoming WebSocket messages to appropriate handlers based on message type.
"""

from .integrations import get_integration_handler
from .tools.lfm_vl_provider import LFMVLProvider
from .tools.cleanup_analyzer import CleanupAnalyzer
from .voice.wake_word_discovery import WakeWordDiscovery
from .audio.pipeline import AudioPipeline
from .agent.tts import get_tts_manager
from .agent import get_agent_kernel
from .core_models import Category, get_sections_for_category
from .state_manager import StateManager, get_state_manager
from .ws_manager import WebSocketManager, get_websocket_manager
import asyncio
import json
import logging
import queue
import re
import threading
import time
import httpx
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Union, Iterator, Callable

# ---------------------------------------------------------------------------
# Pre-compiled regex patterns — used by _clean_for_speech and _speak_response.
# Compiled once at import time to avoid re.compile() overhead on every call.
# ---------------------------------------------------------------------------
_RE_EMOJI = re.compile(
    "[\U0001F300-\U0001F9FF"   # misc symbols, emoticons, transport, food…
    "\U00002702-\U000027B0"    # dingbats
    "\U0001FA00-\U0001FA6F"    # chess, medical …
    "\U0001FA70-\U0001FAFF"    # clothing, science …
    "\U00002500-\U00002BEF"    # CJK / box-drawing misc
    "\U0001F004-\U0001F0CF"    # mahjong / playing cards
    "\U0001F170-\U0001F171"    # blood-type buttons
    "\U0001F191-\U0001F251"    # enclosed characters
    "]+",
    flags=re.UNICODE,
)
_RE_MD_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_RE_MD_BULLET = re.compile(r"^\s*[-*•]\s+", re.MULTILINE)
_RE_MD_BOLD = re.compile(r"\*\*(.*?)\*\*")
_RE_MD_ITALIC = re.compile(r"\*(.*?)\*")
_RE_MD_CODE = re.compile(r"`(.*?)`")
_RE_EXCLAIM = re.compile(r"!+")
_RE_QUESTION_DOT = re.compile(r"\?\.")
_RE_MULTI_DOT = re.compile(r"\.{2,}")
_RE_MULTI_SPACE = re.compile(r" +")
_RE_MULTI_NL = re.compile(r"\n{2,}")
# Sentence boundary: punctuation followed by whitespace (used in split + get_spoken_version)
_RE_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")


logger = logging.getLogger(__name__)


class IRISGateway:
    """
    Central gateway for routing WebSocket messages to appropriate handlers.
    Handles navigation, settings, voice, chat, and status messages.
    """

    def __init__(
        self,
        ws_manager: Optional[WebSocketManager] = None,
        state_manager: Optional[StateManager] = None
    ):
        """
        Initialize the IRIS Gateway.

        Args:
            ws_manager: WebSocket manager instance (uses global if None)
            state_manager: State manager instance (uses global if None)
        """
        self._ws_manager = ws_manager or get_websocket_manager()
        self._state_manager = state_manager or get_state_manager()
        self._logger = logging.getLogger(__name__)

        # Initialize wake word discovery
        self._wake_word_discovery = WakeWordDiscovery()
        self._wake_word_discovery.scan_directory()
        self._logger.info(
            f"[IRISGateway] Wake word discovery initialized, "
            f"found {len(self._wake_word_discovery.get_discovered_files())} wake word file(s)"
        )

        # Initialize cleanup analyzer
        self._cleanup_analyzer = CleanupAnalyzer()
        self._logger.info("[IRISGateway] Cleanup analyzer initialized")

        # Initialize LFM2.5-VL vision provider (connects to llama-server port 8081)
        self._vision_provider = LFMVLProvider()
        self._logger.info(
            "[IRISGateway] Vision provider initialized (LFM2.5-VL @ http://localhost:8081/v1)")

        # Initialize model cache for lazy loading (5 minute TTL)
        self._model_cache: Dict[str, tuple[List[str], datetime]] = {}
        self._model_cache_ttl = timedelta(minutes=5)
        self._logger.info("[IRISGateway] Model cache initialized (5 min TTL)")
        self._tts_prewarmed = False
        self._main_loop = None
        self._speech_interrupted = False

        self._voice_handler = None          # set via set_voice_handler() after construction
        # session_id -> client_id for wake word routing
        self._active_voice_client: dict = {}
        # Sessions currently in conversation mode (auto-relisten after TTS)
        self._conversation_sessions: set = set()
        # How long to wait for speech onset during relisten before returning to idle
        self._relisten_pre_speech_timeout: float = 8.0
        # Captured once the first async message is handled; used by sync callbacks
        # (e.g. _on_voice_result) that need to dispatch back to the event loop from
        # a background thread without calling asyncio.get_event_loop() in that thread.
        import threading
        threading.Thread(target=self._prewarm_tts,
                         daemon=True, name="tts-prewarm").start()

    def set_main_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Capture the running event loop for background task dispatch.

        Mandatory call from main.py's lifespan startup to ensure wake-word callbacks
        can reach the event loop before the first UI WebSocket connects.
        """
        self._main_loop = loop
        self._logger.info("[IRISGateway] Main event loop captured.")

    async def handle_message(self, client_id: str, message: dict, session_id: Optional[str] = None) -> None:
        """
        Main message dispatcher. Routes incoming WebSocket messages to appropriate handlers.

        Error Handling:
        - Parse errors: Log and send error response, continue processing
        - Invalid message format: Log and send error response
        - Unknown message types: Log warning and send error response
        - Handler exceptions: Log with context and send error response

        Args:
            client_id: ID of the client sending the message
            message: Message dictionary with 'type' and optional 'payload'
            session_id: Session ID pre-resolved by the caller (avoids race with disconnect)

        Raises:
            ValueError: If message format is invalid
        """
        # Capture the running loop once so background-thread callbacks can use it.
        if self._main_loop is None:
            try:
                self._main_loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

        try:
            # Validate message format
            if not isinstance(message, dict):
                self._logger.error(
                    f"Invalid message format from client {client_id}: not a dict",
                    extra={"client_id": client_id,
                           "message_type": type(message).__name__}
                )
                await self._send_error(client_id, "Invalid message format: expected dict")
                return

            msg_type = message.get("type")
            if not msg_type:
                self._logger.error(
                    f"Missing message type from client {client_id}",
                    extra={"client_id": client_id, "raw_message": str(message)[
                        :200]}
                )
                await self._send_error(client_id, "Invalid message format: missing 'type' field")
                return

            # Resolve session ID — use caller-supplied value when available to avoid
            # the race where heartbeat disconnect removes the mapping before we look it up.
            if session_id is None:
                session_id = self._ws_manager.get_session_id_for_client(
                    client_id)
            if not session_id:
                self._logger.error(
                    f"No session found for client {client_id}",
                    extra={"client_id": client_id, "message_type": msg_type}
                )
                await self._send_error(client_id, "No active session")
                return

            self._logger.info(
                f"[Session: {session_id}] Processing message type: {msg_type}",
                extra={"session_id": session_id,
                       "client_id": client_id, "message_type": msg_type}
            )

            # Route to appropriate handler based on message type
            if msg_type in ["select_category", "select_section", "go_back"]:
                await self._handle_navigation(session_id, client_id, message)

            elif msg_type in ["update_field", "update_theme", "confirm_card"]:
                await self._handle_settings(session_id, client_id, message)

            elif msg_type == "set_model_selection":
                await self._handle_set_model_selection(session_id, client_id, message)

            elif msg_type in ["voice_command_start", "voice_command_end", "voice_command"]:
                await self._handle_voice(session_id, client_id, message)

            elif msg_type in ["get_wake_words", "select_wake_word"]:
                if msg_type == "get_wake_words":
                    await self._handle_get_wake_words(session_id, client_id)
                else:
                    await self._handle_select_wake_word(session_id, client_id, message)

            elif msg_type in ["get_cleanup_report", "execute_cleanup"]:
                if msg_type == "get_cleanup_report":
                    await self._handle_get_cleanup_report(session_id, client_id, message)
                else:
                    await self._handle_execute_cleanup(session_id, client_id, message)

            elif msg_type in ["text_message", "clear_chat"]:
                await self._handle_chat(session_id, client_id, message)

            elif msg_type in ["get_agent_status", "get_agent_tools", "agent_status", "agent_tools"]:
                await self._handle_status(session_id, client_id, message)

            elif msg_type == "get_available_models":
                await self._handle_get_available_models(session_id, client_id, message)

            elif msg_type == "request_models":
                await self._handle_request_models(session_id, client_id, message)

            # Local GGUF model management (llama-cpp-python on port 8082)
            elif msg_type == "get_local_models":
                await self._handle_get_local_models(session_id, client_id, message)

            elif msg_type == "load_local_model":
                await self._handle_load_local_model(session_id, client_id, message)

            elif msg_type == "unload_local_model":
                await self._handle_unload_local_model(session_id, client_id, message)

            elif msg_type == "get_local_model_status":
                await self._handle_get_local_model_status(session_id, client_id, message)

            elif msg_type == "get_hardware_info":
                await self._handle_get_hardware_info(session_id, client_id, message)

            elif msg_type == "download_gguf_model":
                await self._handle_download_gguf_model(session_id, client_id, message)

            elif msg_type == "search_hf_models":
                await self._handle_search_hf_models(session_id, client_id, message)

            elif msg_type == "set_vision_enabled":
                await self._handle_set_vision_enabled(session_id, client_id, message)

            elif msg_type == "toggle_model_pin":
                await self._handle_toggle_model_pin(session_id, client_id, message)

            elif msg_type == "get_audio_devices":
                await self._handle_get_audio_devices(session_id, client_id)

            elif msg_type == "test_connection":
                await self._handle_test_connection(session_id, client_id, message)

            # GAP-01 FIX: Additional message types from main.py
            elif msg_type == "collapse_to_idle":
                await self._handle_collapse_to_idle(session_id, client_id, message)

            elif msg_type == "expand_to_main":
                await self._handle_expand_to_main(session_id, client_id, message)

            elif msg_type == "reload_skills":
                await self._handle_reload_skills(session_id, client_id, message)

            elif msg_type == "get_skills":
                await self._handle_get_skills(session_id, client_id)

            elif msg_type == "toggle_skill":
                await self._handle_toggle_skill(session_id, client_id, message)

            elif msg_type == "delete_skill":
                await self._handle_delete_skill(session_id, client_id, message)

            elif msg_type == "create_skill":
                await self._handle_create_skill(session_id, client_id, message)

            elif msg_type == "execute_tool":
                await self._handle_execute_tool(session_id, client_id, message)

            elif msg_type == "tts_play":
                # Frontend play-icon clicked — speak the supplied text via TTS
                await self._handle_tts_play(session_id, client_id, message)

            elif msg_type == "ping":
                await self._ws_manager.send_to_client(client_id, {"type": "pong", "payload": {}})

            elif msg_type == "pong":
                await self._ws_manager.handle_pong(client_id)

            elif msg_type == "request_state":
                await self._handle_request_state(session_id, client_id)

            elif msg_type == "enable_vision":
                await self._handle_enable_vision(session_id, client_id)

            elif msg_type == "disable_vision":
                await self._handle_disable_vision(session_id, client_id)

            elif msg_type == "get_vision_status":
                await self._handle_get_vision_status(session_id, client_id)

            elif msg_type == "message_exported":
                await self._handle_message_exported(session_id, client_id, message)

            elif msg_type in {
                "integration_list", "integration_enable", "integration_disable",
                "integration_state", "integration_oauth_callback",
                "integration_credentials_auth", "integration_telegram_auth",
                "integration_restart", "integration_forget", "app_cleanup",
                "activity_get_recent", "logs_subscribe", "logs_get_history",
                "logs_unsubscribe", "marketplace_preference_store",
                "marketplace_preferences_get", "marketplace_recommendations_get",
            }:
                # Delegate to the integration subsystem handler
                await get_integration_handler().handle_message(client_id, message)

            else:
                self._logger.warning(
                    f"Unknown message type: {msg_type}",
                    extra={"session_id": session_id,
                           "client_id": client_id, "message_type": msg_type}
                )
                await self._send_error(client_id, f"Unknown message type: {msg_type}")

        except json.JSONDecodeError as e:
            # Handle JSON parse errors
            self._logger.error(
                f"JSON parse error from client {client_id}: {e}",
                exc_info=True,
                extra={"client_id": client_id, "error": str(e)}
            )
            await self._send_error(client_id, "Invalid JSON format")

        except Exception as e:
            # Handle all other exceptions
            msg_type = message.get("type", "unknown") if isinstance(
                message, dict) else "unknown"
            self._logger.error(
                f"Error handling message type {msg_type} from client {client_id}: {e}",
                exc_info=True,
                extra={"client_id": client_id,
                       "message_type": msg_type, "error": str(e)}
            )
            await self._send_error(client_id, f"Error processing message: {str(e)}")

    async def _handle_navigation(self, session_id: str, client_id: str, message: dict) -> None:
        """
        Handle navigation messages: select_category, select_section, go_back.

        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary
        """
        msg_type = message.get("type")

        if msg_type == "select_category":
            category = message.get("category") or message.get(
                "payload", {}).get("category")

            if not category:
                await self._send_validation_error(client_id, "category", "Category is required")
                return

            # Validate category
            try:
                category_enum = Category(category) if isinstance(
                    category, str) else category
            except ValueError:
                await self._send_validation_error(client_id, "category", f"Invalid category: {category}")
                return

            # Update state
            await self._state_manager.set_category(session_id, category_enum)

            # Get sections for this category
            sections = get_sections_for_category(category_enum)

            # Send confirmation with sections
            await self._ws_manager.send_to_client(client_id, {
                "type": "category_changed",
                "payload": {
                    "category": category,
                    "sections": [s.model_dump() for s in sections]
                }
            })

            # Broadcast state update to other clients in session
            await self._broadcast_state_update(session_id, exclude_client=client_id)

        elif msg_type == "select_section":
            section_id = message.get("section_id") or message.get(
                "payload", {}).get("section_id")

            if not section_id:
                await self._send_validation_error(client_id, "section_id", "Section ID is required")
                return

            # Update state
            await self._state_manager.set_section(session_id, section_id)

            # Send confirmation
            await self._ws_manager.send_to_client(client_id, {
                "type": "section_changed",
                "payload": {
                    "section_id": section_id
                }
            })

            # Broadcast state update to other clients in session
            await self._broadcast_state_update(session_id, exclude_client=client_id)

        elif msg_type == "go_back":
            # Navigate back
            await self._state_manager.go_back(session_id)

            # Broadcast state update to all clients in session
            await self._broadcast_state_update(session_id, exclude_client=client_id)

    async def _handle_settings(self, session_id: str, client_id: str, message: dict) -> None:
        """
        Handle settings messages: update_field, update_theme, confirm_card.

        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary
        """
        msg_type = message.get("type")
        payload = message.get("payload", {})

        if msg_type == "update_field":
            # Use only section_id (cleanup complete)
            section_id = message.get("section_id") or payload.get("section_id")
            field_id = message.get("field_id") or payload.get("field_id")
            value = message.get(
                "value") if "value" in message else payload.get("value")
            # Optional timestamp from client
            timestamp = payload.get("timestamp")

            if not section_id or not field_id:
                await self._send_validation_error(
                    client_id,
                    "field",
                    "Both section_id and field_id are required"
                )
                return

            # Update field value with timestamp handling
            success, update_timestamp = await self._state_manager.update_field(
                session_id, section_id, field_id, value, timestamp
            )

            if success:
                # NOTE: Service reinitialization (TTS, model selection, audio devices) is
                # intentionally deferred to confirm_card. update_field only persists the value
                # to state so it is available when the user presses Confirm.

                # Mask API keys in the response
                response_value = value
                if field_id == "openai_api_key" and value:
                    from .utils.encryption import mask_api_key
                    response_value = mask_api_key(value)

                # Send confirmation with timestamp - include both new and legacy field names
                await self._ws_manager.send_to_client(client_id, {
                    "type": "field_updated",
                    "payload": {
                        "section_id": section_id,
                        "field_id": field_id,
                        "value": response_value,
                        "valid": True,
                        "timestamp": update_timestamp
                    }
                })

                # Broadcast to other clients in session with timestamp (also masked)
                await self._ws_manager.broadcast_to_session(
                    session_id,
                    {
                        "type": "field_updated",
                        "payload": {
                            "section_id": section_id,
                            "field_id": field_id,
                            "value": response_value,
                            "valid": True,
                            "timestamp": update_timestamp
                        }
                    },
                    exclude_clients={client_id}
                )
            else:
                # Send validation error
                await self._send_validation_error(
                    client_id,
                    field_id,
                    "Field validation failed"
                )

        elif msg_type == "update_theme":
            glow_color = payload.get("glow_color")
            font_color = payload.get("font_color")
            state_colors = payload.get("state_colors")

            # Update theme
            await self._state_manager.update_theme(
                session_id,
                glow_color=glow_color,
                font_color=font_color,
                state_colors=state_colors
            )

            # Get updated theme
            state = await self._state_manager.get_state(session_id)
            if state:
                # GAP-10 FIX: Send theme_updated with direct properties (not nested payload)
                # to match format expected by frontend
                theme_data = state.active_theme.model_dump()
                await self._ws_manager.broadcast_to_session(
                    session_id,
                    {
                        "type": "theme_updated",
                        "glow": theme_data.get("glow"),
                        "font": theme_data.get("font"),
                        "state_colors_enabled": theme_data.get("state_colors_enabled"),
                        "idle_color": theme_data.get("idle_color"),
                        "listening_color": theme_data.get("listening_color"),
                        "processing_color": theme_data.get("processing_color"),
                        "error_color": theme_data.get("error_color"),
                    }
                )

        elif msg_type == "confirm_card":
            # Use only section_id (cleanup complete)
            section_id = payload.get("section_id")
            values = payload.get("values", {})

            if not section_id:
                await self._send_validation_error(client_id, "section_id", "Section ID is required")
                return

            # Apply wake word configuration when the wake section is confirmed
            if section_id == "wake" and values:
                try:
                    from .agent.wake_config import get_wake_config
                    wake_config = get_wake_config()
                    config_updates = {}

                    wake_phrase = values.get("wake_phrase")
                    if wake_phrase is not None:
                        # Rescan to catch any .ppn files that may not have been visible at startup
                        # (e.g., when running from a git worktree with an empty models/wake_words/)
                        discovered = self._wake_word_discovery.scan_directory()
                        # Case-insensitive match: "Hey IRIS" and "Hey Iris" both find the same file
                        custom_file = next(
                            (wf for wf in discovered
                             if wf.display_name.lower() == wake_phrase.lower() and wf.platform != "builtin"),
                            None
                        )
                        config_updates["wake_phrase"] = wake_phrase
                        config_updates["custom_model_path"] = custom_file.path if custom_file else None

                    sensitivity = values.get("wake_word_sensitivity")
                    if sensitivity is not None:
                        # UI slider is 1-10; Porcupine needs 0.0-1.0
                        config_updates["detection_sensitivity"] = float(
                            sensitivity) / 10.0

                    wake_enabled = values.get("wake_word_enabled")
                    if wake_enabled is not None:
                        config_updates["wake_word_enabled"] = bool(
                            wake_enabled)

                    if config_updates:
                        wake_config.update_config(**config_updates)
                        self._logger.info(
                            f"[Session: {session_id}] Wake config applied on confirm: {config_updates}",
                            extra={"session_id": session_id,
                                   "client_id": client_id}
                        )
                except Exception as wc_e:
                    self._logger.error(
                        f"[Session: {session_id}] Error applying wake config on confirm: {wc_e}",
                        extra={"session_id": session_id,
                               "client_id": client_id}
                    )

            # Apply TTS configuration when speech section is confirmed
            elif section_id == "speech" and values:
                try:
                    tts = get_tts_manager()
                    kwargs = {}
                    if "tts_enabled" in values:
                        kwargs["tts_enabled"] = values["tts_enabled"]
                    if "tts_voice" in values:
                        kwargs["tts_voice"] = values["tts_voice"]
                    if "speaking_rate" in values:
                        kwargs["speaking_rate"] = float(
                            values["speaking_rate"])
                    if kwargs:
                        tts.update_config(**kwargs)
                        self._logger.info(
                            f"[Session: {session_id}] TTS config applied: {kwargs}",
                            extra={"session_id": session_id,
                                   "client_id": client_id}
                        )
                except Exception as e:
                    self._logger.error(
                        f"[Session: {session_id}] Error applying TTS config: {e}",
                        extra={"session_id": session_id,
                               "client_id": client_id}
                    )

            # Apply model selection when models section is confirmed
            # CARD_TO_SECTION_ID maps 'models-card' -> 'model_selection'
            elif section_id == "model_selection" and values:
                try:
                    from .agent.agent_kernel import get_agent_kernel
                    kernel = get_agent_kernel(session_id)
                    reasoning = values.get("reasoning_model")
                    # cards.ts field is 'tool_model' (not 'tool_execution_model')
                    tool_exec = values.get("tool_model") or values.get(
                        "tool_execution_model")
                    # "local" | "vps" | "api"
                    provider = values.get("model_provider")

                    # Always pass the provider so the kernel knows which inference
                    # backend to route to (Ollama / VPS / OpenAI).
                    kernel.set_model_selection(
                        reasoning_model=reasoning,
                        tool_execution_model=tool_exec,
                        model_provider=provider,
                    )
                    self._logger.info(
                        f"[Session: {session_id}] Model selection applied on confirm: "
                        f"reasoning={reasoning}, tool={tool_exec}, provider={provider}",
                        extra={"session_id": session_id,
                               "client_id": client_id}
                    )

                    # Wire up the correct inference backend based on provider.
                    if provider == "lmstudio":
                        # LM Studio / any OpenAI-compatible local server.
                        lms_endpoint = values.get(
                            "lmstudio_endpoint", "http://localhost:1234") or "http://localhost:1234"
                        kernel.configure_lmstudio(lms_endpoint)
                        kernel.configure_vps({"enabled": False})
                        self._logger.info(
                            f"[Session: {session_id}] LM Studio configured: {lms_endpoint}",
                            extra={"session_id": session_id}
                        )
                        # Pre-warm: fire a 1-token request so LM Studio loads the model
                        # into VRAM now so cold-start delay doesn't hit the first message.
                        kernel.prewarm_lmstudio()

                    elif provider == "local":
                        # Ollama native API.
                        ollama_endpoint = values.get(
                            "ollama_endpoint", "http://localhost:11434") or "http://localhost:11434"
                        kernel.configure_ollama(ollama_endpoint)
                        kernel.configure_vps({"enabled": False})
                        self._logger.info(
                            f"[Session: {session_id}] Ollama configured: {ollama_endpoint}",
                            extra={"session_id": session_id}
                        )

                    elif provider == "api":
                        # Remote OpenAI-compatible API (OpenAI, Groq, Together, OpenRouter, etc.)
                        api_key = values.get("api_key", "") or ""
                        api_base_url = values.get(
                            "api_base_url", "https://api.openai.com/v1") or "https://api.openai.com/v1"
                        kernel.configure_api(api_key, api_base_url)
                        kernel.configure_vps({"enabled": False})
                        self._logger.info(
                            f"[Session: {session_id}] Remote API configured: {api_base_url}",
                            extra={"session_id": session_id}
                        )

                    elif provider == "vps":
                        vps_endpoint = values.get("vps_endpoint", "")
                        vps_token = values.get("vps_token", "")
                        if vps_endpoint:
                            kernel.configure_vps({
                                "enabled": True,
                                "endpoints": [vps_endpoint],
                                "auth_token": vps_token or None,
                            })
                            self._logger.info(
                                f"[Session: {session_id}] VPS gateway configured: {vps_endpoint}",
                                extra={"session_id": session_id}
                            )

                    elif provider == "iris_local":
                        # llama-cpp-python server on port 8082 (OpenAI-compatible).
                        # Reuses the LM Studio code path since both expose /v1.
                        from .agent.local_model_manager import get_local_model_manager
                        mgr = get_local_model_manager()
                        kernel.configure_lmstudio(mgr.ENDPOINT)
                        kernel.configure_vps({"enabled": False})
                        self._logger.info(
                            f"[Session: {session_id}] iris_local provider configured: {mgr.ENDPOINT}",
                            extra={"session_id": session_id}
                        )

                    # Handle vision_enabled toggle
                    if "vision_enabled" in values:
                        vision_on = bool(values.get("vision_enabled", False))
                        await self._handle_set_vision_enabled(session_id, client_id, {"payload": {"enabled": vision_on}})

                    # Refresh model dropdown so UI reflects available models for the
                    # new provider immediately.
                    if "model_provider" in values:
                        await self._handle_get_available_models(session_id, client_id, {})
                except Exception as e:
                    self._logger.error(
                        f"[Session: {session_id}] Error applying model selection on confirm: {e}",
                        extra={"session_id": session_id,
                               "client_id": client_id}
                    )

            # Apply audio device selection when input section is confirmed
            elif section_id == "input" and values:
                try:
                    from .audio.engine import get_audio_engine
                    engine = get_audio_engine()
                    # Field ID is 'input_device' per data/cards.ts
                    device = values.get("input_device")
                    if device is not None and device != "":
                        # UI sends device names (strings); resolve to integer index so
                        # sounddevice doesn't encounter multiple host-API matches.
                        device = self._resolve_device_index(
                            device, want_input=True)
                        engine.update_config(input_device=device)
                        self._logger.info(
                            f"[Session: {session_id}] Input device applied on confirm: {device}",
                            extra={"session_id": session_id,
                                   "client_id": client_id}
                        )
                except Exception as e:
                    self._logger.error(
                        f"[Session: {session_id}] Error applying input device on confirm: {e}",
                        extra={"session_id": session_id,
                               "client_id": client_id}
                    )

            # Apply audio device selection when output section is confirmed
            elif section_id == "output" and values:
                try:
                    from .audio.engine import get_audio_engine
                    engine = get_audio_engine()
                    # Field ID is 'output_device' per data/cards.ts
                    device = values.get("output_device")
                    if device is not None and device != "":
                        # UI sends device names (strings); resolve to integer index.
                        device = self._resolve_device_index(
                            device, want_input=False)
                        engine.update_config(output_device=device)
                        self._logger.info(
                            f"[Session: {session_id}] Output device applied on confirm: {device}",
                            extra={"session_id": session_id,
                                   "client_id": client_id}
                        )
                except Exception as e:
                    self._logger.error(
                        f"[Session: {session_id}] Error applying output device on confirm: {e}",
                        extra={"session_id": session_id,
                               "client_id": client_id}
                    )

            # Get current category
            state = await self._state_manager.get_state(session_id)
            if not state or not state.current_category:
                await self._send_error(client_id, "No active category")
                return

            # Confirm section
            orbit_angle = await self._state_manager.confirm_section(
                session_id,
                state.current_category.value,
                section_id,
                values
            )

            if orbit_angle is not None:
                # Send confirmation with section context so the UI can show feedback
                await self._ws_manager.send_to_client(client_id, {
                    "type": "card_confirmed",
                    "payload": {
                        "section_id": section_id,
                        "orbit_angle": orbit_angle,
                        "applied": True
                    }
                })

                # Broadcast state update
                await self._broadcast_state_update(session_id, exclude_client=client_id)
            else:
                await self._send_error(client_id, "Failed to confirm card")

    def set_voice_handler(self, voice_handler) -> None:
        """Wire the VoiceCommandHandler so voice triggers can delegate to it."""
        self._voice_handler = voice_handler
        voice_handler.set_command_result_callback(self._on_voice_result)

    async def _handle_voice(self, session_id: str, client_id: str, message: dict, auto_stop: bool = False) -> None:
        """
        Handle voice_command_start / voice_command_end from double-click or wake word.
        Delegates audio capture + LFM2-Audio processing to VoiceCommandHandler/ModelManager.
        All 4 pillars run after transcription is received via _on_voice_result callback.
        """
        msg_type = message.get("type")
        if msg_type == "voice_command":
            msg_type = "voice_command_start"

        try:
            if msg_type == "voice_command_start":
                self._logger.info(
                    f"[Session: {session_id}] Voice command start")
                # Enable conversation mode — will auto-relisten after each TTS response
                self._conversation_sessions.add(session_id)

                # Interrupt TTS only if it is currently playing.
                # Calling interrupt_speech() unconditionally sets
                # _speech_interrupted = True and the flag persists until the
                # playback loop in _speak_response() consumes it.  If no TTS
                # was running, the flag stays True and the *next* TTS response
                # bails immediately at the is_speech_interrupted() check —
                # producing silence even though the orb animates as "speaking".
                try:
                    from .audio.engine import get_audio_engine
                    engine = get_audio_engine()
                    if engine._tts_active:
                        engine.interrupt_speech()
                except Exception:
                    pass  # non-fatal — audio engine may not be up yet

                # Track which client triggered this so wake-word callback knows where to respond
                self._active_voice_client[session_id] = client_id

                # Safety-net: if the startup TTS prewarm hasn't finished yet, kick it
                # again now so it completes before the user finishes speaking.
                if not self._tts_prewarmed:
                    import threading
                    threading.Thread(
                        target=self._prewarm_tts, daemon=True, name="tts-prewarm-ondemand"
                    ).start()

                # Broadcast LISTENING immediately so IrisOrb animates
                await self._ws_manager.broadcast_to_session(session_id, {
                    "type": "listening_state",
                    "payload": {"state": "listening"}
                })

                # Delegate recording to the shared VoiceCommandHandler
                if self._voice_handler:
                    self._voice_handler.set_active_session(session_id)
                    success = self._voice_handler.start_recording(
                        auto_stop=auto_stop)
                    if not success:
                        self._logger.warning(
                            f"[Session: {session_id}] VoiceCommandHandler start_recording() failed — resetting orb to idle")
                        await self._ws_manager.broadcast_to_session(session_id, {
                            "type": "listening_state", "payload": {"state": "idle"}
                        })
                else:
                    self._logger.error(
                        "[Voice] VoiceCommandHandler not wired — call set_voice_handler()")
                    await self._ws_manager.broadcast_to_session(session_id, {
                        "type": "listening_state", "payload": {"state": "error"}
                    })
                    # Auto-recover from error state after 2 s
                    await asyncio.sleep(2.0)
                    await self._ws_manager.broadcast_to_session(session_id, {
                        "type": "listening_state", "payload": {"state": "idle"}
                    })

            elif msg_type == "voice_command_end":
                self._logger.info(f"[Session: {session_id}] Voice command end")

                has_audio = (
                    self._voice_handler is not None
                    and len(getattr(self._voice_handler, "audio_buffer", [])) > 30
                )

                # Always call stop_recording() regardless of how the recording
                # was started (wake-word auto_stop or manual double-click).
                #
                # For the wake-word path (auto_stop=True), VAD has already
                # stopped the recording and queued Whisper before this message
                # arrives, so stop_recording() is a no-op (is_recording=False).
                # The Whisper transcription fires normally via _on_voice_result.
                #
                # For the manual double-click path (auto_stop=False), this
                # signals the background thread to exit its _stop_event.wait()
                # and proceed to Whisper transcription.
                #
                # Previously this branched on is_auto_stop and called
                # cancel_recording() for the wake-word path, which set
                # _cancelled=True and skipped Whisper entirely — silently
                # breaking the entire voice pipeline.
                if has_audio:
                    await self._ws_manager.broadcast_to_session(session_id, {
                        "type": "listening_state",
                        "payload": {"state": "processing_conversation"}
                    })
                else:
                    await self._ws_manager.broadcast_to_session(session_id, {
                        "type": "listening_state",
                        "payload": {"state": "idle"}
                    })
                if self._voice_handler:
                    self._voice_handler.stop_recording()

            elif msg_type == "voice_command_cancel":
                self._logger.info(f"[Session: {session_id}] Voice command cancelled by user")
                # Exit conversation mode — user explicitly stopped
                self._conversation_sessions.discard(session_id)
                if self._voice_handler:
                    self._voice_handler.cancel_recording()
                # Interrupt TTS if currently playing
                try:
                    from .audio.engine import get_audio_engine
                    engine = get_audio_engine()
                    if engine._tts_active:
                        engine.interrupt_speech()
                except Exception:
                    pass
                await self._ws_manager.broadcast_to_session(session_id, {
                    "type": "listening_state",
                    "payload": {"state": "idle"}
                })

        except Exception as e:
            self._logger.error(
                f"[Voice] Error in _handle_voice: {e}", exc_info=True)
            await self._ws_manager.broadcast_to_session(session_id, {
                "type": "listening_state", "payload": {"state": "error"}
            })

    def _on_voice_result(self, result: dict) -> None:
        """
        Callback fired by VoiceCommandHandler when LFM2-Audio finishes processing.
        Extracts transcript + audio context and routes through 4-pillar pipeline.
        Called from a background thread — uses asyncio.run_coroutine_threadsafe.
        """
        try:
            transcript = result.get("transcript", "").strip()
            audio_context = result.get("audio_context", "").strip()
            session_id = result.get("session_id", "default")
            client_id = self._active_voice_client.get(session_id)

            # Use the loop captured during the first async message dispatch.
            # Never call asyncio.get_event_loop() here — this runs in a background
            # thread and that call raises "no current event loop" on Python 3.10+.
            loop = self._main_loop
            if loop is None or not loop.is_running():
                self._logger.error(
                    "[Voice] _on_voice_result: main event loop not available")
                return

            if not transcript or not client_id:
                self._logger.warning(
                    f"[Voice] Empty transcript or unknown client for session {session_id}")
                # Empty transcript during conversation mode relisten = user finished talking
                # Clear conversation mode so we return to true idle
                self._conversation_sessions.discard(session_id)
                asyncio.run_coroutine_threadsafe(
                    self._ws_manager.broadcast_to_session(session_id, {
                        "type": "listening_state", "payload": {"state": "idle"}
                    }),
                    loop
                )
                return

            asyncio.run_coroutine_threadsafe(
                self._process_voice_transcription(
                    session_id, client_id, transcript, audio_context),
                loop
            )
        except Exception as e:
            self._logger.error(
                f"[Voice] _on_voice_result error: {e}", exc_info=True)

    async def _process_voice_transcription(
        self, session_id: str, client_id: str, transcript: str, audio_context: str
    ) -> None:
        """
        Full 4-pillar pipeline after STT transcription.

        State machine:
          listening → processing_conversation (LLM thinking)
                    → speaking               (TTS playing)
                    → idle                   (TTS done / no spoken text)

        The text response appears in ChatView as soon as the LLM returns,
        independent of TTS.  TTS plays after the full response is ready so
        the orb transitions correctly and never gets stuck in speaking state.
        """
        import asyncio
        import threading
        loop = asyncio.get_running_loop()
        _tts_started = False
        try:
            # ── Pillar 1A: user bubble ──────────────────────────────────────
            await self._ws_manager.send_to_client(client_id, {
                "type": "text_response",
                "payload": {"text": transcript, "sender": "user"}
            })

            enriched = transcript
            if audio_context:
                enriched = f"{transcript}\n\n[Audio context: {audio_context}]"

            from .agent.agent_kernel import get_agent_kernel
            agent_kernel = get_agent_kernel(session_id)

            if agent_kernel._tool_bridge is None:
                from .agent.tool_bridge import get_agent_tool_bridge
                agent_kernel._tool_bridge = get_agent_tool_bridge()

            # ── Orb: thinking while LLM runs ────────────────────────────────
            await self._ws_manager.broadcast_to_session(session_id, {
                "type": "listening_state",
                "payload": {"state": "processing_conversation"}
            })

            def _execute_agent():
                def chunk_callback(chunk: str):
                    asyncio.run_coroutine_threadsafe(
                        self._ws_manager.send_to_client(client_id, {
                            "type": "chat_chunk",
                            "payload": {"chunk": chunk}
                        }),
                        self._main_loop
                    )

                resp = agent_kernel.process_text_message(
                    enriched,
                    session_id=session_id,
                    chunk_callback=chunk_callback
                )
                spoken = agent_kernel.prepare_spoken_text(resp, enriched)
                return resp, spoken

            # Run agent synchronously in thread pool
            response, spoken = await loop.run_in_executor(None, _execute_agent)

            # ── Pillar 1B: assistant bubble in ChatView ─────────────────────
            thinking = getattr(agent_kernel, "_pending_thinking", "") or ""
            await self._ws_manager.send_to_client(client_id, {
                "type": "text_response",
                "payload": {
                    "text": response,
                    "sender": "assistant",
                    **({"thinking": thinking} if thinking else {}),
                }
            })

            # ── TTS: speak the response ─────────────────────────────────────
            if spoken.strip():
                await self._ws_manager.broadcast_to_session(session_id, {
                    "type": "listening_state",
                    "payload": {"state": "speaking"}
                })
                _tts_started = True
                threading.Thread(
                    target=self._speak_response,
                    args=(spoken, session_id),
                    daemon=True,
                    name="voice-tts"
                ).start()
                # _speak_response sends idle when TTS finishes
            else:
                await self._ws_manager.broadcast_to_session(session_id, {
                    "type": "listening_state",
                    "payload": {"state": "idle"}
                })

        except Exception as e:
            self._logger.error(
                f"[Voice] Pipeline error for session {session_id}: {e}", exc_info=True)
            await self._ws_manager.broadcast_to_session(session_id, {
                "type": "listening_state", "payload": {"state": "error"}
            })
            await asyncio.sleep(2.0)
            await self._ws_manager.broadcast_to_session(session_id, {
                "type": "listening_state", "payload": {"state": "idle"}
            })

        finally:
            if not _tts_started:
                # Safety net: if TTS never started, ensure we always reach idle.
                # (TTS path sends idle itself via _speak_response finally block.)
                pass
            self._logger.debug(f"[Voice] Pipeline complete for session {session_id}")

    def _prewarm_tts(self) -> None:
        """Pre-load CosyVoice2-0.5B and register voice reference in a background thread.

        Idempotent — early-exits if already called successfully so re-triggering
        on the first voice command (as a safety net) does not double-load.

        A 6-second startup delay is intentional: it lets the backend finish
        initialising other components (FastAPI, audio pipeline, WebSocket manager,
        Porcupine) before the ~1-2 GB CosyVoice model begins loading into RAM.
        This smooths the startup memory curve without delaying the first voice
        response (the model is ready long before the user speaks).
        """
        if self._tts_prewarmed:
            return
        try:
            import time as _time
            _time.sleep(6)  # let backend fully start before CosyVoice RAM load
            from .agent.tts import get_tts_manager
            tts = get_tts_manager()
            if tts.config.get("tts_voice") == "Built-in":
                self._tts_prewarmed = True  # built-in engine needs no warm-up
                return
            tts._warm_tts_pipeline()
            self._tts_prewarmed = True
            self._logger.info("[IRISGateway] CosyVoice2 pipeline warmed up")
        except Exception as e:
            self._logger.warning(
                f"[IRISGateway] TTS pre-warm failed (non-fatal): {e}")
        finally:
            # Mark as pre-warmed / attempted regardless of success to prevent 
            # infinite retry loops in _handle_voice (which would spam logs).
            self._tts_prewarmed = True

    @staticmethod
    def _clean_for_speech(text: str) -> str:
        """Sanitise *text* before sending to the TTS engine.

        Removes emoji (which TTS models spell out letter-by-letter or skip
        unpredictably), strips markdown formatting, and replaces exclamation
        marks with periods so the cloned voice delivers a calm, measured tone
        instead of the overly energetic delivery that occurs when the model
        generates sentences ending in '!'.
        """
        # Use module-level pre-compiled patterns — no per-call re.compile() cost.
        text = _RE_EMOJI.sub("", text)
        text = _RE_MD_HEADING.sub("", text)
        text = _RE_MD_BULLET.sub("", text)
        text = _RE_MD_BOLD.sub(r"\1", text)
        text = _RE_MD_ITALIC.sub(r"\1", text)
        text = _RE_MD_CODE.sub(r"\1", text)
        text = _RE_EXCLAIM.sub(".", text)
        text = _RE_QUESTION_DOT.sub("?", text)
        text = _RE_MULTI_DOT.sub(".", text)
        text = _RE_MULTI_SPACE.sub(" ", text)
        text = _RE_MULTI_NL.sub("\n", text)
        return text.strip()

    def _speak_response(self, input_source: Union[str, queue.Queue], session_id: str = None) -> None:
        """
        Synthesise and play text through the configured TTS engine.
        Using a producer-consumer pattern to stream audio chunks as soon as they
        are ready, minimizing latency for the first spoken word.

        Args:
            input_source: Either the full text to speak (str) or a queue.Queue 
                       that will receive sentences in real-time.
            session_id: Optional session ID to broadcast idle state to when finished.
        """
        from .agent import get_tts_manager
        from .agent.tts import OUTPUT_SAMPLE_RATE as _TTS_SAMPLE_RATE
        from .audio.engine import get_audio_engine

        engine = get_audio_engine()
        tts = get_tts_manager()

        if not engine.pipeline:
            return

        # 1. Internal state
        audio_queue: queue.Queue = queue.Queue(
            maxsize=4)  # Buffer a few chunks
        interrupted = threading.Event()

        # Dynamic chunking: synthesise first sentence immediately for instant
        # voice onset, then use larger chunks for stable continuous playback.
        FIRST_CHUNK_THRESHOLD = 1
        NORMAL_CHUNK_THRESHOLD = 8

        # 2. Synthesiser thread (producer)
        def _producer():
            try:
                if isinstance(input_source, str):
                    # Single-call path: pass the FULL text to CosyVoice in one go.
                    # This preserves natural prosody across the entire response —
                    # sentence-by-sentence synthesis creates prosody breaks and
                    # robotic-sounding stitching at boundaries.
                    text = self._clean_for_speech(input_source)
                    if not text.strip():
                        return
                    self._logger.info(f"[Voice] TTS synthesizing {len(text.split())} words in single pass")
                    for audio_chunk in tts.synthesize_stream(text):
                        if interrupted.is_set():
                            break
                        if audio_chunk is not None and len(audio_chunk) > 0:
                            audio_queue.put(audio_chunk)

                elif isinstance(input_source, queue.Queue):
                    # Streaming path: read from sentence queue
                    _pending = []
                    _pending_words = 0
                    while True:
                        item = input_source.get()
                        if item is None:
                            # Final flush
                            if _pending and not interrupted.is_set():
                                chunk = " ".join(_pending)
                                for audio_chunk in tts.synthesize_stream(chunk):
                                    if audio_chunk is not None and len(audio_chunk) > 0:
                                        audio_queue.put(audio_chunk)
                            break

                        _pending.append(item)
                        _pending_words += len(item.split())

                        # Trigger synthesis if we hit the word count OR if it's the
                        # very first sentence (regardless of length) for instant response.
                        if _pending_words >= _target or (is_first_chunk and len(_pending) >= 1):
                            if interrupted.is_set():
                                break
                            chunk = " ".join(_pending)
                            for audio_chunk in tts.synthesize_stream(chunk):
                                if audio_chunk is not None and len(audio_chunk) > 0:
                                    audio_queue.put(audio_chunk)
                            _pending = []
                            _pending_words = 0
                            if is_first_chunk:
                                is_first_chunk = False
                                _target = NORMAL_CHUNK_THRESHOLD
            except Exception as exc:
                self._logger.error(f"[Voice] TTS Producer error: {exc}")
            finally:
                audio_queue.put(None)

        # 3. Suppress Porcupine while IRIS is speaking
        engine.set_tts_active(True)
        engine.is_speech_interrupted()

        try:
            producer_thread = threading.Thread(
                target=_producer, daemon=True, name="tts-producer")
            producer_thread.start()

            # 4. Consumer: play each chunk as soon as it arrives.
            # First-chunk timeout is generous (90 s) to cover CosyVoice model
            # load time on first call after startup.  Subsequent chunks use
            # a tighter timeout (15 s) — once the model is warm each chunk
            # arrives within ~1-2 s even on CPU.
            import numpy as _np
            _first_chunk = True
            while True:
                _timeout = 90 if _first_chunk else 15
                try:
                    chunk = audio_queue.get(timeout=_timeout)
                except queue.Empty:
                    self._logger.error(
                        f"[Voice] TTS audio queue timed out after {_timeout}s — forcing idle"
                    )
                    interrupted.set()
                    break
                _first_chunk = False
                if chunk is None:
                    break

                if engine.is_speech_interrupted():
                    interrupted.set()
                    while not audio_queue.empty():
                        try:
                            audio_queue.get_nowait()
                        except queue.Empty:
                            break
                    break

                # Play each chunk immediately as it arrives.
                # Do NOT greedily concatenate multiple chunks — that creates large
                # blocking write() calls which starve the audio card buffer and cause
                # gaps between bursts. Small individual writes let PortAudio maintain
                # a continuous stream in its internal ring buffer.
                # Pass the TTS native sample rate so sd.play() does one conversion
                # step (24 kHz → device rate) instead of the previous two-step path
                # (24 kHz → 16 kHz in _resample → device rate in sounddevice).
                engine.pipeline.play_audio(chunk, sample_rate=_TTS_SAMPLE_RATE)

            producer_thread.join(timeout=5)
        except Exception as e:
            self._logger.error(f"[Voice] TTS Consumer error: {e}")
        finally:
            engine.set_tts_active(False)
            if session_id and self._main_loop and self._main_loop.is_running():
                import asyncio as _asyncio
                # Conversation mode: auto-relisten unless interrupted or cancelled
                in_conversation = session_id in self._conversation_sessions
                was_interrupted = interrupted.is_set()
                if in_conversation and not was_interrupted and self._voice_handler:
                    self._logger.info(
                        f"[Voice] Conversation mode: auto-resuming listen for session {session_id}")
                    _asyncio.run_coroutine_threadsafe(
                        self._ws_manager.broadcast_to_session(session_id, {
                            "type": "listening_state",
                            "payload": {"state": "listening"}
                        }),
                        self._main_loop
                    )
                    # Give audio pipeline a moment to flush before recording
                    import time as _time
                    _time.sleep(0.15)
                    self._voice_handler.set_active_session(session_id)
                    self._voice_handler.start_recording(
                        auto_stop=True,
                        pre_speech_timeout_sec=self._relisten_pre_speech_timeout,
                    )
                else:
                    _asyncio.run_coroutine_threadsafe(
                        self._ws_manager.broadcast_to_session(session_id, {
                            "type": "listening_state",
                            "payload": {"state": "idle"}
                        }),
                        self._main_loop
                    )

    async def _handle_tts_play(self, session_id: str, client_id: str, message: dict) -> None:
        """
        Handle tts_play message sent when the user clicks the play icon in ChatView.
        Runs TTS synthesis + playback in an executor so the event loop stays free.
        """
        text = (message.get("payload") or {}).get("text", "").strip()
        if not text:
            return
        import asyncio
        loop = asyncio.get_running_loop()
        try:
            await self._ws_manager.send_to_client(client_id, {
                "type": "listening_state",
                "payload": {"state": "speaking"},
            })
            await loop.run_in_executor(None, self._speak_response, text, session_id)
        except Exception as e:
            self._logger.error(f"[Voice] tts_play error: {e}")
        finally:
            await self._ws_manager.send_to_client(client_id, {
                "type": "listening_state",
                "payload": {"state": "idle"},
            })

    async def _handle_chat(self, session_id: str, client_id: str, message: dict) -> None:
        """
        Handle chat messages: text_message, clear_chat.

        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary
        """
        msg_type = message.get("type")
        payload = message.get("payload", {})

        if msg_type == "text_message":
            text = payload.get("text")

            if not text:
                await self._send_validation_error(client_id, "text", "Message text is required")
                return

            # Get AgentKernel for this session
            try:
                import time as _time
                _t_gate = _time.perf_counter()

                agent_kernel = get_agent_kernel(session_id)
                _t_kernel = _time.perf_counter()
                self._logger.debug(
                    f"[Timing] get_agent_kernel: {(_t_kernel - _t_gate) * 1000:.1f} ms",
                    extra={"session_id": session_id}
                )

                # Wire tool bridge if not already set (enables real tool execution)
                from backend.agent.tool_bridge import get_agent_tool_bridge
                if agent_kernel._tool_bridge is None:
                    agent_kernel._tool_bridge = get_agent_tool_bridge()

                _t_bridge = _time.perf_counter()
                self._logger.debug(
                    f"[Timing] tool_bridge wire: {(_t_bridge - _t_kernel) * 1000:.1f} ms",
                    extra={"session_id": session_id}
                )

                # Signal ChatView: AI is processing (typing indicator only — does NOT affect orb)
                await self._ws_manager.send_to_client(client_id, {
                    "type": "chat_typing",
                    "payload": {"active": True}
                })

                # Process message in executor to avoid blocking event loop
                loop = asyncio.get_running_loop()
                _t_exec_start = _time.perf_counter()

                def _execute_agent():
                    try:
                        response = agent_kernel.process_text_message(
                            text,
                            session_id=session_id,
                            chunk_callback=lambda chunk: asyncio.run_coroutine_threadsafe(
                                self._ws_manager.send_to_client(client_id, {
                                    "type": "chat_chunk",
                                    "payload": {"chunk": chunk}
                                }),
                                self._main_loop
                            )
                        )
                    except Exception as e:
                        self._logger.error(f"[Chat] Agent processing error: {e}")
                        raise

                    return response

                response = await loop.run_in_executor(None, _execute_agent)

                _t_exec_end = _time.perf_counter()
                _elapsed_ms = round((_t_exec_end - _t_exec_start) * 1000)
                self._logger.info(
                    f"[Timing] process_text_message (streamed): {_elapsed_ms:.0f} ms",
                    extra={"session_id": session_id}
                )

                # Emit inference_event for InferenceConsolePanel
                try:
                    _prompt_tok = max(1, len(text) // 4)
                    _comp_tok = max(1, len(response or "") // 4)
                    _elapsed_s = _elapsed_ms / 1000 or 0.001
                    _model_name = getattr(agent_kernel, "_selected_reasoning_model", None) or "local-model"
                    _lms_ep = getattr(agent_kernel, "_lmstudio_endpoint", None) or ""
                    if _lms_ep:
                        await self._ws_manager.broadcast_to_session(session_id, {
                            "type": "inference_event",
                            "payload": {
                                "model": _model_name,
                                "prompt_tokens": _prompt_tok,
                                "completion_tokens": _comp_tok,
                                "total_tokens": _prompt_tok + _comp_tok,
                                "time_ms": _elapsed_ms,
                                "tps": round(_comp_tok / _elapsed_s, 1),
                                "timestamp": _time.time(),
                            },
                        })
                except Exception:
                    pass  # never block the response

                # Send final complete message (updates the UI with the full text + metadata)
                thinking = getattr(agent_kernel, "_pending_thinking", "") or ""
                await self._ws_manager.send_to_client(client_id, {
                    "type": "chat_message",
                    "payload": {
                        "role": "assistant",
                        "content": response,
                        "thinking": thinking,
                        "timestamp": datetime.now().isoformat()
                    }
                })

                # Clear ChatView typing indicator
                await self._ws_manager.send_to_client(client_id, {
                    "type": "chat_typing",
                    "payload": {"active": False}
                })

            except Exception as e:
                self._logger.error(
                    f"Error processing text message: {e}", exc_info=True)
                # Clear typing indicator on error
                await self._ws_manager.send_to_client(client_id, {
                    "type": "chat_typing",
                    "payload": {"active": False}
                })
                await self._send_error(client_id, f"Agent kernel error: {str(e)}")

        elif msg_type == "clear_chat":
            # Get AgentKernel for this session and clear conversation
            try:
                agent_kernel = get_agent_kernel(session_id)
                agent_kernel.clear_conversation()

                self._logger.info(
                    f"Conversation cleared for session {session_id}")

                await self._ws_manager.send_to_client(client_id, {
                    "type": "chat_cleared",
                    "payload": {}
                })

            except Exception as e:
                self._logger.error(f"Error clearing chat: {e}", exc_info=True)
                await self._send_error(client_id, f"Error clearing chat: {str(e)}")

    async def _handle_status(self, session_id: str, client_id: str, message: dict) -> None:
        """
        Handle status messages: get_agent_status, get_agent_tools.
        GAP-02 FIX: Also supports agent_status and agent_tools (legacy from main.py).

        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary
        """
        msg_type = message.get("type")

        # GAP-02: Support both get_agent_status (new) and agent_status (legacy)
        if msg_type in ["get_agent_status", "agent_status"]:
            # Get AgentKernel status for this session
            try:
                agent_kernel = get_agent_kernel(session_id)
                status = agent_kernel.get_status()

                await self._ws_manager.send_to_client(client_id, {
                    "type": "agent_status",
                    "payload": status
                })

            except Exception as e:
                self._logger.error(
                    f"Error getting agent status: {e}", exc_info=True)
                await self._ws_manager.send_to_client(client_id, {
                    "type": "agent_status",
                    "payload": {
                        "ready": False,
                        "models_loaded": 0,
                        "total_models": 0,
                        "tool_bridge_available": False,
                        "error": f"Failed to get agent status: {str(e)}"
                    }
                })

        # GAP-02: Support both get_agent_tools (new) and agent_tools (legacy)
        elif msg_type in ["get_agent_tools", "agent_tools"]:
            try:
                from backend.agent.tool_bridge import get_agent_tool_bridge
                bridge = get_agent_tool_bridge()
                tools = bridge.get_available_tools()

                await self._ws_manager.send_to_client(client_id, {
                    "type": "agent_tools",
                    "payload": {
                        "tools": tools
                    }
                })
            except Exception as e:
                self._logger.error(f"Error getting agent tools: {e}")
                await self._ws_manager.send_to_client(client_id, {
                    "type": "agent_tools",
                    "payload": {"tools": [], "error": str(e)}
                })

    async def _handle_get_available_models(self, session_id: str, client_id: str, message: dict) -> None:
        """
        Handle get_available_models message - dynamically query models from the active inference source.

        Inference modes:
        - "Local Models"  → query Ollama at configured endpoint (default http://localhost:11434)
        - "VPS Gateway"   → probe vps_url/v1/models or return VPS fallback list
        - "OpenAI API"    → query openai.com/v1/models with api_key or return GPT fallback list

        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary
        """
        try:
            # Get session-specific field values
            session_state = await self._state_manager._get_session_state_manager(session_id)

            # Defaults — overridden by whatever the user saved in their settings card.
            inference_mode = "lmstudio"
            vps_url = ""
            openai_api_key = ""
            api_base_url = "https://api.openai.com/v1"
            ollama_endpoint = "http://localhost:11434"
            lmstudio_endpoint = "http://localhost:1234"

            if session_state:
                # model_provider: 'lmstudio' | 'local' | 'api' | 'vps'
                inference_mode = await session_state.get_field_value("model_selection", "model_provider", "lmstudio") or "lmstudio"
                vps_url = await session_state.get_field_value("model_selection", "vps_endpoint", "") or ""
                openai_api_key = await session_state.get_field_value("model_selection", "api_key", "") or ""
                api_base_url = await session_state.get_field_value("model_selection", "api_base_url", "https://api.openai.com/v1") or "https://api.openai.com/v1"
                lmstudio_endpoint = await session_state.get_field_value("model_selection", "lmstudio_endpoint", "http://localhost:1234") or "http://localhost:1234"
                ollama_endpoint = await session_state.get_field_value("model_selection", "ollama_endpoint", "http://localhost:11434") or "http://localhost:11434"

            self._logger.info(
                f"[Session: {session_id}] Getting available models for provider: {inference_mode}"
            )

            available_models = []

            # Vision-only models should NOT appear in reasoning/tool dropdowns.
            # They belong exclusively in the vision_model dropdown.
            _VISION_ONLY_PREFIXES = (
                "lfm2.5-vl", "llava", "bakllava", "llava-llama3", "llava-phi3",
                "moondream", "cogvlm", "internvl",
            )

            def _is_vision_only(model_id: str) -> bool:
                """Check if a model is vision-only based on its name/id.

                Handles namespaced IDs like 'openbmb/minicpm-o4.5:latest' by
                checking both the full name and the part after the last '/'.
                """
                name_lower = model_id.lower().split(
                    ":")[0]  # strip tag like ":latest"
                # Also check the base name after namespace (e.g. "openbmb/minicpm-o4.5" → "minicpm-o4.5")
                base_name = name_lower.rsplit(
                    "/", 1)[-1] if "/" in name_lower else name_lower
                return (
                    any(name_lower.startswith(p) for p in _VISION_ONLY_PREFIXES) or
                    any(base_name.startswith(p) for p in _VISION_ONLY_PREFIXES)
                )

            if inference_mode == "local":
                # Query Ollama for locally installed models
                try:
                    async with httpx.AsyncClient(timeout=3.0) as http_client:
                        r = await http_client.get(f"{ollama_endpoint.rstrip('/')}/api/tags")
                        if r.status_code == 200:
                            tags = r.json().get("models", [])
                            # Exclude vision-only models from reasoning/tool list
                            available_models = [
                                {"id": m["name"], "name": m["name"],
                                    "source": "local"}
                                for m in tags
                                if not _is_vision_only(m["name"])
                            ]
                            self._logger.info(
                                f"[Session: {session_id}] Found {len(available_models)} Ollama model(s) "
                                f"({len(tags) - len(available_models)} vision-only filtered out)"
                            )
                        else:
                            self._logger.warning(
                                f"[Session: {session_id}] Ollama returned status {r.status_code}"
                            )
                except Exception as ollama_err:
                    self._logger.warning(
                        f"[Session: {session_id}] Ollama not reachable at {ollama_endpoint}: {ollama_err}"
                    )

                # Scan the local models/ directory for HuggingFace-format models
                # (e.g. LFM2.5-1.2B-Instruct, LFM2-8B-A1B) that aren't in Ollama.
                # NOTE: subprocess.run() blocks the asyncio event loop; use
                # run_in_executor to perform the git worktree discovery off-thread.
                try:
                    from pathlib import Path
                    import concurrent.futures as _cf

                    # Resolve project root (handles git worktrees)
                    project_dir = Path(__file__).parent.parent.resolve()
                    models_dir = project_dir / "models"

                    # If we're in a worktree, also check the main repo's models dir.
                    # Run the blocking git commands in a thread so the event loop
                    # stays free to handle WebSocket messages (including ping/pong).
                    def _find_model_dirs():
                        import subprocess
                        dirs = [models_dir]
                        try:
                            result = subprocess.run(
                                ["git", "rev-parse", "--show-toplevel"],
                                capture_output=True, text=True, timeout=3,
                                cwd=str(project_dir),
                            )
                            common = subprocess.run(
                                ["git", "rev-parse", "--git-common-dir"],
                                capture_output=True, text=True, timeout=3,
                                cwd=str(project_dir),
                            )
                            if result.returncode == 0 and common.returncode == 0:
                                wt_root = Path(result.stdout.strip()).resolve()
                                main_root = Path(
                                    common.stdout.strip()).resolve().parent
                                if wt_root != main_root:
                                    try:
                                        rel = project_dir.relative_to(wt_root)
                                        main_models = main_root / rel / "models"
                                        if main_models != models_dir:
                                            dirs.append(main_models)
                                    except ValueError:
                                        pass
                        except Exception:
                            pass
                        return dirs

                    loop = asyncio.get_event_loop()
                    candidates = await loop.run_in_executor(None, _find_model_dirs)

                    ollama_ids = {m["id"] for m in available_models}
                    for mdir in candidates:
                        if not mdir.is_dir():
                            continue
                        for child in sorted(mdir.iterdir()):
                            if not child.is_dir():
                                continue
                            config_file = child / "config.json"
                            if not config_file.exists():
                                continue
                            # It's a HuggingFace model directory
                            model_name = child.name
                            if model_name in ollama_ids:
                                continue
                            if _is_vision_only(model_name):
                                continue
                            # Skip non-model dirs (cache, wake_words, etc.)
                            if model_name.lower() in ("cache", "wake_words", "audio_detokenizer"):
                                continue
                            available_models.append({
                                "id": str(child),
                                "name": model_name,
                                "source": "local_hf",
                            })
                    hf_count = sum(1 for m in available_models if m.get(
                        "source") == "local_hf")
                    if hf_count:
                        self._logger.info(
                            f"[Session: {session_id}] Found {hf_count} local HuggingFace model(s)"
                        )
                except Exception as scan_err:
                    self._logger.warning(
                        f"[Session: {session_id}] Local model scan failed: {scan_err}"
                    )

                # Fallback: show popular Ollama models when the daemon is not running
                # and no local HuggingFace models were found either
                if not available_models:
                    available_models = [
                        {"id": "llama3.2",
                            "name": "Llama 3.2 (3B)", "source": "local"},
                        {"id": "llama3.2:1b",
                            "name": "Llama 3.2 (1B)", "source": "local"},
                        {"id": "llama3.1",
                            "name": "Llama 3.1 (8B)", "source": "local"},
                        {"id": "mistral", "name": "Mistral 7B", "source": "local"},
                        {"id": "qwen2.5:3b",
                            "name": "Qwen 2.5 (3B)", "source": "local"},
                        {"id": "phi4",
                            "name": "Phi-4 (14B)", "source": "local"},
                        {"id": "deepseek-r1:7b",
                            "name": "DeepSeek R1 (7B)", "source": "local"},
                        {"id": "codellama", "name": "Code Llama", "source": "local"},
                    ]
                    self._logger.info(
                        f"[Session: {session_id}] No models found — returning fallback list"
                    )

            elif inference_mode == "lmstudio":
                # LM Studio exposes an OpenAI-compatible REST API at localhost:1234.
                # Query /v1/models to get whatever model(s) the user currently has loaded.
                try:
                    async with httpx.AsyncClient(timeout=3.0) as http_client:
                        r = await http_client.get(
                            f"{lmstudio_endpoint.rstrip('/')}/v1/models",
                            headers={"Authorization": "Bearer lm-studio"},
                        )
                        if r.status_code == 200:
                            models_data = r.json().get("data", [])
                            available_models = [
                                {
                                    "id": m["id"],
                                    "name": m.get("id", m["id"]),
                                    "source": "lmstudio",
                                }
                                for m in models_data
                                if not _is_vision_only(m.get("id", ""))
                            ]
                            self._logger.info(
                                f"[Session: {session_id}] LM Studio: found {len(available_models)} model(s)"
                            )
                        else:
                            self._logger.warning(
                                f"[Session: {session_id}] LM Studio returned status {r.status_code}"
                            )
                except Exception as lms_err:
                    self._logger.warning(
                        f"[Session: {session_id}] LM Studio not reachable at {lmstudio_endpoint}: {lms_err}"
                    )

                # Fallback: common models users load in LM Studio
                if not available_models:
                    available_models = [
                        {"id": "local-model", "name": "Currently Loaded Model",
                            "source": "lmstudio"},
                        {"id": "llama-3.2-3b-instruct",
                            "name": "Llama 3.2 3B Instruct", "source": "lmstudio"},
                        {"id": "llama-3.1-8b-instruct",
                            "name": "Llama 3.1 8B Instruct", "source": "lmstudio"},
                        {"id": "mistral-7b-instruct-v0.3",
                            "name": "Mistral 7B Instruct", "source": "lmstudio"},
                        {"id": "qwen2.5-7b-instruct",
                            "name": "Qwen 2.5 7B Instruct", "source": "lmstudio"},
                        {"id": "deepseek-r1-distill-qwen-7b",
                            "name": "DeepSeek R1 7B", "source": "lmstudio"},
                    ]
                    self._logger.info(
                        f"[Session: {session_id}] LM Studio unreachable — showing fallback model list"
                    )

            elif inference_mode == "api":
                # Query the user-configured API base URL for available models.
                # Works with OpenAI, Groq, Together, OpenRouter, Mistral, or any
                # OpenAI-compatible remote API.
                models_url = f"{api_base_url.rstrip('/')}/models"
                headers = {}
                if openai_api_key:
                    headers["Authorization"] = f"Bearer {openai_api_key}"
                try:
                    async with httpx.AsyncClient(timeout=5.0) as http_client:
                        r = await http_client.get(models_url, headers=headers)
                        if r.status_code == 200:
                            models_data = r.json().get("data", [])
                            available_models = [
                                {"id": m["id"], "name": m.get("id", m["id"]),
                                    "source": "api"}
                                for m in models_data
                                if not _is_vision_only(m.get("id", ""))
                            ]
                            self._logger.info(
                                f"[Session: {session_id}] Found {len(available_models)} model(s) "
                                f"from {api_base_url}"
                            )
                except Exception as api_err:
                    self._logger.warning(
                        f"[Session: {session_id}] API models query failed ({api_base_url}): {api_err}"
                    )

                # Fallback list if no key or query failed
                if not available_models:
                    available_models = [
                        {"id": "gpt-4o", "name": "GPT-4o", "source": "openai"},
                        {"id": "gpt-4-turbo", "name": "GPT-4 Turbo",
                            "source": "openai"},
                        {"id": "gpt-4", "name": "GPT-4", "source": "openai"},
                        {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo",
                            "source": "openai"},
                    ]

            elif inference_mode == "vps":
                # Try to query the VPS endpoint for models
                if vps_url:
                    try:
                        async with httpx.AsyncClient(timeout=3.0) as http_client:
                            r = await http_client.get(f"{vps_url.rstrip('/')}/v1/models")
                            if r.status_code == 200:
                                models_data = r.json().get("data", [])
                                available_models = [
                                    {"id": m["id"], "name": m["id"],
                                        "source": "vps"}
                                    for m in models_data
                                ]
                                self._logger.info(
                                    f"[Session: {session_id}] Found {len(available_models)} VPS model(s)"
                                )
                    except Exception as vps_err:
                        self._logger.warning(
                            f"[Session: {session_id}] VPS endpoint query failed: {vps_err}"
                        )

                # Fallback list if no endpoint or query failed
                if not available_models:
                    available_models = [
                        {"id": "lfm2-8b", "name": "LFM2 8B", "source": "vps"},
                        {"id": "lfm2.5-1.2b-instruct",
                            "name": "LFM2.5 1.2B Instruct", "source": "vps"},
                    ]

            elif inference_mode == "iris_local":
                # llama-cpp-python server on port 8082.
                # Only shows a model when one is actively loaded.
                try:
                    from .agent.local_model_manager import get_local_model_manager
                    mgr = get_local_model_manager()
                    if mgr.is_loaded():
                        status = mgr.get_status()
                        from pathlib import Path as _Path
                        model_name = _Path(status["model_path"]).stem if status.get("model_path") else "gguf-model"
                        available_models = [{"id": model_name, "name": model_name, "source": "iris_local"}]
                    else:
                        available_models = []
                    self._logger.info(
                        f"[Session: {session_id}] iris_local models: {len(available_models)} loaded"
                    )
                except Exception as il_err:
                    self._logger.warning(f"[Session: {session_id}] iris_local query failed: {il_err}")

            await self._ws_manager.send_to_client(client_id, {
                "type": "available_models",
                "payload": {
                    "models": available_models,
                    "model_provider": inference_mode,   # 'lmstudio' | 'local' | 'api' | 'vps'
                    "inference_mode": inference_mode    # kept for backward compat
                }
            })

        except Exception as e:
            self._logger.error(
                f"Error getting available models: {e}", exc_info=True)
            await self._ws_manager.send_to_client(client_id, {
                "type": "available_models",
                "payload": {
                    "models": [],
                    "error": f"Failed to get available models: {str(e)}"
                }
            })

    async def _handle_request_models(self, session_id: str, client_id: str, message: dict) -> None:
        """
        Handle request_models message - lazy load models from Ollama with caching.
        Task 7.4: Implements lazy loading for model dropdowns with 5-minute cache.

        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary with optional 'endpoint' in payload
        """
        payload = message.get("payload", {})
        endpoint = payload.get("endpoint", "http://localhost:11434")

        # Check cache first
        cached_models, cache_time = self._model_cache.get(
            endpoint, (None, None))
        if cached_models and cache_time and (datetime.now() - cache_time) < self._model_cache_ttl:
            self._logger.info(
                f"[IRISGateway] Returning cached models for {endpoint}")
            await self._ws_manager.send_to_client(client_id, {
                "type": "models_loaded",
                "payload": {
                    "models": cached_models,
                    "endpoint": endpoint,
                    "cached": True
                }
            })
            return

        # Fetch models from Ollama
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{endpoint}/api/tags")

                if response.status_code == 200:
                    data = response.json()
                    models = [model["name"]
                              for model in data.get("models", [])]

                    # Cache the results
                    self._model_cache[endpoint] = (models, datetime.now())

                    self._logger.info(
                        f"[IRISGateway] Loaded {len(models)} models from Ollama at {endpoint}")

                    await self._ws_manager.send_to_client(client_id, {
                        "type": "models_loaded",
                        "payload": {
                            "models": models,
                            "endpoint": endpoint,
                            "cached": False
                        }
                    })
                else:
                    error_msg = f"Ollama returned status {response.status_code}"
                    self._logger.error(f"[IRISGateway] {error_msg}")
                    await self._ws_manager.send_to_client(client_id, {
                        "type": "models_loaded",
                        "payload": {
                            "models": [],
                            "endpoint": endpoint,
                            "error": error_msg
                        }
                    })

        except httpx.ConnectError as e:
            error_msg = f"Cannot connect to Ollama at {endpoint}. Is Ollama running?"
            self._logger.error(f"[IRISGateway] {error_msg}: {e}")
            await self._ws_manager.send_to_client(client_id, {
                "type": "models_loaded",
                "payload": {
                    "models": [],
                    "endpoint": endpoint,
                    "error": error_msg
                }
            })
        except httpx.TimeoutException:
            error_msg = f"Connection to Ollama at {endpoint} timed out"
            self._logger.error(f"[IRISGateway] {error_msg}")
            await self._ws_manager.send_to_client(client_id, {
                "type": "models_loaded",
                "payload": {
                    "models": [],
                    "endpoint": endpoint,
                    "error": error_msg
                }
            })
        except Exception as e:
            error_msg = f"Failed to fetch models: {str(e)}"
            self._logger.error(f"[IRISGateway] {error_msg}", exc_info=True)
            await self._ws_manager.send_to_client(client_id, {
                "type": "models_loaded",
                "payload": {
                    "models": [],
                    "endpoint": endpoint,
                    "error": error_msg
                }
            })

    async def _handle_set_model_selection(self, session_id: str, client_id: str, message: dict) -> None:
        """
        Handle set_model_selection message - set user-selected models for reasoning and tool execution.

        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary with reasoning_model and tool_execution_model
        """
        payload = message.get("payload", {})
        reasoning_model = payload.get("reasoning_model")
        tool_execution_model = payload.get("tool_execution_model")

        try:
            # Get AgentKernel for this session
            agent_kernel = get_agent_kernel(session_id)

            # Set model selection
            success = agent_kernel.set_model_selection(
                reasoning_model, tool_execution_model)

            if success:
                # Update state manager with model selection
                state = await self._state_manager.get_state(session_id)
                if state:
                    state.selected_reasoning_model = reasoning_model
                    state.selected_tool_execution_model = tool_execution_model
                    # State manager will auto-save

                # Send confirmation to client
                await self._ws_manager.send_to_client(client_id, {
                    "type": "model_selection_updated",
                    "payload": {
                        "reasoning_model": reasoning_model,
                        "tool_execution_model": tool_execution_model,
                        "success": True
                    }
                })

                # Broadcast to other clients in session
                await self._ws_manager.broadcast_to_session(
                    session_id,
                    {
                        "type": "model_selection_updated",
                        "payload": {
                            "reasoning_model": reasoning_model,
                            "tool_execution_model": tool_execution_model,
                            "success": True
                        }
                    },
                    exclude_clients={client_id}
                )
            else:
                # Send error
                await self._send_error(client_id, "Failed to set model selection - models may not be available")

        except Exception as e:
            self._logger.error(
                f"Error setting model selection: {e}", exc_info=True)
            await self._send_error(client_id, f"Failed to set model selection: {str(e)}")

    async def _handle_test_connection(self, session_id: str, client_id: str, message: dict) -> None:
        """
        Handle test_connection message - test OpenAI API connection with provided credentials.

        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary with connection_type (e.g., "openai")
        """
        payload = message.get("payload", {})
        connection_type = payload.get("connection_type", "openai")

        try:
            if connection_type == "openai":
                # Get API key and URL from state or payload
                api_key = payload.get("api_key")
                api_url = payload.get("api_url")

                # If not in payload, try to get from state
                if not api_key:
                    state_manager = await self._state_manager._get_session_state_manager(session_id)
                    if state_manager:
                        api_key = await state_manager.get_decrypted_field_value("model", "openai_api_key")

                if not api_url:
                    state_manager = await self._state_manager._get_session_state_manager(session_id)
                    if state_manager:
                        api_url = await state_manager.get_field_value("model", "openai_api_url")

                # Use default URL if not provided
                if not api_url:
                    api_url = "https://api.openai.com/v1"

                if not api_key:
                    await self._ws_manager.send_to_client(client_id, {
                        "type": "connection_test_result",
                        "payload": {
                            "connection_type": "openai",
                            "success": False,
                            "message": "API key is required",
                            "tested_url": api_url
                        }
                    })
                    return

                # Test the connection
                from .utils.openai_connection_test import test_openai_connection
                success, message = await test_openai_connection(api_key, api_url)

                # Send result to client
                await self._ws_manager.send_to_client(client_id, {
                    "type": "connection_test_result",
                    "payload": {
                        "connection_type": "openai",
                        "success": success,
                        "message": message,
                        "tested_url": api_url
                    }
                })
            else:
                await self._send_error(client_id, f"Unknown connection type: {connection_type}")

        except Exception as e:
            self._logger.error(f"Error testing connection: {e}", exc_info=True)
            await self._ws_manager.send_to_client(client_id, {
                "type": "connection_test_result",
                "payload": {
                    "connection_type": connection_type,
                    "success": False,
                    "message": f"Error testing connection: {str(e)}"
                }
            })

    async def _handle_request_state(self, session_id: str, client_id: str) -> None:
        """
        Handle request_state message - send full state to client.

        Args:
            session_id: Session ID
            client_id: Client ID
        """
        state = await self._state_manager.get_state(session_id)

        await self._ws_manager.send_to_client(client_id, {
            "type": "initial_state",
            "payload": {
                "state": state.model_dump() if state else {}
            }
        })

    async def _handle_get_wake_words(self, session_id: str, client_id: str) -> None:
        """
        Handle get_wake_words message - return built-in pvporcupine keywords + discovered .ppn files.

        Args:
            session_id: Session ID
            client_id: Client ID
        """
        try:
            self._logger.info(
                f"[Session: {session_id}] Processing get_wake_words request",
                extra={"session_id": session_id, "client_id": client_id}
            )

            # 1. Get built-in pvporcupine keywords from WakeConfig class attribute
            from .agent.wake_config import WakeConfig
            builtin_list = [
                {
                    "filename": phrase.replace(" ", "_"),
                    "display_name": phrase.title(),
                    "platform": "builtin",
                    "version": "builtin",
                    "is_builtin": True
                }
                for phrase in WakeConfig.SUPPORTED_PHRASES
            ]

            # 2. Rescan the wake words directory each time to pick up newly added .ppn files
            #    (scan_directory is a fast glob — safe to call on each get_wake_words request)
            discovered_files = self._wake_word_discovery.scan_directory()
            custom_list = [
                {
                    "filename": wf.filename,
                    "display_name": wf.display_name,
                    "platform": wf.platform,
                    "version": wf.version,
                    "is_builtin": False
                }
                for wf in discovered_files
            ]

            # 3. Combine: built-ins first, then custom files
            wake_words_list = builtin_list + custom_list

            self._logger.info(
                f"[Session: {session_id}] Returning {len(wake_words_list)} wake word(s) "
                f"({len(builtin_list)} built-in, {len(custom_list)} custom)",
                extra={"session_id": session_id, "client_id": client_id,
                       "count": len(wake_words_list)}
            )

            # Send response to client — type "wake_words" matches the frontend hook's case "wake_words"
            await self._ws_manager.send_to_client(client_id, {
                "type": "wake_words",
                "payload": {
                    "wake_words": wake_words_list,
                    "count": len(wake_words_list)
                }
            })

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error handling get_wake_words: {e}",
                exc_info=True,
                extra={"session_id": session_id,
                       "client_id": client_id, "error": str(e)}
            )
            await self._send_error(client_id, f"Error retrieving wake words: {str(e)}")

    async def _handle_get_audio_devices(self, session_id: str, client_id: str) -> None:
        """
        Handle get_audio_devices message - return available audio devices.

        Args:
            session_id: Session ID
            client_id: Client ID
        """
        try:
            self._logger.info(
                f"[Session: {session_id}] Processing get_audio_devices request",
                extra={"session_id": session_id, "client_id": client_id}
            )

            # Get available audio devices
            devices = AudioPipeline.list_devices()

            # Separate input and output devices
            input_devices = [
                {
                    "index": d["index"],
                    "name": d["name"],
                    "sample_rate": d["sample_rate"]
                }
                for d in devices if d["input"]
            ]
            output_devices = [
                {
                    "index": d["index"],
                    "name": d["name"],
                    "sample_rate": d["sample_rate"]
                }
                for d in devices if d["output"]
            ]

            self._logger.info(
                f"[Session: {session_id}] Returning {len(input_devices)} input device(s) and {len(output_devices)} output device(s)",
                extra={"session_id": session_id, "client_id": client_id, "input_count": len(
                    input_devices), "output_count": len(output_devices)}
            )

            # Send response to client
            await self._ws_manager.send_to_client(client_id, {
                "type": "audio_devices",
                "payload": {
                    "input_devices": input_devices,
                    "output_devices": output_devices,
                    "input_count": len(input_devices),
                    "output_count": len(output_devices)
                }
            })

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error handling get_audio_devices: {e}",
                exc_info=True,
                extra={"session_id": session_id,
                       "client_id": client_id, "error": str(e)}
            )
            await self._send_error(client_id, f"Error retrieving audio devices: {str(e)}")

    async def _handle_select_wake_word(self, session_id: str, client_id: str, message: dict) -> None:
        """
        Handle select_wake_word message - load wake word file into PorcupineDetector.

        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary containing filename in payload
        """
        try:
            # Extract filename from message
            filename = message.get("payload", {}).get("filename")

            if not filename:
                self._logger.warning(
                    f"[Session: {session_id}] select_wake_word missing filename",
                    extra={"session_id": session_id, "client_id": client_id}
                )
                await self._send_error(client_id, "No filename provided")
                return

            self._logger.info(
                f"[Session: {session_id}] Processing select_wake_word: {filename}",
                extra={"session_id": session_id, "client_id": client_id,
                       "wake_word_filename": filename}
            )

            # Look up wake word file — try cached results first, rescan if not found
            wake_word_file = self._wake_word_discovery.get_file_by_filename(
                filename)
            if not wake_word_file:
                # Cache may be stale (e.g., select_wake_word called before get_wake_words).
                # Rescan once to pick up newly visible .ppn files.
                self._wake_word_discovery.scan_directory()
                wake_word_file = self._wake_word_discovery.get_file_by_filename(
                    filename)

            if not wake_word_file:
                self._logger.warning(
                    f"[Session: {session_id}] Wake word file not found: {filename}",
                    extra={"session_id": session_id, "client_id": client_id,
                           "wake_word_filename": filename}
                )
                await self._send_error(client_id, f"Wake word file not found: {filename}")
                return

            # Update WakeConfig — the registered callback triggers reinitialize_porcupine().
            # Custom .ppn files store the absolute path; built-ins use the keyword name.
            try:
                from .agent.wake_config import get_wake_config
                wake_config = get_wake_config()
                is_builtin = (wake_word_file.platform == "builtin")
                if is_builtin:
                    wake_config.update_config(
                        wake_phrase=wake_word_file.display_name.lower(),
                        custom_model_path=None
                    )
                else:
                    wake_config.update_config(
                        wake_phrase=wake_word_file.display_name,
                        custom_model_path=wake_word_file.path
                    )
                self._logger.info(
                    f"[Session: {session_id}] Wake word updated: '{wake_word_file.display_name}' "
                    f"({'builtin' if is_builtin else wake_word_file.path})",
                    extra={
                        "session_id": session_id,
                        "client_id": client_id,
                        "wake_word_filename": wake_word_file.filename,
                        "display_name": wake_word_file.display_name,
                        "platform": wake_word_file.platform
                    }
                )
            except Exception as cfg_e:
                self._logger.error(
                    f"[Session: {session_id}] Failed to update WakeConfig for wake word: {cfg_e}",
                    extra={"session_id": session_id, "client_id": client_id}
                )

            # Broadcast selection to all clients in session
            await self._ws_manager.broadcast_to_session(session_id, {
                "type": "wake_word_selected",
                "payload": {
                    "filename": wake_word_file.filename,
                    "display_name": wake_word_file.display_name,
                    "platform": wake_word_file.platform,
                    "version": wake_word_file.version
                }
            })

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error handling select_wake_word: {e}",
                exc_info=True,
                extra={"session_id": session_id,
                       "client_id": client_id, "error": str(e)}
            )
            await self._send_error(client_id, f"Error selecting wake word: {str(e)}")

    async def _handle_get_cleanup_report(self, session_id: str, client_id: str, message: dict) -> None:
        """
        Handle get_cleanup_report message - generates cleanup report and sends to client.

        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary with optional 'dry_run' in payload
        """
        try:
            payload = message.get("payload", {})
            dry_run = payload.get("dry_run", True)

            self._logger.info(
                f"[Session: {session_id}] Generating cleanup report (dry_run={dry_run})",
                extra={"session_id": session_id,
                       "client_id": client_id, "dry_run": dry_run}
            )

            # Generate cleanup report
            report = self._cleanup_analyzer.generate_report(dry_run=dry_run)

            # Convert report to dict for JSON serialization
            report_dict = {
                "unused_models": [
                    {
                        "path": f.path,
                        "size_bytes": f.size_bytes,
                        "last_accessed": f.last_accessed.isoformat(),
                        "reason": f.reason
                    }
                    for f in report.unused_models
                ],
                "unused_dependencies": [
                    {
                        "name": d.name,
                        "version": d.version,
                        "install_size_bytes": d.install_size_bytes,
                        "reason": d.reason
                    }
                    for d in report.unused_dependencies
                ],
                "unused_wake_words": [
                    {
                        "path": f.path,
                        "size_bytes": f.size_bytes,
                        "last_accessed": f.last_accessed.isoformat(),
                        "reason": f.reason
                    }
                    for f in report.unused_wake_words
                ],
                "unused_configs": [
                    {
                        "path": f.path,
                        "size_bytes": f.size_bytes,
                        "last_accessed": f.last_accessed.isoformat(),
                        "reason": f.reason
                    }
                    for f in report.unused_configs
                ],
                "total_size_bytes": report.total_size_bytes,
                "total_count": report.total_count,
                "warnings": report.warnings,
                "timestamp": report.timestamp.isoformat()
            }

            self._logger.info(
                f"[Session: {session_id}] Cleanup report generated: "
                f"{report.total_count} items, {report.total_size_bytes / (1024*1024):.2f} MB",
                extra={
                    "session_id": session_id,
                    "total_count": report.total_count,
                    "total_size_mb": report.total_size_bytes / (1024*1024)
                }
            )

            # Send report to client
            await self._ws_manager.send_to_client(client_id, {
                "type": "cleanup_report",
                "payload": report_dict
            })

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error generating cleanup report: {e}",
                exc_info=True,
                extra={"session_id": session_id,
                       "client_id": client_id, "error": str(e)}
            )
            await self._send_error(client_id, f"Error generating cleanup report: {str(e)}")

    async def _handle_execute_cleanup(self, session_id: str, client_id: str, message: dict) -> None:
        """
        Handle execute_cleanup message - executes cleanup with specified items and sends result.

        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary with 'items' in payload
        """
        try:
            payload = message.get("payload", {})
            items = payload.get("items", [])

            if not items:
                await self._send_error(client_id, "No items specified for cleanup")
                return

            self._logger.info(
                f"[Session: {session_id}] Executing cleanup for {len(items)} item(s)",
                extra={"session_id": session_id,
                       "client_id": client_id, "item_count": len(items)}
            )

            # Execute cleanup
            result = self._cleanup_analyzer.execute_cleanup(items)

            # Convert result to dict for JSON serialization
            result_dict = {
                "success": result.success,
                "removed_files": result.removed_files,
                "removed_dependencies": result.removed_dependencies,
                "freed_bytes": result.freed_bytes,
                "errors": result.errors,
                "backup_path": result.backup_path
            }

            self._logger.info(
                f"[Session: {session_id}] Cleanup executed: "
                f"success={result.success}, freed {result.freed_bytes / (1024*1024):.2f} MB",
                extra={
                    "session_id": session_id,
                    "success": result.success,
                    "freed_mb": result.freed_bytes / (1024*1024),
                    "removed_files": len(result.removed_files),
                    "removed_deps": len(result.removed_dependencies),
                    "errors": len(result.errors)
                }
            )

            # Send result to client
            await self._ws_manager.send_to_client(client_id, {
                "type": "cleanup_result",
                "payload": result_dict
            })

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error executing cleanup: {e}",
                exc_info=True,
                extra={"session_id": session_id,
                       "client_id": client_id, "error": str(e)}
            )
            await self._send_error(client_id, f"Error executing cleanup: {str(e)}")

    # ============================================================================
    # GAP-01 FIX: Additional handlers from main.py
    # ============================================================================

    async def _handle_collapse_to_idle(self, session_id: str, client_id: str, message: dict) -> None:
        """
        Handle collapse_to_idle message - collapse navigation to idle state.

        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary
        """
        try:
            self._logger.info(
                f"[Session: {session_id}] Collapsing to idle",
                extra={"session_id": session_id, "client_id": client_id}
            )

            await self._state_manager.collapse_to_idle(session_id)
            await self._broadcast_state_update(session_id, exclude_client=client_id)

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error collapsing to idle: {e}",
                exc_info=True,
                extra={"session_id": session_id,
                       "client_id": client_id, "error": str(e)}
            )
            await self._send_error(client_id, f"Error collapsing to idle: {str(e)}")

    async def _handle_expand_to_main(self, session_id: str, client_id: str, message: dict) -> None:
        """
        Handle expand_to_main message - expand to main category view.
        GAP-02 FIX: Handler for expand_to_main message type.

        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary
        """
        try:
            self._logger.info(
                f"[Session: {session_id}] Expanding to main view",
                extra={"session_id": session_id, "client_id": client_id}
            )

            # Send confirmation to client
            await self._ws_manager.send_to_client(client_id, {
                "type": "category_expanded",
                "payload": {}
            })

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error expanding to main: {e}",
                exc_info=True,
                extra={"session_id": session_id,
                       "client_id": client_id, "error": str(e)}
            )
            await self._send_error(client_id, f"Error expanding to main: {str(e)}")

    async def _handle_reload_skills(self, session_id: str, client_id: str, message: dict) -> None:
        """
        Handle reload_skills message - reload skills configuration.

        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary
        """
        try:
            self._logger.info(
                f"[Session: {session_id}] Reloading skills",
                extra={"session_id": session_id, "client_id": client_id}
            )

            from backend.agent.skills import get_skills_loader
            loader = get_skills_loader()
            loader.reload()

            await self._ws_manager.send_to_client(client_id, {
                "type": "skills_reloaded",
                "payload": {"skills": loader.list_skills()}
            })

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error reloading skills: {e}",
                exc_info=True,
                extra={"session_id": session_id,
                       "client_id": client_id, "error": str(e)}
            )
            await self._ws_manager.send_to_client(client_id, {
                "type": "skills_error",
                "payload": {"error": str(e)}
            })

    # ============================================================================
    # GAP-06 & GAP-11: Session Cleanup
    # ============================================================================

    async def cleanup_session(self, session_id: str) -> None:
        """
        Clean up session resources including voice callbacks.
        GAP-06 & GAP-11 FIX: Unregisters voice callbacks and cleans up session resources.

        Args:
            session_id: Session ID to clean up
        """
        try:
            self._logger.info(
                f"[Session: {session_id}] Cleaning up session resources")

            # Remove active voice client tracking
            self._active_voice_client.pop(session_id, None)

            # Reset per-session LFM ChatState
            try:
                from .audio.engine import get_audio_engine
                engine = get_audio_engine()
                if engine.model_manager and engine.model_manager.is_loaded:
                    engine.model_manager.reset_session(session_id)
            except Exception:
                pass

            self._logger.info(
                f"[Session: {session_id}] Session cleanup completed")

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error during cleanup: {e}",
                exc_info=True,
            )

    async def _handle_execute_tool(self, session_id: str, client_id: str, message: dict) -> None:
        """
        Handle execute_tool message - execute a specific tool directly.

        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary
        """
        try:
            payload = message.get("payload", {})
            tool_name = payload.get("tool_name")
            parameters = payload.get("parameters", {})

            if not tool_name:
                await self._send_validation_error(client_id, "tool_name", "Tool name is required")
                return

            self._logger.info(
                f"[Session: {session_id}] Executing tool: {tool_name}",
                extra={"session_id": session_id,
                       "client_id": client_id, "tool": tool_name}
            )

            # Get agent kernel from app state via global
            from backend.agent import get_agent_kernel
            from backend.agent.tool_bridge import get_agent_tool_bridge
            agent_kernel = get_agent_kernel(session_id)

            # Wire tool bridge if not already set
            if agent_kernel and agent_kernel._tool_bridge is None:
                agent_kernel._tool_bridge = get_agent_tool_bridge()

            if agent_kernel and agent_kernel._tool_bridge:
                try:
                    result = await agent_kernel._tool_bridge.execute_tool(tool_name, parameters)
                    await self._ws_manager.send_to_client(client_id, {
                        "type": "tool_result",
                        "payload": {"tool": tool_name, "result": result}
                    })
                except Exception as e:
                    await self._ws_manager.send_to_client(client_id, {
                        "type": "tool_result",
                        "payload": {"tool": tool_name, "error": str(e)}
                    })
            else:
                await self._ws_manager.send_to_client(client_id, {
                    "type": "tool_result",
                    "payload": {"tool": tool_name, "error": "Tool bridge not available"}
                })

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error executing tool: {e}",
                exc_info=True,
                extra={"session_id": session_id,
                       "client_id": client_id, "error": str(e)}
            )
            await self._send_error(client_id, f"Error executing tool: {str(e)}")

    async def _handle_enable_vision(self, session_id: str, client_id: str) -> None:
        """
        Handle enable_vision message — checks if LFM2.5-VL llama-server is reachable.
        Vision is a separate process (llama-server port 8081); enabling = health check.
        """
        try:
            self._logger.info(f"[Session: {session_id}] Checking vision server availability")

            # Send loading status while we check
            await self._ws_manager.send_to_client(client_id, {
                "type": "vision_status",
                "payload": {
                    "status": "loading",
                    "vram_usage_mb": None,
                    "load_progress_percent": None,
                    "error_message": None,
                    "model_name": "lfm2.5-vl",
                    "quantization_enabled": False,
                    "is_available": False
                }
            })

            import asyncio
            available = await asyncio.get_event_loop().run_in_executor(
                None, self._vision_provider.health_check
            )

            status_payload = {
                "status": "enabled" if available else "error",
                "vram_usage_mb": None,
                "load_progress_percent": None,
                "error_message": None if available else "Vision server not running on port 8081. Start start_vl.bat first.",
                "model_name": "lfm2.5-vl",
                "quantization_enabled": False,
                "is_available": available
            }

            await self._ws_manager.send_to_client(client_id, {
                "type": "enable_vision",
                "payload": {"success": available, "error": status_payload.get("error_message")}
            })
            await self._ws_manager.broadcast_to_session(session_id, {
                "type": "vision_status",
                "payload": status_payload
            })

        except Exception as e:
            self._logger.error(f"[Session: {session_id}] Error enabling vision: {e}", exc_info=True)
            await self._ws_manager.send_to_client(client_id, {
                "type": "enable_vision",
                "payload": {"success": False, "error": str(e)}
            })

    async def _handle_disable_vision(self, session_id: str, client_id: str) -> None:
        """
        Handle disable_vision message.
        LFM2.5-VL is a separate process — disabling means the agent stops calling vision tools.
        """
        try:
            self._logger.info(f"[Session: {session_id}] Vision disabled by user")
            await self._ws_manager.send_to_client(client_id, {
                "type": "disable_vision",
                "payload": {"success": True}
            })
            await self._ws_manager.broadcast_to_session(session_id, {
                "type": "vision_status",
                "payload": {
                    "status": "disabled",
                    "vram_usage_mb": None,
                    "load_progress_percent": None,
                    "error_message": None,
                    "model_name": "lfm2.5-vl",
                    "quantization_enabled": False,
                    "is_available": False
                }
            })
        except Exception as e:
            self._logger.error(f"[Session: {session_id}] Error disabling vision: {e}", exc_info=True)
            await self._ws_manager.send_to_client(client_id, {
                "type": "disable_vision",
                "payload": {"success": False, "error": str(e)}
            })

    async def _handle_get_vision_status(self, session_id: str, client_id: str) -> None:
        """
        Handle get_vision_status message — pings LFM2.5-VL server.
        """
        try:
            import asyncio
            available = await asyncio.get_event_loop().run_in_executor(
                None, self._vision_provider.health_check
            )
            await self._ws_manager.send_to_client(client_id, {
                "type": "vision_status",
                "payload": {
                    "status": "enabled" if available else "error",
                    "vram_usage_mb": None,
                    "load_progress_percent": None,
                    "error_message": None if available else "Vision server not running on port 8081",
                    "model_name": "lfm2.5-vl",
                    "quantization_enabled": False,
                    "is_available": available
                }
            })
        except Exception as e:
            self._logger.error(f"[Session: {session_id}] Error getting vision status: {e}", exc_info=True)
            await self._send_error(client_id, f"Error getting vision status: {str(e)}")

    async def _handle_message_exported(self, session_id: str, client_id: str, message: dict) -> None:
        """
        Handle message_exported event for analytics/logging.

        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary with payload containing message_id and content_type
        """
        try:
            payload = message.get("payload", {})
            message_id = payload.get("message_id")
            content_type = payload.get("content_type")

            self._logger.info(
                f"[Session: {session_id}] Message exported",
                extra={
                    "session_id": session_id,
                    "client_id": client_id,
                    "message_id": message_id,
                    "content_type": content_type
                }
            )
        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error handling message export: {e}", exc_info=True)

    async def _broadcast_state_update(self, session_id: str, exclude_client: Optional[str] = None) -> None:
        """
        Broadcast state update to all clients in a session.
        GAP-05 FIX: Uses 'state_sync' instead of 'state_update' for consistency.

        Args:
            session_id: Session ID
            exclude_client: Optional client ID to exclude from broadcast
        """
        state = await self._state_manager.get_state(session_id)
        if state:
            exclude_set = {exclude_client} if exclude_client else None
            await self._ws_manager.broadcast_to_session(
                session_id,
                {
                    "type": "state_sync",
                    "payload": {
                        "state": state.model_dump()
                    }
                },
                exclude_clients=exclude_set
            )

    async def _send_error(self, client_id: str, error_message: str) -> None:
        """
        Send error message to client.

        Args:
            client_id: Client ID
            error_message: Error message
        """
        await self._ws_manager.send_to_client(client_id, {
            "type": "error",
            "payload": {
                "message": error_message
            }
        })

    async def _send_validation_error(self, client_id: str, field_id: str, error_message: str) -> None:
        """
        Send validation error message to client.
        GAP-09 FIX: Uses flat payload structure for consistency.

        Args:
            client_id: Client ID
            field_id: Field ID that failed validation
            error_message: Error message
        """
        await self._ws_manager.send_to_client(client_id, {
            "type": "validation_error",
            "field_id": field_id,
            "error": error_message
        })

    # --------------------------------------------------------------------------
    # Skills management handlers
    # --------------------------------------------------------------------------

    _SKILLS_ROOT = None  # resolved lazily

    def _get_skills_root(self):
        """Return the absolute path to the skills directory."""
        if IRISGateway._SKILLS_ROOT is None:
            from pathlib import Path
            IRISGateway._SKILLS_ROOT = Path(
                __file__).resolve().parent / "agent" / "skills"
        return IRISGateway._SKILLS_ROOT

    def _read_skill_config(self):
        """Read config.yaml and return the set of disabled skill keys."""
        try:
            import yaml
            from pathlib import Path
            cfg_path = self._get_skills_root() / "config.yaml"
            if cfg_path.exists():
                data = yaml.safe_load(
                    cfg_path.read_text(encoding="utf-8")) or {}
                return set(data.get("disabled_skills", []))
        except Exception as e:
            self._logger.warning(
                f"[IRISGateway] Could not read skill config: {e}")
        return set()

    def _write_skill_config(self, disabled: set):
        """Persist the disabled skills list to config.yaml."""
        try:
            import yaml
            cfg_path = self._get_skills_root() / "config.yaml"
            existing = {}
            if cfg_path.exists():
                existing = yaml.safe_load(
                    cfg_path.read_text(encoding="utf-8")) or {}
            existing["disabled_skills"] = sorted(disabled)
            cfg_path.write_text(
                yaml.dump(existing, default_flow_style=False,
                          allow_unicode=True),
                encoding="utf-8"
            )
        except Exception as e:
            self._logger.error(
                f"[IRISGateway] Could not write skill config: {e}")

    def _extract_skill_description(self, skill_md_text: str) -> str:
        """Pull the description from YAML frontmatter, or return first content line."""
        in_fm = False
        seen_fm = False
        fm_closed = False
        for line in skill_md_text.splitlines():
            stripped = line.strip()
            if stripped == "---":
                if not seen_fm:
                    in_fm = True
                    seen_fm = True
                elif in_fm:
                    in_fm = False
                    fm_closed = True
                continue
            if in_fm and stripped.lower().startswith("description:"):
                return stripped.split(":", 1)[1].strip().strip('"').strip("'")
        # Fallback: first non-empty, non-header content line
        in_fm = False
        seen_fm = False
        for line in skill_md_text.splitlines():
            stripped = line.strip()
            if stripped == "---":
                if not seen_fm:
                    in_fm = True
                    seen_fm = True
                elif in_fm:
                    in_fm = False
                continue
            if in_fm:
                continue
            if stripped and not stripped.startswith("#"):
                return stripped[:120]
        return ""

    async def _handle_get_skills(self, session_id: str, client_id: str) -> None:
        """List all user/agent-created skills (excludes skill-creator and built-ins)."""
        from pathlib import Path
        # Built-in system skills never shown in the learned list
        SYSTEM_SKILLS = {"skill-creator"}

        skills_root = self._get_skills_root()
        disabled = self._read_skill_config()
        skills = []

        if skills_root.is_dir():
            for child in sorted(skills_root.iterdir()):
                if not child.is_dir() or child.name in SYSTEM_SKILLS:
                    continue
                skill_md = child / "SKILL.md"
                if not skill_md.exists():
                    continue
                try:
                    content = skill_md.read_text(encoding="utf-8")
                    description = self._extract_skill_description(content)
                    # Extract name from frontmatter or use directory name
                    name = child.name
                    in_fm = False
                    seen_fm = False
                    for line in content.splitlines():
                        stripped = line.strip()
                        if stripped == "---":
                            if not seen_fm:
                                in_fm = True
                                seen_fm = True
                            elif in_fm:
                                in_fm = False
                            continue
                        if in_fm and stripped.lower().startswith("name:"):
                            name = stripped.split(
                                ":", 1)[1].strip().strip('"').strip("'")
                            break
                    skills.append({
                        "key": child.name,
                        "name": name,
                        "description": description,
                        "enabled": child.name not in disabled,
                    })
                except Exception as e:
                    self._logger.warning(
                        f"[IRISGateway] Could not read skill {child.name}: {e}")

        await self._ws_manager.send_to_client(client_id, {
            "type": "skills_list",
            "payload": {"skills": skills}
        })

    async def _handle_toggle_skill(self, session_id: str, client_id: str, message: dict) -> None:
        """Enable or disable a skill by updating config.yaml."""
        payload = message.get("payload", {})
        key = payload.get("key") or message.get("key", "")
        enabled = payload.get("enabled", True)

        if not key:
            await self._send_error(client_id, "toggle_skill: 'key' is required")
            return

        disabled = self._read_skill_config()
        if enabled:
            disabled.discard(key)
        else:
            disabled.add(key)
        self._write_skill_config(disabled)

        self._logger.info(
            f"[IRISGateway] Skill '{key}' {'enabled' if enabled else 'disabled'}")
        await self._ws_manager.send_to_client(client_id, {
            "type": "skill_toggled",
            "payload": {"key": key, "enabled": enabled}
        })

    async def _handle_delete_skill(self, session_id: str, client_id: str, message: dict) -> None:
        """Permanently delete a user-created skill directory."""
        import shutil
        from pathlib import Path

        SYSTEM_SKILLS = {"skill-creator"}
        payload = message.get("payload", {})
        key = payload.get("key") or message.get("key", "")

        if not key:
            await self._send_error(client_id, "delete_skill: 'key' is required")
            return
        if key in SYSTEM_SKILLS:
            await self._send_error(client_id, f"delete_skill: cannot delete built-in skill '{key}'")
            return

        skill_dir = self._get_skills_root() / key
        if not skill_dir.exists():
            await self._send_error(client_id, f"delete_skill: skill '{key}' not found")
            return

        try:
            shutil.rmtree(skill_dir)
            # Also remove from disabled list if present
            disabled = self._read_skill_config()
            disabled.discard(key)
            self._write_skill_config(disabled)
            self._logger.info(f"[IRISGateway] Deleted skill '{key}'")
            await self._ws_manager.send_to_client(client_id, {
                "type": "skill_deleted",
                "payload": {"key": key}
            })
        except Exception as e:
            self._logger.error(
                f"[IRISGateway] Failed to delete skill '{key}': {e}")
            await self._send_error(client_id, f"Failed to delete skill: {e}")

    async def _handle_create_skill(self, session_id: str, client_id: str, message: dict) -> None:
        """Create a new skill directory with a SKILL.md file."""
        from pathlib import Path
        import re

        payload = message.get("payload", {})
        name = (payload.get("name") or message.get("name", "")).strip()
        description = (payload.get("description")
                       or message.get("description", "")).strip()
        content = payload.get("content") or message.get("content", "")

        if not name:
            await self._send_error(client_id, "create_skill: 'name' is required")
            return

        # Create a safe directory key from the name
        key = re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")
        key = re.sub(r"-+", "-", key)
        if not key:
            key = "custom-skill"

        skill_dir = self._get_skills_root() / key
        skill_md = skill_dir / "SKILL.md"

        # Build the SKILL.md content if not provided
        if not content:
            content = (
                f"---\nname: {name}\ndescription: {description or 'Custom skill created by IRIS.'}\n---\n\n"
                f"# {name}\n\n{description or 'No description provided.'}\n"
            )

        try:
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_md.write_text(content, encoding="utf-8")
            self._logger.info(
                f"[IRISGateway] Created skill '{key}' at {skill_md}")
            await self._ws_manager.send_to_client(client_id, {
                "type": "skill_created",
                "payload": {
                    "key": key,
                    "name": name,
                    "description": description,
                    "enabled": True,
                }
            })
        except Exception as e:
            self._logger.error(
                f"[IRISGateway] Failed to create skill '{key}': {e}")
            await self._send_error(client_id, f"Failed to create skill: {e}")

    def _resolve_device_index(self, device: Any, want_input: bool) -> Any:
        """Resolve a device name string to an integer sounddevice index.

        The UI dropdown populates with device *names* (strings).  Passing a
        name to sounddevice raises "Multiple input/output devices found" on
        Windows because the same physical device appears under MME, DirectSound,
        WASAPI, and WDM-KS host APIs.  AudioPipeline.list_devices() already
        deduplicates those and returns the best integer index for each device,
        so we look up by name here.

        If the value is already an int (or can't be matched), it is returned as-is.
        """
        if isinstance(device, int):
            return device
        if not isinstance(device, str) or device == "":
            return device
        try:
            devices = AudioPipeline.list_devices()
            # Exact match first
            for d in devices:
                if want_input and not d.get("input"):
                    continue
                if not want_input and not d.get("output"):
                    continue
                if d["name"] == device:
                    return d["index"]
            # Prefix match (handles MME name truncation at 31 chars)
            key = device[:31].lower().rstrip()
            for d in devices:
                if want_input and not d.get("input"):
                    continue
                if not want_input and not d.get("output"):
                    continue
                if d["name"][:31].lower().rstrip() == key:
                    return d["index"]
            # Substring match (handles API-level name differences)
            device_lower = device.lower()
            for d in devices:
                if want_input and not d.get("input"):
                    continue
                if not want_input and not d.get("output"):
                    continue
                name_lower = d["name"].lower()
                if device_lower in name_lower or name_lower in device_lower:
                    self._logger.debug(
                        f"[IRISGateway] Resolved '{device}' via substring match → "
                        f"'{d['name']}' (index {d['index']})"
                    )
                    return d["index"]
            available = [d["name"] for d in devices if d.get("input" if want_input else "output")]
            self._logger.warning(
                f"[IRISGateway] Could not resolve device name '{device}' to an index — "
                f"using name as-is. Available: {available}"
            )
        except Exception as e:
            self._logger.error(
                f"[IRISGateway] Error resolving device index for '{device}': {e}")
        return device

    # ─────────────────────────────────────────────────────────────────────────
    # Local GGUF model handlers
    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_get_local_models(self, session_id: str, client_id: str, message: dict) -> None:
        """Return scanned GGUF models and hardware info."""
        from .agent.local_model_manager import get_local_model_manager
        try:
            mgr = get_local_model_manager()
            loop = __import__("asyncio").get_event_loop()
            models = await loop.run_in_executor(None, mgr.scan_models)
            hardware = await loop.run_in_executor(None, mgr.get_hardware_info)
            await self._ws_manager.send_to_client(client_id, {
                "type": "local_models_list",
                "payload": {"models": models, "hardware": hardware},
            })
        except Exception as e:
            self._logger.error(f"[LocalModel] get_local_models error: {e}")
            await self._ws_manager.send_to_client(client_id, {
                "type": "local_models_list",
                "payload": {"models": [], "hardware": {}, "error": str(e)},
            })

    async def _handle_load_local_model(self, session_id: str, client_id: str, message: dict) -> None:
        """Spawn llama-cpp-python server subprocess for the selected GGUF."""
        from .agent.local_model_manager import get_local_model_manager
        payload = message.get("payload", message)
        model_path = payload.get("model_path", "")
        profile = payload.get("profile", "balanced")
        custom_params = payload.get("custom_params", {})

        if not model_path:
            await self._ws_manager.send_to_client(client_id, {
                "type": "local_model_loading",
                "payload": {"status": "error", "error": "model_path is required"},
            })
            return

        await self._ws_manager.send_to_client(client_id, {
            "type": "local_model_loading",
            "payload": {"status": "starting", "model_path": model_path, "profile": profile},
        })

        try:
            mgr = get_local_model_manager()
            ok = await mgr.load_model(model_path, profile, custom_params)
            status = "ready" if ok else "error"
            payload_out = {"status": status, "model_path": model_path, "profile": profile}
            if not ok:
                payload_out["error"] = "Server did not start within timeout"
            await self._ws_manager.send_to_client(client_id, {
                "type": "local_model_loading",
                "payload": payload_out,
            })
            # Refresh model dropdown if load succeeded
            if ok:
                await self._handle_get_available_models(session_id, client_id, {})
                import time as _time
                await self._ws_manager.broadcast_to_session(session_id, {
                    "type": "model_load_event",
                    "payload": {
                        "action": "loaded",
                        "model": model_path,
                        "profile": profile,
                        "timestamp": _time.time(),
                    },
                })
        except Exception as e:
            self._logger.error(f"[LocalModel] load_local_model error: {e}")
            await self._ws_manager.send_to_client(client_id, {
                "type": "local_model_loading",
                "payload": {"status": "error", "error": str(e), "model_path": model_path},
            })

    async def _handle_unload_local_model(self, session_id: str, client_id: str, message: dict) -> None:
        """Stop the llama-cpp-python server subprocess."""
        from .agent.local_model_manager import get_local_model_manager
        try:
            mgr = get_local_model_manager()
            status_before = mgr.get_status()
            model_path_before = status_before.get("model_path") if isinstance(status_before, dict) else None
            await mgr.unload_model()
            await self._ws_manager.send_to_client(client_id, {
                "type": "local_model_status",
                "payload": {"loaded": False, "model_path": None, "profile": None},
            })
            import time as _time
            await self._ws_manager.broadcast_to_session(session_id, {
                "type": "model_load_event",
                "payload": {
                    "action": "unloaded",
                    "model": model_path_before or "",
                    "profile": "",
                    "timestamp": _time.time(),
                },
            })
        except Exception as e:
            self._logger.error(f"[LocalModel] unload error: {e}")

    async def _handle_get_local_model_status(self, session_id: str, client_id: str, message: dict) -> None:
        """Return current load status of the GGUF server."""
        from .agent.local_model_manager import get_local_model_manager
        try:
            mgr = get_local_model_manager()
            status = mgr.get_status()
            await self._ws_manager.send_to_client(client_id, {
                "type": "local_model_status",
                "payload": status,
            })
        except Exception as e:
            self._logger.error(f"[LocalModel] get_status error: {e}")

    async def _handle_get_hardware_info(self, session_id: str, client_id: str, message: dict) -> None:
        """Return GPU/VRAM/RAM hardware info."""
        from .agent.local_model_manager import get_local_model_manager
        try:
            mgr = get_local_model_manager()
            loop = __import__("asyncio").get_event_loop()
            hw = await loop.run_in_executor(None, mgr.get_hardware_info)
            await self._ws_manager.send_to_client(client_id, {
                "type": "hardware_info",
                "payload": hw,
            })
        except Exception as e:
            self._logger.error(f"[LocalModel] get_hardware_info error: {e}")

    async def _handle_download_gguf_model(self, session_id: str, client_id: str, message: dict) -> None:
        """Stream HuggingFace GGUF download progress to client."""
        from .agent.local_model_manager import get_local_model_manager
        payload = message.get("payload", message)
        repo_id = payload.get("repo_id", "")
        filename = payload.get("filename", "")

        if not repo_id or not filename:
            await self._ws_manager.send_to_client(client_id, {
                "type": "gguf_download_progress",
                "payload": {"status": "error", "error": "repo_id and filename required"},
            })
            return

        mgr = get_local_model_manager()
        try:
            async for progress in mgr.download_model(repo_id, filename):
                await self._ws_manager.send_to_client(client_id, {
                    "type": "gguf_download_progress",
                    "payload": {**progress, "repo_id": repo_id, "filename": filename},
                })
                if progress.get("status") == "complete":
                    # Refresh installed models list
                    await self._handle_get_local_models(session_id, client_id, {})
        except Exception as e:
            self._logger.error(f"[LocalModel] download error: {e}")
            await self._ws_manager.send_to_client(client_id, {
                "type": "gguf_download_progress",
                "payload": {"status": "error", "error": str(e), "repo_id": repo_id, "filename": filename},
            })

    async def _handle_search_hf_models(self, session_id: str, client_id: str, message: dict) -> None:
        """Search HuggingFace Hub for GGUF models. No API key required for public models."""
        import httpx as _httpx
        payload = message.get("payload", {})
        query = payload.get("query", "").strip()
        limit = min(int(payload.get("limit", 20)), 50)
        try:
            params: dict = {
                "filter": "gguf",
                "sort": "downloads",
                "direction": -1,
                "limit": limit,
                "full": "false",
            }
            if query:
                params["search"] = query
            async with _httpx.AsyncClient(timeout=10.0) as hf_client:
                r = await hf_client.get("https://huggingface.co/api/models", params=params)
                models = r.json() if r.status_code == 200 else []
            await self._ws_manager.send_to_client(client_id, {
                "type": "hf_models_list",
                "payload": {"models": models, "query": query},
            })
        except Exception as e:
            self._logger.warning(f"[HFSearch] search failed: {e}")
            await self._ws_manager.send_to_client(client_id, {
                "type": "hf_models_list",
                "payload": {"models": [], "query": query, "error": str(e)},
            })

    async def _handle_set_vision_enabled(self, session_id: str, client_id: str, message: dict) -> None:
        """Start or stop the LFM2.5-VL llama-server subprocess on port 8081."""
        payload = message.get("payload", message)
        enabled = bool(payload.get("enabled", False))
        try:
            from .tools.lfm_vl_provider import get_lfm_vl_provider
            vl = get_lfm_vl_provider()
            if enabled:
                # Start vision server if not already running
                running = await vl.health_check() if hasattr(vl, "health_check") else False
                status = "running" if running else "not_started"
            else:
                # Signal the provider that vision is disabled
                if hasattr(vl, "disable"):
                    vl.disable()
                status = "stopped"
            await self._ws_manager.send_to_client(client_id, {
                "type": "vision_status",
                "payload": {"enabled": enabled, "running": enabled, "port": 8081, "status": status},
            })
        except Exception as e:
            self._logger.warning(f"[Vision] set_vision_enabled error: {e}")
            await self._ws_manager.send_to_client(client_id, {
                "type": "vision_status",
                "payload": {"enabled": enabled, "running": False, "port": 8081, "error": str(e)},
            })

    async def _handle_toggle_model_pin(self, session_id: str, client_id: str, message: dict) -> None:
        """Toggle pin/favorite state for a local GGUF model."""
        from .agent.local_model_manager import get_local_model_manager
        payload = message.get("payload", message)
        filename = payload.get("filename", "")
        if not filename:
            return
        try:
            mgr = get_local_model_manager()
            new_pin = mgr.toggle_pin(filename)
            await self._ws_manager.send_to_client(client_id, {
                "type": "model_pin_updated",
                "payload": {"filename": filename, "pinned": new_pin},
            })
        except Exception as e:
            self._logger.error(f"[LocalModel] toggle_pin error: {e}")


# Global instance
_iris_gateway: Optional[IRISGateway] = None


def get_iris_gateway() -> IRISGateway:
    """Get or create the singleton IRISGateway."""
    global _iris_gateway
    if _iris_gateway is None:
        _iris_gateway = IRISGateway()
    return _iris_gateway
