"""
IRIS Gateway - WebSocket Message Router
Routes incoming WebSocket messages to appropriate handlers based on message type.
"""

from .iris_config import IRISConfig, load_config, save_config, InferenceConfig, save_field_values, load_field_values
from .integrations import get_integration_handler
from .tools.lfm_vl_provider import LFMVLProvider
from .tools.cleanup_analyzer import CleanupAnalyzer
from .voice.wake_word_discovery import WakeWordDiscovery
from .audio.pipeline import AudioPipeline
from .agent.tts import get_tts_manager
from .agent import get_agent_kernel
from .agent.swarm_inference_manager import SwarmInferenceManager
from .core_models import Category, get_sections_for_category
from .state_manager import StateManager, get_state_manager
from .ws_manager import WebSocketManager, get_websocket_manager
import asyncio
import json
import logging
import math
import numpy as np
import os
from pathlib import Path
import queue
import re
import threading
import time
import httpx
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Union, Iterator, Callable
from backend.utils.observability import get_turn_id, loud_error

# ---------------------------------------------------------------------------
# Port config accessor â€” read from env-var-aware config, cached after first
# call so we don't re-load the JSON file on every reference.
# ---------------------------------------------------------------------------

_config_cache: "IRISConfig | None" = None


def _get_port_config() -> "PortConfig":
    """Return cached PortConfig, loading from iris_config if needed."""
    # Import PortConfig lazily to avoid circular imports
    from .iris_config import PortConfig as _PC

    global _config_cache
    if _config_cache is None:
        _config_cache = load_config()
    ports = _config_cache.ports
    # Always apply env-var overrides (they may have changed since load)
    return _PC(
        backend_port=ports.backend_port,
        brain_port=ports.brain_port,
        vision_port=ports.vision_port,
    )


_BRAIN_PORT: int = _get_port_config().brain_port
_VISION_PORT: int = _get_port_config().vision_port
_BACKEND_PORT: int = _get_port_config().backend_port
# Provider URL defaults (also env-var overridable via IRIS_LMSTUDIO_URL / IRIS_OLLAMA_URL)
_DEFAULT_LMSTUDIO_URL: str = load_config().inference.lm_studio_url or "http://localhost:1234"
_DEFAULT_OLLAMA_URL: str = load_config().inference.ollama_url or "http://localhost:11434"


# ---------------------------------------------------------------------------
# Pre-compiled regex patterns â€” used by _clean_for_speech and _speak_response.
# Compiled once at import time to avoid re.compile() overhead on every call.
# ---------------------------------------------------------------------------
_RE_EMOJI = re.compile(
    "[\U0001f300-\U0001f9ff"  # misc symbols, emoticons, transport, foodâ€¦
    "\U00002702-\U000027b0"  # dingbats
    "\U0001fa00-\U0001fa6f"  # chess, medical â€¦
    "\U0001fa70-\U0001faff"  # clothing, science â€¦
    "\U00002500-\U00002bef"  # CJK / box-drawing misc
    "\U0001f004-\U0001f0cf"  # mahjong / playing cards
    "\U0001f170-\U0001f171"  # blood-type buttons
    "\U0001f191-\U0001f251"  # enclosed characters
    "]+",
    flags=re.UNICODE,
)
_RE_MD_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_RE_MD_BULLET = re.compile(r"^\s*[-*â€¢]\s+", re.MULTILINE)
_RE_MD_BOLD = re.compile(r"\*\*(.*?)\*\*")
_RE_MD_ITALIC = re.compile(r"\*(.*?)\*")
_RE_MD_CODE = re.compile(r"`(.*?)`")
_RE_EXCLAIM = re.compile(r"!+")
_RE_QUESTION_DOT = re.compile(r"\?\.")
_RE_MULTI_DOT = re.compile(r"\.{2,}")
_RE_MULTI_SPACE = re.compile(r" +")
_RE_MULTI_NL = re.compile(r"\n{2,}")
# Sentence boundary: punctuation followed by whitespace (used in split + get_spoken_version)
_RE_SENTENCE_SPLIT = re.compile(r"(?<=[.!?â€¦])\s+|\n+")

# Sentinel object placed in audio_queue when TTS producer finishes.
# MUST be unique â€” use an object, not None (None is also what queue.get
# returns on timeout, making the two cases indistinguishable).
_TTS_END_STREAM = object()


logger = logging.getLogger(__name__)


class IRISGateway:
    """
    Central gateway for routing WebSocket messages to appropriate handlers.
    Handles navigation, settings, voice, chat, and status messages.
    """

    def __init__(
        self,
        ws_manager: Optional[WebSocketManager] = None,
        state_manager: Optional[StateManager] = None,
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
            "[IRISGateway] Vision provider initialized (LFM2.5-VL @ http://localhost:8081/v1)"
        )

        # Initialize model cache for lazy loading (5 minute TTL)
        # Entries are purged by _purge_model_cache() called on every lookup
        self._model_cache: Dict[str, tuple[List[str], datetime]] = {}
        self._model_cache_ttl = timedelta(minutes=5)
        self._logger.info("[IRISGateway] Model cache initialized (5 min TTL)")
        self._tts_prewarmed = False
        self._main_loop = None
        self._speech_interrupted = False

        self._voice_handler = None  # set via set_voice_handler() after construction
        # session_id -> client_id for wake word routing
        self._active_voice_client: dict = {}
        # Track which session is currently playing TTS â€” used by the barge-in
        # handler to know which conversation to resume on interruption.
        self._active_tts_session: Optional[str] = None
        # Barge-in stop event: set by _on_barge_in_detected to stop cadence
        # threads immediately when user speech is detected over TTS playback.
        # Created per-session by _speak_response / _handle_tts_play.
        self._barge_in_stop: Optional[threading.Event] = None
        # Sessions currently in conversation mode (auto-relisten after TTS)
        self._conversation_sessions: set = set()
        # Track last-seen timestamp for each session (for GC)
        self._session_last_seen: dict[str, float] = {}
        # Session GC task reference
        self._session_gc_task: Optional[asyncio.Task] = None
        # Track auto_research/background tasks
        self._research_tasks: set[asyncio.Task] = set()
        # How long to wait for speech onset during relisten before returning to idle
        self._relisten_pre_speech_timeout: float = 8.0
        # Captured once the first async message is handled; used by sync callbacks
        # (e.g. _on_voice_result) that need to dispatch back to the event loop from
        # a background thread without calling asyncio.get_event_loop() in that thread.
        import threading

        # Pocket-TTS loads lazily â€” only on first actual TTS synthesis request
        # inside _speak_response â†’ synthesize_stream.  _tts_prewarmed = True
        # suppresses all "safety net" re-trigger paths so nothing tries to load
        # it early.  synthesize_stream calls _select_engine() + _load_pocket_tts()
        # itself when it first runs.
        self._tts_prewarmed = (
            True  # Pocket-TTS loads in ~1s â€” no startup prewarm needed
        )

    # â”€â”€ Routing Mode Resolver â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _resolve_routing_mode(self) -> str:
        """
        Read config and return the effective routing mode string.
        Swarm takes priority â€” when enabled, routing mode is 'SWARM'.
        Otherwise returns the configured provider (api, lmstudio, ollama, iris_local).
        """
        try:
            cfg = load_config()
            if cfg.inference.swarm_enabled:
                return "SWARM"
            return cfg.inference.provider or "api"
        except Exception:
            return "api"

    def set_main_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Capture the running event loop for background task dispatch.

        Mandatory call from main.py's lifespan startup to ensure wake-word callbacks
        can reach the event loop before the first UI WebSocket connects.
        """
        self._main_loop = loop
        self._logger.info("[IRISGateway] Main event loop captured.")
        # Start session GC task
        if self._session_gc_task is None:
            self._session_gc_task = asyncio.create_task(self._session_gc_loop())
            self._logger.info("[IRISGateway] Session GC task started.")

        if not self._tts_prewarmed:
            pass  # Pocket-TTS loads in ~1s â€” no startup prewarm

    def _touch_session(self, session_id: str) -> None:
        """Update the last-seen timestamp for a session."""
        self._session_last_seen[session_id] = time.monotonic()

    async def _session_gc_loop(self) -> None:
        """Background task to clean up stale sessions every 5 minutes."""
        while True:
            try:
                await asyncio.sleep(300)  # 5 min
                cutoff = time.monotonic() - 1800  # 30 min
                stale = [
                    sid for sid, t in self._session_last_seen.items() if t < cutoff
                ]
                for sid in stale:
                    self._active_voice_client.pop(sid, None)
                    self._conversation_sessions.discard(sid)
                    self._session_last_seen.pop(sid, None)
                if stale:
                    self._logger.info(
                        f"[Gateway] Session GC swept {len(stale)} stale sessions"
                    )
            except asyncio.CancelledError:
                return
            except Exception as e:
                self._logger.warning(f"[Gateway] Session GC error: {e}")

    async def handle_message(
        self, client_id: str, message: dict, session_id: Optional[str] = None
    ) -> None:
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
            # Touch the idle tracker on every incoming message so background workers
            # (distillation, retention, MCP health checks) know the user is active.
            try:
                from backend.core.idle_tracker import get_idle_tracker

                get_idle_tracker().touch()
            except Exception:
                pass  # never block message processing on tracker failure

            # Validate message format
            if not isinstance(message, dict):
                self._logger.error(
                    f"Invalid message format from client {client_id}: not a dict",
                    extra={
                        "client_id": client_id,
                        "message_type": type(message).__name__,
                    },
                )
                await self._send_error(
                    client_id, "Invalid message format: expected dict"
                )
                return

            msg_type = message.get("type")
            if not msg_type:
                self._logger.error(
                    f"Missing message type from client {client_id}",
                    extra={"client_id": client_id, "raw_message": str(message)[:200]},
                )
                await self._send_error(
                    client_id, "Invalid message format: missing 'type' field"
                )
                return

            # Resolve session ID â€” use caller-supplied value when available to avoid
            # the race where heartbeat disconnect removes the mapping before we look it up.
            if session_id is None:
                session_id = self._ws_manager.get_session_id_for_client(client_id)
            if not session_id:
                self._logger.error(
                    f"No session found for client {client_id}",
                    extra={"client_id": client_id, "message_type": msg_type},
                )
                await self._send_error(client_id, "No active session")
                return

            # Touch session timestamp for GC tracking
            self._touch_session(session_id)

            self._logger.info(
                f"[Session: {session_id}] Processing message type: {msg_type}",
                extra={
                    "session_id": session_id,
                    "client_id": client_id,
                    "message_type": msg_type,
                },
            )

            # Route to appropriate handler based on message type
            if msg_type in ["select_category", "select_section", "go_back"]:
                await self._handle_navigation(session_id, client_id, message)

            elif msg_type in ["update_field", "update_theme", "confirm_card"]:
                await self._handle_settings(session_id, client_id, message)

            elif msg_type == "set_model_selection":
                await self._handle_set_model_selection(session_id, client_id, message)

            elif msg_type in [
                "voice_command_start",
                "voice_command_end",
                "voice_command_cancel",
                "voice_command",
                "test_audio",
            ]:
                await self._handle_voice(session_id, client_id, message)

            elif msg_type in ["get_wake_words", "select_wake_word"]:
                if msg_type == "get_wake_words":
                    await self._handle_get_wake_words(session_id, client_id)
                else:
                    await self._handle_select_wake_word(session_id, client_id, message)

            elif msg_type in ["get_cleanup_report", "execute_cleanup"]:
                if msg_type == "get_cleanup_report":
                    await self._handle_get_cleanup_report(
                        session_id, client_id, message
                    )
                else:
                    await self._handle_execute_cleanup(session_id, client_id, message)

            elif msg_type in ["text_message", "clear_chat", "new_conversation"]:
                await self._handle_chat(session_id, client_id, message)

            elif msg_type in [
                "get_agent_status",
                "get_agent_tools",
                "agent_status",
                "agent_tools",
            ]:
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

            elif msg_type in ("start_swarm", "stop_swarm", "swarm_action"):
                await self._handle_swarm_action(session_id, client_id, message)

            elif msg_type == "load_local_model":
                await self._handle_load_local_model(session_id, client_id, message)

            elif msg_type == "unload_local_model":
                await self._handle_unload_local_model(session_id, client_id, message)

            elif msg_type == "apply_inference_settings":
                await self._handle_apply_inference_settings(
                    session_id, client_id, message
                )

            elif msg_type == "get_local_model_status":
                await self._handle_get_local_model_status(
                    session_id, client_id, message
                )

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

            elif msg_type == "select_audio_device":
                await self._handle_select_audio_device(session_id, client_id, message)

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
                # Frontend play-icon clicked â€” speak the supplied text via TTS
                await self._handle_tts_play(session_id, client_id, message)

            elif msg_type == "voice_result":
                # Parakeet ASR final transcription â†’ parrot to all clients in
                # the same session (used for Tailscale multi-view, where a
                # phone via Tailscale should see the Tauri client's transcript).
                self._logger.info(
                    "[Voice] voice_result relay from %s â†’ session %s",
                    client_id[:8], session_id,
                )
                if session_id:
                    await self._ws_manager.broadcast_to_session(
                        session_id,
                        {
                            "type": "voice_result",
                            "turn_id": get_turn_id(),
                            "payload": message.get("payload", {}),
                        },
                    )

            elif msg_type == "voice_audio_chunk":
                # PCM chunk from frontend â†’ forward to in-process Parakeet ASR.
                # Parakeet is now embedded in VoiceCommandHandler â€” no separate
                # service needed.  This handler is a secondary / monitor path.
                self._logger.debug(
                    "[Voice] Audio chunk received from %s (%.0f bytes)",
                    client_id[:8],
                    len(message.get("payload", {}).get("chunk", b"") or b""),
                )

            elif msg_type == "ping":
                await self._ws_manager.send_to_client(
                    client_id, {"type": "pong", "payload": {}}
                )

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

            elif msg_type == "crawler_query":
                # Explicit web research request â€” route to CrawlerEngine
                await self._handle_crawler_query(session_id, client_id, message)

            elif msg_type == "dev_cli":
                # Developer mode â€” route query to CLI tool via DevOrchestrator
                await self._handle_dev_cli(session_id, client_id, message)

            elif msg_type == "dev_abort":
                # Developer mode â€” abort active CLI subprocess for this session
                await self._handle_dev_abort(session_id, client_id)

            elif msg_type == "terminal_input":
                await self._handle_terminal_input(session_id, client_id, message)

            elif msg_type in {
                "integration_list",
                "integration_enable",
                "integration_disable",
                "integration_state",
                "integration_oauth_callback",
                "integration_credentials_auth",
                "integration_telegram_auth",
                "integration_restart",
                "integration_forget",
                "app_cleanup",
                "activity_get_recent",
                "logs_subscribe",
                "logs_get_history",
                "logs_unsubscribe",
                "marketplace_preference_store",
                "marketplace_preferences_get",
                "marketplace_recommendations_get",
            }:
                # Delegate to the integration subsystem handler
                await get_integration_handler().handle_message(client_id, message)

            else:
                self._logger.warning(
                    f"Unknown message type: {msg_type}",
                    extra={
                        "session_id": session_id,
                        "client_id": client_id,
                        "message_type": msg_type,
                    },
                )
                await self._send_error(client_id, f"Unknown message type: {msg_type}")

        except json.JSONDecodeError as e:
            # Handle JSON parse errors
            self._logger.error(
                f"JSON parse error from client {client_id}: {e}",
                exc_info=True,
                extra={"client_id": client_id, "error": str(e)},
            )
            await self._send_error(client_id, "Invalid JSON format")

        except Exception as e:
            # Handle all other exceptions
            msg_type = (
                message.get("type", "unknown")
                if isinstance(message, dict)
                else "unknown"
            )
            self._logger.error(
                f"Error handling message type {msg_type} from client {client_id}: {e}",
                exc_info=True,
                extra={
                    "client_id": client_id,
                    "message_type": msg_type,
                    "error": str(e),
                },
            )
            await self._send_error(client_id, f"Error processing message: {str(e)}")

    async def _handle_navigation(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """
        Handle navigation messages: select_category, select_section, go_back.

        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary
        """
        msg_type = message.get("type")

        if msg_type == "select_category":
            category = message.get("category") or message.get("payload", {}).get(
                "category"
            )

            if not category:
                await self._send_validation_error(
                    client_id, "category", "Category is required"
                )
                return

            # Validate category
            try:
                category_enum = (
                    Category(category) if isinstance(category, str) else category
                )
            except ValueError:
                await self._send_validation_error(
                    client_id, "category", f"Invalid category: {category}"
                )
                return

            # Update state
            await self._state_manager.set_category(session_id, category_enum)

            # Get sections for this category
            sections = get_sections_for_category(category_enum)

            # Send confirmation with sections
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "category_changed",
                    "payload": {
                        "category": category,
                        "sections": [s.model_dump() for s in sections],
                    },
                },
            )

            # Broadcast state update to other clients in session
            await self._broadcast_state_update(session_id, exclude_client=client_id)

        elif msg_type == "select_section":
            section_id = message.get("section_id") or message.get("payload", {}).get(
                "section_id"
            )

            if not section_id:
                await self._send_validation_error(
                    client_id, "section_id", "Section ID is required"
                )
                return

            # Update state
            await self._state_manager.set_section(session_id, section_id)

            # Send confirmation
            await self._ws_manager.send_to_client(
                client_id,
                {"type": "section_changed", "payload": {"section_id": section_id}},
            )

            # Broadcast state update to other clients in session
            await self._broadcast_state_update(session_id, exclude_client=client_id)

        elif msg_type == "go_back":
            # Navigate back
            await self._state_manager.go_back(session_id)

            # Broadcast state update to all clients in session
            await self._broadcast_state_update(session_id, exclude_client=client_id)

    async def _handle_settings(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """
        Handle settings messages: update_field, update_theme, confirm_card.

        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary
        """
        # Load current config at function entry so subsequent references to `cfg`
        # resolve to the live config (this function also reassigns `cfg` later,
        # which would otherwise cause UnboundLocalError on the early read).
        cfg = load_config()
        msg_type = message.get("type")
        payload = message.get("payload", {})

        if msg_type == "update_field":
            # Use only section_id (cleanup complete)
            section_id = message.get("section_id") or payload.get("section_id")
            field_id = message.get("field_id") or payload.get("field_id")
            value = message.get("value") if "value" in message else payload.get("value")
            # Optional timestamp from client
            timestamp = payload.get("timestamp")

            if not section_id or not field_id:
                await self._send_validation_error(
                    client_id, "field", "Both section_id and field_id are required"
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
                # Persist raw field_values to disk so they survive frontend remounts.
                save_field_values(self._state_manager.get_state(session_id).field_values)

                # Mask API keys in the response
                response_value = value
                if field_id == "openai_api_key" and value:
                    from .utils.encryption import mask_api_key

                    response_value = mask_api_key(value)

                # Send confirmation with timestamp - include both new and legacy field names
                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "field_updated",
                        "payload": {
                            "section_id": section_id,
                            "field_id": field_id,
                            "value": response_value,
                            "valid": True,
                            "timestamp": update_timestamp,
                        },
                    },
                )

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
                            "timestamp": update_timestamp,
                        },
                    },
                    exclude_clients={client_id},
                )
            else:
                # Send validation error
                await self._send_validation_error(
                    client_id, field_id, "Field validation failed"
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
                state_colors=state_colors,
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
                    },
                )

        elif msg_type == "confirm_card":
            # Use only section_id (cleanup complete)
            section_id = payload.get("section_id")
            values = payload.get("values", {})

            if not section_id:
                await self._send_validation_error(
                    client_id, "section_id", "Section ID is required"
                )
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
                            (
                                wf
                                for wf in discovered
                                if wf.display_name.lower() == wake_phrase.lower()
                                and wf.platform != "builtin"
                            ),
                            None,
                        )
                        config_updates["wake_phrase"] = wake_phrase
                        config_updates["custom_model_path"] = (
                            custom_file.path if custom_file else None
                        )

                    sensitivity = values.get("wake_word_sensitivity")
                    if sensitivity is not None:
                        # UI slider is 1-10; Porcupine needs 0.0-1.0
                        config_updates["detection_sensitivity"] = (
                            float(sensitivity) / 10.0
                        )

                    wake_enabled = values.get("wake_word_enabled")
                    if wake_enabled is not None:
                        config_updates["wake_word_enabled"] = bool(wake_enabled)

                    if config_updates:
                        wake_config.update_config(**config_updates)
                        self._logger.info(
                            f"[Session: {session_id}] Wake config applied on confirm: {config_updates}",
                            extra={"session_id": session_id, "client_id": client_id},
                        )
                except Exception as wc_e:
                    self._logger.error(
                        f"[Session: {session_id}] Error applying wake config on confirm: {wc_e}",
                        extra={"session_id": session_id, "client_id": client_id},
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
                        kwargs["speaking_rate"] = float(values["speaking_rate"])
                    if kwargs:
                        tts.update_config(**kwargs)
                        # Persist TTS settings to data/iris_config.json
                        try:
                            cfg = load_config()
                            for k, v in kwargs.items():
                                setattr(cfg.tts, k, v)
                            cfg.field_values = self._state_manager.get_field_values(session_id)
                            save_config(cfg)
                        except Exception as _cfg_err:
                            self._logger.warning(
                                f"[Session: {session_id}] Failed to persist TTS config: {_cfg_err}"
                            )
                        self._logger.info(
                            f"[Session: {session_id}] TTS config applied: {kwargs}",
                            extra={"session_id": session_id, "client_id": client_id},
                        )
                except Exception as e:
                    self._logger.error(
                        f"[Session: {session_id}] Error applying TTS config: {e}",
                        extra={"session_id": session_id, "client_id": client_id},
                    )

            # Apply inference_mode card values when that section is confirmed.
            # NOTE: Provider routing is handled by the model_selection section.
            # This handler only processes inference-behaviour fields:
            #   agent_thinking_style, max_response_length, reasoning_effort,
            #   tool_mode, swarm_enabled.
            elif section_id == "inference_mode" and values:
                self._logger.info(
                    f"[DEBUG] inference_mode VALUES: {json.dumps(values, default=str)}"
                )
                try:
                    from .agent.agent_kernel import get_agent_kernel

                    kernel = get_agent_kernel(session_id)

                    # â”€â”€ Provider routing (DELEGATED to model_selection) â”€â”€â”€â”€â”€â”€
                    # The inference_mode card no longer has an "inference_mode"
                    # field. Provider routing is handled exclusively by the
                    # model_selection section.
                    self._logger.info(
                        f"[Session: {session_id}] inference_mode card confirmed "
                        f"(provider routing delegated to model_selection section)"
                    )

                    # Apply swarm_enabled if present in inference_mode values
                    if "swarm_enabled" in values:
                        swarm_on = bool(values.get("swarm_enabled", False))
                        if hasattr(kernel, "set_swarm_enabled"):
                            kernel.set_swarm_enabled(swarm_on)
                            self._logger.info(
                                f"[Session: {session_id}] Swarm {'enabled' if swarm_on else 'disabled'}"
                            )
                        if not swarm_on:
                            # Clear global snapshot so new sessions don't inherit
                            # a stale swarm config after the user disabled it.
                            try:
                                import backend.agent.agent_kernel as _ak_mod

                                _ak_mod._swarm_config_snapshot = None
                                self._logger.info(
                                    f"[Session: {session_id}] Swarm snapshot cleared"
                                )
                            except Exception:
                                pass

                    # â”€â”€ Local / Swarm config â€” only applies when provider is iris_local â”€â”€
                    # If the user selected an API provider, skip all inference_mode startup.
                    current_provider = cfg.inference.provider if cfg else ""
                    is_local = current_provider in ("local", "iris_local")

                    if is_local and not swarm_on:
                        _model_path = values.get("iris_local_model_path", "").strip()
                        _profile = values.get("iris_local_profile", "balanced")
                        _models_dir = values.get("models_directory", "").strip()

                        # Persist to config so Load button in model browser knows what to load
                        if _model_path:
                            cfg.inference.local_model_path = _model_path
                        cfg.inference.hardware_profile = _profile
                        if _models_dir:
                            cfg.inference.models_directory = _models_dir

                        # Set models_directory on the manager so scan_models() finds models
                        if _models_dir:
                            from .agent.local_model_manager import (
                                get_local_model_manager,
                            )

                            mgr = get_local_model_manager()
                            mgr.set_models_directory(_models_dir)
                            self._logger.info(
                                f"[inference_mode] Models directory: {_models_dir}",
                                extra={"session_id": session_id},
                            )

                        self._logger.info(
                            f"[inference_mode] Local config saved â€” model not loaded. "
                            f"Use Load button in model browser.",
                            extra={"session_id": session_id},
                        )

                    # Only start swarm when using iris_local provider
                    if is_local and swarm_on and "swarm_mode" in values:
                        mode = values.get("swarm_mode", "local_fast")
                        worker_ctx = int(values.get("worker_context", 2048))
                        try:
                            # â”€â”€ Guard: unload in-process model before spawning swarm â”€â”€
                            try:
                                from .agent.local_model_manager import (
                                    get_local_model_manager,
                                )

                                _lm_mgr = get_local_model_manager()
                                if _lm_mgr.is_loaded():
                                    self._logger.info(
                                        f"[inference_mode] Unloading in-process model "
                                        f"before swarm spawn",
                                        extra={"session_id": session_id},
                                    )
                                    await _lm_mgr.unload_model()
                                    self._logger.info(
                                        f"[inference_mode] In-process model unloaded OK",
                                        extra={"session_id": session_id},
                                    )
                            except Exception as _ul_err:
                                self._logger.warning(
                                    f"[inference_mode] Failed to unload "
                                    f"in-process model: {_ul_err}"
                                )

                            mgr = SwarmInferenceManager()
                            cfg = mgr.apply_swarm_mode(mode, worker_ctx)
                            if mode == "api_director":
                                # Director uses API â€” ensure API provider is configured
                                self._logger.info(
                                    f"[Session: {session_id}] Swarm mode=api_director â€” "
                                    f"Director will use API, workers on GPU"
                                )
                            else:
                                await mgr.start_swarm()
                                self._logger.info(
                                    f"[Session: {session_id}] Swarm started: "
                                    f"mode={cfg.mode.value}, director={cfg.director_model or 'API'}, "
                                    f"workers={cfg.worker_model}, worker_ctx={cfg.worker_ctx}"
                                )
                                # â”€â”€ Route kernel inference to swarm endpoints â”€â”€
                                # The kernel currently supports a single OpenAI-compatible
                                # endpoint.  quality_director â†’ Director (8081) for quality;
                                # local_fast      â†’ Workers (8082) for speed.
                                _swarm_ep = (
                                    cfg.director_endpoint
                                    if cfg.mode.value == "quality_director"
                                    else cfg.workers_endpoint
                                )
                                kernel.configure_openai_compat(
                                    _swarm_ep.rstrip("/").removesuffix("/v1"),
                                    provider_name="iris_local",
                                )
                                # Pick model names that llama-server will accept
                                _dir_name = (
                                    Path(cfg.director_model).stem
                                    if cfg.director_model
                                    else "local-model"
                                )
                                _wrk_name = Path(cfg.worker_model).stem
                                kernel._selected_reasoning_model = _dir_name
                                kernel._selected_tool_execution_model = _wrk_name
                                self._logger.info(
                                    f"[Session: {session_id}] Kernel routed to swarm: "
                                    f"endpoint={_swarm_ep}, reasoning={_dir_name}, tool={_wrk_name}"
                                )
                                # â”€â”€ Persist swarm snapshot for future sessions â”€â”€
                                # New sessions created after this point will auto-hydrate
                                # from this snapshot instead of staying "uninitialized".
                                import backend.agent.agent_kernel as _ak_mod

                                _ak_mod._swarm_config_snapshot = {
                                    "endpoint": _swarm_ep.rstrip("/").removesuffix(
                                        "/v1"
                                    ),
                                    "reasoning_model": _dir_name,
                                    "tool_model": _wrk_name,
                                    "mode": cfg.mode.value,
                                }
                                self._logger.info(
                                    f"[Session: {session_id}] Swarm config snapshot stored: "
                                    f"{_ak_mod._swarm_config_snapshot}"
                                )
                                # â”€â”€ Broadcast swarm config to ALL sessions â”€â”€
                                # The frontend may have multiple WebSocket connections
                                # (e.g. one for the UI, one for integration). Ensure every
                                # session kernel points to the swarm so chat messages
                                # from any connection reach the local llama-server.
                                from backend.agent.agent_kernel import (
                                    _agent_kernel_instances,
                                )

                                for _sid, _k in _agent_kernel_instances.items():
                                    if _sid == session_id:
                                        continue
                                    _k.configure_openai_compat(
                                        _swarm_ep.rstrip("/").removesuffix("/v1"),
                                        provider_name="iris_local",
                                    )
                                    _k._selected_reasoning_model = _dir_name
                                    _k._selected_tool_execution_model = _wrk_name
                                    # Propagate inference behaviour so all sessions share them.
                                    _k._thinking_style = kernel._thinking_style
                                    _k._response_length = kernel._response_length
                                    _k._reasoning_effort = kernel._reasoning_effort
                                    _k._tool_mode = kernel._tool_mode
                                    self._logger.info(
                                        f"[Session: {_sid}] Kernel also routed to swarm: "
                                        f"endpoint={_swarm_ep}"
                                    )
                            # Store manager reference on kernel for status queries
                            if hasattr(kernel, "_swarm_inference_mgr"):
                                kernel._swarm_inference_mgr = mgr

                            # â”€â”€ Defensive re-apply: if swarm is ON but provider drifted, fix it â”€â”€
                            if (
                                swarm_on
                                and getattr(kernel, "_model_provider", "")
                                != "iris_local"
                            ):
                                self._logger.warning(
                                    f"[Session: {session_id}] Swarm ON but provider="
                                    f"'{kernel._model_provider}' â€” forcing re-configure to iris_local"
                                )
                                kernel.configure_openai_compat(
                                    _swarm_ep.rstrip("/").removesuffix("/v1"),
                                    provider_name="iris_local",
                                )
                                kernel._selected_reasoning_model = _dir_name
                                kernel._selected_tool_execution_model = _wrk_name
                        except Exception as _swarm_err:
                            self._logger.error(
                                f"[Session: {session_id}] Swarm start failed: {_swarm_err}",
                                exc_info=True,
                            )

                    # â”€â”€ Wire up inference behaviour fields (dead settings fix) â”€â”€
                    # These fields have always been stored in session state but never
                    # consumed by the backend. Map them to kernel attributes so they
                    # actually affect inference.
                    _thinking = values.get("agent_thinking_style")
                    if _thinking in ("concise", "balanced", "thorough"):
                        kernel._thinking_style = _thinking
                        self._logger.info(
                            f"[Session: {session_id}] Thinking style set to '{_thinking}'"
                        )

                    _response_len = values.get("max_response_length")
                    if _response_len in ("short", "medium", "long"):
                        kernel._response_length = _response_len
                        self._logger.info(
                            f"[Session: {session_id}] Response length set to '{_response_len}'"
                        )

                    _reasoning_effort = values.get("reasoning_effort")
                    if _reasoning_effort in ("fast", "balanced", "accurate"):
                        kernel._reasoning_effort = _reasoning_effort
                        self._logger.info(
                            f"[Session: {session_id}] Reasoning effort set to '{_reasoning_effort}'"
                        )

                    _tool_mode = values.get("tool_mode")
                    if _tool_mode in ("auto", "ask_first", "disabled"):
                        kernel._tool_mode = _tool_mode
                        self._logger.info(
                            f"[Session: {session_id}] Tool mode set to '{_tool_mode}'"
                        )

                    # â”€â”€ GGUF Models Directory â”€â”€
                    # Allow user to override where local GGUF models are scanned from.
                    # Empty string means keep default (env var / ~/.lmstudio/models).
                    _models_dir = values.get("models_directory", "").strip()
                    if _models_dir:
                        self._logger.info(
                            f"[Session: {session_id}] Setting models directory to '{_models_dir}'"
                        )
                        from .agent.local_model_manager import get_local_model_manager

                        mgr = get_local_model_manager()
                        mgr.set_models_directory(_models_dir)
                        # Persist to config so it survives restart
                        self._config.inference.models_directory = _models_dir
                    elif "models_directory" in values:
                        # Explicitly empty â€” clear override, revert to default
                        from .agent.local_model_manager import get_local_model_manager

                        mgr = get_local_model_manager()
                        mgr.set_models_directory("")
                        self._config.inference.models_directory = ""

                except Exception as e:
                    self._logger.error(
                        f"[Session: {session_id}] Error applying inference_mode: {e}",
                        exc_info=True,
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
                        "tool_execution_model"
                    )
                    # "local" | "vps" | "api"
                    provider = values.get("model_provider") or values.get("provider")

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
                        extra={"session_id": session_id, "client_id": client_id},
                    )

                    # â”€â”€ Provider URL map â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                    # Named providers with well-known endpoints.
                    # Each maps to a base URL; the user only needs to provide an API key.
                    PROVIDER_ENDPOINTS = {
                        "opencodego": "https://opencode.ai/zen/go/v1",
                        "cerebras": "https://api.cerebras.ai/v1",
                        "chutes": "https://llm.chutes.ai/v1",
                        # Cohere OpenAI-compatible API: https://docs.cohere.com/docs/compatibility-api
                        "cohere": "https://api.cohere.ai/compatibility/v1",
                        "deepseek": "https://api.deepseek.com",
                        # Anthropic OpenAI-compatible API: https://platform.claude.com/docs/en/api/openai-sdk
                        "anthropic": "https://api.anthropic.com/v1",
                    }
                    api_key = values.get("api_key", "") or ""

                    if provider in PROVIDER_ENDPOINTS:
                        # Named API provider â€” URL is pre-configured
                        base_url = PROVIDER_ENDPOINTS[provider]
                        kernel.configure_api(api_key, base_url)
                        kernel.configure_vps({"enabled": False})
                        self._logger.info(
                            f"[Session: {session_id}] {provider} configured: {base_url}",
                            extra={"session_id": session_id},
                        )

                    elif provider == "lmstudio":
                        # LM Studio / any OpenAI-compatible local server.
                        lms_endpoint = (
                            values.get("lmstudio_endpoint", _DEFAULT_LMSTUDIO_URL)
                            or _DEFAULT_LMSTUDIO_URL
                        )
                        kernel.configure_lmstudio(lms_endpoint)
                        kernel.configure_vps({"enabled": False})
                        self._logger.info(
                            f"[Session: {session_id}] LM Studio configured: {lms_endpoint}",
                            extra={"session_id": session_id},
                        )
                        # Pre-warm: fire a 1-token request so LM Studio loads the model
                        # into VRAM now so cold-start delay doesn't hit the first message.
                        kernel.prewarm_lmstudio()

                    elif provider in ("local", "iris_local"):
                        # Local GGUF model â€” configure kernel for in-process endpoint.
                        # Model loading is triggered separately via the Load button
                        # in the model browser (POST /api/models/load).
                        from .agent.local_model_manager import get_local_model_manager

                        mgr = get_local_model_manager()
                        _iris_base = mgr.ENDPOINT.rstrip("/").removesuffix("/v1")
                        kernel.configure_openai_compat(
                            _iris_base, provider_name="iris_local"
                        )
                        if hasattr(kernel, "configure_inprocess_local"):
                            kernel.configure_inprocess_local(mgr)
                        kernel.configure_vps({"enabled": False})
                        self._logger.info(
                            f"[Session: {session_id}] iris_local configured: {_iris_base}",
                            extra={"session_id": session_id},
                        )

                    # Handle vision_enabled toggle
                    if "vision_enabled" in values:
                        vision_on = bool(values.get("vision_enabled", False))
                        await self._handle_set_vision_enabled(
                            session_id, client_id, {"payload": {"enabled": vision_on}}
                        )

                    # Refresh model dropdown so UI reflects available models for the
                    # new provider immediately.
                    if "model_provider" in values:
                        await self._handle_get_available_models(
                            session_id, client_id, {}
                        )

                    # Persist model config via IRISConfig (single source of truth)
                    try:
                        from .iris_config import with_modify_config, RoutingMode

                        def _update_model_config(cfg):
                            cfg.inference.provider = provider or ""
                            cfg.inference.reasoning_model = reasoning or ""
                            cfg.inference.tool_execution_model = tool_exec or ""
                            # Derive base URL from provider name or use lmstudio_endpoint
                            _provider_endpoints = {
                                "opencodego": "https://opencode.ai/zen/go/v1",
                                "cerebras": "https://api.cerebras.ai/v1",
                                "chutes": "https://llm.chutes.ai/v1",
                                "cohere": "https://api.cohere.ai/compatibility/v1",
                                "deepseek": "https://api.deepseek.com",
                                "anthropic": "https://api.anthropic.com/v1",
                            }
                            if provider in _provider_endpoints:
                                cfg.inference.api_base_url = _provider_endpoints[
                                    provider
                                ]
                                cfg.inference.api_key = values.get("api_key", "")
                            elif provider == "lmstudio":
                                cfg.inference.api_base_url = values.get(
                                    "lmstudio_endpoint",
                    load_config().inference.lm_studio_url or "http://localhost:1234",
                                )
                            elif provider in ("local", "iris_local"):
                                # Local GGUF â€” endpoint is the in-process llama server
                                cfg.inference.api_base_url = ""
                                cfg.routing.mode = RoutingMode.SINGLE_LOCAL
                                cfg.inference.provider = "local"
                            # Routing: model_selection only handles API/endpoint providers.
                            # LOCAL/SWARM routing is set by inference_mode confirm_card.
                            if provider not in ("local", "iris_local"):
                                cfg.routing.mode = RoutingMode.SINGLE_API
                                # Force swarm OFF for API providers â€” prevents stale
                                # swarm config from overriding the API provider selection
                                # when the initial state is loaded from localStorage.
                                cfg.inference.swarm_enabled = False

                        cfg = with_modify_config(_update_model_config)
                        self._logger.info(
                            f"[Session: {session_id}] Model config persisted via IRISConfig",
                            extra={"session_id": session_id},
                        )
                    except Exception as _e2:
                        self._logger.warning(
                            f"[Session: {session_id}] Could not persist model config: {_e2}"
                        )
                except Exception as e:
                    self._logger.error(
                        f"[Session: {session_id}] Error applying model selection on confirm: {e}",
                        extra={"session_id": session_id, "client_id": client_id},
                    )

            # â”€â”€ Local Model card â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Apply local_model card values when that section is confirmed.
            # NOTE: This only saves config. Model loading is triggered by the
            # Load button (action: load_local_model) in the card.
            elif section_id == "local_model" and values:
                try:
                    cfg = load_config()
                    path = values.get("local_model_path", "")
                    profile = values.get("local_model_profile", "balanced")
                    ctx = int(values.get("local_model_ctx", 16384))
                    gpu_layers = int(values.get("local_model_gpu_layers", -1))
                    models_dir = values.get("models_directory", "").strip()

                    # Auto-unload previous model if model changed and one is loaded
                    if (
                        cfg.inference.local_model_status == "loaded"
                        and path != cfg.inference.local_model_path
                    ):
                        try:
                            from .agent.local_model_manager import (
                                get_local_model_manager,
                            )

                            mgr = get_local_model_manager()
                            if mgr.is_loaded():
                                await mgr.unload_model()
                                self._logger.info(
                                    f"[Session: {session_id}] Auto-unloaded previous model on config change"
                                )
                        except Exception as ul_e:
                            self._logger.warning(
                                f"[Session: {session_id}] Auto-unload failed: {ul_e}"
                            )
                        cfg.inference.local_model_status = "unloaded"

                    cfg.inference.local_model_path = path
                    cfg.inference.local_model_profile = profile
                    cfg.inference.local_model_ctx = ctx
                    cfg.inference.local_model_gpu_layers = gpu_layers
                    if models_dir:
                        cfg.inference.models_directory = models_dir
                        cfg.inference.local_model_path = ""
                        from .agent.local_model_manager import get_local_model_manager

                        mgr = get_local_model_manager()
                        mgr.set_models_directory(models_dir)
                    save_config(cfg)
                    self._logger.info(
                        f"[Session: {session_id}] Local model config saved on confirm: "
                        f"path={path}, profile={profile}, ctx={ctx}, gpu_layers={gpu_layers}"
                    )
                except Exception as e:
                    self._logger.error(
                        f"[Session: {session_id}] Error applying local_model: {e}",
                        exc_info=True,
                    )

            # â”€â”€ Swarm Setup card â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Apply swarm_setup card values when that section is confirmed.
            # NOTE: This only saves config. Swarm is started/stopped by the
            # Start Swarm / Stop Swarm buttons in the card.
            elif section_id == "swarm_setup" and values:
                try:
                    cfg = load_config()
                    swarm_on = bool(values.get("swarm_enabled", False))
                    mode = values.get("swarm_mode", "local_fast")
                    worker_ctx = int(values.get("worker_context", 2048))
                    models_dir = values.get("models_directory", "").strip()

                    cfg.inference.swarm_enabled = swarm_on
                    cfg.inference.swarm_mode = mode
                    cfg.inference.worker_context = str(worker_ctx)
                    if models_dir:
                        cfg.inference.models_directory = models_dir
                    save_config(cfg)
                    self._logger.info(
                        f"[Session: {session_id}] Swarm config saved on confirm: "
                        f"enabled={swarm_on}, mode={mode}, worker_ctx={worker_ctx}"
                    )
                except Exception as e:
                    self._logger.error(
                        f"[Session: {session_id}] Error applying swarm_setup: {e}",
                        exc_info=True,
                    )

            # Apply memory settings when the memory section is confirmed.
            # The context_window slider lets the user override the auto-detected
            # value (in thousands of tokens).  The kernel resolves the actual
            # context window from the selected model; this slider is a ceiling.
            elif section_id == "memory" and values:
                try:
                    from .agent.agent_kernel import get_agent_kernel

                    kernel = get_agent_kernel(session_id)
                    ctx_override = values.get("context_window")
                    if ctx_override is not None:
                        # Slider value is in thousands (5 = 5k, 50 = 50k)
                        ctx_tokens = int(float(ctx_override)) * 1000
                        ctx_tokens = max(1000, min(ctx_tokens, 1_000_000))
                        # Set as override so resolve_context_window returns this
                        # instead of auto-detecting
                        model = (
                            kernel._selected_reasoning_model
                            or kernel._model_name
                            or "current"
                        )
                        kernel._context_window_overrides[model] = ctx_tokens
                        kernel._sync_context_window()
                        self._logger.info(
                            f"[Session: {session_id}] Memory context_window "
                            f"override â†’ {ctx_tokens} tokens (model={model})"
                        )
                except Exception as e:
                    self._logger.error(
                        f"[Session: {session_id}] Error applying memory settings: {e}",
                        exc_info=True,
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
                        device = self._resolve_device_index(device, want_input=True)
                        engine.update_config(input_device=device)
                        self._logger.info(
                            f"[Session: {session_id}] Input device applied on confirm: {device}",
                            extra={"session_id": session_id, "client_id": client_id},
                        )
                except Exception as e:
                    self._logger.error(
                        f"[Session: {session_id}] Error applying input device on confirm: {e}",
                        extra={"session_id": session_id, "client_id": client_id},
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
                        device = self._resolve_device_index(device, want_input=False)
                        engine.update_config(output_device=device)
                        self._logger.info(
                            f"[Session: {session_id}] Output device applied on confirm: {device}",
                            extra={"session_id": session_id, "client_id": client_id},
                        )
                except Exception as e:
                    self._logger.error(
                        f"[Session: {session_id}] Error applying output device on confirm: {e}",
                        extra={"session_id": session_id, "client_id": client_id},
                    )

            # â”€â”€ Monitor cards: analytics / logs / diagnostics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # These cards show system status.  When confirmed we push live
            # data back into the card fields via update_field messages.
            elif section_id in ("analytics", "logs", "diagnostics") and values is not None:
                await self._handle_monitor_card(
                    session_id, client_id, section_id, values
                )
                # Return early so we skip orbit confirmation (monitor is global)
                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "card_confirmed",
                        "payload": {
                            "section_id": section_id,
                            "orbit_angle": 0,
                            "applied": True,
                        },
                    },
                )
                return

            # Get current category
            state = await self._state_manager.get_state(session_id)
            if not state or not state.current_category:
                # Model selection and critical config sections should work
                # even without an active orbit category â€” they're global settings.
                if section_id in ("model_selection", "identity", "inference_mode"):
                    logger.info(
                        f"[Gateway] confirm_card {section_id} applied (no active category â€” "
                        "skipping orbit confirmation)"
                    )
                    # Broadcast that config was applied even without orbit
                    await self._ws_manager.send_to_client(
                        client_id,
                        {
                            "type": "card_confirmed",
                            "payload": {
                                "section_id": section_id,
                                "orbit_angle": 0,
                                "applied": True,
                            },
                        },
                    )
                    return
                await self._send_error(client_id, "No active category")
                return

            # Confirm section
            orbit_angle = await self._state_manager.confirm_section(
                session_id, state.current_category.value, section_id, values
            )

            if orbit_angle is not None:
                # Send confirmation with section context so the UI can show feedback
                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "card_confirmed",
                        "payload": {
                            "section_id": section_id,
                            "orbit_angle": orbit_angle,
                            "applied": True,
                        },
                    },
                )

                # Broadcast state update
                await self._broadcast_state_update(session_id, exclude_client=client_id)
            else:
                await self._send_error(client_id, "Failed to confirm card")

    def set_voice_handler(self, voice_handler) -> None:
        """Wire the VoiceCommandHandler so voice triggers can delegate to it."""
        self._voice_handler = voice_handler
        voice_handler.set_command_result_callback(self._on_voice_result)

        # v2 (Phase 7): Instantiate ConversationKernel â€” thin wrapper
        # on the existing voice pipeline. The kernel adds Caducean
        # phase-awareness to decisions the existing classes already make.
        # No new VAD, no new TTS, no new state machine (see plan Â§Component 5).
        # Broadcast real-time audio levels during recording so the IrisOrb
        # can animate its pulse in sync with the user's voice.
        # The callback is called from the VAD background thread every ~100 ms.
        def _on_audio_level(level: float) -> None:
            # FIX: Don't gate on _active_session_id â€” if the voice handler
            # hasn't set one yet (e.g. during the first wake-word cycle),
            # broadcast to "default" so the orb still pulses.
            session_id = getattr(voice_handler, "_active_session_id", None) or "default"
            loop = self._main_loop
            if loop and loop.is_running():
                import asyncio as _asyncio

                _asyncio.run_coroutine_threadsafe(
                    self._ws_manager.broadcast_to_session(
                        session_id,
                        {
                            "type": "audio_level",
                            "payload": {"level": level},
                        },
                    ),
                    loop,
                )
            else:
                # FIX: Log when the main loop isn't available â€” this is a
                # silent failure mode that was hiding audio level issues.
                _diag_count = getattr(self, "_audio_level_no_loop_count", 0)
                if _diag_count < 3:
                    self._audio_level_no_loop_count = _diag_count + 1
                    logger.warning(
                        f"[AUDIO_LEVEL] Cannot broadcast: main loop "
                        f"not running (level={level:.3f}, session={session_id})"
                    )

        # Set the private attribute directly so that ConversationKernel sees it
        # and chains it without us having to call set_audio_level_callback first.
        if hasattr(voice_handler, "set_audio_level_callback"):
            voice_handler._on_audio_level = _on_audio_level

        kernel_ok = False
        try:
            from backend.agent.conversation_kernel import (
                ConversationKernel,
                set_conversation_kernel,
            )

            audio_pipeline = getattr(self, "_audio_pipeline", None)
            kernel = ConversationKernel(
                voice_handler=voice_handler,
                tts_manager=getattr(self, "_tts_manager", None),
                audio_pipeline=audio_pipeline,
                session_id_getter=lambda: getattr(self, "_caducean_session_id", None),
            )
            kernel.register_callbacks()
            set_conversation_kernel(kernel)
            logger.info("[iris_gateway] ConversationKernel instantiated and wired")
            kernel_ok = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[iris_gateway] ConversationKernel setup failed (non-fatal): %s", exc
            )

        # If ConversationKernel failed to register, fall back to registering directly.
        if not kernel_ok and hasattr(voice_handler, "set_audio_level_callback"):
            voice_handler.set_audio_level_callback(_on_audio_level)

        # Broadcast consolidated audio_envelope (rms + cadence + phase) for XurOrb.
        # This carries richer data than the legacy audio_level message and covers
        # both listening (STT) and speaking (TTS) phases in a single message type.
        def _on_audio_envelope(rms: float, cadence: float, phase: str) -> None:
            session_id = getattr(voice_handler, "_active_session_id", None)
            if not session_id:
                return
            loop = self._main_loop
            if loop and loop.is_running():
                import asyncio as _asyncio

                _asyncio.run_coroutine_threadsafe(
                    self._ws_manager.broadcast_to_session(
                        session_id,
                        {
                            "type": "audio_envelope",
                            "payload": {
                                "rms": rms,
                                "cadence": cadence,
                                "phase": phase,
                            },
                        },
                    ),
                    loop,
                )

        if hasattr(voice_handler, "set_audio_envelope_callback"):
            voice_handler.set_audio_envelope_callback(_on_audio_envelope)

        # Register energy-based barge-in callback on the audio engine.
        # When the user speaks over TTS playback, this fires from the PortAudio
        # input thread to stop playback and start a new recording.
        try:
            from .audio.engine import get_audio_engine as _get_ae

            _engine = _get_ae()
            _engine.set_barge_in_detected_callback(self._on_barge_in_detected)
        except Exception:
            pass

    # â”€â”€ Energy-based barge-in handler â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Fired from the PortAudio input thread when user speech is detected over
    # active TTS playback.  Reopens the half-duplex gate, stops TTS, and
    # starts a new recording â€” all without wake word involvement.
    def _on_barge_in_detected(self) -> None:
        """Stop TTS and start listening when user speaks over playback."""
        try:
            from .audio.engine import get_audio_engine as _get_ae

            _engine = _get_ae()
            if not _engine._tts_active:
                return  # safety: not in TTS state, ignore

            # Resolve session: use the active TTS session, falling back to any
            # conversation session or "default".  This ensures the new recording
            # targets the correct conversation and auto-relisten works after TTS.
            _sid = self._active_tts_session
            if _sid is None and self._conversation_sessions:
                _sid = next(iter(self._conversation_sessions))
            if _sid is None:
                _sid = "default"

            self._logger.info(
                f"[BargeIn] User speech over TTS â€” interrupting session {_sid}"
            )

            # 1. Ensure conversation mode so TTS response auto-relistens
            self._conversation_sessions.add(_sid)

            # 2. Reopen half-duplex gate immediately â€” don't wait for finally
            _engine.set_tts_active(False)

            # 3. Stop TTS synthesis + native player
            _engine.interrupt_speech()

            # 4. Stop cadence threads so orb transitions out of Mode D
            if self._barge_in_stop is not None:
                self._barge_in_stop.set()

            # 5. Broadcast listening to the correct session via event loop
            if self._main_loop and self._main_loop.is_running():
                import asyncio as _asyncio

                _asyncio.run_coroutine_threadsafe(
                    self._ws_manager.broadcast_to_session(
                        _sid,
                        {
                            "type": "listening_state",
                            "payload": {"state": "listening"},
                        },
                    ),
                    self._main_loop,
                )

            # 6. Start a new recording on the correct session
            if self._voice_handler is not None:
                self._voice_handler.set_active_session(_sid)
                self._voice_handler.start_recording(
                    auto_stop=True,
                    pre_speech_timeout_sec=self._relisten_pre_speech_timeout,
                    play_beep=False,  # skip beep during barge-in re-recording
                )
                self._logger.info(
                    f"[BargeIn] Recording started for session {_sid}"
                )

        except Exception as _b_exc:
            self._logger.error(
                f"[BargeIn] handler error: {_b_exc}", exc_info=True
            )

    async def _handle_voice(
        self,
        session_id: str,
        client_id: str,
        message: dict,
        auto_stop: bool = True,
        pre_speech_timeout_sec: float | None = None
    ) -> None:
        """
        Handle voice_command_start / voice_command_end from double-click or wake word.
        Delegates audio capture + LFM2-Audio processing to VoiceCommandHandler/ModelManager.
        All 4 pillars run after transcription is received via _on_voice_result callback.

        pre_speech_timeout_sec: For auto_stop mode, give up if speech doesn't start
            within this many seconds. None = use VoiceCommandHandler default (0 = 30s max).

        auto_stop is True by default (VAD-driven). When True:
          - Recording auto-stops after `silence_timeout_sec` seconds of silence
          - Then STT processes, agent responds, and conversation mode auto-relistens
          - This enables the back-and-forth conversational flow

          When False (only for backward compat):
          - User must manually send voice_command_end to trigger STT
        """
        msg_type = message.get("type")
        if msg_type == "voice_command":
            msg_type = "voice_command_start"

        # DIAGNOSTIC: log every voice message with payload summary
        payload_keys = list(message.get("payload", {}).keys()) if isinstance(message.get("payload"), dict) else []
        self._logger.info(
            f"[VoiceMSG] type={msg_type} session={session_id} client={client_id} "
            f"auto_stop={auto_stop} payload_keys={payload_keys}"
        )

        try:
            if msg_type == "voice_command_start":
                self._logger.info(f"[Session: {session_id}] Voice command start")
                # Enable conversation mode â€” will auto-relisten after each TTS response
                self._conversation_sessions.add(session_id)

                # Interrupt TTS only if it is currently playing.
                # Calling interrupt_speech() unconditionally sets
                # _speech_interrupted = True and the flag persists until the
                # playback loop in _speak_response() consumes it.  If no TTS
                # was running, the flag stays True and the *next* TTS response
                # bails immediately at the is_speech_interrupted() check â€”
                # producing silence even though the orb animates as "speaking".
                try:
                    from .audio.engine import get_audio_engine

                    engine = get_audio_engine()
                    if engine._tts_active:
                        engine.interrupt_speech()
                except Exception:
                    pass  # non-fatal â€” audio engine may not be up yet

                # Track which client triggered this so wake-word callback knows where to respond
                self._active_voice_client[session_id] = client_id

                # Pocket-TTS loads lazily on first synthesize_stream() call.
                # No pre-trigger here â€” model must not load until the user
                # actually requests speech output.

                # Broadcast LISTENING immediately so IrisOrb animates
                await self._ws_manager.broadcast_to_session(
                    session_id,
                    {"type": "listening_state", "payload": {"state": "listening"}},
                )

                # Delegate recording to the shared VoiceCommandHandler
                if self._voice_handler:
                    self._voice_handler.set_active_session(session_id)
                    kw = {"auto_stop": auto_stop}
                    if pre_speech_timeout_sec is not None:
                        kw["pre_speech_timeout_sec"] = pre_speech_timeout_sec
                    success = self._voice_handler.start_recording(**kw)
                    if not success:
                        self._logger.warning(
                            f"[Session: {session_id}] VoiceCommandHandler start_recording() failed â€” resetting orb to idle"
                        )
                        await self._ws_manager.broadcast_to_session(
                            session_id,
                            {"type": "listening_state", "payload": {"state": "idle"}},
                        )
                else:
                    self._logger.error(
                        "[Voice] VoiceCommandHandler not wired â€” call set_voice_handler()"
                    )
                    await self._ws_manager.broadcast_to_session(
                        session_id,
                        {"type": "listening_state", "payload": {"state": "error"}},
                    )
                    # Auto-recover from error state after 2 s
                    await asyncio.sleep(2.0)
                    await self._ws_manager.broadcast_to_session(
                        session_id,
                        {"type": "listening_state", "payload": {"state": "idle"}},
                    )

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
                # _cancelled=True and skipped Whisper entirely â€” silently
                # breaking the entire voice pipeline.
                if has_audio:
                    await self._ws_manager.broadcast_to_session(
                        session_id,
                        {
                            "type": "listening_state",
                            "payload": {"state": "processing_conversation"},
                        },
                    )
                else:
                    await self._ws_manager.broadcast_to_session(
                        session_id,
                        {"type": "listening_state", "payload": {"state": "idle"}},
                    )
                if self._voice_handler:
                    self._voice_handler.stop_recording()

            elif msg_type == "voice_command_cancel":
                self._logger.info(
                    f"[Session: {session_id}] Voice command cancelled by user"
                )
                # Exit conversation mode â€” user explicitly stopped
                self._conversation_sessions.discard(session_id)
                if self._voice_handler:
                    self._voice_handler.cancel_recording()
                # Interrupt TTS if currently playing
                try:
                    from .audio.engine import get_audio_engine

                    engine = get_audio_engine()
                    engine.interrupt_speech()  # idempotent â€” safe to call when idle
                    # Also flush the native player's ring buffer so already-queued
                    # audio stops immediately (synthesis cancel â‰  playback stop).
                    if engine.pipeline:
                        engine.pipeline.interrupt()
                except Exception:
                    pass
                await self._ws_manager.broadcast_to_session(
                    session_id,
                    {"type": "listening_state", "payload": {"state": "idle"}},
                )

            elif msg_type == "test_audio":
                subtask = message.get("payload", {}).get("type", "")
                try:
                    from .audio.engine import get_audio_engine
                    engine = get_audio_engine()
                except Exception:
                    engine = None
                if subtask == "output" and engine and engine.pipeline:
                    # Play the activation sound as a test tone
                    self._logger.info("[Test] Playing test output sound")
                    try:
                        import numpy as np
                        sr = 24000
                        t = np.linspace(0, 0.2, int(sr * 0.2))
                        tone = (0.25 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
                        engine.pipeline.play_audio(tone, sample_rate=sr)
                        await self._ws_manager.broadcast_to_session(
                            session_id,
                            {"type": "notification", "payload": {"text": "Playing test tone on output device"}},
                        )
                    except Exception as be:
                        self._logger.warning(f"[Test] Output test failed: {be}")
                elif subtask == "input" and engine and engine.pipeline:
                    level = 0.0
                    try:
                        level = engine.pipeline.get_current_input_level()
                    except Exception:
                        pass
                    self._logger.info(f"[Test] Current mic level: {level:.4f}")
                    await self._ws_manager.broadcast_to_session(
                        session_id,
                        {"type": "notification", "payload": {"text": f"Mic level: {level:.4f}"}},
                    )
                else:
                    self._logger.info(f"[Test] No audio pipeline for test_{subtask}")

        except Exception as e:
            self._logger.error(f"[Voice] Error in _handle_voice: {e}", exc_info=True)
            await self._ws_manager.broadcast_to_session(
                session_id, {"type": "listening_state", "payload": {"state": "error"}}
            )

    def _on_voice_result(self, result: dict) -> None:
        """
        Callback fired by VoiceCommandHandler when LFM2-Audio finishes processing.
        Extracts transcript + audio context and routes through 4-pillar pipeline.
        Called from a background thread â€” uses asyncio.run_coroutine_threadsafe.
        """
        try:
            transcript = result.get("transcript", "").strip()
            audio_context = result.get("audio_context", "").strip()
            session_id = result.get("session_id", "default")
            client_id = self._active_voice_client.get(session_id)

            # Use the loop captured during the first async message dispatch.
            # Never call asyncio.get_event_loop() here â€” this runs in a background
            # thread and that call raises "no current event loop" on Python 3.10+.
            loop = self._main_loop
            if loop is None or not loop.is_running():
                self._logger.error(
                    "[Voice] _on_voice_result: main event loop not available"
                )
                return

            if not transcript or not client_id:
                self._logger.warning(
                    f"[Voice] Empty transcript or unknown client for session {session_id}"
                )
                # Empty transcript during conversation mode relisten = user finished talking
                # Clear conversation mode so we return to true idle
                self._conversation_sessions.discard(session_id)
                asyncio.run_coroutine_threadsafe(
                    self._ws_manager.broadcast_to_session(
                        session_id,
                        {"type": "listening_state", "payload": {"state": "idle"}},
                    ),
                    loop,
                )
                return

            asyncio.run_coroutine_threadsafe(
                self._process_voice_transcription(
                    session_id, client_id, transcript, audio_context
                ),
                loop,
            )
        except Exception as e:
            self._logger.error(f"[Voice] _on_voice_result error: {e}", exc_info=True)

    # ------------------------------------------------------------------ #
    # Helper: build a text_response WS message with a unique turn_id.   #
    # Every text_response MUST carry a turn_id so the frontend dedup     #
    # logic can reject duplicates (Issue #2 from the audio pipeline      #
    # audit).  Use this method everywhere we dispatch text_response.     #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _text_response(
        text: str,
        sender: str = "assistant",
        *,
        turn_id: str | None = None,
        thinking: str | None = None,
        suggestions: list[dict] | None = None,
        **kw,
    ) -> dict:
        msg: dict = {
            "type": "text_response",
            "turn_id": turn_id or get_turn_id(),
            "text": text,
            "sender": sender,
        }
        if thinking is not None:
            msg["thinking"] = thinking
        if suggestions is not None:
            msg["suggestions"] = suggestions
        msg.update(kw)
        return msg

    async def _process_voice_transcription(
        self, session_id: str, client_id: str, transcript: str, audio_context: str
    ) -> None:
        """
        Full 4-pillar pipeline after STT transcription.

        State machine:
          listening â†’ processing_conversation (LLM thinking)
                    â†’ speaking               (TTS playing)
                    â†’ idle                   (TTS done / no spoken text)

        The text response appears in ChatView as soon as the LLM returns,
        independent of TTS.  TTS plays after the full response is ready so
        the orb transitions correctly and never gets stuck in speaking state.
        """
        import asyncio
        import threading

        loop = asyncio.get_running_loop()
        _tts_started = False
        import time as _voice_time

        # Voice pipeline timing profiler.  Logs deltas at key stages so we can
        # see exactly where the 8-15s delay lives (VAD -> LLM -> TTS -> audio).
        self._voice_timing = {
            "vad_end": _voice_time.monotonic(),
            "llm_start": None,
            "first_chunk": None,
            "first_sentence": None,
            "tts_thread_start": None,
            "first_tts_chunk": None,
            "first_audio_played": None,
            "llm_end": None,
            "text_response_sent": None,
        }

        def _log_timing(label: str):
            self._voice_timing[label] = _voice_time.monotonic()
            t0 = self._voice_timing["vad_end"]
            dt = self._voice_timing[label] - t0
            self._logger.info(f"[VOICE_TIMING] {label}: +{dt:.3f}s")

        try:
            # â”€â”€ Pillar 1A: user bubble â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "text_response",
                    "turn_id": get_turn_id(),
                    "payload": {"text": transcript, "sender": "user"},
                },
            )

            enriched = transcript
            if audio_context:
                enriched = f"{transcript}\n\n[Audio context: {audio_context}]"

            from .agent.agent_kernel import get_agent_kernel

            agent_kernel = get_agent_kernel(session_id)

            if agent_kernel._tool_bridge is None:
                from .agent.tool_bridge import get_agent_tool_bridge

                agent_kernel._tool_bridge = get_agent_tool_bridge()

            # â”€â”€ Orb: thinking while LLM runs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            await self._ws_manager.broadcast_to_session(
                session_id,
                {
                    "type": "listening_state",
                    "payload": {"state": "processing_conversation"},
                },
            )

            # â”€â”€ Looping "processing" sound while LLM thinks â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Load the WAV file BEFORE starting the thread so playback begins
            # immediately â€” the file load + resample takes ~50ms and if the
            # agent responds before that, the stop event is already set and
            # zero iterations play.
            _sttproc_stop = threading.Event()
            _sttproc_data = None
            _sttproc_sr = None
            _sttproc_dev = None
            try:
                import sounddevice as _sd_s
                import soundfile as _sf_s
                import numpy as _np_s
                _path = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)),
                    "data", "STTPROC.wav",
                )
                if os.path.isfile(_path):
                    _sttproc_data, _sttproc_sr = _sf_s.read(_path, dtype="float32")
                    if _sttproc_data.ndim > 1:
                        _sttproc_data = _sttproc_data.mean(axis=1)
                    # 3x gain: STTPROC.wav is âˆ’27.4 dBFS, target ~âˆ’17.9 dBFS
                    _sttproc_data = _np_s.clip(_sttproc_data * 3.0, -0.99, 0.99)
                    if _sttproc_sr != 24000:
                        _ratio = 24000 / _sttproc_sr
                        _len = int(len(_sttproc_data) * _ratio)
                        _sttproc_data = _np_s.interp(
                            _np_s.linspace(0, len(_sttproc_data) - 1, _len),
                            _np_s.arange(len(_sttproc_data)),
                            _sttproc_data,
                        )
                        _sttproc_sr = 24000
                    from .audio.engine import get_audio_engine as _getae_s
                    _eng_s = _getae_s()
                    _sttproc_dev = _eng_s.pipeline.output_device if (_eng_s.pipeline and _eng_s.pipeline.output_device is not None) else None
                    # Resolve "Default" string → None for sounddevice compatibility
                    if isinstance(_sttproc_dev, str) and _sttproc_dev.lower() in ("default", ""):
                        _sttproc_dev = None
                    self._logger.info(
                        f"[STTPROC] Pre-loaded {len(_sttproc_data)} samples @ {_sttproc_sr}Hz "
                        f"device={_sttproc_dev}"
                    )
            except Exception as _stt_pre:
                self._logger.warning(f"[STTPROC] Pre-load failed: {_stt_pre}")

            def _loop_sttproc():
                if _sttproc_data is None:
                    return
                try:
                    import sounddevice as _sd2
                    _loop_count = 0
                    self._logger.info("[STTPROC] Loop starting...")
                    while True:
                        _loop_count += 1
                        _sd2.play(_sttproc_data, _sttproc_sr, device=_sttproc_dev, blocking=True)
                        # Check AFTER playback â€” ensures current iteration finishes
                        # and gives TTS a moment to start before we go silent.
                        if _sttproc_stop.is_set():
                            # Play one more short overlap to avoid dead silence gap
                            _sttproc_stop.wait(0.3)
                            break
                    self._logger.info(f"[STTPROC] Loop ended ({_loop_count} iterations)")
                except Exception as _stt_err:
                    self._logger.warning(f"[STTPROC] Playback error: {_stt_err}")

            _sttproc_thread = threading.Thread(
                target=_loop_sttproc, daemon=True, name="sttproc-loop"
            )
            _sttproc_thread.start()

            # â”€â”€ Streaming TTS: sentence queue shared between LLM and playback â”€
            import re as _re

            sentence_queue = queue.Queue()
            sentence_buf = []
            _sentence_buf_words = 0
            _SENTENCE_MAX_WORDS = 50  # flush if sentence grows too long

            def _execute_agent():
                _log_timing("llm_start")
                _first_chunk_seen = False
                _first_sentence_seen = False

                def chunk_callback(chunk: str):
                    if loop and loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            self._ws_manager.send_to_client(
                                client_id,
                                {
                                    "type": "chat_chunk",
                                    "payload": {"chunk": chunk},
                                },
                            ),
                            loop,
                        )

                    # Stream sentences into TTS from RESPONSE text
                    # (chunk_callback receives actual response content from the LLM,
                    #  NOT reasoning/thinking â€” reasoning goes through reasoning_callback).
                    nonlocal _sentence_buf_words
                    nonlocal _first_chunk_seen
                    nonlocal _first_sentence_seen
                    if not _first_chunk_seen:
                        _first_chunk_seen = True
                        _log_timing("first_chunk")
                    sentence_buf.append(chunk)
                    _sentence_buf_words += chunk.count(" ") + (
                        1 if chunk.strip() else 0
                    )
                    text = "".join(sentence_buf)
                    if m := _re.search(r"([.!?;,:])\s+|(?<=.{30})\s+", text):
                        if not _first_sentence_seen:
                            _first_sentence_seen = True
                            _log_timing("first_sentence")
                        # Flush on hard stops (. ! ?) or soft pauses (; , :) or 30+ chars at word boundary
                        complete = text[: m.end()]
                        sentence_queue.put(complete)
                        remainder = text[m.end() :]
                        sentence_buf[:] = [remainder]
                        _sentence_buf_words = remainder.count(" ") + (
                            1 if remainder.strip() else 0
                        )
                    elif _sentence_buf_words >= _SENTENCE_MAX_WORDS:
                        if not _first_sentence_seen:
                            _first_sentence_seen = True
                            _log_timing("first_sentence")
                        # Flush oversized sentence to avoid infinite buffering
                        sentence_queue.put(text)
                        sentence_buf.clear()
                        _sentence_buf_words = 0

                def reasoning_callback(chunk: str):
                    if loop and loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            self._ws_manager.send_to_client(
                                client_id,
                                {
                                    "type": "chat_reasoning",
                                    "payload": {"chunk": chunk},
                                },
                            ),
                            loop,
                        )

                try:
                    resp = agent_kernel.process_text_message(
                        enriched,
                        session_id=session_id,
                        chunk_callback=chunk_callback,
                        reasoning_callback=reasoning_callback,
                        from_voice=True,
                    )
                    _log_timing("llm_end")
                    # Final flush â€” any remaining text becomes a sentence
                    if sentence_buf:
                        sentence_queue.put("".join(sentence_buf))
                        sentence_buf.clear()
                    spoken = agent_kernel.prepare_spoken_text(resp, enriched)
                    return resp, spoken
                finally:
                    # ALWAYS put sentinel â€” even if agent throws, the TTS thread
                    # must not block forever on sentence_queue.get().
                    sentence_queue.put(None)

            # "speaking" state is now sent by _speak_response when audio actually
            # starts playing â€” not here while the LLM is still thinking.
            _tts_started = True

            # â”€â”€ Start TTS thread BEFORE agent runs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # chunk_callback pushes response sentences into sentence_queue
            # during LLM generation.  The TTS thread picks them up and starts
            # playing the first sentence immediately â€” no waiting for full reply.
            _loop = asyncio.get_running_loop()

            def _wrap_tts_streaming(q: queue.Queue, sid: str, cid: str, _l):
                """Consume sentences from the queue and stream TTS.

                Always ensures voice state returns to idle on error.
                On success, _speak_response's finally block handles state
                (auto-relisten in conversation, idle otherwise).
                """
                _log_timing("tts_thread_start")
                _succeeded = False
                try:
                    self._logger.info("[TTS] _wrap_tts_streaming started â€” calling _speak_response")
                    self._speak_response(q, sid, _sttproc_stop=_sttproc_stop, _client_id=cid)
                    self._logger.info("[TTS] _speak_response completed")
                    _succeeded = True
                except Exception as _tts_err:
                    self._logger.error(f"[TTS] streaming fatal: {_tts_err}", exc_info=True)
                finally:
                    # Only send idle on ERROR â€” _speak_response's own finally
                    # block already handles the success case (auto-relisten or idle).
                    # Sending idle unconditionally would override conversation-mode
                    # auto-relisten and break back-and-forth flow.
                    if not _succeeded:
                        try:
                            _l.call_soon_threadsafe(
                                lambda: asyncio.ensure_future(
                                    self._ws_manager.send_to_client(
                                        cid,
                                        {
                                            "type": "listening_state",
                                            "payload": {"state": "idle"},
                                        },
                                    )
                                )
                            )
                        except Exception:
                            pass

            threading.Thread(
                target=_wrap_tts_streaming,
                args=(sentence_queue, session_id, client_id, _loop),
                daemon=True,
                name="voice-tts-streaming",
            ).start()

            # Run agent synchronously in thread pool â€” chunk_callback pushes
            # sentences into sentence_queue as the LLM streams the response.
            response, spoken = await loop.run_in_executor(None, _execute_agent)

            # â”€â”€ Pillar 1B: assistant bubble in ChatView â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            thinking = getattr(agent_kernel, "_pending_thinking", "") or ""
            _log_timing("text_response_sent")
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "text_response",
                    "turn_id": get_turn_id(),
                    "payload": {
                        "text": response,
                        "sender": "assistant",
                        **({"thinking": thinking} if thinking else {}),
                    },
                },
            )

        except Exception as e:
            self._logger.error(
                f"[Voice] Pipeline error for session {session_id}: {e}", exc_info=True
            )
            if _sttproc_stop is not None:
                _sttproc_stop.set()  # stop STTPROC immediately on error
            await self._ws_manager.broadcast_to_session(
                session_id, {"type": "listening_state", "payload": {"state": "error"}}
            )
            await asyncio.sleep(2.0)
            await self._ws_manager.broadcast_to_session(
                session_id, {"type": "listening_state", "payload": {"state": "idle"}}
            )

        finally:
            if not _tts_started:
                # Safety net: if TTS never started, ensure STTPROC stops
                # and we always reach idle.
                if _sttproc_stop is not None:
                    _sttproc_stop.set()
            # â”€â”€ Voice pipeline timing summary â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if hasattr(self, "_voice_timing"):
                t0 = self._voice_timing["vad_end"]
                total = _voice_time.monotonic() - t0
                summary_lines = ["[VOICE_TIMING_SUMMARY] pipeline timings:"]
                labels = [
                    ("vad_end", "VAD end / pipeline start"),
                    ("llm_start", "LLM start"),
                    ("first_chunk", "LLM first text chunk"),
                    ("first_sentence", "First sentence flushed"),
                    ("tts_thread_start", "TTS thread start"),
                    ("first_sentence_in_producer", "Producer received first sentence"),
                    ("first_tts_synth_start", "TTS synthesis start (first chunk)"),
                    ("first_audio_pushed", "First audio chunk pushed to player"),
                    ("tts_started_event_sent", "tts_started event sent"),
                    ("llm_end", "LLM end"),
                    ("text_response_sent", "text_response sent"),
                ]
                for key, desc in labels:
                    ts = self._voice_timing.get(key)
                    if ts:
                        summary_lines.append(f"  {desc}: +{ts - t0:.3f}s")
                summary_lines.append(f"  total elapsed: +{total:.3f}s")
                self._logger.info("\n".join(summary_lines))
                delattr(self, "_voice_timing")
            self._logger.debug(f"[Voice] Pipeline complete for session {session_id}")

    @staticmethod
    def _clean_for_speech(text: str) -> str:
        """Sanitise *text* before sending to the TTS engine.

        Removes emoji (which TTS models spell out letter-by-letter or skip
        unpredictably), strips markdown formatting, and replaces exclamation
        marks with periods so the cloned voice delivers a calm, measured tone
        instead of the overly energetic delivery that occurs when the model
        generates sentences ending in '!'.
        """
        # Use module-level pre-compiled patterns â€” no per-call re.compile() cost.
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

    def _speak_response(
        self,
        input_source: Union[str, queue.Queue],
        session_id: str = None,
        _sttproc_stop: Optional[threading.Event] = None,
        _client_id: str = None,
    ) -> None:
        """
        Synthesise and play text through the configured TTS engine.
        Using a producer-consumer pattern to stream audio chunks as soon as they
        are ready, minimizing latency for the first spoken word.

        Args:
            input_source: Either the full text to speak (str) or a queue.Queue
                       that will receive sentences in real-time.
            session_id: Optional session ID to broadcast idle state to when finished.
            _sttproc_stop: Optional event to signal that TTS playback has started.
                       The "processing" loop sound (STTPROC.wav) stops when this
                       fires â€” set here at the point where audio device opens,
                       not when the TTS thread begins.
        """
        from .agent import get_tts_manager
        from .agent.tts import OUTPUT_SAMPLE_RATE as _TTS_SAMPLE_RATE
        from .audio.engine import get_audio_engine
        import logging as _logging

        _root_log = _logging.getLogger()
        engine = get_audio_engine()
        tts = get_tts_manager()

        import threading as _thr
        _tts_call_id = id(_thr.current_thread())
        _root_log.info(
            f"[TTS] _speak_response #{_tts_call_id}: "
            f"input_type={type(input_source).__name__}, "
            f"session={session_id}, text_preview={str(input_source)[:80]!r}"
        )

        # Track active TTS session for barge-in handler
        if session_id:
            self._active_tts_session = session_id

        if not engine.pipeline:
            _root_log.error("[TTS] _speak_response: no engine.pipeline, aborting")
            return
        _root_log.info(f"[TTS] engine.pipeline OK, tts manager loaded={tts.is_loaded()}")

        # 1. Internal state
        audio_queue: queue.Queue = queue.Queue(maxsize=4)  # Buffer a few chunks
        interrupted = threading.Event()
        loop = self._main_loop or asyncio.get_event_loop()

        # Dynamic chunking: synthesise first sentence immediately for instant
        # voice onset, then use larger chunks for stable continuous playback.
        # v2 (Phase 7): if ConversationKernel is active, scale the chunk
        # thresholds by force_magnitude from Caducean. Same physics signal
        # that gates every other phase-driven decision in v2.
        # When kernel is inactive, fall back to the v1 hardcoded defaults.
        _first_chunk_threshold = 1
        _normal_chunk_threshold = 8
        try:
            from backend.agent.conversation_kernel import get_conversation_kernel

            _ck = get_conversation_kernel()
            if _ck is not None:
                # chunk size is in tokens; convert to words (~0.75 words/token)
                # then subtract a small "first chunk" bonus for instant onset.
                _ck_tokens = _ck.get_tts_chunk_size()
                _ck_words = max(1, int(_ck_tokens * 0.75))
                _first_chunk_threshold = 1  # always 1 word for instant onset
                _normal_chunk_threshold = max(2, _ck_words)
                logger.debug(
                    "[_speak_response] Caducean-modulated TTS chunks: first=1, normal=%d (tokens=%d)",
                    _normal_chunk_threshold,
                    _ck_tokens,
                )
        except Exception as _ck_exc:  # noqa: BLE001
            logger.debug("[_speak_response] kernel modulation unavailable: %s", _ck_exc)
        FIRST_CHUNK_THRESHOLD = _first_chunk_threshold
        NORMAL_CHUNK_THRESHOLD = _normal_chunk_threshold

        # â”€â”€ Notify frontend: TTS is starting â”€â”€
        # Must happen regardless of native vs fallback player path.
        # Only for string input â€” queue input gets "speaking" from the caller.
        if (
            isinstance(input_source, str)
            and session_id
            and self._main_loop
            and self._main_loop.is_running()
        ):
            import asyncio as _asyncio

            _asyncio.run_coroutine_threadsafe(
                self._ws_manager.broadcast_to_session(
                    session_id,
                    {"type": "listening_state", "payload": {"state": "speaking"}},
                ),
                self._main_loop,
            )

        # â”€â”€ Native C++ audio fast-path (no asyncio.Queue, no polling) â”€â”€
        _native = (
            engine.pipeline._native_available
            and engine.pipeline._native_player is not None
        )
        if _native:
            try:
                if not engine.pipeline._native_player.open(
                    engine.pipeline.output_device or -1, _TTS_SAMPLE_RATE
                ):
                    _native = False
            except Exception as _native_err:
                self._logger.warning(
                    f"[Voice] Native player open failed ({_native_err}), falling back"
                )
                _native = False

        # Track total synthesized samples for native-path cadence thread duration.
        # Defined in _speak_response scope so both _producer (thread) and native
        # path (main thread) can read/write it via mutating the list element.
        _total_synth_samples = [0]

        # Track latest audio RMS for cadence threads â€” written by _push_or_queue
        # (~10Hz during synthesis), read by cadence threads (~10Hz during playback).
        # A mutable list so both producer thread and cadence thread can access it.
        _latest_rms = [0.06]  # default non-zero so cadence starts immediately

        # Accumulate all spoken words for tts_word events during playback.
        # Populated by the producer thread, consumed after it joins.
        _all_words: list = []

        # Synchronization event: set when first audio chunk reaches the device.
        # Word-highlight threads wait on this instead of hardcoded sleep(0.15).
        _playback_event: threading.Event = threading.Event()

        def _producer():
            # Helper: push chunk to native player with auto-fallback to queue
            _last_level_time = [0.0]  # mutable for closure; throttle to ~10 Hz

            def _push_or_queue(audio_chunk: np.ndarray):
                native_ok = False
                if engine.pipeline and engine.pipeline._native_player is not None:
                    try:
                        # Apply 2.5x gain + clip ONLY for native player path.
                        # The fallback path (via play_stream) applies its own gain.
                        gained = np.clip(audio_chunk * 2.5, -0.99, 0.99)
                        engine.pipeline._native_player.push_chunk(gained)
                        native_ok = True
                        # Signal that audio playback has started (first chunk)
                        if _playback_event is not None and not _playback_event.is_set():
                            _playback_event.set()
                    except Exception:
                        pass
                if not native_ok:
                    # Push raw chunk â€” play_stream will apply gain/normalization
                    audio_queue.put(audio_chunk)

                # Track total samples for native-path cadence duration
                _total_synth_samples[0] += len(audio_chunk)

                # Broadcast audio level for orb speaking animation (throttled ~10 Hz)
                import time as _time

                now = _time.monotonic()
                if now - _last_level_time[0] >= 0.1:
                    _last_level_time[0] = now
                    if session_id and self._main_loop and self._main_loop.is_running():
                        try:
                            rms = float(np.sqrt(np.mean(np.square(audio_chunk))))
                            level = min(1.0, rms * 5.0)
                            # Share RMS with cadence threads for real breathing
                            _latest_rms[0] = level
                            import asyncio as _asyncio

                            # Legacy audio_level (old IrisOrb.tsx)
                            _asyncio.run_coroutine_threadsafe(
                                self._ws_manager.broadcast_to_session(
                                    session_id,
                                    {
                                        "type": "audio_level",
                                        "payload": {"level": level},
                                    },
                                ),
                                self._main_loop,
                            )
                            # New consolidated audio_envelope (XurOrb)
                            # TTS cadence = RMS (no spectral flux for playback)
                            _asyncio.run_coroutine_threadsafe(
                                self._ws_manager.broadcast_to_session(
                                    session_id,
                                    {
                                        "type": "audio_envelope",
                                        "payload": {
                                            "rms": level,
                                            "cadence": level,
                                            "phase": "speaking",
                                        },
                                    },
                                ),
                                self._main_loop,
                            )
                        except Exception:
                            pass

            def _mark(label: str):
                import time as _t
                now = _t.monotonic()
                if hasattr(self, "_voice_timing"):
                    self._voice_timing[label] = now
                    t0 = self._voice_timing.get("vad_end", now)
                    dt = now - t0
                    self._logger.info(f"[VOICE_TIMING] {label}: +{dt:.3f}s")
                else:
                    # voice_timing dict already deleted (the async handler's
                    # finally block printed the summary before the producer
                    # thread finished).  Log the raw monotonic time instead.
                    self._logger.info(f"[VOICE_TIMING] {label}: raw={now:.3f}s (post-summary)")

            _first_sentence_received = False
            _first_tts_start = False
            _first_audio_pushed = False

            try:
                _native = (
                    engine.pipeline is not None
                    and engine.pipeline._native_player is not None
                )
                if isinstance(input_source, str):
                    _all_words[:] = input_source.split()
                    _mark("first_tts_synth_start")
                    for audio_chunk in tts.synthesize_stream(input_source):
                        if interrupted.is_set() or engine.is_speech_interrupted():
                            break
                        _push_or_queue(audio_chunk)

                elif isinstance(input_source, queue.Queue):
                    _pending = []
                    _pending_words = 0
                    _target = FIRST_CHUNK_THRESHOLD
                    is_first_chunk = True
                    _speaking_broadcasted = False
                    # v2 (Phase 7): If ConversationKernel is active, mark
                    # speaking so on_audio_level() can detect barge-in.
                    # No-op if kernel is None (backward compatible with v1).
                    try:
                        from backend.agent.conversation_kernel import (
                            get_conversation_kernel,
                        )

                        _ck = get_conversation_kernel()
                        if _ck is not None:
                            _ck.mark_speaking(True)
                    except Exception:  # noqa: BLE001
                        pass
                    while True:
                        item = input_source.get()
                        if not _first_sentence_received and item is not None:
                            _first_sentence_received = True
                            _mark("first_sentence_in_producer")
                        # DIAG: log items coming into the producer
                        if not hasattr(self, "_diag_producer_items"):
                            self._diag_producer_items = 0
                        self._diag_producer_items += 1
                        if self._diag_producer_items <= 5 or self._diag_producer_items % 10 == 0:
                            _root_log.info(
                                f"[DIAG][producer] item#{self._diag_producer_items} "
                                f"item_type={type(item).__name__} "
                                f"item_preview={str(item)[:40]!r}"
                            )
                        # v2 (Phase 7): halt on Caducean TOPO_VIOLATION (rec=3).
                        # The kernel's should_halt_on_violation() calls
                        # audio_pipeline.interrupt() internally, so the
                        # existing interrupt path takes over. We just
                        # break out of the synthesis loop here.
                        try:
                            from backend.agent.conversation_kernel import (
                                get_conversation_kernel,
                            )

                            _ck = get_conversation_kernel()
                            if _ck is not None and _ck.should_halt_on_violation():
                                _root_log.info(
                                    "[_speak_response] TOPO_VIOLATION â€” halting TTS"
                                )
                                _ck.mark_speaking(False)
                                break
                        except Exception:  # noqa: BLE001
                            pass
                        if item is None:
                            if (
                                _pending
                                and not interrupted.is_set()
                                and not engine.is_speech_interrupted()
                            ):
                                chunk = " ".join(_pending)
                                for audio_chunk in tts.synthesize_stream(chunk):
                                    if audio_chunk is not None and len(audio_chunk) > 0:
                                        if _native:
                                            gained = np.clip(
                                                audio_chunk * 2.5, -0.99, 0.99
                                            )
                                            try:
                                                engine.pipeline._native_player.push_chunk(
                                                    gained
                                                )
                                            except Exception as _push_err:
                                                self._logger.warning(
                                                    f"[Voice] Native push failed ({_push_err})"
                                                )
                                        else:
                                            audio_queue.put(audio_chunk)
                            break

                        _pending.append(item)
                        _pending_words += len(item.split())
                        _all_words.extend(item.split())

                        if _pending_words >= _target or (
                            is_first_chunk and len(_pending) >= 1
                        ):
                            if interrupted.is_set() or engine.is_speech_interrupted():
                                break
                            chunk = " ".join(_pending)
                            if not _first_tts_start:
                                _first_tts_start = True
                                _mark("first_tts_synth_start")
                            _diag_chunks = 0
                            for audio_chunk in tts.synthesize_stream(chunk):
                                _diag_chunks += 1
                                if audio_chunk is not None and len(audio_chunk) > 0:
                                    # Track total samples for word timing denominator
                                    _total_synth_samples[0] += len(audio_chunk)
                                    if _native:
                                        gained = np.clip(audio_chunk * 2.5, -0.99, 0.99)
                                        try:
                                            engine.pipeline._native_player.push_chunk(
                                                gained
                                            )
                                            if not _first_audio_pushed:
                                                _first_audio_pushed = True
                                                _mark("first_audio_pushed")
                                                # â”€â”€ First-chunk housekeeping â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                                                if is_first_chunk:
                                                    is_first_chunk = False
                                                    _target = NORMAL_CHUNK_THRESHOLD
                                                    # Stop STTPROC immediately
                                                    if _sttproc_stop is not None:
                                                        _sttproc_stop.set()
                                                    # Broadcast "speaking" so the frontend
                                                    # shows the indicator in sync with audio
                                                    if (
                                                        not _speaking_broadcasted
                                                        and session_id
                                                        and self._main_loop
                                                        and self._main_loop.is_running()
                                                    ):
                                                        _speaking_broadcasted = True
                                                        _mark("tts_started_event_sent")
                                                        try:
                                                            import asyncio as _asyncio
                                                            _asyncio.run_coroutine_threadsafe(
                                                                self._ws_manager.broadcast_to_session(
                                                                    session_id,
                                                                    {
                                                                        "type": "listening_state",
                                                                        "payload": {"state": "speaking"},
                                                                    },
                                                                ),
                                                                self._main_loop,
                                                            )
                                                            _asyncio.run_coroutine_threadsafe(
                                                                self._ws_manager.broadcast_to_session(
                                                                    session_id,
                                                                    {"type": "tts_started"},
                                                                ),
                                                                self._main_loop,
                                                            )
                                                        except Exception:
                                                            pass
                                        except Exception as _push_err:
                                            self._logger.warning(
                                                f"[Voice] Native push failed ({_push_err})"
                                            )
                                    else:
                                        audio_queue.put(audio_chunk)
                                        if not _first_audio_pushed:
                                            _first_audio_pushed = True
                                            _mark("first_audio_pushed")
                                            # â”€â”€ First-chunk housekeeping â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                                            if is_first_chunk:
                                                is_first_chunk = False
                                                _target = NORMAL_CHUNK_THRESHOLD
                                                if _sttproc_stop is not None:
                                                    _sttproc_stop.set()
                                                if (
                                                    not _speaking_broadcasted
                                                    and session_id
                                                    and self._main_loop
                                                    and self._main_loop.is_running()
                                                ):
                                                    _speaking_broadcasted = True
                                                    _mark("tts_started_event_sent")
                                                    try:
                                                        import asyncio as _asyncio
                                                        _asyncio.run_coroutine_threadsafe(
                                                            self._ws_manager.broadcast_to_session(
                                                                session_id,
                                                                {"type": "listening_state", "payload": {"state": "speaking"}},
                                                            ),
                                                            self._main_loop,
                                                        )
                                                        _asyncio.run_coroutine_threadsafe(
                                                            self._ws_manager.broadcast_to_session(
                                                                session_id,
                                                                {"type": "tts_started"},
                                                            ),
                                                            self._main_loop,
                                                        )
                                                    except Exception:
                                                        pass
                            _pending = []
                            _pending_words = 0
                            _root_log.info(
                                f"[TTS][producer] synthesized {_diag_chunks} audio chunks "
                                f"for chunk of {len(chunk)} chars ({chunk[:50]!r})"
                            )
            except Exception as exc:
                self._logger.error(f"[Voice] TTS Producer error: {exc}")
            finally:
                # v2 (Phase 7): mark speaking=False on any exit path so
                # the kernel's on_audio_level() stops checking for barge-in.
                try:
                    from backend.agent.conversation_kernel import (
                        get_conversation_kernel,
                    )

                    _ck = get_conversation_kernel()
                    if _ck is not None:
                        _ck.mark_speaking(False)
                except Exception:  # noqa: BLE001
                    pass
                # Send final audio_envelope with zero values so XurOrb
                # stops breathing when TTS playback ends.
                if session_id and self._main_loop and self._main_loop.is_running():
                    try:
                        import asyncio as _asyncio

                        _asyncio.run_coroutine_threadsafe(
                            self._ws_manager.broadcast_to_session(
                                session_id,
                                {
                                    "type": "audio_envelope",
                                    "payload": {
                                        "rms": 0.0,
                                        "cadence": 0.0,
                                        "phase": "idle",
                                    },
                                },
                            ),
                            self._main_loop,
                        )
                    except Exception:
                        pass
                if not _native:
                    # Sentinel object â€” distinct from the timeout â†’ None case.
                    audio_queue.put(_TTS_END_STREAM)

        # 3. Suppress Porcupine while IRIS is speaking
        # Clear any stale _speech_interrupted flag from a previous
        # voice-command interruption so the next auto-relisten isn't skipped.
        engine._speech_interrupted = False
        # Note: STTPROC.wav stop moved into producer thread â€” stops on first
        # TTS audio chunk to avoid the "talking into silence" gap.
        engine.set_tts_active(True)

        try:
            producer_thread = threading.Thread(
                target=_producer, daemon=True, name="tts-producer"
            )
            producer_thread.start()

            if _native:
                # Native path: producer pushes directly; just wait for it to finish
                producer_thread.join()

                # Detect zero-audio production (model was unavailable)
                if _total_synth_samples[0] == 0:
                    self._logger.error(
                        "[TTS] _speak_response native: produced ZERO audio samples â€” "
                        "TTS model returned no output. Check TTSManager error logs."
                    )

                # â”€â”€ Cadence thread for native path â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                # The producer's _push_or_queue sends audio_envelope with actual
                # RMS during synthesis (~10Hz), but stops when the producer thread
                # finishes.  The native player buffers audio and plays
                # asynchronously â€” without a cadence thread covering the full
                # playback duration, the orb stops breathing mid-TTS.
                _native_cadence_thread = None
                _approx_dur = _total_synth_samples[0] / _TTS_SAMPLE_RATE
                if session_id and self._main_loop and _approx_dur > 0.5:
                    self._logger.info(
                        f"[TTS] Starting native cadence thread (dur={_approx_dur:.1f}s)"
                    )
                    # Expose a stop event so the barge-in handler can stop this
                    # thread immediately when user speech is detected over TTS.
                    _barge_in_stop = threading.Event()
                    self._barge_in_stop = _barge_in_stop

                    def _broadcast_native_cadence():
                        import asyncio as _asyncio2
                        import math as _math2
                        import time as _time2
                        _start = _time2.monotonic()
                        _end = _start + _approx_dur
                        _phase = 0.0
                        _count = 0
                        while _time2.monotonic() < _end and not _barge_in_stop.is_set():
                            _phase += 0.15
                            try:
                                _asyncio2.run_coroutine_threadsafe(
                                    self._ws_manager.broadcast_to_session(
                                        session_id,
                                        {
                                            "type": "audio_envelope",
                                            "payload": {
                                                "rms": 0.06,
                                                "cadence": abs(_math2.sin(_phase)),
                                                "phase": "speaking",
                                            },
                                        },
                                    ),
                                    self._main_loop,
                                )
                            except Exception as _cad_err:
                                self._logger.warning(
                                    f"[TTS] Native cadence broadcast error: {_cad_err}"
                                )
                            _count += 1
                            if _count % 10 == 0:
                                self._logger.info(
                                    f"[TTS] Native cadence #{_count} sent to {session_id}"
                                )
                            _time2.sleep(0.1)
                    _native_cadence_thread = threading.Thread(
                        target=_broadcast_native_cadence,
                        daemon=True,
                        name="tts-native-cadence",
                    )
                    _native_cadence_thread.start()

                # â”€â”€ Word-timing thread for native path â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                # Broadcast tts_word events with character-proportional timing
                # so word highlighting syncs with speech rhythm.
                # MUST start BEFORE wait_done() so words fire during playback.
                _native_word_thread = None
                if _all_words and _approx_dur > 0.3:
                    _word_count = len(_all_words)
                    _total_chars = sum(len(w) for w in _all_words) or 1
                    _word_timings = []
                    _cumulative = 0.0
                    for _w in _all_words:
                        _cumulative += (len(_w) / _total_chars) * _approx_dur
                        _word_timings.append(_cumulative)

                    def _broadcast_native_words():
                        import asyncio as _asyncio2
                        import time as _time2
                        # Wait for first chunk to reach audio device before firing
                        # word events â€” eliminates hardcoded sleep guess.
                        if _playback_event is not None:
                            _playback_event.wait(timeout=2.0)
                        _time2.sleep(0.03)  # tiny buffer for device latency
                        _start = _time2.monotonic()
                        for _i in range(_word_count):
                            _sleep = _word_timings[_i] - (_time2.monotonic() - _start)
                            if _sleep > 0:
                                _time2.sleep(_sleep)
                            try:
                                _asyncio2.run_coroutine_threadsafe(
                                    self._ws_manager.send_to_client(
                                        client_id,
                                        {
                                            "type": "tts_word",
                                            "payload": {
                                                "word_index": _i,
                                                "total_words": _word_count,
                                                "is_final": _i == _word_count - 1,
                                            },
                                        },
                                    ),
                                    self._main_loop,
                                )
                            except Exception:
                                pass

                    _native_word_thread = threading.Thread(
                        target=_broadcast_native_words,
                        daemon=True,
                        name="tts-native-words",
                    )
                    _native_word_thread.start()

                try:
                    engine.pipeline._native_player.wait_done()
                except Exception as _wait_err:
                    self._logger.warning(
                        f"[Voice] Native wait_done failed ({_wait_err})"
                    )

                if _native_cadence_thread:
                    _native_cadence_thread.join(timeout=3)
                if _native_word_thread:
                    _native_word_thread.join(timeout=3)
            else:
                # Fallback path: asyncio.Queue + streaming consumer.
                # Play each chunk as it arrives so the user hears audio
                # immediately instead of waiting for the full sentence to be
                # generated.  The old accumulator pattern (play_stream at end)
                # caused a 1-2s silent delay between "speaking" indicator and
                # actual audio.
                import sounddevice as _sd
                _sd_stream = None
                _sd_stream_started = False
                _buffered_chunks = []  # kept for word timing calculation
                _stream_start_time = None
                _rms_peak = 0.0  # running peak RMS for normalization
                _word_monitor_started = False
                _total_written_for_words = 0  # cumulative samples written to OutputStream

                while True:
                    # Fast timeout (0.5s) after streaming starts so barge-in
                    # (interrupt_speech) is detected promptly.
                    _timeout = 300 if not _sd_stream_started else 0.5
                    try:
                        chunk = audio_queue.get(timeout=_timeout)
                    except queue.Empty:
                        # Check for interruption during the wait
                        if _sd_stream_started and engine.is_speech_interrupted():
                            interrupted.set()
                            while not audio_queue.empty():
                                try:
                                    audio_queue.get_nowait()
                                except queue.Empty:
                                    break
                            break
                        chunk = None
                    if chunk is _TTS_END_STREAM:
                        break
                    if chunk is None:
                        self._logger.error(
                            f"[Voice] TTS audio queue timed out after {_timeout}s â€” skipping TTS, continuing conversation"
                        )
                        break

                    if engine.is_speech_interrupted():
                        interrupted.set()
                        while not audio_queue.empty():
                            try:
                                audio_queue.get_nowait()
                            except queue.Empty:
                                break
                        break

                    _buffered_chunks.append(chunk)

                    # â”€â”€ Stream immediately â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                    if not _sd_stream_started:
                        _sd_stream_started = True
                        _stream_start_time = time.monotonic()
                        _sd_stream = _sd.OutputStream(
                            samplerate=_TTS_SAMPLE_RATE,
                            channels=1,
                            dtype="float32",
                            latency="low",
                        )
                        _sd_stream.start()
                        if _playback_event is not None:
                            _playback_event.set()

                    if _sd_stream is not None:
                        ch_f32 = np.asarray(chunk, dtype=np.float32)
                        _sd_stream.write(ch_f32)
                        _total_written_for_words += len(ch_f32)

                        # â”€â”€ Word monitor (starts on first chunk) â”€â”€â”€â”€â”€â”€â”€â”€â”€
                        # Uses _sd_stream.time (real audio playback position)
                        # to determine the current word.  This is the
                        # Time-based word indexing: wall-clock elapsed * speaking_rate.
                        # Monitors every 50ms, broadcasts word index to frontend.
                        if not _word_monitor_started:
                            _word_monitor_started = True
                            _last_word_idx = -1

                            def _monitor_words():
                                import asyncio as _aw
                                import time as _tw
                                _wn = len(_all_words)
                                self._logger.info(f"[TTS][words] Monitor started, {_wn} words initially")
                                if _wn == 0:
                                    self._logger.warning("[TTS][words] Zero words — bailing out")
                                    return
                                while _sd_stream is not None:
                                    if _total_written_for_words <= 0:
                                        _tw.sleep(0.05)
                                        continue
                                    if _stream_start_time is None:
                                        _tw.sleep(0.05)
                                        continue
                                    # Time-based word indexing: elapsed * speaking_rate.
                                    # Old fraction approach stuck at ~0.93 because both
                                    # pos and total_dur grow at ~1x realtime.
                                    _elapsed = _tw.monotonic() - _stream_start_time
                                    _wn = len(_all_words) or 1
                                    _idx = int(_elapsed * 3.5)
                                    _idx = min(_idx, _wn - 1)
                                    nonlocal _last_word_idx
                                    if _idx > _last_word_idx:
                                        _last_word_idx = _idx
                                        self._logger.info(
                                            f"[TTS][words] Broadcasting word {_idx}/{_wn} "
                                            f"(elapsed={_elapsed:.2f}s)"
                                        )
                                        try:
                                            _aw.run_coroutine_threadsafe(
                                                self._ws_manager.send_to_client(
                                                    _client_id or session_id,
                                                    {
                                                        "type": "tts_word",
                                                        "payload": {
                                                            "word_index": _idx,
                                                            "total_words": _wn,
                                                            "is_final": False,
                                                        },
                                                    },
                                                ),
                                                self._main_loop,
                                            )
                                        except Exception:
                                            pass
                                    _tw.sleep(0.05)

                            # Final broadcast: stream closed — send is_final
                            try:
                                _aw.run_coroutine_threadsafe(
                                    self._ws_manager.send_to_client(
                                        _client_id or session_id,
                                        {"type": "tts_word", "payload": {"word_index": _last_word_idx, "total_words": _wn, "is_final": True}},
                                    ),
                                    self._main_loop,
                                )
                            except Exception:
                                pass

                            _word_monitor = threading.Thread(
                                target=_monitor_words,
                                daemon=True,
                                name="tts-words",
                            )
                            _word_monitor.start()

                        # â”€â”€ Broadcast cadence per-chunk â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                        # So the orb breathing matches audio in real-time
                        # instead of waiting for all chunks to accumulate.
                        _rms = float(np.sqrt(np.mean(np.square(ch_f32))))
                        if _rms > _rms_peak:
                            _rms_peak = _rms
                        _norm_rms = min(1.0, _rms / (_rms_peak + 1e-10) * 2.0)
                        if session_id and self._main_loop:
                            try:
                                import asyncio as _async_envelope
                                _async_envelope.run_coroutine_threadsafe(
                                    self._ws_manager.broadcast_to_session(
                                        session_id,
                                        {
                                            "type": "audio_envelope",
                                            "payload": {
                                                "rms": _norm_rms,
                                                "cadence": _norm_rms,
                                                "phase": "speaking",
                                            },
                                        },
                                    ),
                                    self._main_loop,
                                )
                            except Exception:
                                pass

                # Close the streaming output
                if _sd_stream is not None:
                    if interrupted.is_set():
                        # Barge-in or orb click: discard buffered audio
                        # immediately instead of draining it (which would
                        # keep playing the queued chunks).
                        _sd_stream.close()
                    else:
                        _sd_stream.stop()
                        _sd_stream.close()

                # â”€â”€ Monitor for late interrupts â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                # If the consumer loop exited normally (END_STREAM) moments
                # before the user clicked the orb, the interrupt flag might
                # arrive after the stream already closed.  If so, still
                # broadcast the idle envelope so the frontend resets.
                if not interrupted.is_set() and _sd_stream_started:
                    for _check in range(10):  # 10 Ã— 100ms = 1s window
                        if engine.is_speech_interrupted():
                            interrupted.set()
                            break
                        time.sleep(0.1)

                # â”€â”€ Tell frontend the orb should stop breathing â”€â”€â”€â”€â”€â”€â”€â”€
                if session_id and self._main_loop and _sd_stream_started:
                    try:
                        import asyncio as _async_idle
                        _async_idle.run_coroutine_threadsafe(
                            self._ws_manager.broadcast_to_session(
                                session_id,
                                {
                                    "type": "audio_envelope",
                                    "payload": {"rms": 0, "cadence": 0, "phase": "idle"},
                                },
                            ),
                            self._main_loop,
                        )
                    except Exception:
                        pass

                # ── Send tts_word is_final to stop word highlighting ────
                # The word monitor thread loop (while _sd_stream is not None)
                # never exits because _sd_stream is only closed, not set to
                # None.  Without this, the frontend never receives is_final
                # and word highlighting gets stuck or relies on the 200ms
                # fallback interval which may not match actual audio timing.
                if session_id and self._main_loop and _word_monitor_started:
                    try:
                        import asyncio as _async_words_final
                        _wn_final = len(_all_words) if _all_words else 0
                        _async_words_final.run_coroutine_threadsafe(
                            self._ws_manager.send_to_client(
                                _client_id or session_id,
                                {
                                    "type": "tts_word",
                                    "payload": {
                                        "word_index": max(0, _wn_final - 1),
                                        "total_words": _wn_final,
                                        "is_final": True,
                                    },
                                },
                            ),
                            self._main_loop,
                        )
                    except Exception:
                        pass

                # â€"â€" Word timing is handled by the streaming monitor â€"â€"â€"â€"
                # (started when the first chunk is written, uses
                #  _sd_stream.time for real playback position).
                # The post-loop thread has been replaced â€" see line ~3089.

                producer_thread.join(timeout=5)
        except Exception as e:
            self._logger.error(f"[Voice] TTS Consumer error: {e}")
        finally:
            if _native:
                try:
                    engine.pipeline._native_player.close()
                except Exception:
                    pass
            engine.set_tts_active(False)
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
            # ---- SPEAK RESPONSE END: BROADCAST IDLE OR AUTO-RELISTEN ----
            #
            # The orb on the frontend MUST receive a `listening_state: "idle"`
            # signal so it unsticks.  We prefer session-scoped broadcast (which
            # doesn't leak to unrelated clients), but fall back to a global
            # broadcast when session_id is not available (e.g. tts_play button
            # without an active conversation session).
            #
            _main_loop = self._main_loop
            if _main_loop and not _main_loop.is_running():
                _main_loop = None  # dead loop â€” fall through

            if session_id and _main_loop:
                import asyncio as _asyncio

                # Conversation mode: auto-relisten unless interrupted or cancelled
                in_conversation = session_id in self._conversation_sessions
                was_interrupted = interrupted.is_set()
                if in_conversation and not was_interrupted and self._voice_handler:
                    self._logger.info(
                        f"[Voice] Conversation mode: auto-resuming listen for session {session_id}"
                    )
                    _asyncio.run_coroutine_threadsafe(
                        self._ws_manager.broadcast_to_session(
                            session_id,
                            {
                                "type": "listening_state",
                                "payload": {"state": "listening"},
                            },
                        ),
                        _main_loop,
                    )
                    # Give audio pipeline a moment to flush before recording
                    import time as _time

                    _time.sleep(0.15)
                    self._voice_handler.set_active_session(session_id)
                    self._voice_handler.start_recording(
                        auto_stop=True,
                        pre_speech_timeout_sec=self._relisten_pre_speech_timeout,
                        play_beep=False,  # skip beep for seamless auto-relisten
                    )
                elif in_conversation and was_interrupted:
                    # User double-clicked to interrupt TTS â€” voice_command_start
                    # already sent "listening" and started recording.  Sending
                    # "idle" here would override that state and break barge-in.
                    self._logger.info(
                        f"[Voice] Conversation interrupted â€” state managed by voice_command_start"
                    )
                else:
                    _asyncio.run_coroutine_threadsafe(
                        self._ws_manager.broadcast_to_session(
                            session_id,
                            {"type": "listening_state", "payload": {"state": "idle"}},
                        ),
                        _main_loop,
                    )
            elif _main_loop:
                # Fallback: no session_id â†’ broadcast idle to ALL connected
                # clients so their orbs don't stay stuck in "speaking".
                import asyncio as _asyncio

                _asyncio.run_coroutine_threadsafe(
                    self._ws_manager.broadcast(
                        {"type": "listening_state", "payload": {"state": "idle"}}
                    ),
                    _main_loop,
                )
            else:
                # No main_loop available at all â€” safe no-op.  The frontend
                # unstick timer (chat-view.tsx) will clear the speaking state
                # after the word-highlight interval completes.
                self._logger.debug(
                    "[Voice] No main loop to broadcast idle â€” relying on frontend timeout"
                )

    async def _handle_tts_play(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """
        Handle tts_play message sent when the user clicks the play icon in ChatView.
        Synthesises and plays the response text directly through the desktop audio
        device, bypassing the streaming producer/consumer path used for live LLM
        responses. This keeps the play-button path simple and robust.
        """
        import asyncio
        import logging as _logging

        _root_log = _logging.getLogger()
        text = (message.get("payload") or {}).get("text", "").strip()
        if not text:
            _root_log.warning("[TTS] tts_play received with empty text")
            return

        _root_log.info(f"[TTS] tts_play requested ({len(text)} chars)")

        # Track active TTS session for barge-in handler
        if session_id:
            self._active_tts_session = session_id

        import numpy as np

        # â”€â”€ Phase 1: Synthesize audio in thread executor â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        def _synthesize() -> list:
            """Blocking TTS synthesis â€” returns list of float32 chunks."""
            from .agent import get_tts_manager

            tts = get_tts_manager()
            if not tts.is_loaded():
                tts._load_pocket_tts()

            audio_chunks: list = []
            for chunk in tts.synthesize_stream(text):
                if chunk is not None and len(chunk) > 0:
                    audio_chunks.append(chunk)
            return audio_chunks

        try:
            await self._ws_manager.send_to_client(
                client_id,
                {"type": "listening_state", "payload": {"state": "speaking"}},
            )

            loop = asyncio.get_running_loop()
            audio_chunks = await loop.run_in_executor(None, _synthesize)

            if not audio_chunks:
                raise RuntimeError("TTS produced no audio chunks")

            # â”€â”€ Calculate per-word timing (character-proportional) â”€â”€â”€â”€â”€â”€â”€
            # Instead of uniform total_duration/word_count (which gives short
            # words as much time as long words), allocate time proportional to
            # each word's character length.  A 6-char word gets ~2Ã— the time
            # of a 3-char word, matching natural speech rhythm more closely.
            from .agent.tts import OUTPUT_SAMPLE_RATE as _TTS_SAMPLE_RATE

            sample_rate = _TTS_SAMPLE_RATE
            total_samples = sum(len(c) for c in audio_chunks)
            total_duration_s = total_samples / sample_rate
            words = text.split()
            word_count = len(words)
            total_chars = sum(len(w) for w in words) or 1
            word_offsets = []
            cumulative = 0.0
            for w in words:
                cumulative += (len(w) / total_chars) * total_duration_s
                word_offsets.append(cumulative)
            _root_log.info(
                f"[TTS] {word_count} words over {total_duration_s:.1f}s "
                f"(char-proportional timing) "
                f"audio {len(audio_chunks)} chunks ({total_samples} samples)"
            )

            # â”€â”€ Phase 2: Start playback in thread executor (non-blocking) â”€
            def _play() -> None:
                from .audio.engine import get_audio_engine

                engine = get_audio_engine()
                if not engine or not engine.pipeline:
                    raise RuntimeError("Audio pipeline not available")
                engine.pipeline.play_stream(audio_chunks, sample_rate=sample_rate)

            playback_future = loop.run_in_executor(None, _play)

            # â”€â”€ Phase 2b: Broadcast audio_envelope for orb animation â”€â”€â”€â”€â”€â”€
            # The orb needs periodic audio_envelope messages during playback
            # so the breathing animation reacts to the speech rhythm.
            import math as _math
            _cadence_thread = None
            if session_id and total_duration_s > 0.3:
                _root_log.info(
                    f"[TTS] tts_play: starting cadence thread (dur={total_duration_s:.1f}s)"
                )
                _barge_in_stop = threading.Event()
                self._barge_in_stop = _barge_in_stop

                def _broadcast_cadence():
                    import asyncio as _asyncio
                    import time as _time
                    start = _time.monotonic()
                    end = start + total_duration_s + 0.3  # overshoot slightly
                    _phase = 0.0
                    while _time.monotonic() < end and not _barge_in_stop.is_set():
                        _phase += 0.15
                        try:
                            _asyncio.run_coroutine_threadsafe(
                                self._ws_manager.broadcast_to_session(
                                    session_id,
                                    {
                                        "type": "audio_envelope",
                                        "payload": {
                                            "rms": 0.06,
                                            "cadence": abs(_math.sin(_phase)),
                                            "phase": "speaking",
                                        },
                                    },
                                ),
                                self._main_loop,
                            )
                        except Exception:
                            pass
                        _time.sleep(0.1)
                _cadence_thread = threading.Thread(
                    target=_broadcast_cadence,
                    daemon=True,
                    name="tts-play-cadence",
                )
                _cadence_thread.start()

            # â”€â”€ Phase 3: Send word events while playback runs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Uses character-proportional timing (word_offsets) so short words
            # flash quickly while long words keep highlighting longer, matching
            # natural speech rhythm better than uniform total_duration/word_count.
            # Account for audio playback startup latency: the audio device
            # needs ~100ms to open and buffer the first chunk.  Without this
            # offset, word events fire before the speaker produces sound.
            _PLAYBACK_STARTUP_DELAY_S = 0.10
            await asyncio.sleep(_PLAYBACK_STARTUP_DELAY_S)

            _start_time = time.monotonic()
            for i in range(word_count):
                _scheduled = word_offsets[i]
                _elapsed = time.monotonic() - _start_time
                _wait = _scheduled - _elapsed
                if _wait > 0:
                    await asyncio.sleep(_wait)
                try:
                    await self._ws_manager.send_to_client(
                        client_id,
                        {
                            "type": "tts_word",
                            "payload": {
                                "word_index": i,
                                "total_words": word_count,
                                "is_final": False,
                            },
                        },
                    )
                except Exception as we:
                    _root_log.debug(f"[TTS] word event {i} failed: {we}")
            # Final word event
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "tts_word",
                    "payload": {
                        "word_index": word_count - 1,
                        "total_words": word_count,
                        "is_final": True,
                    },
                },
            )
            # Wait for actual playback to finish
            await playback_future

            # Wait for cadence thread to finish
            if _cadence_thread:
                _cadence_thread.join(timeout=2)

            # Send final audio_envelope with zero values so orb stops breathing
            if session_id and self._main_loop and self._main_loop.is_running():
                try:
                    import asyncio as _asyncio
                    _asyncio.run_coroutine_threadsafe(
                        self._ws_manager.broadcast_to_session(
                            session_id,
                            {
                                "type": "audio_envelope",
                                "payload": {
                                    "rms": 0.0,
                                    "cadence": 0.0,
                                    "phase": "idle",
                                },
                            },
                        ),
                        self._main_loop,
                    )
                except Exception:
                    pass

        except Exception as e:
            _root_log.error(f"[TTS] tts_play failed: {e}", exc_info=True)
        finally:
            # After TTS playback, preserve the conversation state instead of
            # forcing "idle". If the user is in an active voice conversation,
            # the orb stays listening so they can respond back.
            post_tts_state = "listening" if session_id in self._conversation_sessions else "idle"
            _root_log.info(f"[TTS] after play => {post_tts_state} (session_id={session_id})")
            try:
                await self._ws_manager.send_to_client(
                    client_id,
                    {"type": "listening_state", "payload": {"state": post_tts_state}},
                )
            except Exception as e:
                _root_log.warning(f"[TTS] send {post_tts_state} state failed: {e}")

            # â”€â”€ Bug 2 fix: restart VAD recording when returning to conversation â”€â”€
            # Sending "listening" state alone is not enough â€” the orb shows the
            # listening animation but no audio is captured.  We must also restart
            # the voice handler so VAD can detect the next utterance.
            if post_tts_state == "listening" and self._voice_handler:
                _root_log.info(
                    f"[TTS] Conversation mode: restarting recording for session {session_id}"
                )
                try:
                    self._voice_handler.set_active_session(session_id)
                    self._voice_handler.start_recording(
                        auto_stop=True,
                        pre_speech_timeout_sec=self._relisten_pre_speech_timeout,
                        play_beep=False,  # skip beep for seamless post-TTS relisten
                    )
                except Exception as _re_err:
                    _root_log.warning(
                        f"[TTS] start_recording after play failed: {_re_err}"
                    )

    async def _chat_heartbeat(self, client_id: str, interval: float = 5.0):
        """Send periodic chat_heartbeat messages to keep the TCP layer alive
        during long inference.  The frontend ignores this type."""
        while True:
            await asyncio.sleep(interval)
            try:
                await self._ws_manager.send_to_client(
                    client_id, {"type": "chat_heartbeat", "payload": {}}
                )
            except Exception:
                break

    async def _handle_chat(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """
        Handle chat messages: text_message, clear_chat, new_conversation.

        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary
        """
        msg_type = message.get("type")
        payload = message.get("payload", {})

        if msg_type == "new_conversation":
            # Reset the agent kernel's conversation context so the next
            # voice command or text message starts fresh.  The frontend sends
            # this when the user creates a "New Conversation" in the chat UI.
            try:
                agent_kernel = get_agent_kernel(session_id)
                agent_kernel.clear_conversation()
                self._logger.info(
                    f"[Chat] Cleared conversation context for session {session_id}"
                )
            except Exception as exc:
                self._logger.warning(
                    f"[Chat] Failed to clear conversation for {session_id}: {exc}"
                )
            return

        if msg_type == "text_message":
            text = payload.get("text")
            turn_id = get_turn_id()

            if not text:
                await self._send_validation_error(
                    client_id, "text", "Message text is required"
                )
                return

            # Get AgentKernel for this session
            try:
                import time as _time

                _t_gate = _time.perf_counter()

                agent_kernel = get_agent_kernel(session_id)
                _t_kernel = _time.perf_counter()
                self._logger.debug(
                    f"[Timing] get_agent_kernel: {(_t_kernel - _t_gate) * 1000:.1f} ms",
                    extra={"session_id": session_id},
                )

                # Wire tool bridge if not already set (enables real tool execution)
                from backend.agent.tool_bridge import get_agent_tool_bridge

                if agent_kernel._tool_bridge is None:
                    agent_kernel._tool_bridge = get_agent_tool_bridge()

                _t_bridge = _time.perf_counter()
                self._logger.debug(
                    f"[Timing] tool_bridge wire: {(_t_bridge - _t_kernel) * 1000:.1f} ms",
                    extra={"session_id": session_id},
                )

                # Signal ChatView: AI is processing (typing indicator only â€” does NOT affect orb)
                await self._ws_manager.send_to_client(
                    client_id, {"type": "chat_typing", "payload": {"active": True}}
                )

                # Process message in executor to avoid blocking event loop
                loop = asyncio.get_running_loop()
                # Refresh captured loop so callbacks always target the current one
                self._main_loop = loop
                _t_exec_start = _time.perf_counter()

                def _execute_agent():
                    def _chunk_cb(chunk: str):
                        _loop = self._main_loop
                        if _loop and _loop.is_running():
                            try:
                                _future = asyncio.run_coroutine_threadsafe(
                                    self._ws_manager.send_to_client(
                                        client_id,
                                        {
                                            "type": "chat_chunk",
                                            "payload": {"chunk": chunk},
                                        },
                                    ),
                                    _loop,
                                )
                                # Fire-and-forget: don't block the stream thread.
                                # Delivery failures are handled by the reconnect buffer.
                                _future.add_done_callback(
                                    lambda f: (
                                        None
                                        if f.exception() is None
                                        else self._ws_manager.buffer_message(
                                            session_id,
                                            {
                                                "type": "chat_chunk",
                                                "payload": {"chunk": chunk},
                                            },
                                        )
                                    )
                                )
                            except Exception:
                                self._ws_manager.buffer_message(
                                    session_id,
                                    {"type": "chat_chunk", "payload": {"chunk": chunk}},
                                )

                    def _reasoning_cb(chunk: str):
                        _loop = self._main_loop
                        if _loop and _loop.is_running():
                            try:
                                _future = asyncio.run_coroutine_threadsafe(
                                    self._ws_manager.send_to_client(
                                        client_id,
                                        {
                                            "type": "chat_reasoning",
                                            "payload": {"chunk": chunk},
                                        },
                                    ),
                                    _loop,
                                )
                                _future.add_done_callback(
                                    lambda f: (
                                        None
                                        if f.exception() is None
                                        else self._ws_manager.buffer_message(
                                            session_id,
                                            {
                                                "type": "chat_reasoning",
                                                "payload": {"chunk": chunk},
                                            },
                                        )
                                    )
                                )
                            except Exception:
                                self._ws_manager.buffer_message(
                                    session_id,
                                    {
                                        "type": "chat_reasoning",
                                        "payload": {"chunk": chunk},
                                    },
                                )

                    try:
                        response = agent_kernel.process_text_message(
                            text,
                            session_id=session_id,
                            chunk_callback=_chunk_cb,
                            reasoning_callback=_reasoning_cb,
                            turn_id=turn_id,
                        )
                    except Exception as e:
                        self._logger.error(f"[Chat] Agent processing error: {e}")
                        # Signal error to UI stream so user sees something before
                        # the outer handler sends the final error message.
                        _chunk_cb(f"\n[IRIS error: {type(e).__name__}: {str(e)[:200]}]")
                        raise

                    return response

                heartbeat_task = asyncio.create_task(self._chat_heartbeat(client_id))
                try:
                    response = await loop.run_in_executor(None, _execute_agent)
                finally:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass

                _t_exec_end = _time.perf_counter()
                _elapsed_ms = round((_t_exec_end - _t_exec_start) * 1000)
                self._logger.info(
                    f"[Timing] process_text_message (streamed): {_elapsed_ms:.0f} ms",
                    extra={"session_id": session_id},
                )

                # Emit inference_event for InferenceConsolePanel â€” fires for all backends
                try:
                    _prompt_tok = max(1, len(text) // 4)
                    _comp_tok = max(1, len(response or "") // 4)
                    _elapsed_s = _elapsed_ms / 1000 or 0.001
                    _model_name = (
                        getattr(agent_kernel, "_selected_reasoning_model", None)
                        or "local-model"
                    )
                    await self._ws_manager.broadcast_to_session(
                        session_id,
                        {
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
                        },
                    )
                except Exception as _inf_exc:
                    loud_error(_inf_exc, "broadcast inference_event")

                # Send final complete message (updates the UI with the full text + metadata)
                thinking = getattr(agent_kernel, "_pending_thinking", "") or ""
                _final_msg = {
                    "type": "chat_message",
                    "payload": {
                        "role": "assistant",
                        "content": response,
                        "thinking": thinking,
                        "timestamp": datetime.now().isoformat(),
                        "turn_id": turn_id,
                    },
                }
                _delivered = await self._ws_manager.send_to_client(
                    client_id, _final_msg
                )
                if not _delivered:
                    # Client disconnected mid-inference â€” buffer for replay on reconnect
                    self._ws_manager.buffer_message(session_id, _final_msg)

                # Clear ChatView typing indicator
                await self._ws_manager.send_to_client(
                    client_id, {"type": "chat_typing", "payload": {"active": False}}
                )

            except Exception as e:
                self._logger.error(f"Error processing text message: {e}", exc_info=True)
                # Clear typing indicator on error
                await self._ws_manager.send_to_client(
                    client_id, {"type": "chat_typing", "payload": {"active": False}}
                )
                # Translate the raw exception into a friendly user-facing message.
                # Common cases: 401 wrong key, 404 model not found, 429 rate limit.
                err_str = str(e)
                user_msg = err_str
                for prefix in ("Agent kernel error: ", "Agent kernel error:"):
                    if user_msg.startswith(prefix):
                        user_msg = user_msg[len(prefix) :]
                        break
                # Try to extract a clean message field from any embedded JSON blob.
                import json as _json

                try:
                    blob_start = user_msg.find("{")
                    if blob_start != -1:
                        parsed = _json.loads(user_msg[blob_start:])
                        if isinstance(parsed, dict) and "message" in parsed:
                            user_msg = parsed["message"]
                except Exception:
                    pass
                # Bucket the error so the frontend can style it.
                if "API returned 401" in err_str or "API returned 403" in err_str:
                    friendly = (
                        f"API key rejected by upstream. "
                        f"Check your key in SYSTEM HUD. ({user_msg})"
                    )
                elif "API returned 404" in err_str:
                    friendly = (
                        f"Model not found at upstream. "
                        f"Check the model name in SYSTEM HUD. ({user_msg})"
                    )
                elif "API returned 429" in err_str:
                    friendly = (
                        f"Upstream rate limit hit. Please wait and try again. "
                        f"({user_msg})"
                    )
                else:
                    friendly = f"Agent kernel error: {user_msg}"
                # Send error as chat_message so it appears in the chat UI
                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "chat_message",
                        "payload": {
                            "role": "error",
                            "content": friendly,
                            "timestamp": datetime.now().isoformat(),
                            "turn_id": turn_id,
                        },
                    },
                )
                await self._send_error(client_id, friendly)

            # Flush any buffered chunks/messages that failed to send mid-inference.
            # This ensures reconnecting clients get the full response replay.
            try:
                await self._ws_manager.flush_pending(session_id, client_id)
            except Exception as _flush_err:
                self._logger.debug(
                    f"[Session: {session_id}] flush_pending failed: {_flush_err}"
                )

        elif msg_type == "clear_chat":
            # Get AgentKernel for this session and clear conversation
            try:
                agent_kernel = get_agent_kernel(session_id)
                agent_kernel.clear_conversation()

                self._logger.info(f"Conversation cleared for session {session_id}")

                await self._ws_manager.send_to_client(
                    client_id, {"type": "chat_cleared", "payload": {}}
                )

            except Exception as e:
                self._logger.error(f"Error clearing chat: {e}", exc_info=True)
                await self._send_error(client_id, f"Error clearing chat: {str(e)}")

    async def _handle_status(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
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

                await self._ws_manager.send_to_client(
                    client_id, {"type": "agent_status", "payload": status}
                )

            except Exception as e:
                self._logger.error(f"Error getting agent status: {e}", exc_info=True)
                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "agent_status",
                        "payload": {
                            "ready": False,
                            "models_loaded": 0,
                            "total_models": 0,
                            "tool_bridge_available": False,
                            "error": f"Failed to get agent status: {str(e)}",
                        },
                    },
                )

        # GAP-02: Support both get_agent_tools (new) and agent_tools (legacy)
        elif msg_type in ["get_agent_tools", "agent_tools"]:
            try:
                from backend.agent.tool_bridge import get_agent_tool_bridge

                bridge = get_agent_tool_bridge()
                tools = bridge.get_available_tools()

                await self._ws_manager.send_to_client(
                    client_id, {"type": "agent_tools", "payload": {"tools": tools}}
                )
            except Exception as e:
                self._logger.error(f"Error getting agent tools: {e}")
                await self._ws_manager.send_to_client(
                    client_id,
                    {"type": "agent_tools", "payload": {"tools": [], "error": str(e)}},
                )

    async def _handle_get_available_models(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """
        Handle get_available_models message - dynamically query models from the active inference source.

        Inference modes:
        - "Local Models"  â†’ query Ollama at configured endpoint (default http://localhost:11434)
        - "VPS Gateway"   â†’ probe vps_url/v1/models or return VPS fallback list
        - "OpenAI API"    â†’ query openai.com/v1/models with api_key or return GPT fallback list

        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary
        """
        try:
            # Get session-specific field values
            session_state = await self._state_manager._get_session_state_manager(
                session_id
            )

            # Defaults â€” overridden by whatever the user saved in their settings card.
            inference_mode = "lmstudio"
            vps_url = ""
            openai_api_key = ""
            api_base_url = "https://api.openai.com/v1"
            ollama_endpoint = _DEFAULT_OLLAMA_URL
            lmstudio_endpoint = _DEFAULT_LMSTUDIO_URL

            if session_state:
                # model_provider field lives in the 'model_selection' section.
                # The UI shows display values; normalise them to internal keys:
                #   "LM Studio" / "lmstudio" â†’ "lmstudio"
                #   "Local Models" / "local"  â†’ "local"   (Ollama)
                #   "VPS Gateway"  / "vps"    â†’ "vps"
                #   "OpenAI API"   / "api"    â†’ "api"
                payload = message.get("payload", {})
                _raw_mode = (
                    payload.get("model_provider")
                    or session_state.get_field_value(
                        "model_selection", "model_provider", ""
                    )
                    or "lmstudio"
                )
                _mode_map = {
                    "lm studio": "lmstudio",
                    "lmstudio": "lmstudio",
                    "local models": "local",
                    "local": "local",
                    "vps gateway": "vps",
                    "vps": "vps",
                    "openai api": "api",
                    "api": "api",
                }
                inference_mode = _mode_map.get(
                    str(_raw_mode).lower().strip(), "lmstudio"
                )
                vps_url = (
                    session_state.get_field_value("model_selection", "vps_url", "")
                    or ""
                )
                openai_api_key = (
                    payload.get("api_key")  # override from frontend
                    or session_state.get_field_value("model_selection", "api_key", "")
                    or ""
                )
                api_base_url = (
                    payload.get("api_base_url")  # override from frontend
                    or session_state.get_field_value(
                        "model_selection", "api_base_url", "https://api.openai.com/v1"
                    )
                    or "https://api.openai.com/v1"
                )
                lmstudio_endpoint = (
                    session_state.get_field_value(
                        "model_selection", "lmstudio_endpoint", _DEFAULT_LMSTUDIO_URL
                    )
                    or _DEFAULT_LMSTUDIO_URL
                )
                ollama_endpoint = (
                    session_state.get_field_value(
                        "model_selection", "ollama_endpoint", _DEFAULT_OLLAMA_URL
                    )
                    or _DEFAULT_OLLAMA_URL
                )

            self._logger.info(
                f"[Session: {session_id}] Getting available models for provider: {inference_mode}"
            )

            # If swarm is active (provider='iris_local'), skip LM Studio probe
            # entirely â€” it just generates false warnings in the logs.
            try:
                from backend.agent.agent_kernel import get_agent_kernel as _gk

                _kernel = _gk(session_id)
                if (
                    getattr(_kernel, "_swarm_enabled", False)
                    and inference_mode == "lmstudio"
                ):
                    self._logger.info(
                        f"[Session: {session_id}] Swarm is active â€” skipping LM Studio probe"
                    )
                    await self._ws_manager.send_to_client(
                        client_id,
                        {
                            "type": "available_models",
                            "payload": {
                                "models": [
                                    {
                                        "id": _kernel._selected_reasoning_model
                                        or "local-model",
                                        "name": _kernel._selected_reasoning_model
                                        or "Swarm Director Model",
                                        "source": "iris_local",
                                    }
                                ]
                            },
                        },
                    )
                    return
            except Exception:
                pass  # non-fatal â€” continue to normal flow

            available_models = []

            # Vision-only models should NOT appear in reasoning/tool dropdowns.
            # They belong exclusively in the vision_model dropdown.
            _VISION_ONLY_PREFIXES = (
                "lfm2.5-vl",
                "llava",
                "bakllava",
                "llava-llama3",
                "llava-phi3",
                "moondream",
                "cogvlm",
                "internvl",
            )

            def _is_vision_only(model_id: str) -> bool:
                """Check if a model is vision-only based on its name/id.

                Handles namespaced IDs like 'openbmb/minicpm-o4.5:latest' by
                checking both the full name and the part after the last '/'.
                """
                name_lower = model_id.lower().split(":")[0]  # strip tag like ":latest"
                # Also check the base name after namespace (e.g. "openbmb/minicpm-o4.5" â†’ "minicpm-o4.5")
                base_name = (
                    name_lower.rsplit("/", 1)[-1] if "/" in name_lower else name_lower
                )
                return any(
                    name_lower.startswith(p) for p in _VISION_ONLY_PREFIXES
                ) or any(base_name.startswith(p) for p in _VISION_ONLY_PREFIXES)

            if inference_mode == "local":
                # Query Ollama for locally installed models
                try:
                    async with httpx.AsyncClient(timeout=3.0) as http_client:
                        r = await http_client.get(
                            f"{ollama_endpoint.rstrip('/')}/api/tags"
                        )
                        if r.status_code == 200:
                            tags = r.json().get("models", [])
                            # Exclude vision-only models from reasoning/tool list
                            available_models = [
                                {"id": m["name"], "name": m["name"], "source": "local"}
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
                                capture_output=True,
                                text=True,
                                timeout=3,
                                cwd=str(project_dir),
                            )
                            common = subprocess.run(
                                ["git", "rev-parse", "--git-common-dir"],
                                capture_output=True,
                                text=True,
                                timeout=3,
                                cwd=str(project_dir),
                            )
                            if result.returncode == 0 and common.returncode == 0:
                                wt_root = Path(result.stdout.strip()).resolve()
                                main_root = Path(common.stdout.strip()).resolve().parent
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
                            if model_name.lower() in (
                                "cache",
                                "wake_words",
                                "audio_detokenizer",
                            ):
                                continue
                            available_models.append(
                                {
                                    "id": str(child),
                                    "name": model_name,
                                    "source": "local_hf",
                                }
                            )
                    hf_count = sum(
                        1 for m in available_models if m.get("source") == "local_hf"
                    )
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
                        {"id": "llama3.2", "name": "Llama 3.2 (3B)", "source": "local"},
                        {
                            "id": "llama3.2:1b",
                            "name": "Llama 3.2 (1B)",
                            "source": "local",
                        },
                        {"id": "llama3.1", "name": "Llama 3.1 (8B)", "source": "local"},
                        {"id": "mistral", "name": "Mistral 7B", "source": "local"},
                        {
                            "id": "qwen2.5:3b",
                            "name": "Qwen 2.5 (3B)",
                            "source": "local",
                        },
                        {"id": "phi4", "name": "Phi-4 (14B)", "source": "local"},
                        {
                            "id": "deepseek-r1:7b",
                            "name": "DeepSeek R1 (7B)",
                            "source": "local",
                        },
                        {"id": "codellama", "name": "Code Llama", "source": "local"},
                    ]
                    self._logger.info(
                        f"[Session: {session_id}] No models found â€” returning fallback list"
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
                        {
                            "id": "local-model",
                            "name": "Currently Loaded Model",
                            "source": "lmstudio",
                        },
                        {
                            "id": "llama-3.2-3b-instruct",
                            "name": "Llama 3.2 3B Instruct",
                            "source": "lmstudio",
                        },
                        {
                            "id": "llama-3.1-8b-instruct",
                            "name": "Llama 3.1 8B Instruct",
                            "source": "lmstudio",
                        },
                        {
                            "id": "mistral-7b-instruct-v0.3",
                            "name": "Mistral 7B Instruct",
                            "source": "lmstudio",
                        },
                        {
                            "id": "qwen2.5-7b-instruct",
                            "name": "Qwen 2.5 7B Instruct",
                            "source": "lmstudio",
                        },
                        {
                            "id": "deepseek-r1-distill-qwen-7b",
                            "name": "DeepSeek R1 7B",
                            "source": "lmstudio",
                        },
                    ]
                    self._logger.info(
                        f"[Session: {session_id}] LM Studio unreachable â€” showing fallback model list"
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
                                {
                                    "id": m["id"],
                                    "name": m.get("id", m["id"]),
                                    "source": "api",
                                }
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

                # Fallback list â€” provider-aware based on api_base_url
                if not available_models:
                    _base_lower = api_base_url.lower()
                    if "cohere" in _base_lower:
                        available_models = [
                            {
                                "id": "command-a-plus-05-2026",
                                "name": "Command A+ (latest)",
                                "source": "cohere",
                            },
                            {
                                "id": "command-a-03-2025",
                                "name": "Command A",
                                "source": "cohere",
                            },
                            {
                                "id": "command-r-plus-08-2024",
                                "name": "Command R+",
                                "source": "cohere",
                            },
                            {
                                "id": "command-r-08-2024",
                                "name": "Command R",
                                "source": "cohere",
                            },
                            {
                                "id": "command-r7b-12-2024",
                                "name": "Command R7B",
                                "source": "cohere",
                            },
                        ]
                    elif "groq" in _base_lower:
                        available_models = [
                            {
                                "id": "llama-3.3-70b-versatile",
                                "name": "Llama 3.3 70B",
                                "source": "groq",
                            },
                            {
                                "id": "llama-3.1-8b-instant",
                                "name": "Llama 3.1 8B",
                                "source": "groq",
                            },
                            {
                                "id": "mixtral-8x7b-32768",
                                "name": "Mixtral 8x7B",
                                "source": "groq",
                            },
                        ]
                    elif "mistral" in _base_lower:
                        available_models = [
                            {
                                "id": "mistral-large-latest",
                                "name": "Mistral Large",
                                "source": "mistral",
                            },
                            {
                                "id": "mistral-medium-latest",
                                "name": "Mistral Medium",
                                "source": "mistral",
                            },
                            {
                                "id": "open-mixtral-8x7b",
                                "name": "Mixtral 8x7B",
                                "source": "mistral",
                            },
                        ]
                    elif "together" in _base_lower:
                        available_models = [
                            {
                                "id": "meta-llama/Llama-3-70b-chat-hf",
                                "name": "Llama 3 70B",
                                "source": "together",
                            },
                            {
                                "id": "meta-llama/Llama-3-8b-chat-hf",
                                "name": "Llama 3 8B",
                                "source": "together",
                            },
                        ]
                    elif "openrouter" in _base_lower:
                        available_models = [
                            {
                                "id": "openai/gpt-4o",
                                "name": "GPT-4o (via OpenRouter)",
                                "source": "openrouter",
                            },
                            {
                                "id": "anthropic/claude-3.5-sonnet",
                                "name": "Claude 3.5 Sonnet",
                                 "source": "openrouter",
                             },
                         ]
                    elif "cerebras" in _base_lower:
                        available_models = [
                            {
                                "id": "gemma-4-31b",
                                "name": "Gemma 4 31B",
                                "source": "cerebras",
                            },
                        ]
                    elif "chutes" in _base_lower:
                        available_models = [
                            {
                                "id": "deepseek-ai/DeepSeek-V3.2-TEE",
                                "name": "DeepSeek V3.2",
                                "source": "chutes",
                            },
                            {
                                "id": "Qwen/Qwen3-32B-TEE",
                                "name": "Qwen3 32B",
                                "source": "chutes",
                            },
                            {
                                "id": "google/gemma-4-31B-turbo-TEE",
                                "name": "Gemma 4 31B",
                                "source": "chutes",
                            },
                            {
                                "id": "zai-org/GLM-5.1-TEE",
                                "name": "GLM 5.1",
                                "source": "chutes",
                            },
                            {
                                "id": "moonshotai/Kimi-K2.6-TEE",
                                "name": "Kimi K2.6",
                                "source": "chutes",
                            },
                        ]
                    elif "opencode" in _base_lower:
                        available_models = [
                            {
                                "id": "deepseek-v4-pro",
                                "name": "DeepSeek V4 Pro",
                                "source": "opencode",
                            },
                            {
                                "id": "deepseek-v4-flash",
                                "name": "DeepSeek V4 Flash",
                                "source": "opencode",
                            },
                            {
                                "id": "kimi-k2.6",
                                "name": "Kimi K2.6",
                                "source": "opencode",
                            },
                            {
                                "id": "minimax-m2.7",
                                "name": "MiniMax M2.7",
                                "source": "opencode",
                            },
                            {
                                "id": "glm-5.1",
                                "name": "GLM 5.1",
                                "source": "opencode",
                            },
                        ]
                    elif "commandcode" in _base_lower or "command-code" in _base_lower:
                        available_models = [
                            {
                                "id": "gpt-5.5",
                                "name": "GPT-5.5",
                                "source": "commandcode",
                            },
                            {
                                "id": "gpt-5.4",
                                "name": "GPT-5.4",
                                "source": "commandcode",
                            },
                            {
                                "id": "gpt-5.4-mini",
                                "name": "GPT-5.4 Mini",
                                "source": "commandcode",
                            },
                            {
                                "id": "gpt-5.3-codex",
                                "name": "GPT-5.3 Codex",
                                "source": "commandcode",
                            },
                            {
                                "id": "claude-sonnet-4-6",
                                "name": "Claude Sonnet 4.6",
                                "source": "commandcode",
                            },
                            {
                                "id": "claude-opus-4-7",
                                "name": "Claude Opus 4.7",
                                "source": "commandcode",
                            },
                            {
                                "id": "claude-haiku-4-5-20251001",
                                "name": "Claude Haiku 4.5",
                                "source": "commandcode",
                            },
                            {
                                "id": "moonshotai/Kimi-K2.6",
                                "name": "Kimi K2.6",
                                "source": "commandcode",
                            },
                            {
                                "id": "moonshotai/Kimi-K2.5",
                                "name": "Kimi K2.5",
                                "source": "commandcode",
                            },
                            {
                                "id": "zai-org/GLM-5.1",
                                "name": "GLM 5.1",
                                "source": "commandcode",
                            },
                        ]
                    else:
                        # Default: OpenAI models
                        available_models = [
                            {"id": "gpt-4o", "name": "GPT-4o", "source": "openai"},
                            {
                                "id": "gpt-4-turbo",
                                "name": "GPT-4 Turbo",
                                "source": "openai",
                            },
                            {"id": "gpt-4", "name": "GPT-4", "source": "openai"},
                            {
                                "id": "gpt-3.5-turbo",
                                "name": "GPT-3.5 Turbo",
                                "source": "openai",
                            },
                        ]

            elif inference_mode == "vps":
                # Try to query the VPS endpoint for models
                if vps_url:
                    try:
                        async with httpx.AsyncClient(timeout=3.0) as http_client:
                            r = await http_client.get(
                                f"{vps_url.rstrip('/')}/v1/models"
                            )
                            if r.status_code == 200:
                                models_data = r.json().get("data", [])
                                available_models = [
                                    {"id": m["id"], "name": m["id"], "source": "vps"}
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
                        {
                            "id": "lfm2.5-1.2b-instruct",
                            "name": "LFM2.5 1.2B Instruct",
                            "source": "vps",
                        },
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

                        model_name = (
                            _Path(status["model_path"]).stem
                            if status.get("model_path")
                            else "gguf-model"
                        )
                        available_models = [
                            {
                                "id": model_name,
                                "name": model_name,
                                "source": "iris_local",
                            }
                        ]
                    else:
                        available_models = []
                    self._logger.info(
                        f"[Session: {session_id}] iris_local models: {len(available_models)} loaded"
                    )
                except Exception as il_err:
                    self._logger.warning(
                        f"[Session: {session_id}] iris_local query failed: {il_err}"
                    )

            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "available_models",
                    "payload": {
                        "models": available_models,
                        "model_provider": inference_mode,  # 'lmstudio' | 'local' | 'api' | 'vps'
                        "inference_mode": inference_mode,  # kept for backward compat
                    },
                },
            )

        except Exception as e:
            self._logger.error(f"Error getting available models: {e}", exc_info=True)
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "available_models",
                    "payload": {
                        "models": [],
                        "error": f"Failed to get available models: {str(e)}",
                    },
                },
            )

    async def _handle_monitor_card(
        self, session_id: str, client_id: str, section_id: str, values: dict
    ) -> None:
        """Handle monitor cards (analytics / logs / diagnostics).

        When the user confirms a monitor card we gather live data and push it
        back into the card fields via update_field messages so the UI shows
        actual system status instead of empty placeholders.
        """
        try:
            from .agent.agent_kernel import get_agent_kernel, _agent_kernel_instances

            kernel = get_agent_kernel(session_id)

            if section_id == "diagnostics":
                # â”€â”€ Run diagnostics via DiagnosticsManager â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                import json
                import subprocess as _sp

                from backend.monitor.diagnostics import get_diagnostics_manager, HealthCheck

                diag_mgr = get_diagnostics_manager()
                health_checks_raw = await diag_mgr.run_health_checks()

                # Convert HealthCheck dataclasses to dicts
                health_checks = [
                    {
                        "component": c.component,
                        "status": c.status,
                        "message": c.message,
                        "latency_ms": c.latency_ms,
                    }
                    for c in health_checks_raw
                ]

                # Add kernel-specific checks (live process state)
                # llama-server check
                try:
                    ll_result = _sp.run(
                        ["tasklist", "/FI", "IMAGENAME eq llama-server.exe"],
                        capture_output=True, text=True, timeout=5,
                    )
                    if "llama-server.exe" in ll_result.stdout:
                        health_checks.append({
                            "component": "llama_server",
                            "status": "healthy",
                            "message": "Running",
                            "latency_ms": 0,
                        })
                    else:
                        health_checks.append({
                            "component": "llama_server",
                            "status": "idle",
                            "message": "Not running (use swarm to start)",
                            "latency_ms": 0,
                        })
                except Exception:
                    health_checks.append({
                        "component": "llama_server",
                        "status": "warning",
                        "message": "Could not query process list",
                        "latency_ms": 0,
                    })

                # GPU check
                try:
                    gpu_result = _sp.run(
                        ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                         "--format=csv,noheader"],
                        capture_output=True, text=True, timeout=5,
                    )
                    if gpu_result.returncode == 0 and gpu_result.stdout.strip():
                        first_gpu = gpu_result.stdout.strip().split("\n")[0]
                        health_checks.append({
                            "component": "gpu",
                            "status": "healthy",
                            "message": first_gpu,
                            "latency_ms": 0,
                        })
                    else:
                        health_checks.append({
                            "component": "gpu",
                            "status": "idle",
                            "message": "No GPU detected or nvidia-smi unavailable",
                            "latency_ms": 0,
                        })
                except Exception:
                    health_checks.append({
                        "component": "gpu",
                        "status": "idle",
                        "message": "nvidia-smi not available",
                        "latency_ms": 0,
                    })

                # Send structured health checks
                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "update_field",
                        "section_id": "diagnostics",
                        "field_id": "system_health",
                        "value": json.dumps(health_checks),
                    },
                )

                # Build troubleshoot from checks + kernel state
                issues = []
                warnings = []
                for c in health_checks:
                    if c.get("status") == "error":
                        issues.append(f"ERROR [{c.get('component')}]: {c.get('message', '')}")
                    elif c.get("status") == "warning":
                        warnings.append(f"WARN [{c.get('component')}]: {c.get('message', '')}")

                if kernel._model_provider == "uninitialized":
                    issues.append("Kernel provider is 'uninitialized'. Confirm Inference Mode settings.")
                if not getattr(kernel, "_swarm_enabled", False):
                    warnings.append("Swarm is disabled. Enable in Inference Mode for local GPU inference.")
                if kernel._model_provider == "api":
                    warnings.append("Using remote API. Local swarm NOT active.")

                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "update_field",
                        "section_id": "diagnostics",
                        "field_id": "troubleshoot",
                        "value": json.dumps({
                            "issues": issues,
                            "warnings": warnings,
                            "summary": (
                                f"{len(issues)} error{'s' if len(issues) != 1 else ''}, {len(warnings)} warning{'s' if len(warnings) != 1 else ''}"
                                if (issues or warnings)
                                else "All checks passed. Ready for inference."
                            ),
                        }),
                    },
                )

                # Debug info
                debug_lines = [
                    f"Provider: {kernel._model_provider}",
                    f"Endpoint: {kernel._lmstudio_endpoint}",
                    f"Swarm: {getattr(kernel, '_swarm_enabled', False)}",
                    f"Reasoning model: {kernel._selected_reasoning_model or 'None'}",
                    f"Tool model: {kernel._selected_tool_execution_model or 'None'}",
                    f"Active kernels: {len(_agent_kernel_instances)}",
                    f"Session: {session_id}",
                ]
                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "update_field",
                        "section_id": "diagnostics",
                        "field_id": "debug_info",
                        "value": json.dumps(debug_lines),
                    },
                )
                self._logger.info(f"[Session: {session_id}] Diagnostics pushed to UI ({len(health_checks)} checks)")

            elif section_id == "logs":
                # â”€â”€ Read logs from actual log files on disk â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                import json
                import os as _os
                system_logs = []
                error_logs = []

                try:
                    from pathlib import Path as _Path
                    log_dir = _Path(__file__).parent / "logs"

                    # Try the live structured log file first, then rotated backups
                    log_files = sorted(
                        log_dir.glob("irisvoice.log*"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )
                    parsed = []
                    for lf in log_files[:3]:  # up to 3 rotated files
                        try:
                            with open(lf, "r", encoding="utf-8", errors="replace") as f:
                                for line in f:
                                    line = line.strip()
                                    if not line:
                                        continue
                                    try:
                                        entry = json.loads(line)
                                        ts = entry.get("timestamp", "")
                                        lvl = entry.get("level", "INFO").upper()
                                        msg = entry.get("message", "")
                                        mod = entry.get("module", "")
                                        fn = entry.get("function", "")
                                        source = mod.split(".")[0] if mod else "system"
                                        parsed.append({
                                            "timestamp": ts,
                                            "level": lvl,
                                            "source": source,
                                            "message": f"[{fn}] {msg}" if fn else msg,
                                        })
                                    except json.JSONDecodeError:
                                        # Plain text line â€” wrap as INFO
                                        parsed.append({
                                            "timestamp": "",
                                            "level": "INFO",
                                            "source": "system",
                                            "message": line,
                                        })
                        except (OSError, PermissionError):
                            continue

                    # Sort newest first, take top 50 for system, top 40 for errors
                    parsed.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
                    system_logs = parsed[:50]
                    error_logs = [
                        e for e in parsed
                        if e["level"] in ("ERROR", "CRITICAL", "FATAL", "WARNING")
                    ][:40]

                except Exception as _le:
                    system_logs = [{
                        "timestamp": "",
                        "level": "ERROR",
                        "source": "system",
                        "message": f"Log read failed: {_le}",
                    }]
                    error_logs = []

                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "update_field",
                        "section_id": "logs",
                        "field_id": "system_logs",
                        "value": json.dumps(system_logs),
                    },
                )
                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "update_field",
                        "section_id": "logs",
                        "field_id": "error_logs",
                        "value": json.dumps(error_logs),
                    },
                )
                self._logger.info(f"[Session: {session_id}] Logs pushed to UI ({len(system_logs)} system, {len(error_logs)} errors)")

            elif section_id == "analytics":
                # â”€â”€ Gather usage stats from AnalyticsManager â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                try:
                    from backend.monitor.analytics import get_analytics_manager

                    analytics = get_analytics_manager()
                    all_data = analytics.get_all_analytics()

                    # Send structured analytics data to frontend
                    await self._ws_manager.send_to_client(
                        client_id,
                        {
                            "type": "monitor_analytics_data",
                            "payload": all_data,
                        },
                    )

                    # Also send a text summary for backward compat (usage_stats field)
                    stats = all_data.get("stats", {})
                    models = all_data.get("models", [])
                    summary_lines = [
                        f"Total calls: {stats.get('total_calls', 0)}",
                        f"Total tokens: {stats.get('total_tokens', 0):,}",
                        f"  Prompt: {stats.get('total_prompt_tokens', 0):,}",
                        f"  Completion: {stats.get('total_completion_tokens', 0):,}",
                        f"  Audio: {stats.get('total_audio_tokens', 0):,}",
                        f"Estimated cost: ${stats.get('estimated_cost', 0):.4f}",
                        f"Avg latency: {stats.get('avg_latency_ms', 0):.1f} ms",
                        f"Session duration: {stats.get('session_duration_minutes', 0):.1f} min",
                        f"Models used: {len(models)}",
                    ]
                    for m in models[:5]:
                        summary_lines.append(
                            f"  {m['model']}: {m['total_tokens']:,} tokens ({m['percentage']}%)"
                        )

                    await self._ws_manager.send_to_client(
                        client_id,
                        {
                            "type": "update_field",
                            "section_id": "analytics",
                            "field_id": "usage_stats",
                            "value": "\n".join(summary_lines),
                        },
                    )
                except Exception as analytics_err:
                    self._logger.warning(
                        f"[Session: {session_id}] Analytics manager error: {analytics_err}"
                    )
                    # Fallback to old behavior
                    stats = [
                        f"Active sessions: {len(_agent_kernel_instances)}",
                        f"Current provider: {kernel._model_provider}",
                        f"Reasoning model: {kernel._selected_reasoning_model or 'None'}",
                        f"Tool model: {kernel._selected_tool_execution_model or 'None'}",
                        f"Swarm enabled: {getattr(kernel, '_swarm_enabled', False)}",
                        f"Endpoint: {kernel._lmstudio_endpoint}",
                    ]
                    await self._ws_manager.send_to_client(
                        client_id,
                        {
                            "type": "update_field",
                            "section_id": "analytics",
                            "field_id": "usage_stats",
                            "value": "\n".join(stats),
                        },
                    )
                self._logger.info(f"[Session: {session_id}] Analytics pushed to UI")

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Monitor card handler error: {e}",
                exc_info=True,
            )

    async def _handle_request_models(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
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

        # Purge expired entries on every lookup to prevent unbounded dict growth
        now = datetime.now()
        expired_keys = [
            k
            for k, (_, t) in self._model_cache.items()
            if (now - t) >= self._model_cache_ttl
        ]
        for k in expired_keys:
            del self._model_cache[k]

        # Check cache first
        cached_models, cache_time = self._model_cache.get(endpoint, (None, None))
        if cached_models and cache_time and (now - cache_time) < self._model_cache_ttl:
            self._logger.info(f"[IRISGateway] Returning cached models for {endpoint}")
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "models_loaded",
                    "payload": {
                        "models": cached_models,
                        "endpoint": endpoint,
                        "cached": True,
                    },
                },
            )
            return

        # Fetch models from Ollama
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{endpoint}/api/tags")

                if response.status_code == 200:
                    data = response.json()
                    models = [model["name"] for model in data.get("models", [])]

                    # Cache the results
                    self._model_cache[endpoint] = (models, datetime.now())

                    self._logger.info(
                        f"[IRISGateway] Loaded {len(models)} models from Ollama at {endpoint}"
                    )

                    await self._ws_manager.send_to_client(
                        client_id,
                        {
                            "type": "models_loaded",
                            "payload": {
                                "models": models,
                                "endpoint": endpoint,
                                "cached": False,
                            },
                        },
                    )
                else:
                    error_msg = f"Ollama returned status {response.status_code}"
                    self._logger.error(f"[IRISGateway] {error_msg}")
                    await self._ws_manager.send_to_client(
                        client_id,
                        {
                            "type": "models_loaded",
                            "payload": {
                                "models": [],
                                "endpoint": endpoint,
                                "error": error_msg,
                            },
                        },
                    )

        except httpx.ConnectError as e:
            error_msg = f"Cannot connect to Ollama at {endpoint}. Is Ollama running?"
            self._logger.error(f"[IRISGateway] {error_msg}: {e}")
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "models_loaded",
                    "payload": {"models": [], "endpoint": endpoint, "error": error_msg},
                },
            )
        except httpx.TimeoutException:
            error_msg = f"Connection to Ollama at {endpoint} timed out"
            self._logger.error(f"[IRISGateway] {error_msg}")
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "models_loaded",
                    "payload": {"models": [], "endpoint": endpoint, "error": error_msg},
                },
            )
        except Exception as e:
            error_msg = f"Failed to fetch models: {str(e)}"
            self._logger.error(f"[IRISGateway] {error_msg}", exc_info=True)
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "models_loaded",
                    "payload": {"models": [], "endpoint": endpoint, "error": error_msg},
                },
            )

    async def _handle_set_model_selection(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
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
                reasoning_model, tool_execution_model
            )

            if success:
                # Update state manager with model selection
                pass
            state = await self._state_manager.get_state(session_id)
            if state:
                state.selected_reasoning_model = reasoning_model
                state.selected_tool_execution_model = tool_execution_model
                # State manager will auto-save

                # Send confirmation to client
                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "model_selection_updated",
                        "payload": {
                            "reasoning_model": reasoning_model,
                            "tool_execution_model": tool_execution_model,
                            "success": True,
                        },
                    },
                )

                # Broadcast to other clients in session
                await self._ws_manager.broadcast_to_session(
                    session_id,
                    {
                        "type": "model_selection_updated",
                        "payload": {
                            "reasoning_model": reasoning_model,
                            "tool_execution_model": tool_execution_model,
                            "success": True,
                        },
                    },
                    exclude_clients={client_id},
                )

                # Emit model_load_event for InferenceConsolePanel
                try:
                    import time as _time_ml

                    await self._ws_manager.broadcast_to_session(
                        session_id,
                        {
                            "type": "model_load_event",
                            "payload": {
                                "action": "loaded",
                                "model": reasoning_model or "unknown",
                                "profile": "reasoning",
                                "timestamp": _time_ml.time(),
                            },
                        },
                    )
                except Exception:
                    pass
            else:
                # Send error
                await self._send_error(
                    client_id,
                    "Failed to set model selection - models may not be available",
                )

        except Exception as e:
            self._logger.error(f"Error setting model selection: {e}", exc_info=True)
            await self._send_error(
                client_id, f"Failed to set model selection: {str(e)}"
            )

    async def _handle_test_connection(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
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
                    state_manager = (
                        await self._state_manager._get_session_state_manager(session_id)
                    )
                    if state_manager:
                        api_key = state_manager.get_decrypted_field_value(
                            "model", "openai_api_key"
                        )

                if not api_url:
                    state_manager = (
                        await self._state_manager._get_session_state_manager(session_id)
                    )
                    if state_manager:
                        api_url = state_manager.get_field_value(
                            "model", "openai_api_url"
                        )

                # Use default URL if not provided
                if not api_url:
                    api_url = "https://api.openai.com/v1"

                if not api_key:
                    await self._ws_manager.send_to_client(
                        client_id,
                        {
                            "type": "connection_test_result",
                            "payload": {
                                "connection_type": "openai",
                                "success": False,
                                "message": "API key is required",
                                "tested_url": api_url,
                            },
                        },
                    )
                    return

                # Test the connection
                from .utils.openai_connection_test import test_openai_connection

                _conn_result = await test_openai_connection(api_key, api_url)
                success, _conn_msg = _conn_result

                # Send result to client
                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "connection_test_result",
                        "payload": {
                            "connection_type": "openai",
                            "success": success,
                            "message": _conn_msg,
                            "tested_url": api_url,
                        },
                    },
                )
            else:
                await self._send_error(
                    client_id, f"Unknown connection type: {connection_type}"
                )

        except Exception as e:
            self._logger.error(f"Error testing connection: {e}", exc_info=True)
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "connection_test_result",
                    "payload": {
                        "connection_type": connection_type,
                        "success": False,
                        "message": f"Error testing connection: {str(e)}",
                    },
                },
            )

    async def _handle_request_state(self, session_id: str, client_id: str) -> None:
        """
        Handle request_state message - send full state to client.
        Also flushes any buffered undelivered messages (guaranteed delivery).

        Args:
            session_id: Session ID
            client_id: Client ID
        """
        state = await self._state_manager.get_state(session_id)
        # Hydrate field_values from persisted config so the user's
        # wheel-view settings survive frontend remounts / page reloads.
        _saved_fv = load_field_values()
        if _saved_fv:
            for section_id, fields in _saved_fv.items():
                if section_id in state.field_values:
                    state.field_values[section_id].update(fields)

        await self._ws_manager.send_to_client(
            client_id,
            {
                "type": "initial_state",
                "payload": {"state": state.model_dump() if state else {}},
            },
        )

        # Flush any pending deliveries that were buffered while disconnected
        await self._ws_manager.flush_pending(session_id, client_id)

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
                extra={"session_id": session_id, "client_id": client_id},
            )

            # 1. Get built-in pvporcupine keywords from WakeConfig class attribute
            from .agent.wake_config import WakeConfig

            builtin_list = [
                {
                    "filename": phrase.replace(" ", "_"),
                    "display_name": phrase.title(),
                    "platform": "builtin",
                    "version": "builtin",
                    "is_builtin": True,
                }
                for phrase in WakeConfig.SUPPORTED_PHRASES
            ]

            # 2. Rescan the wake words directory each time to pick up newly added .ppn files
            #    (scan_directory is a fast glob â€” safe to call on each get_wake_words request)
            discovered_files = self._wake_word_discovery.scan_directory()
            custom_list = [
                {
                    "filename": wf.filename,
                    "display_name": wf.display_name,
                    "platform": wf.platform,
                    "version": wf.version,
                    "is_builtin": False,
                }
                for wf in discovered_files
            ]

            # 3. Combine: built-ins first, then custom files
            wake_words_list = builtin_list + custom_list

            self._logger.info(
                f"[Session: {session_id}] Returning {len(wake_words_list)} wake word(s) "
                f"({len(builtin_list)} built-in, {len(custom_list)} custom)",
                extra={
                    "session_id": session_id,
                    "client_id": client_id,
                    "count": len(wake_words_list),
                },
            )

            # Send response to client â€” type "wake_words" matches the frontend hook's case "wake_words"
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "wake_words",
                    "payload": {
                        "wake_words": wake_words_list,
                        "count": len(wake_words_list),
                    },
                },
            )

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error handling get_wake_words: {e}",
                exc_info=True,
                extra={
                    "session_id": session_id,
                    "client_id": client_id,
                    "error": str(e),
                },
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
                extra={"session_id": session_id, "client_id": client_id},
            )

            # Get available audio devices
            devices = AudioPipeline.list_devices()

            # Separate input and output devices (sorted alphabetically by name)
            input_devices = sorted(
                [
                    {
                        "index": d["index"],
                        "name": d["name"],
                        "sample_rate": d["sample_rate"],
                    }
                    for d in devices
                    if d["input"]
                ],
                key=lambda x: x["name"].lower(),
            )
            output_devices = sorted(
                [
                    {
                        "index": d["index"],
                        "name": d["name"],
                        "sample_rate": d["sample_rate"],
                    }
                    for d in devices
                    if d["output"]
                ],
                key=lambda x: x["name"].lower(),
            )

            self._logger.info(
                f"[Session: {session_id}] Returning {len(input_devices)} input device(s) and {len(output_devices)} output device(s)",
                extra={
                    "session_id": session_id,
                    "client_id": client_id,
                    "input_count": len(input_devices),
                    "output_count": len(output_devices),
                },
            )

            # Send response to client
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "audio_devices",
                    "payload": {
                        "input_devices": input_devices,
                        "output_devices": output_devices,
                        "input_count": len(input_devices),
                        "output_count": len(output_devices),
                    },
                },
            )

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error handling get_audio_devices: {e}",
                exc_info=True,
                extra={
                    "session_id": session_id,
                    "client_id": client_id,
                    "error": str(e),
                },
            )
            await self._send_error(
                client_id, f"Error retrieving audio devices: {str(e)}"
            )

    async def _handle_select_audio_device(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """
        Handle select_audio_device message â€” switch input or output device at runtime.

        Payload:
            device_type  "input" | "output"
            device_index  sounddevice device index (int)
            device_name   human-readable name for logging
        """
        try:
            payload = message.get("payload", {})
            device_type = payload.get("device_type")
            device_index = payload.get("device_index")
            device_name = payload.get("device_name", f"index {device_index}")

            if device_type not in ("input", "output"):
                await self._send_error(client_id,
                    "select_audio_device requires device_type: 'input' or 'output'")
                return
            if device_index is None:
                await self._send_error(client_id,
                    "select_audio_device requires device_index")
                return

            self._logger.info(
                f"[Session: {session_id}] Switching {device_type} device to "
                f"'{device_name}' (index {device_index})"
            )

            # Tell AudioEngine to restart the pipeline with the new device.
            # update_config() handles stop â†’ initialize â†’ start atomically.
            from .audio.engine import get_audio_engine
            engine = get_audio_engine()
            engine.update_config(**{f"{device_type}_device": device_index})

            self._logger.info(
                f"[Session: {session_id}] {device_type} device switched to "
                f"'{device_name}' â€” pipeline restarted"
            )

            # Confirm to client
            await self._ws_manager.send_to_client(client_id, {
                "type": "audio_device_selected",
                "payload": {
                    "device_type": device_type,
                    "device_index": device_index,
                    "name": device_name,
                },
            })

            # Re-push the full device list so the UI shows the new active device
            await self._handle_get_audio_devices(session_id, client_id)

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error handling select_audio_device: {e}",
                exc_info=True,
            )
            await self._send_error(
                client_id, f"Error switching audio device: {str(e)}"
            )

    async def _handle_select_wake_word(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
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
                    extra={"session_id": session_id, "client_id": client_id},
                )
                await self._send_error(client_id, "No filename provided")
                return

            self._logger.info(
                f"[Session: {session_id}] Processing select_wake_word: {filename}",
                extra={
                    "session_id": session_id,
                    "client_id": client_id,
                    "wake_word_filename": filename,
                },
            )

            # Look up wake word file â€” try cached results first, rescan if not found
            wake_word_file = self._wake_word_discovery.get_file_by_filename(filename)
            if not wake_word_file:
                # Cache may be stale (e.g., select_wake_word called before get_wake_words).
                # Rescan once to pick up newly visible .ppn files.
                self._wake_word_discovery.scan_directory()
                wake_word_file = self._wake_word_discovery.get_file_by_filename(
                    filename
                )

            if not wake_word_file:
                self._logger.warning(
                    f"[Session: {session_id}] Wake word file not found: {filename}",
                    extra={
                        "session_id": session_id,
                        "client_id": client_id,
                        "wake_word_filename": filename,
                    },
                )
                await self._send_error(
                    client_id, f"Wake word file not found: {filename}"
                )
                return

            # Update WakeConfig â€” the registered callback triggers reinitialize_porcupine().
            # Custom .ppn files store the absolute path; built-ins use the keyword name.
            try:
                from .agent.wake_config import get_wake_config

                wake_config = get_wake_config()
                is_builtin = wake_word_file.platform == "builtin"
                if is_builtin:
                    wake_config.update_config(
                        wake_phrase=wake_word_file.display_name.lower(),
                        custom_model_path=None,
                    )
                else:
                    wake_config.update_config(
                        wake_phrase=wake_word_file.display_name,
                        custom_model_path=wake_word_file.path,
                    )
                self._logger.info(
                    f"[Session: {session_id}] Wake word updated: '{wake_word_file.display_name}' "
                    f"({'builtin' if is_builtin else wake_word_file.path})",
                    extra={
                        "session_id": session_id,
                        "client_id": client_id,
                        "wake_word_filename": wake_word_file.filename,
                        "display_name": wake_word_file.display_name,
                        "platform": wake_word_file.platform,
                    },
                )
            except Exception as cfg_e:
                self._logger.error(
                    f"[Session: {session_id}] Failed to update WakeConfig for wake word: {cfg_e}",
                    extra={"session_id": session_id, "client_id": client_id},
                )

            # Broadcast selection to all clients in session
            await self._ws_manager.broadcast_to_session(
                session_id,
                {
                    "type": "wake_word_selected",
                    "payload": {
                        "filename": wake_word_file.filename,
                        "display_name": wake_word_file.display_name,
                        "platform": wake_word_file.platform,
                        "version": wake_word_file.version,
                    },
                },
            )

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error handling select_wake_word: {e}",
                exc_info=True,
                extra={
                    "session_id": session_id,
                    "client_id": client_id,
                    "error": str(e),
                },
            )
            await self._send_error(client_id, f"Error selecting wake word: {str(e)}")

    async def _handle_get_cleanup_report(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
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
                extra={
                    "session_id": session_id,
                    "client_id": client_id,
                    "dry_run": dry_run,
                },
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
                        "reason": f.reason,
                    }
                    for f in report.unused_models
                ],
                "unused_dependencies": [
                    {
                        "name": d.name,
                        "version": d.version,
                        "install_size_bytes": d.install_size_bytes,
                        "reason": d.reason,
                    }
                    for d in report.unused_dependencies
                ],
                "unused_wake_words": [
                    {
                        "path": f.path,
                        "size_bytes": f.size_bytes,
                        "last_accessed": f.last_accessed.isoformat(),
                        "reason": f.reason,
                    }
                    for f in report.unused_wake_words
                ],
                "unused_configs": [
                    {
                        "path": f.path,
                        "size_bytes": f.size_bytes,
                        "last_accessed": f.last_accessed.isoformat(),
                        "reason": f.reason,
                    }
                    for f in report.unused_configs
                ],
                "total_size_bytes": report.total_size_bytes,
                "total_count": report.total_count,
                "warnings": report.warnings,
                "timestamp": report.timestamp.isoformat(),
            }

            self._logger.info(
                f"[Session: {session_id}] Cleanup report generated: "
                f"{report.total_count} items, {report.total_size_bytes / (1024 * 1024):.2f} MB",
                extra={
                    "session_id": session_id,
                    "total_count": report.total_count,
                    "total_size_mb": report.total_size_bytes / (1024 * 1024),
                },
            )

            # Send report to client
            await self._ws_manager.send_to_client(
                client_id, {"type": "cleanup_report", "payload": report_dict}
            )

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error generating cleanup report: {e}",
                exc_info=True,
                extra={
                    "session_id": session_id,
                    "client_id": client_id,
                    "error": str(e),
                },
            )
            await self._send_error(
                client_id, f"Error generating cleanup report: {str(e)}"
            )

    async def _handle_execute_cleanup(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
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
                extra={
                    "session_id": session_id,
                    "client_id": client_id,
                    "item_count": len(items),
                },
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
                "backup_path": result.backup_path,
            }

            self._logger.info(
                f"[Session: {session_id}] Cleanup executed: "
                f"success={result.success}, freed {result.freed_bytes / (1024 * 1024):.2f} MB",
                extra={
                    "session_id": session_id,
                    "success": result.success,
                    "freed_mb": result.freed_bytes / (1024 * 1024),
                    "removed_files": len(result.removed_files),
                    "removed_deps": len(result.removed_dependencies),
                    "errors": len(result.errors),
                },
            )

            # Send result to client
            await self._ws_manager.send_to_client(
                client_id, {"type": "cleanup_result", "payload": result_dict}
            )

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error executing cleanup: {e}",
                exc_info=True,
                extra={
                    "session_id": session_id,
                    "client_id": client_id,
                    "error": str(e),
                },
            )
            await self._send_error(client_id, f"Error executing cleanup: {str(e)}")

    # ============================================================================
    # GAP-01 FIX: Additional handlers from main.py
    # ============================================================================

    async def _handle_collapse_to_idle(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
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
                extra={"session_id": session_id, "client_id": client_id},
            )

            await self._state_manager.collapse_to_idle(session_id)
            await self._broadcast_state_update(session_id, exclude_client=client_id)

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error collapsing to idle: {e}",
                exc_info=True,
                extra={
                    "session_id": session_id,
                    "client_id": client_id,
                    "error": str(e),
                },
            )
            await self._send_error(client_id, f"Error collapsing to idle: {str(e)}")

    async def _handle_expand_to_main(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
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
                extra={"session_id": session_id, "client_id": client_id},
            )

            # Send confirmation to client
            await self._ws_manager.send_to_client(
                client_id, {"type": "category_expanded", "payload": {}}
            )

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error expanding to main: {e}",
                exc_info=True,
                extra={
                    "session_id": session_id,
                    "client_id": client_id,
                    "error": str(e),
                },
            )
            await self._send_error(client_id, f"Error expanding to main: {str(e)}")

    async def _handle_reload_skills(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
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
                extra={"session_id": session_id, "client_id": client_id},
            )

            from backend.agent.skills import get_skills_loader

            loader = get_skills_loader()
            loader.reload()

            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "skills_reloaded",
                    "payload": {"skills": loader.list_skills()},
                },
            )

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error reloading skills: {e}",
                exc_info=True,
                extra={
                    "session_id": session_id,
                    "client_id": client_id,
                    "error": str(e),
                },
            )
            await self._ws_manager.send_to_client(
                client_id, {"type": "skills_error", "payload": {"error": str(e)}}
            )

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
            self._logger.info(f"[Session: {session_id}] Cleaning up session resources")

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

            self._logger.info(f"[Session: {session_id}] Session cleanup completed")

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error during cleanup: {e}",
                exc_info=True,
            )

    async def _handle_execute_tool(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
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
                await self._send_validation_error(
                    client_id, "tool_name", "Tool name is required"
                )
                return

            self._logger.info(
                f"[Session: {session_id}] Executing tool: {tool_name}",
                extra={
                    "session_id": session_id,
                    "client_id": client_id,
                    "tool": tool_name,
                },
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
                    result = await agent_kernel._tool_bridge.execute_tool(
                        tool_name, parameters
                    )
                    await self._ws_manager.send_to_client(
                        client_id,
                        {
                            "type": "tool_result",
                            "payload": {"tool": tool_name, "result": result},
                        },
                    )
                except Exception as e:
                    await self._ws_manager.send_to_client(
                        client_id,
                        {
                            "type": "tool_result",
                            "payload": {"tool": tool_name, "error": str(e)},
                        },
                    )
            else:
                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "tool_result",
                        "payload": {
                            "tool": tool_name,
                            "error": "Tool bridge not available",
                        },
                    },
                )

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error executing tool: {e}",
                exc_info=True,
                extra={
                    "session_id": session_id,
                    "client_id": client_id,
                    "error": str(e),
                },
            )
            await self._send_error(client_id, f"Error executing tool: {str(e)}")

    async def _handle_enable_vision(self, session_id: str, client_id: str) -> None:
        """
        Handle enable_vision message â€” checks if LFM2.5-VL llama-server is reachable.
        Vision is a separate process (llama-server port 8081); enabling = health check.
        """
        try:
            self._logger.info(
                f"[Session: {session_id}] Checking vision server availability"
            )

            # Send loading status while we check
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "vision_status",
                    "payload": {
                        "status": "loading",
                        "vram_usage_mb": None,
                        "load_progress_percent": None,
                        "error_message": None,
                        "model_name": "lfm2.5-vl",
                        "quantization_enabled": False,
                        "is_available": False,
                    },
                },
            )

            import asyncio

            available = await asyncio.get_event_loop().run_in_executor(
                None, self._vision_provider.health_check
            )

            status_payload = {
                "status": "enabled" if available else "error",
                "vram_usage_mb": None,
                "load_progress_percent": None,
                "error_message": None
                if available
                else "Vision server not running on port 8081. Start start_vl.bat first.",
                "model_name": "lfm2.5-vl",
                "quantization_enabled": False,
                "is_available": available,
            }

            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "enable_vision",
                    "payload": {
                        "success": available,
                        "error": status_payload.get("error_message"),
                    },
                },
            )
            await self._ws_manager.broadcast_to_session(
                session_id, {"type": "vision_status", "payload": status_payload}
            )

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error enabling vision: {e}", exc_info=True
            )
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "enable_vision",
                    "payload": {"success": False, "error": str(e)},
                },
            )

    async def _handle_disable_vision(self, session_id: str, client_id: str) -> None:
        """
        Handle disable_vision message.
        LFM2.5-VL is a separate process â€” disabling means the agent stops calling vision tools.
        """
        try:
            self._logger.info(f"[Session: {session_id}] Vision disabled by user")
            await self._ws_manager.send_to_client(
                client_id, {"type": "disable_vision", "payload": {"success": True}}
            )
            await self._ws_manager.broadcast_to_session(
                session_id,
                {
                    "type": "vision_status",
                    "payload": {
                        "status": "disabled",
                        "vram_usage_mb": None,
                        "load_progress_percent": None,
                        "error_message": None,
                        "model_name": "lfm2.5-vl",
                        "quantization_enabled": False,
                        "is_available": False,
                    },
                },
            )
        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error disabling vision: {e}", exc_info=True
            )
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "disable_vision",
                    "payload": {"success": False, "error": str(e)},
                },
            )

    async def _handle_get_vision_status(self, session_id: str, client_id: str) -> None:
        """
        Handle get_vision_status message â€” pings LFM2.5-VL server.
        """
        try:
            import asyncio

            available = await asyncio.get_event_loop().run_in_executor(
                None, self._vision_provider.health_check
            )
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "vision_status",
                    "payload": {
                        "status": "enabled" if available else "error",
                        "vram_usage_mb": None,
                        "load_progress_percent": None,
                        "error_message": None
                        if available
                        else "Vision server not running on port 8081",
                        "model_name": "lfm2.5-vl",
                        "quantization_enabled": False,
                        "is_available": available,
                    },
                },
            )
        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error getting vision status: {e}",
                exc_info=True,
            )
            await self._send_error(client_id, f"Error getting vision status: {str(e)}")

    async def _handle_message_exported(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
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
                    "content_type": content_type,
                },
            )
        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error handling message export: {e}",
                exc_info=True,
            )

    async def _broadcast_state_update(
        self, session_id: str, exclude_client: Optional[str] = None
    ) -> None:
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
                {"type": "state_sync", "payload": {"state": state.model_dump()}},
                exclude_clients=exclude_set,
            )

    async def _send_error(self, client_id: str, error_message: str) -> None:
        """
        Send error message to client.

        Args:
            client_id: Client ID
            error_message: Error message
        """
        await self._ws_manager.send_to_client(
            client_id, {"type": "error", "payload": {"message": error_message}}
        )

    async def _send_validation_error(
        self, client_id: str, field_id: str, error_message: str
    ) -> None:
        """
        Send validation error message to client.
        GAP-09 FIX: Uses flat payload structure for consistency.

        Args:
            client_id: Client ID
            field_id: Field ID that failed validation
            error_message: Error message
        """
        await self._ws_manager.send_to_client(
            client_id,
            {"type": "validation_error", "field_id": field_id, "error": error_message},
        )

    # --------------------------------------------------------------------------
    # Skills management handlers
    # --------------------------------------------------------------------------

    _SKILLS_ROOT = None  # resolved lazily

    def _get_skills_root(self):
        """Return the absolute path to the skills directory."""
        if IRISGateway._SKILLS_ROOT is None:
            from pathlib import Path

            IRISGateway._SKILLS_ROOT = (
                Path(__file__).resolve().parent / "agent" / "skills"
            )
        return IRISGateway._SKILLS_ROOT

    def _read_skill_config(self):
        """Read config.yaml and return the set of disabled skill keys."""
        try:
            import yaml
            from pathlib import Path

            cfg_path = self._get_skills_root() / "config.yaml"
            if cfg_path.exists():
                data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                return set(data.get("disabled_skills", []))
        except Exception as e:
            self._logger.warning(f"[IRISGateway] Could not read skill config: {e}")
        return set()

    def _write_skill_config(self, disabled: set):
        """Persist the disabled skills list to config.yaml."""
        try:
            import yaml

            cfg_path = self._get_skills_root() / "config.yaml"
            existing = {}
            if cfg_path.exists():
                existing = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            existing["disabled_skills"] = sorted(disabled)
            cfg_path.write_text(
                yaml.dump(existing, default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )
        except Exception as e:
            self._logger.error(f"[IRISGateway] Could not write skill config: {e}")

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
                            name = (
                                stripped.split(":", 1)[1].strip().strip('"').strip("'")
                            )
                            break
                    skills.append(
                        {
                            "key": child.name,
                            "name": name,
                            "description": description,
                            "enabled": child.name not in disabled,
                        }
                    )
                except Exception as e:
                    self._logger.warning(
                        f"[IRISGateway] Could not read skill {child.name}: {e}"
                    )

        await self._ws_manager.send_to_client(
            client_id, {"type": "skills_list", "payload": {"skills": skills}}
        )

    async def _handle_toggle_skill(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
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
            f"[IRISGateway] Skill '{key}' {'enabled' if enabled else 'disabled'}"
        )
        await self._ws_manager.send_to_client(
            client_id,
            {"type": "skill_toggled", "payload": {"key": key, "enabled": enabled}},
        )

    async def _handle_delete_skill(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
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
            await self._send_error(
                client_id, f"delete_skill: cannot delete built-in skill '{key}'"
            )
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
            await self._ws_manager.send_to_client(
                client_id, {"type": "skill_deleted", "payload": {"key": key}}
            )
        except Exception as e:
            self._logger.error(f"[IRISGateway] Failed to delete skill '{key}': {e}")
            await self._send_error(client_id, f"Failed to delete skill: {e}")

    async def _handle_create_skill(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """Create a new skill directory with a SKILL.md file."""
        from pathlib import Path
        import re

        payload = message.get("payload", {})
        name = (payload.get("name") or message.get("name", "")).strip()
        description = (
            payload.get("description") or message.get("description", "")
        ).strip()
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
            self._logger.info(f"[IRISGateway] Created skill '{key}' at {skill_md}")
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "skill_created",
                    "payload": {
                        "key": key,
                        "name": name,
                        "description": description,
                        "enabled": True,
                    },
                },
            )
        except Exception as e:
            self._logger.error(f"[IRISGateway] Failed to create skill '{key}': {e}")
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

        NOTE: Loopback devices (Stereo Mix, CABLE Output, VoiceMeeter, "What U Hear")
        are excluded from output resolution because they route audio BACK into the
        capture bus instead of to the user's speakers, which causes:
          - Audio feedback / static (user hears nothing or distorted output)
          - Half-duplex gate on activation sound blocks the mic for 38+ seconds
          - Wake word fires on its own TTS output repeatedly
        """
        if isinstance(device, int):
            return device
        if not isinstance(device, str) or device == "":
            return device

        # â”€â”€ Loopback device keywords to skip â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        _LOOPBACK_KEYWORDS = (
            "stereo mix",
            "what u hear",
            "cable output",
            "cable input",
            "voicemeeter output",
            "voicemeeter aux",
            "vb-audio",
        )

        def _is_loopback(name: str) -> bool:
            n = name.lower()
            return any(kw in n for kw in _LOOPBACK_KEYWORDS)

        try:
            devices = AudioPipeline.list_devices()
            # Exact match first
            for d in devices:
                if want_input and not d.get("input"):
                    continue
                if not want_input and not d.get("output"):
                    continue
                if not want_input and _is_loopback(d.get("name", "")):
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
                if not want_input and _is_loopback(d.get("name", "")):
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
                if not want_input and _is_loopback(d.get("name", "")):
                    continue
                name_lower = d["name"].lower()
                if device_lower in name_lower or name_lower in device_lower:
                    self._logger.debug(
                        f"[IRISGateway] Resolved '{device}' via substring match â†’ "
                        f"'{d['name']}' (index {d['index']})"
                    )
                    return d["index"]
            available = [
                d["name"] for d in devices if d.get("input" if want_input else "output")
            ]
            self._logger.warning(
                f"[IRISGateway] Could not resolve device name '{device}' to an index â€” "
                f"using name as-is. Available: {available}"
            )
        except Exception as e:
            self._logger.error(
                f"[IRISGateway] Error resolving device index for '{device}': {e}"
            )
        return device

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Local GGUF model handlers
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def _handle_get_local_models(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """Return scanned GGUF models and hardware info."""
        from .agent.local_model_manager import get_local_model_manager

        try:
            mgr = get_local_model_manager()
            loop = __import__("asyncio").get_event_loop()
            models = await loop.run_in_executor(None, mgr.scan_models)
            hardware = await loop.run_in_executor(None, mgr.get_hardware_info)
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "local_models_list",
                    "payload": {"models": models, "hardware": hardware},
                },
            )
        except Exception as e:
            self._logger.error(f"[LocalModel] get_local_models error: {e}")
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "local_models_list",
                    "payload": {"models": [], "hardware": {}, "error": str(e)},
                },
            )

    async def _handle_load_local_model(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """Spawn llama-cpp-python server subprocess for the selected GGUF."""
        from .agent.local_model_manager import get_local_model_manager

        payload = message.get("payload", message)
        model_path = payload.get("model_path", "")
        profile = payload.get("profile", "balanced")
        custom_params = payload.get("custom_params", {})

        if not model_path:
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "local_model_loading",
                    "payload": {"status": "error", "error": "model_path is required"},
                },
            )
            return

        # [10.8] Broadcast "switching" state if a model is already loaded
        mgr_pre = None
        try:
            from .agent.local_model_manager import get_local_model_manager as _get_mgr

            mgr_pre = _get_mgr()
            if mgr_pre.is_loaded():
                import time as _t

                await self._ws_manager.broadcast_to_session(
                    session_id,
                    {
                        "type": "local_model_loading",
                        "payload": {
                            "status": "switching",
                            "from_model": mgr_pre.get_status().get("model_path", ""),
                            "to_model": model_path,
                            "profile": profile,
                            "pct": 0,
                            "msg": "Switching model â€” finishing current requests...",
                        },
                    },
                )
        except Exception:
            pass

        await self._ws_manager.send_to_client(
            client_id,
            {
                "type": "local_model_loading",
                "payload": {
                    "status": "starting",
                    "model_path": model_path,
                    "profile": profile,
                    "pct": 0,
                },
            },
        )

        try:
            mgr = get_local_model_manager()

            # Progress callback â€” sends incremental layer-loading updates to the client.
            # Called as each significant progress milestone is parsed from llama.cpp stdout.
            async def _progress_cb(event: dict) -> None:
                try:
                    await self._ws_manager.send_to_client(
                        client_id,
                        {
                            "type": "local_model_loading",
                            "payload": {
                                "status": "loading",
                                "phase": event.get("phase", "loading"),
                                "pct": event.get("pct", 0),
                                "msg": event.get("msg", ""),
                                "model_path": model_path,
                                "profile": profile,
                            },
                        },
                    )
                except Exception:
                    pass

            # [10.7] Crash callback â€” watchdog calls this if subprocess dies after load
            async def _crash_cb() -> None:
                try:
                    await self._ws_manager.broadcast_to_session(
                        session_id,
                        {
                            "type": "local_model_status",
                            "payload": {
                                "loaded": False,
                                "model_path": None,
                                "profile": None,
                                "status": "crashed",
                                "error": "Model server exited unexpectedly",
                            },
                        },
                    )
                    # De-wire kernel after crash (both HTTP + in-process paths)
                    from .agent import get_agent_kernel

                    kernel = get_agent_kernel(session_id)
                    kernel.configure_openai_compat(None)
                    if hasattr(kernel, "configure_inprocess_local"):
                        kernel.configure_inprocess_local(None)
                except Exception:
                    pass

            ok = await mgr.load_model(
                model_path,
                profile,
                custom_params,
                progress_cb=_progress_cb,
                crash_cb=_crash_cb,
            )
            status = "ready" if ok else "error"
            payload_out = {
                "status": status,
                "model_path": model_path,
                "profile": profile,
            }
            if not ok:
                payload_out["error"] = "Server did not start within timeout"
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "local_model_loading",
                    "payload": payload_out,
                },
            )
            # Wire kernel to iris_local provider. When the in-process path is
            # active (IRIS_INPROCESS_LLAMA=1, default) we ALSO bind the manager
            # directly onto the kernel so `_get_lmstudio_client()` returns the
            # in-process adapter instead of creating an HTTP client that would
            # hit a port nobody is listening on.
            if ok:
                try:
                    from .agent import get_agent_kernel

                    kernel = get_agent_kernel(session_id)
                    # mgr.ENDPOINT = "http://127.0.0.1:8082/v1"
                    # _get_lmstudio_client() appends /v1 itself â€” strip to avoid /v1/v1
                    _base = mgr.ENDPOINT.rstrip("/").removesuffix("/v1")
                    kernel.configure_openai_compat(_base, provider_name="iris_local")
                    # In-process binding (no-op on legacy subprocess path since
                    # mgr.get_inprocess_client() returns None when self._llm is None)
                    if hasattr(kernel, "configure_inprocess_local"):
                        kernel.configure_inprocess_local(mgr)
                    _inproc = getattr(mgr, "_llm", None) is not None
                    self._logger.info(
                        f"[iris_local] Kernel wired: {_base} "
                        f"({'in-process' if _inproc else 'subprocess HTTP'}, session {session_id})"
                    )
                except Exception as kw_err:
                    self._logger.warning(f"[iris_local] Kernel wire failed: {kw_err}")

                await self._handle_get_available_models(session_id, client_id, {})
                import time as _time

                await self._ws_manager.broadcast_to_session(
                    session_id,
                    {
                        "type": "model_load_event",
                        "payload": {
                            "action": "loaded",
                            "model": model_path,
                            "profile": profile,
                            "timestamp": _time.time(),
                        },
                    },
                )
        except Exception as e:
            self._logger.error(f"[LocalModel] load_local_model error: {e}")
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "local_model_loading",
                    "payload": {
                        "status": "error",
                        "error": str(e),
                        "model_path": model_path,
                    },
                },
            )

    async def _handle_unload_local_model(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """Stop the iris_local model server subprocess.

        [10.7] Also de-wires the kernel so it does not keep hitting the dead :8082
        endpoint after unload. Kernel provider reset to None â€” the user must explicitly
        choose a new provider before sending the next message.
        """
        from .agent.local_model_manager import get_local_model_manager
        import time as _time

        try:
            mgr = get_local_model_manager()
            status_before = mgr.get_status()
            model_path_before = (
                status_before.get("model_path")
                if isinstance(status_before, dict)
                else None
            )
            await mgr.unload_model()

            # [10.7] De-wire the kernel â€” prevent stale requests to dead :8082 endpoint
            # AND release the in-process adapter binding so the next model load
            # starts from a clean slate.
            try:
                from .agent import get_agent_kernel

                kernel = get_agent_kernel(session_id)
                kernel.configure_openai_compat(None)
                if hasattr(kernel, "configure_inprocess_local"):
                    kernel.configure_inprocess_local(None)
                self._logger.info(
                    f"[iris_local] Kernel de-wired after unload (session {session_id})"
                )
            except Exception as kw_err:
                self._logger.debug(f"[iris_local] Kernel de-wire skipped: {kw_err}")

            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "local_model_status",
                    "payload": {"loaded": False, "model_path": None, "profile": None},
                },
            )
            await self._ws_manager.broadcast_to_session(
                session_id,
                {
                    "type": "model_load_event",
                    "payload": {
                        "action": "unloaded",
                        "model": model_path_before or "",
                        "profile": "",
                        "timestamp": _time.time(),
                    },
                },
            )
        except Exception as e:
            self._logger.error(f"[LocalModel] unload error: {e}")

    async def _handle_apply_inference_settings(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """
        [10.9] Apply new inference settings to the loaded model.
        If the new params require a subprocess restart (n_ctx, n_gpu_layers changed),
        performs a clean unload + reload with the new settings.
        If only hot-applicable params changed (n_batch etc.), acknowledges without reload.
        """
        from .agent.local_model_manager import get_local_model_manager
        import time as _time

        payload = message.get("payload", message)
        new_profile = payload.get("profile", "balanced")
        custom_params = payload.get("custom_params", {})

        try:
            mgr = get_local_model_manager()
            status = mgr.get_status()

            if not status.get("loaded"):
                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "inference_settings_result",
                        "payload": {"status": "error", "error": "No model loaded"},
                    },
                )
                return

            current_model = status.get("model_path", "")
            needs_reload = mgr.would_require_reload(new_profile, custom_params)

            if not needs_reload:
                # Hot-apply: n_ctx and n_gpu_layers unchanged â€” acknowledge only
                # (llama-cpp-python server does not expose a live settings endpoint,
                # so we save the new params for the next load and confirm to the user)
                mgr.save_model_settings(
                    __import__("pathlib").Path(current_model).name,
                    {"last_profile": new_profile},
                )
                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "inference_settings_result",
                        "payload": {
                            "status": "applied",
                            "profile": new_profile,
                            "reload_required": False,
                            "msg": "Settings saved. Will apply on next model load.",
                        },
                    },
                )
                return

            # Reload required (n_ctx or n_gpu_layers changed)
            await self._ws_manager.broadcast_to_session(
                session_id,
                {
                    "type": "local_model_loading",
                    "payload": {
                        "status": "reloading_for_settings",
                        "profile": new_profile,
                        "model_path": current_model,
                        "pct": 0,
                        "msg": "Applying new inference settings â€” reloading model...",
                    },
                },
            )

            async def _progress_cb(event: dict) -> None:
                try:
                    await self._ws_manager.send_to_client(
                        client_id,
                        {
                            "type": "local_model_loading",
                            "payload": {
                                "status": "loading",
                                "phase": event.get("phase", "loading"),
                                "pct": event.get("pct", 0),
                                "msg": event.get("msg", ""),
                                "model_path": current_model,
                                "profile": new_profile,
                            },
                        },
                    )
                except Exception:
                    pass

            async def _crash_cb() -> None:
                await self._ws_manager.broadcast_to_session(
                    session_id,
                    {
                        "type": "local_model_status",
                        "payload": {
                            "loaded": False,
                            "model_path": None,
                            "profile": None,
                            "status": "crashed",
                            "error": "Model server exited unexpectedly",
                        },
                    },
                )

            ok = await mgr.load_model(
                current_model,
                new_profile,
                custom_params,
                progress_cb=_progress_cb,
                crash_cb=_crash_cb,
            )

            if ok:
                try:
                    from .agent import get_agent_kernel

                    kernel = get_agent_kernel(session_id)
                    _base = mgr.ENDPOINT.rstrip("/").removesuffix("/v1")
                    kernel.configure_openai_compat(_base, provider_name="iris_local")
                    # Re-bind in-process adapter after reload (unload above
                    # would have cleared it, so this restores the direct path)
                    if hasattr(kernel, "configure_inprocess_local"):
                        kernel.configure_inprocess_local(mgr)
                except Exception as kw_err:
                    self._logger.warning(
                        f"[iris_local] Kernel re-wire failed: {kw_err}"
                    )

            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "inference_settings_result",
                    "payload": {
                        "status": "applied" if ok else "error",
                        "profile": new_profile,
                        "reload_required": True,
                        "error": None
                        if ok
                        else "Model reload failed after settings change",
                    },
                },
            )

        except Exception as e:
            self._logger.error(f"[LocalModel] apply_inference_settings error: {e}")
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "inference_settings_result",
                    "payload": {"status": "error", "error": str(e)},
                },
            )

    async def _handle_get_local_model_status(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """Return current load status of the GGUF server."""
        from .agent.local_model_manager import get_local_model_manager

        try:
            mgr = get_local_model_manager()
            status = mgr.get_status()
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "local_model_status",
                    "payload": status,
                },
            )
        except Exception as e:
            self._logger.error(f"[LocalModel] get_status error: {e}")

    async def _handle_get_hardware_info(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """Return GPU/VRAM/RAM hardware info."""
        from .agent.local_model_manager import get_local_model_manager

        try:
            mgr = get_local_model_manager()
            loop = __import__("asyncio").get_event_loop()
            hw = await loop.run_in_executor(None, mgr.get_hardware_info)
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "hardware_info",
                    "payload": hw,
                },
            )
        except Exception as e:
            self._logger.error(f"[LocalModel] get_hardware_info error: {e}")

    # â”€â”€ Swarm Action Handler â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    async def _handle_swarm_action(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """Handle start_swarm / stop_swarm / swarm_action messages from card buttons."""
        action = message.get("type", "")
        # Normalise â€” cards send "start_swarm" / "stop_swarm" directly
        if action == "swarm_action":
            action = message.get("action", "")
        payload = message.get("payload", {})

        try:
            from .agent.swarm_inference_manager import SwarmInferenceManager

            mgr = SwarmInferenceManager()
            cfg = load_config()

            if action == "start_swarm":
                self._logger.info(
                    f"[Session: {session_id}] Starting swarm (mode={cfg.inference.swarm_mode})"
                )
                await mgr.start_swarm(
                    director_model=cfg.inference.reasoning_model,
                    worker_count=cfg.inference.swarm_worker_count,
                    mode=cfg.inference.swarm_mode,
                )
                cfg.inference.swarm_enabled = True
                save_config(cfg)
                # Notify dashboard
                await self._broadcast_json(
                    {
                        "type": "swarm_status",
                        "title": "Swarm Started",
                        "message": f"Swarm active â€” {cfg.inference.swarm_worker_count} workers",
                        "progress": 100,
                        "status": "active",
                    }
                )

            elif action == "stop_swarm":
                self._logger.info(f"[Session: {session_id}] Stopping swarm")
                await mgr.stop_swarm()
                cfg.inference.swarm_enabled = False
                save_config(cfg)
                await self._broadcast_json(
                    {
                        "type": "swarm_status",
                        "title": "Swarm Stopped",
                        "message": "All swarm workers terminated",
                        "status": "inactive",
                    }
                )

            else:
                self._logger.warning(
                    f"[Session: {session_id}] Unknown swarm action: {action}"
                )

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Swarm action failed: {e}", exc_info=True
            )
            await self._send_json(
                client_id,
                {
                    "type": "swarm_status",
                    "title": "Swarm Error",
                    "message": str(e),
                    "status": "error",
                },
            )

    # â”€â”€ Local Model Load/Unload Handlers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    async def _handle_load_local_model(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """Load a local GGUF model via the LocalModelManager."""
        try:
            from .agent.local_model_manager import get_local_model_manager

            cfg = load_config()
            model_path = cfg.inference.local_model_path
            if not model_path:
                await self._send_json(
                    client_id,
                    {
                        "type": "model_load_progress",
                        "title": "Model Load Error",
                        "message": "No model selected. Choose a model first.",
                        "status": "error",
                        "progress": 0,
                    },
                )
                return

            mgr = get_local_model_manager()
            self._logger.info(
                f"[Session: {session_id}] Loading local model: {model_path}"
            )
            await self._broadcast_json(
                {
                    "type": "model_load_progress",
                    "title": "Loading Model",
                    "message": f"Loading {model_path}...",
                    "progress": 10,
                    "status": "loading",
                }
            )

            await mgr.load_model(
                model_path=model_path,
                gpu_layers=cfg.inference.local_model_gpu_layers,
                context_length=cfg.inference.local_model_ctx,
                hardware_profile=cfg.inference.local_model_profile,
            )

            cfg.inference.local_model_status = "loaded"
            save_config(cfg)

            await self._broadcast_json(
                {
                    "type": "model_load_progress",
                    "title": "Model Loaded",
                    "message": f"{model_path} ready",
                    "progress": 100,
                    "status": "loaded",
                }
            )
            self._logger.info(
                f"[Session: {session_id}] Local model loaded: {model_path}"
            )

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Failed to load local model: {e}",
                exc_info=True,
            )
            cfg = load_config()
            cfg.inference.local_model_status = "error"
            save_config(cfg)
            await self._broadcast_json(
                {
                    "type": "model_load_progress",
                    "title": "Model Load Error",
                    "message": str(e),
                    "status": "error",
                    "progress": 0,
                }
            )

    async def _handle_unload_local_model(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """Unload the currently loaded local GGUF model."""
        try:
            from .agent.local_model_manager import get_local_model_manager

            mgr = get_local_model_manager()
            self._logger.info(f"[Session: {session_id}] Unloading local model")
            await mgr.unload_model()

            cfg = load_config()
            cfg.inference.local_model_status = "unloaded"
            save_config(cfg)

            await self._broadcast_json(
                {
                    "type": "model_load_progress",
                    "title": "Model Unloaded",
                    "message": "Local model unloaded successfully",
                    "progress": 0,
                    "status": "unloaded",
                }
            )
            self._logger.info(f"[Session: {session_id}] Local model unloaded")

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Failed to unload local model: {e}",
                exc_info=True,
            )
            await self._broadcast_json(
                {
                    "type": "model_load_progress",
                    "title": "Unload Error",
                    "message": str(e),
                    "status": "error",
                    "progress": 0,
                }
            )

    async def _handle_download_gguf_model(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """Stream HuggingFace GGUF download progress to client."""
        from .agent.local_model_manager import get_local_model_manager

        payload = message.get("payload", message)
        repo_id = payload.get("repo_id", "")
        filename = payload.get("filename", "")

        if not repo_id or not filename:
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "gguf_download_progress",
                    "payload": {
                        "status": "error",
                        "error": "repo_id and filename required",
                    },
                },
            )
            return

        mgr = get_local_model_manager()
        try:
            async for progress in mgr.download_model(repo_id, filename):
                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "gguf_download_progress",
                        "payload": {
                            **progress,
                            "repo_id": repo_id,
                            "filename": filename,
                        },
                    },
                )
                if progress.get("status") == "complete":
                    # Refresh installed models list
                    await self._handle_get_local_models(session_id, client_id, {})
        except Exception as e:
            self._logger.error(f"[LocalModel] download error: {e}")
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "gguf_download_progress",
                    "payload": {
                        "status": "error",
                        "error": str(e),
                        "repo_id": repo_id,
                        "filename": filename,
                    },
                },
            )

    async def _handle_search_hf_models(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
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
                r = await hf_client.get(
                    "https://huggingface.co/api/models", params=params
                )
                models = r.json() if r.status_code == 200 else []
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "hf_models_list",
                    "payload": {"models": models, "query": query},
                },
            )
        except Exception as e:
            self._logger.warning(f"[HFSearch] search failed: {e}")
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "hf_models_list",
                    "payload": {"models": [], "query": query, "error": str(e)},
                },
            )

    async def _handle_set_vision_enabled(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """Start or stop the LFM2.5-VL llama-server subprocess on vision_port."""
        payload = message.get("payload", message)
        enabled = bool(payload.get("enabled", False))
        try:
            from .tools.lfm_vl_provider import get_lfm_vl_provider

            vl = get_lfm_vl_provider()
            if enabled:
                # Start vision server if not already running
                running = (
                    await vl.health_check() if hasattr(vl, "health_check") else False
                )
                status = "running" if running else "not_started"
            else:
                # Signal the provider that vision is disabled
                if hasattr(vl, "disable"):
                    vl.disable()
                status = "stopped"
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "vision_status",
                    "payload": {
                        "enabled": enabled,
                        "running": enabled,
                        "port": _VISION_PORT,
                        "status": status,
                    },
                },
            )
        except Exception as e:
            self._logger.warning(f"[Vision] set_vision_enabled error: {e}")
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "vision_status",
                    "payload": {
                        "enabled": enabled,
                        "running": False,
                        "port": _VISION_PORT,
                        "error": str(e),
                    },
                },
            )

    async def _handle_toggle_model_pin(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """Toggle pin/favorite state for a local GGUF model."""
        from .agent.local_model_manager import get_local_model_manager

        payload = message.get("payload", message)
        filename = payload.get("filename", "")
        if not filename:
            return
        try:
            mgr = get_local_model_manager()
            new_pin = mgr.toggle_pin(filename)
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "model_pin_updated",
                    "payload": {"filename": filename, "pinned": new_pin},
                },
            )
        except Exception as e:
            self._logger.error(f"[LocalModel] toggle_pin error: {e}")

    # â”€â”€ Crawler handler â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def _handle_crawler_query(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """
        Handle a crawler_query message.
        Payload: { query: str }
        Flow:
          1. Plan URLs + extraction instructions via CrawlPlanner (LLM)
          2. Emit crawler_started WS event
          3. Crawl pages via CrawlerEngine (Crawl4AI), emitting crawler_page_fetched per page
          4. Extract structured DashboardData via DataExtractor (LLM)
          5. Emit open_tab WS event with DashboardData
          6. Emit text_response with one-liner summary
        """
        import uuid
        from .crawler.crawler_engine import CrawlerEngine, CrawlerUnavailable
        from .crawler.crawl_planner import get_crawl_planner
        from .crawler.data_extractor import get_data_extractor

        payload = message.get("payload", message)
        query: str = payload.get("query", "").strip()

        if not query:
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "text_response",
                    "turn_id": get_turn_id(),
                    "text": "No query provided for web research.",
                    "sender": "assistant",
                },
            )
            return

        async def send(msg: dict) -> None:
            await self._ws_manager.send_to_client(client_id, msg)

        # Step 1: Plan
        try:
            plan = await get_crawl_planner().plan(query)
        except Exception as exc:
            self._logger.error("[Crawler] planning failed: %s", exc)
            await send({"type": "crawler_error", "message": f"Planning failed: {exc}"})
            return

        # Step 2: Notify start
        await send(
            {
                "type": "crawler_started",
                "query": query,
                "url_count": len(plan.urls),
            }
        )

        # Step 3: Crawl
        try:
            loop = asyncio.get_running_loop()

            def _on_page(url: str, page_num: int, total: int) -> None:
                asyncio.run_coroutine_threadsafe(
                    send(
                        {
                            "type": "crawler_page_fetched",
                            "url": url,
                            "page_number": page_num,
                            "total": total,
                        }
                    ),
                    loop,
                )

            async with CrawlerEngine() as engine:
                crawl_result = await engine.crawl(
                    query=query,
                    urls=plan.urls,
                    instructions=plan.instructions,
                    on_page_done=_on_page,
                )
        except CrawlerUnavailable as exc:
            await send({"type": "crawler_error", "message": str(exc)})
            await send(
                {
                    "type": "text_response",
                    "turn_id": get_turn_id(),
                    "text": str(exc),
                    "sender": "assistant",
                }
            )
            return
        except Exception as exc:
            self._logger.error("[Crawler] crawl failed: %s", exc)
            await send({"type": "crawler_error", "message": f"Crawl failed: {exc}"})
            return

        # Step 4: Extract structured DashboardData
        try:
            dashboard_data = await get_data_extractor().extract(
                result=crawl_result,
                instructions=plan.instructions,
                result_type=plan.result_type,
                title=plan.title,
            )
        except Exception as exc:
            self._logger.error("[Crawler] extraction failed: %s", exc)
            await send(
                {"type": "crawler_error", "message": f"Extraction failed: {exc}"}
            )
            return

        # Step 5: Open dashboard tab in wing
        tab_id = str(uuid.uuid4())
        await send(
            {
                "type": "open_tab",
                "tab_type": "dashboard",
                "id": tab_id,
                "title": plan.title,
                "data": dashboard_data,
            }
        )

        # Step 6: Summary text response in ChatView
        page_count = len(crawl_result.pages)
        summary = dashboard_data.get("summary", "")
        await send(
            {
                "type": "text_response",
                "turn_id": get_turn_id(),
                "text": (
                    f"{summary or f'Found results for: {query}'} â€” see Dashboard â†’"
                ),
                "sender": "assistant",
            }
        )

    # â”€â”€ Developer Mode CLI handlers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def _handle_dev_cli(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """
        Route a dev_cli message to the DevOrchestrator.
        Payload: { query: str, workdir: str, tool_hint?: str }
        """
        # [13.3] Capability gate â€” terminal requires developer mode
        from backend.capabilities import CapabilitySet

        try:
            CapabilitySet.require(CapabilitySet.TERMINAL)
        except PermissionError as exc:
            self._logger.warning("[13.3] dev_cli blocked: %s", exc)
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "text_response",
                    "turn_id": get_turn_id(),
                    "text": "Developer CLI is only available in developer mode.",
                    "sender": "assistant",
                },
            )
            return

        from .dev.orchestrator import get_dev_orchestrator  # lazy import

        payload = message.get("payload", message)

        async def _ws_send(msg: dict) -> None:
            await self._ws_manager.send_to_client(client_id, msg)

        orchestrator = get_dev_orchestrator()
        try:
            await orchestrator.handle_dev_cli(session_id, payload, _ws_send)
        except Exception as exc:
            self._logger.error("[DevCLI][%s] error: %s", session_id, exc)
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "text_response",
                    "turn_id": get_turn_id(),
                    "text": f"Developer CLI error: {exc}",
                    "sender": "assistant",
                },
            )

    async def _handle_dev_abort(self, session_id: str, client_id: str) -> None:
        """Abort the active CLI subprocess for this session."""
        # [13.3] Capability gate â€” terminal requires developer mode
        from backend.capabilities import CapabilitySet

        try:
            CapabilitySet.require(CapabilitySet.TERMINAL)
        except PermissionError as exc:
            self._logger.warning("[13.3] dev_abort blocked: %s", exc)
            return

        from .dev.orchestrator import get_dev_orchestrator  # lazy import

        orchestrator = get_dev_orchestrator()
        await orchestrator.abort_session(session_id)
        await self._ws_manager.send_to_client(
            client_id,
            {
                "type": "text_response",
                "turn_id": get_turn_id(),
                "text": "CLI process aborted.",
                "sender": "assistant",
            },
        )

    async def _handle_terminal_input(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """
        Route a terminal_input message to TerminalHandler for direct shell access.
        Domain 13.4 â€” developer mode only, security-filtered.
        """
        from backend.capabilities import CapabilitySet

        try:
            CapabilitySet.require(CapabilitySet.TERMINAL)
        except PermissionError as exc:
            self._logger.warning("[13.4] terminal_input blocked: %s", exc)
            await self._send_error(
                client_id, "Terminal only available in developer mode"
            )
            return

        try:
            from .dev.terminal_handler import get_terminal_handler  # type: ignore[import-not-found]

            payload = message.get("payload", message)
            line = payload.get("line", "")

            async def _ws_send(msg_dict: dict):
                await self._ws_manager.send_to_client(client_id, msg_dict)

            handler = get_terminal_handler()
            await handler.handle_input(session_id, line, _ws_send)
        except Exception as exc:
            self._logger.exception("[13.4] terminal_input error: %s", exc)
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "text_response",
                    "turn_id": get_turn_id(),
                    "payload": {
                        "text": f"Terminal error: {exc}",
                        "sender": "assistant",
                    },
                },
            )

    async def shutdown(self) -> None:
        """Shutdown the gateway and cancel background tasks."""
        if self._session_gc_task:
            self._session_gc_task.cancel()
            try:
                await self._session_gc_task
            except asyncio.CancelledError:
                pass
            self._logger.info("[IRISGateway] Session GC task cancelled.")
        # Cancel any remaining research tasks
        for task in list(self._research_tasks):
            task.cancel()
        if self._research_tasks:
            self._logger.info(
                f"[IRISGateway] Cancelled {len(self._research_tasks)} research tasks."
            )


# Global instance
_iris_gateway: Optional[IRISGateway] = None


def get_iris_gateway() -> IRISGateway:
    """Get or create the singleton IRISGateway."""
    global _iris_gateway
    if _iris_gateway is None:
        _iris_gateway = IRISGateway()
    return _iris_gateway