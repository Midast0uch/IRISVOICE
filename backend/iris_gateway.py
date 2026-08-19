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
from .agent import get_agent_kernel, get_active_kernel, set_active_conversation
from .agent.conversation_context_store import get_context_store
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
from backend.utils.ssl_context import get_ssl_context
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Union, Iterator, Callable
from backend.utils.observability import get_turn_id, loud_error

# ---------------------------------------------------------------------------
# REQ-8 AC2 (T26): spoken-text normalization for the streaming TTS path.
#
# The sentence-flush point feeds the TTS engine directly. Raw model output may
# contain markdown/code that must not be read aloud. This helper produces the
# companion-style spoken form (REQ-8 AC2 edge case: truncated spoken text while
# the FULL text remains in the chat display — the display path is untouched).
# It is intentionally permissive: any failure returns the ORIGINAL text so a
# flush is never dropped silently.
# ---------------------------------------------------------------------------


def _normalize_spoken_sentence(text: str) -> str:
    """Companion-style normalization for one flushed TTS sentence.

    Strips code fences/inline code/markdown headers/bullets and runs the speech
    normalizer (URLs, paths, symbols -> spoken form). Returns the original text
    unchanged if normalization fails, so the TTS queue never goes silent.
    """
    if not text:
        return text
    try:
        import re as _re

        _cleaned = _re.sub(r"```[\s\S]*?```", "", text)
        _cleaned = _re.sub(r"`[^`]+`", "", _cleaned)
        _cleaned = _re.sub(r"^#{1,6}\s+", "", _cleaned, flags=_re.MULTILINE)
        _cleaned = _re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", _cleaned)
        _cleaned = _re.sub(r"^\s*[-*•]\s+", "", _cleaned, flags=_re.MULTILINE)
        from backend.voice.tts_normalizer import normalize_for_speech

        _spoken = normalize_for_speech(_cleaned)
        return _spoken if _spoken.strip() else text
    except Exception:
        # Never drop a flush — degrade to the raw sentence.
        return text


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
        # REQ-8 AC5: wire the reconnect-replacement hook so a stale socket's
        # in-flight DER loop is soft-cancelled when a new socket replaces it
        # (e.g. flipping localhost -> Tailscale mid-response). The incoming
        # sync_state re-binds / cancels as needed (T19/T20).
        try:
            self._ws_manager.on_client_replace = self._on_client_replace
        except Exception:
            pass
        self._logger = logging.getLogger(__name__)

        # Bus -> WebSocket bridge: delivers task/question/permission/context
        # events to the frontend. Started here; main loop captured in
        # set_main_loop() (called from main.py lifespan startup).
        from .agent.ws_event_bridge import WSEventBridge
        self._ws_bridge = WSEventBridge(self._ws_manager)
        self._ws_bridge.start()

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

        # Tier-3 (VL fallback) vision provider — connects to the dedicated
        # LFM2.5-VL llama-server on vision_port. T16: this is no longer the
        # ONLY vision path; `_resolve_vision_availability` below checks the
        # full hierarchy (brain -> tool -> this fallback) first, and only
        # falls through to health-checking THIS server when tier 1/2 cannot
        # see. Kept here unchanged as the tier-3 default (CT-3's lifecycle).
        self._vision_provider = LFMVLProvider()
        self._logger.info(
            "[IRISGateway] Vision provider initialized (LFM2.5-VL @ http://localhost:%d/v1)",
            _VISION_PORT,
        )

        # Initialize model cache for lazy loading (5 minute TTL)
        # Entries are purged by _purge_model_cache() called on every lookup
        self._model_cache: Dict[str, tuple[List[str], datetime]] = {}
        self._model_cache_ttl = timedelta(minutes=5)
        self._logger.info("[IRISGateway] Model cache initialized (5 min TTL)")
        self._tts_prewarmed = False
        self._main_loop = None
        self._speech_interrupted = False

        # Word monitor thread from previous TTS — stored on self so the next
        # _speak_response call can join it before starting a new one.
        self._word_monitor_thread: Optional[threading.Thread] = None
        # Instance-level stop event — shared across _speak_response calls.
        # When a new response starts, it sets this event to kill the old monitor,
        # then creates a fresh Event for the new monitor.
        self._word_monitor_stop: Optional[threading.Event] = None

        self._voice_handler = None  # set via set_voice_handler() after construction
        # session_id -> client_id for wake word routing
        self._active_voice_client: dict = {}
        self._active_conversation_id: dict = {}
        # Track which session is currently playing TTS â€” used by the barge-in
        # handler to know which conversation to resume on interruption.
        self._active_tts_session: Optional[str] = None
        # Barge-in stop event: set by _on_barge_in_detected to stop cadence
        # threads immediately when user speech is detected over TTS playback.
        # Created per-session by _speak_response / _handle_tts_play.
        self._barge_in_stop: Optional[threading.Event] = None
        # Sessions currently in conversation mode (auto-relisten after TTS)
        self._conversation_sessions: set = set()
        # Sessions in low-power "sleep" listen: VAD/recording/ASR released but
        # the wake word (Porcupine) stays armed.  Auto-relisten is suppressed
        # for these sessions until a wake word clears them (see _handle_voice).
        self._sleeping_sessions: set = set()
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
        self._ws_bridge.set_main_loop(loop)
        self._logger.info("[IRISGateway] Main event loop captured.")
        # Start session GC task
        if self._session_gc_task is None:
            self._session_gc_task = asyncio.create_task(self._session_gc_loop())
            self._logger.info("[IRISGateway] Session GC task started.")

        if not self._tts_prewarmed:
            pass  # Pocket-TTS loads in ~1s â€” no startup prewarm

        # Re-discover a local model that was loaded in a previous backend run.
        # The llama-server subprocess can outlive a backend restart, and config
        # keeps local_model_status="loaded", but the in-memory router registration
        # is lost on restart -> the local provider never reappears in the
        # Brain/Tool dropdowns. Probe the server and re-register if reachable.
        try:
            loop.create_task(self._hydrate_local_provider_on_startup())
        except Exception as e:  # never block startup on this
            self._logger.warning(f"[IRISGateway] local hydrate schedule failed: {e}")

        # Pre-warm the shared embedding encoder at boot, OFF the event loop, so
        # the first DER verification never pays a 2-4 minute cold model load
        # (previously a second AutoModel copy was loaded inline — blocking the
        # loop). SemanticVerifier reuses this same encoder (dedupe, 2026-08-12);
        # while it loads, verification falls back to graded F1 (REQ-4 AC4).
        try:
            loop.create_task(self._prewarm_embedding_encoder())
            self._logger.info("[IRISGateway] Embedding encoder pre-warm scheduled.")
        except Exception as e:  # never block startup on this
            self._logger.warning(f"[IRISGateway] embedding pre-warm schedule failed: {e}")

    async def _prewarm_embedding_encoder(self) -> None:
        """Load the shared EmbeddingService encoder in a background thread at boot.

        The EmbeddingService load is already bounded by IRIS_EMBEDDING_LOAD_TIMEOUT_S
        and runs in a daemon thread (Defect 1); ``asyncio.to_thread`` additionally
        keeps even the bounded wait off the event loop. Failure is non-fatal: the
        verifier falls back to graded F1 (REQ-4 AC4) until the encoder is available.
        """
        try:
            from backend.memory.embedding import get_embedding_service

            svc = get_embedding_service()
            if getattr(svc, "_backend", None) != "hash":
                self._logger.info(
                    "[IRISGateway] embedding encoder already loaded (backend=%s)",
                    getattr(svc, "_backend", "?"),
                )
                return
            t0 = time.monotonic()
            # encode_with_meta("") triggers _load_active_backend (lazy, latched,
            # bounded) without doing real inference work.
            await asyncio.to_thread(svc.encode_with_meta, "")
            self._logger.info(
                "[IRISGateway] embedding encoder pre-warmed in %.1fs (backend=%s)",
                time.monotonic() - t0,
                getattr(svc, "_backend", "?"),
            )
        except Exception as exc:
            self._logger.warning(f"[IRISGateway] embedding encoder pre-warm failed: {exc}")

    async def _broadcast_inference_snapshot(
        self, session_id: Optional[str], router: Any = None
    ) -> None:
        """Re-emit the FULL inference snapshot to the frontend.

        Every surface that shows a model (chat-row ModelSwitcher, the dashboard
        Model & Inference card, the wheel-view SidePanel) reads one hook,
        ``useInferenceState``. Any code path that mutates the provider registry
        or the role bindings must call this, or those surfaces keep rendering
        the pre-change state until the next periodic ``system_status`` — which
        is what made a load/unload look like it had not happened.

        Never raises: a broadcast failure must not fail the operation that
        triggered it.
        """
        try:
            from backend.agent.inference.snapshot import build_inference_snapshot

            _r = router
            if _r is None:
                from .agent import get_agent_kernel

                _r = getattr(get_agent_kernel(session_id or "session_iris"), "_router", None)
            _snap = build_inference_snapshot(_r)
            _msg = {"type": "role_bindings_updated", "payload": _snap}
            if session_id:
                await self._ws_manager.broadcast_to_session(session_id, _msg)
            else:
                await self._ws_manager.broadcast(_msg)
        except Exception as exc:
            self._logger.warning(
                "[IRISGateway] inference snapshot broadcast failed: %s", exc
            )

    async def _hydrate_local_provider_on_startup(self) -> None:
        """Re-register the 'local' provider after a backend restart.

        Triggered only when config says a local model is loaded AND the local
        inference server is actually reachable. Registers into every peer kernel
        (same as the live load path) and emits provider_added so the frontend
        dropdown populates without the user re-loading.
        """
        try:
            from .iris_config import load_config as _lc
            from backend.agent.local_model_manager import (
                get_local_model_manager,
                LocalModelManager,
            )
            from backend.agent.inference.provider import (
                ProviderInstance,
                ProviderKind,
            )
            from pathlib import Path as _Path

            _cfg = _lc()
            # local_model_status/local_model_path live on cfg.inference (see
            # InferenceConfig in iris_config.py) — reading them off the ROOT
            # config always returned None, so this whole hydrate returned early
            # and a local model loaded before a backend restart never came back
            # into the dropdowns. Root falls back for older configs.
            _infer_cfg = getattr(_cfg, "inference", None)
            _status = getattr(_infer_cfg, "local_model_status", None) or getattr(
                _cfg, "local_model_status", None
            )
            if _status != "loaded":
                return
            _mgr = get_local_model_manager()
            _endpoint = getattr(_mgr, "ENDPOINT", "http://127.0.0.1:8091/v1")
            # Probe the server (manager.is_loaded() is False after restart because
            # it tracks the subprocess it launched, which is gone).
            try:
                async with httpx.AsyncClient(timeout=3.0) as _c:
                    _r = await _c.get(_endpoint.rstrip("/") + "/models")
                if _r.status_code >= 400:
                    self._logger.info(
                        f"[LocalHydrate] server at {_endpoint} responded "
                        f"{_r.status_code} — skipping re-register"
                    )
                    return
            except Exception as _e:
                self._logger.info(
                    f"[LocalHydrate] local server not reachable ({_e}) — skipping"
                )
                return

            _model_path = (
                getattr(_infer_cfg, "local_model_path", None)
                or getattr(_cfg, "local_model_path", None)
                or (_cfg.field_values or {}).get("iris_local_model_path")
                or getattr(_mgr, "_current_model_path", None)
            )
            _model_name = (
                _Path(_model_path).stem if _model_path else "local-model"
            )
            _inproc = getattr(_mgr, "_llm", None) is not None
            _local_inst = ProviderInstance(
                # Namespaced id (REQ-4 AC1) and the SAME id the live load path
                # registers, so a restart re-hydrates the entry the role
                # bindings already point at instead of a second, bare "local"
                # entry that nothing is bound to.
                id=f"local:{_model_name}",
                label=f"Local: {_Path(_model_path).name if _model_path else _model_name}",
                kind=(
                    ProviderKind.INPROCESS if _inproc else ProviderKind.LOCAL_OPENAI
                ),
                model=_model_name,
                api_base_url="" if _inproc else _endpoint,
                # The server answered /models above — it IS loaded. Without this
                # the ModelSwitcher's `loaded` filter drops it on sight.
                loaded=True,
            )
            _kernels = [self] + [
                pk for pk in _agent_kernel_instances.values() if pk is not self
            ]
            for _kr in _kernels:
                _r = getattr(_kr, "_router", None)
                if _r is None:
                    continue
                _r.add_provider(_local_inst)
                if _inproc:
                    _r.set_inprocess_manager(_mgr)
            self._logger.info(
                f"[LocalHydrate] re-registered local provider '{_local_inst.id}' "
                f"(kind={_local_inst.kind.value}) across {len(_kernels)} kernel(s)"
            )
            # Notify the frontend so the dropdown populates.
            try:
                await self._ws_manager.broadcast(
                    {
                        "type": "provider_added",
                        "payload": _local_inst.to_dict(),
                    }
                )
                await self._broadcast_inference_snapshot(None)
            except Exception as _be:
                self._logger.warning(f"[LocalHydrate] broadcast failed: {_be}")
        except Exception as e:
            self._logger.warning(f"[LocalHydrate] error: {e}")

    def _touch_session(self, session_id: str) -> None:
        """Update the last-seen timestamp for a session."""
        self._session_last_seen[session_id] = time.monotonic()
        # Keep the recency pointer current so the wake-word handler can bind to the
        # user's most recently active conversation thread (REQ-1/REQ-2). Guarded so a
        # missing SessionManager attribute can never break the hot path.
        try:
            mgr = getattr(self, "_session_manager", None)
            if mgr is not None and hasattr(mgr, "_mark_active"):
                mgr._mark_active(session_id)
        except Exception:
            pass

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

            elif msg_type == "set_role_binding":
                await self._handle_set_role_binding(session_id, client_id, message)

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

            elif msg_type in ["text_message", "clear_chat", "new_conversation", "switch_conversation"]:
                await self._handle_chat(session_id, client_id, message)

            elif msg_type == "sync_state":
                # Phase 4.3: frontend sends this on WS reconnect (and on thread
                # resume) so the backend re-attaches the correct per-thread
                # kernel and restores its persisted context.  Without it a
                # reconnect would silently bind to the session kernel and leak
                # the wrong conversation's history into the resumed thread.
                await self._handle_sync_state(session_id, client_id, message)

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

            elif msg_type == "reformat_document":
                await self._handle_reformat_document(session_id, client_id, message)

            elif msg_type == "get_documents":
                await self._handle_get_documents(session_id, client_id, message)

            elif msg_type == "get_cards":
                await self._handle_get_cards(session_id, client_id, message)

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

            elif msg_type == "set_web_mode":
                # Frontend web-search toggle.  This is an internet-access
                # capability gate (app-wide), NOT a routing switch.  When ON,
                # the agent kernel is granted web tools (search / crawler_query)
                # and decides when to use them.  When OFF, the agent has zero
                # internet tools.  See plan Issue E.
                enabled = bool(message.get("payload", {}).get("enabled", False))
                from .agent.agent_kernel import set_global_internet_access
                set_global_internet_access(enabled)
                self._logger.info(
                    f"[WebMode] session={session_id} web_mode={enabled} "
                    f"(global internet access {'ON' if enabled else 'OFF'})"
                )

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

                # REQ-7: persist the Exa API key to .env when saved from settings.
                if field_id == "exa_api_key" and value:
                    try:
                        from pathlib import Path

                        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
                        current = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
                        if "EXA_API_KEY=" in current:
                            # Update existing line
                            lines = current.splitlines()
                            new_lines = []
                            found = False
                            for line in lines:
                                if line.startswith("EXA_API_KEY="):
                                    new_lines.append(f"EXA_API_KEY={value}")
                                    found = True
                                else:
                                    new_lines.append(line)
                            if not found:
                                new_lines.append(f"EXA_API_KEY={value}")
                            env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                        else:
                            with open(env_path, "a", encoding="utf-8") as f:
                                f.write(f"\nEXA_API_KEY={value}\n")
                        # Set the process env immediately — get_search_provider()
                        # resolves os.environ.get("EXA_API_KEY") first (search_
                        # providers/__init__.py), so without this the key only
                        # took effect after a full backend restart even though
                        # it was already written to .env and the cache cleared.
                        os.environ["EXA_API_KEY"] = value

                        # Clear the cached provider so it picks up the new key.
                        from backend.crawler.search_providers import clear_search_provider_cache

                        clear_search_provider_cache()
                        logger.info("[SearchConfig] Exa API key saved to .env and applied to process env")
                    except Exception as exc:
                        logger.warning("[SearchConfig] failed to save Exa key to .env: %s", exc)

                # Clear provider cache when provider selection changes.
                if field_id == "provider" and value:
                    from backend.crawler.search_providers import clear_search_provider_cache
                    clear_search_provider_cache()
                    logger.info("[SearchConfig] Search provider changed to %r", value)

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

            # Apply desktop_control card values when that section is confirmed.
            # This is the ONLY place the desktop-control gate is flipped — without
            # it the agent can launch the user's real browser/apps even when the
            # card says disabled.  OFF by default (see agent_kernel flag default).
            elif section_id == "desktop_control" and values:
                try:
                    from .agent.agent_kernel import set_desktop_control_enabled

                    enabled = bool(values.get("desktop_control_enabled", False))
                    set_desktop_control_enabled(enabled)
                    self._logger.info(
                        f"[Session: {session_id}] Desktop control "
                        f"{'enabled' if enabled else 'disabled'}",
                        extra={"session_id": session_id, "client_id": client_id},
                    )
                except Exception as dc_e:
                    self._logger.error(
                        f"[Session: {session_id}] Error applying desktop_control: {dc_e}",
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
                            # SLICE 5: route kernel inference through the router
                            # (replaces configure_openai_compat) for BOTH modes
                            await self._route_kernel_to_swarm(kernel, session_id, cfg)
                            # Store manager reference on kernel for status queries
                            if hasattr(kernel, "_swarm_inference_mgr"):
                                kernel._swarm_inference_mgr = mgr
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
            # Both the wheelview models-card (model_selection) and the Dashboard
            # Model & Inference card (model_inference) carry the SAME logical
            # payload (provider + reasoning/tool models). Handle both so the
            # Dashboard's selection is never silently dropped.
            elif section_id in ("model_selection", "model_inference") and values:
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

                    # The provider base URL is resolved from the canonical preset
                    # table AFTER the effective provider is known (see the
                    # get_provider_default_endpoint resolution below). The inline
                    # if/elif chain that used to live here drifted from that
                    # table and silently resolved "" for every provider it
                    # forgot (ollama, venice, openai, …).

                    # ── Canonical resolution ───────────────────────────────────
                    # The card's EXPLICIT model_provider is the user's dropdown
                    # choice and WINS; the role bindings (set by Brain/Tool
                    # dropdowns / ModelSwitcher / wheelview provider change via
                    # set_role_binding) are the fallback only when the card names
                    # no provider. Treating the binding as authoritative made
                    # _effective_provider resolve to the OLD provider when the
                    # user switched (2026-08-15 13:40:32,
                    # backend-20260815-134032.log: binding=cerebras, card=ollama
                    # → the ollama selection was discarded and the UI reverted).
                    _existing = {}
                    _existing_override = {}
                    try:
                        _rt = getattr(kernel, "_router", None)
                        if _rt is not None and hasattr(_rt, "_roles"):
                            for _b in _rt._roles.list():
                                _existing[_b.role] = _b.instance_id
                                _existing_override[_b.role] = _b.model_override
                    except Exception:
                        _existing = {}
                        _existing_override = {}
                    _effective_provider = provider or _existing.get("reasoning")
                    _card_names_provider = bool(provider)

                    # A model name only means anything ALONGSIDE the provider it
                    # was chosen for. The card's models start as candidates; a
                    # ROLE BINDING only supersedes them when it serves the
                    # effective provider — either because the card names no
                    # provider (the binding IS the choice) or because the card
                    # names the SAME provider the binding already serves.
                    # Without that guard, a binding left on the previous
                    # provider stamps its model onto the freshly selected one —
                    # "gemma-4-31b" (Cerebras) worn by Cohere (root-caused
                    # 2026-08-13 from backend-20260813-074742.log).
                    # set_model_selection's catalog check below is the second
                    # line of defence for hosted API providers.
                    _effective_reasoning = reasoning
                    _effective_tool = tool_exec

                    # Canonical model source, in order: the ROLE BINDING's own
                    # model_override (which is where an override actually lives —
                    # ProviderInstance has no `model_override` attribute, so the
                    # previous getattr() on the resolved instance was always
                    # None and silently fell through to the card value), then the
                    # bound provider instance's registered model.
                    try:
                        _rp = kernel._router.resolve("reasoning") if _existing.get("reasoning") else None
                        _tp = kernel._router.resolve("tool_execution") if _existing.get("tool_execution") else None
                        if _rp is not None and (
                            not _card_names_provider
                            or _existing.get("reasoning") == _effective_provider
                        ):
                            _effective_reasoning = (
                                _existing_override.get("reasoning")
                                or getattr(_rp, "model", None)
                                or _effective_reasoning
                            )
                        if _tp is not None and (
                            not _card_names_provider
                            or _existing.get("tool_execution") == _effective_provider
                        ):
                            _effective_tool = (
                                _existing_override.get("tool_execution")
                                or getattr(_tp, "model", None)
                                or _effective_tool
                            )
                    except Exception:
                        pass

                    # Last resort: a provider with no resolvable model gets its
                    # OWN catalog default, never a leftover from another one.
                    if not _effective_reasoning:
                        from backend.agent.inference.provider_catalog import (
                            get_default_model_for_provider,
                        )

                        _effective_reasoning = get_default_model_for_provider(
                            _effective_provider
                        )
                    if not _effective_tool:
                        _effective_tool = _effective_reasoning
                    # Resolve the provider base URL so the router instance carries
                    # the correct endpoint (not the previously configured one).
                    # Single source of truth: PROVIDER_PRESETS via
                    # get_provider_default_endpoint — an inline if/elif chain
                    # here forgot ollama (and venice/openai/…), registering
                    # those providers with an empty endpoint.
                    if _effective_provider == "lmstudio":
                        _api_base_url = (
                            values.get("lmstudio_endpoint", _DEFAULT_LMSTUDIO_URL)
                            or _DEFAULT_LMSTUDIO_URL
                        )
                    elif _effective_provider == "ollama":
                        _api_base_url = (
                            values.get("ollama_endpoint", _DEFAULT_OLLAMA_URL)
                            or _DEFAULT_OLLAMA_URL
                        )
                    else:
                        from backend.agent.inference.provider import (
                            get_provider_default_endpoint,
                        )

                        _api_base_url = (
                            get_provider_default_endpoint(_effective_provider) or ""
                        )

                    # Register the provider + apply the EFFECTIVE (canonical) model
                    # names. preserve_bindings=True: never rebind existing roles.
                    kernel.set_model_selection(
                        reasoning_model=_effective_reasoning,
                        tool_execution_model=_effective_tool,
                        model_provider=_effective_provider,
                        api_base_url=_api_base_url,
                        preserve_bindings=True,
                    )

                    # Bind roles that are not already bound — and REBIND both
                    # roles when the card names an explicit provider the
                    # reasoning binding does not serve. The card's provider is
                    # then a SWITCH (the user changed the Provider dropdown):
                    # generate() resolves each role THROUGH its binding, so a
                    # binding left on the previous provider keeps serving it and
                    # every surface (switcher, dashboard, router) reverts to the
                    # old provider (2026-08-15, backend-20260815-134032.log:
                    # cerebras → ollama reverted because preserve_bindings kept
                    # reasoning=cerebras). A card that echoes the reasoning
                    # binding (the global APPLY re-sending the synced provider)
                    # rebinds nothing, so a Brain/Tool split across providers
                    # survives an unrelated APPLY.
                    _provider_switch = bool(provider) and _existing.get("reasoning") not in (
                        None,
                        _effective_provider,
                    )
                    _bound_any = False
                    if _provider_switch or not _existing.get("reasoning"):
                        kernel.set_role_binding(
                            "reasoning", _effective_provider, model_override=_effective_reasoning
                        )
                        _bound_any = True
                    if _provider_switch or not _existing.get("tool_execution"):
                        kernel.set_role_binding(
                            "tool_execution", _effective_provider, model_override=_effective_tool
                        )
                        _bound_any = True
                    if _provider_switch:
                        # Make the switch visible immediately on every surface —
                        # otherwise the frontend keeps its previous snapshot
                        # until the next periodic system_status tick and the
                        # synced card value bounces back to the old provider.
                        try:
                            await self._persist_and_broadcast_role_bindings(
                                session_id, kernel
                            )
                        except Exception as _rb_err:
                            self._logger.warning(
                                f"[Session: {session_id}] Failed to broadcast "
                                f"provider switch: {_rb_err}"
                            )
                        self._logger.info(
                            f"[Session: {session_id}] Provider switch on confirm: "
                            f"rebound reasoning/tool_execution to "
                            f"provider='{_effective_provider}' "
                            f"(reasoning={_effective_reasoning}, "
                            f"tool={_effective_tool}; previous reasoning binding="
                            f"'{_existing.get('reasoning')}')",
                            extra={"session_id": session_id, "client_id": client_id},
                        )
                    elif _bound_any:
                        self._logger.info(
                            f"[Session: {session_id}] Bound unbound roles to "
                            f"provider='{_effective_provider}' (reasoning={_effective_reasoning}, "
                            f"tool={_effective_tool})",
                            extra={"session_id": session_id, "client_id": client_id},
                        )
                    else:
                        self._logger.info(
                            f"[Session: {session_id}] Preserving existing role "
                            f"bindings (reasoning={_existing.get('reasoning')}, "
                            f"tool={_existing.get('tool_execution')}) — card "
                            f"provider='{provider}' did not override them.",
                            extra={"session_id": session_id, "client_id": client_id},
                        )
                    # role_bindings are canonical, and `kernel._model_provider`
                    # now DERIVES from the reasoning binding — so context-window
                    # resolution and scheduler labels agree with actual routing
                    # without an assignment here. The assignment that used to
                    # live here could disagree with the bindings it claimed to
                    # mirror, because it ran even when the branches above had
                    # deliberately preserved a different binding.
                    self._logger.info(
                        f"[Session: {session_id}] Model selection applied on confirm: "
                        f"reasoning={_effective_reasoning}, tool={_effective_tool}, "
                        f"provider={_effective_provider}",
                        extra={"session_id": session_id, "client_id": client_id},
                    )
                    # Persist the EFFECTIVE (canonical) values back to session state
                    # so the next confirm_card from any surface carries CURRENT
                    # values — closing the stale-value propagation loop.
                    try:
                        _ssm = await self._state_manager._get_session_state_manager(
                            session_id
                        )
                        if _ssm:
                            _ssm.set_field_value(
                                "model_selection", "model_provider", _effective_provider
                            )
                            if _effective_reasoning:
                                _ssm.set_field_value(
                                    "model_selection", "reasoning_model", _effective_reasoning
                                )
                            if _effective_tool:
                                _ssm.set_field_value(
                                    "model_selection",
                                    "tool_execution_model",
                                    _effective_tool,
                                )
                    except Exception:
                        self._logger.warning(
                            "[Session: %s] Failed to persist model_selection "
                            "to session state (confirm_card)",
                            session_id,
                            exc_info=True,
                        )

                    # ─── Provider URL map ───
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

                    elif provider == "ollama":
                        # Ollama native server. The router path uses the
                        # registered instance's api_base_url; this keeps the
                        # kernel's legacy _ollama_endpoint field (read by the
                        # direct /api/chat dispatch) pointed at the same server.
                        _oll_ep = (
                            values.get("ollama_endpoint", _DEFAULT_OLLAMA_URL)
                            or _DEFAULT_OLLAMA_URL
                        )
                        kernel.configure_ollama(_oll_ep)
                        kernel.configure_vps({"enabled": False})
                        self._logger.info(
                            f"[Session: {session_id}] Ollama configured: {_oll_ep}",
                            extra={"session_id": session_id},
                        )

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
                            # Persist the EFFECTIVE (canonically resolved) values,
                            # never the raw card fields — the card may carry the
                            # previous provider's model, and persisting that
                            # re-stamps it on restart via the router's config
                            # re-apply (same class as the 2026-08-13 desync).
                            cfg.inference.provider = _effective_provider or ""
                            cfg.inference.reasoning_model = _effective_reasoning or ""
                            cfg.inference.tool_execution_model = _effective_tool or ""
                            # Base URL follows the provider id from the canonical
                            # preset table (never a stale stored value); local
                            # servers take their user-configured endpoint.
                            if _effective_provider == "lmstudio":
                                cfg.inference.api_base_url = values.get(
                                    "lmstudio_endpoint",
                    load_config().inference.lm_studio_url or "http://localhost:1234",
                                )
                            elif _effective_provider == "ollama":
                                cfg.inference.api_base_url = (
                                    values.get("ollama_endpoint", _DEFAULT_OLLAMA_URL)
                                    or _DEFAULT_OLLAMA_URL
                                )
                            elif _effective_provider in ("local", "iris_local") or str(
                                _effective_provider or ""
                            ).startswith("local:"):
                                # Local GGUF — endpoint is the in-process llama server
                                cfg.inference.api_base_url = ""
                                cfg.routing.mode = RoutingMode.SINGLE_LOCAL
                                cfg.inference.provider = "local"
                            else:
                                from backend.agent.inference.provider import (
                                    get_provider_default_endpoint,
                                )

                                _ep = get_provider_default_endpoint(_effective_provider)
                                if _ep:
                                    cfg.inference.api_base_url = _ep
                                # Only write the key when the card actually sent
                                # one. The frontend deliberately omits the key
                                # when it is already stored — writing the blank
                                # here wiped the persisted credential on every
                                # APPLY that didn't re-enter it.
                                if api_key:
                                    cfg.inference.api_key = api_key
                            # Routing: model_selection only handles API/endpoint providers.
                            # LOCAL/SWARM routing is set by inference_mode confirm_card.
                            # Ollama is its own local-server mode (aligned with
                            # _handle_set_model_selection) — not SINGLE_API.
                            if _effective_provider not in (
                                "local",
                                "iris_local",
                                "ollama",
                            ) and not str(_effective_provider or "").startswith(
                                "local:"
                            ):
                                cfg.routing.mode = RoutingMode.SINGLE_API
                                # Force swarm OFF for API providers — prevents stale
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

            # â”€â”€ Vision fallback ladder (T15b, REQ-10 AC2/AC3) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # ModelBrowserPanel sends the user's chosen order over this same
            # confirm_card channel â€” no new WS message type. `values` carries
            # a plain list of model `path` strings (the same identity
            # scan_models()/the browser already use); order = priority
            # (REQ-10 AC2). Empty list is a valid, deliberate choice â€” it
            # means AUTO (REQ-10 AC5) â€” so an empty list is persisted too,
            # not skipped.
            elif section_id == "vision_fallback_ladder" and values is not None:
                try:
                    cfg = load_config()
                    ladder = values.get("vision_fallback_ladder", [])
                    if not isinstance(ladder, list):
                        raise ValueError(
                            f"vision_fallback_ladder must be a list, got {type(ladder)}"
                        )
                    cfg.inference.vision_fallback_ladder = [
                        str(p) for p in ladder if p
                    ]
                    save_config(cfg)
                    self._logger.info(
                        f"[Session: {session_id}] Vision fallback ladder saved on "
                        f"confirm: {cfg.inference.vision_fallback_ladder}"
                    )
                except Exception as e:
                    self._logger.error(
                        f"[Session: {session_id}] Error applying vision_fallback_ladder: {e}",
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
                if section_id in (
                    "model_selection",
                    "identity",
                    "inference_mode",
                    "vision_fallback_ladder",
                ):
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

            # Bound broadcaster so agent-initiated speech (SpeakTool / fillers)
            # can drive the SAME frontend narration contract the response path
            # uses (audio_envelope + listening_state).  Wraps the WS send in the
            # main-loop coroutine, matching iris_gateway's own broadcast pattern.
            def _broadcast_narration_event(session_id: str, msg: dict) -> None:
                ws = getattr(self, "_ws_manager", None)
                loop = getattr(self, "_main_loop", None)
                if ws is None or loop is None or not loop.is_running():
                    return
                import asyncio as _asyncio

                _asyncio.run_coroutine_threadsafe(
                    ws.broadcast_to_session(session_id, msg), loop
                )

            kernel = ConversationKernel(
                voice_handler=voice_handler,
                # Use the canonical TTS singleton (get_tts_manager) so the kernel
                # shares the same TTS instance the pipeline uses. Previously this
                # passed getattr(self, "_tts_manager", None) which was always None
                # (iris_gateway never sets _tts_manager), so agent utterances were
                # silently dropped — the user never heard progress speaks / narration.
                tts_manager=get_tts_manager(),
                audio_pipeline=audio_pipeline,
                session_id_getter=lambda: getattr(self, "_caducean_session_id", None),
                broadcast_event=_broadcast_narration_event,
            )
            kernel.register_callbacks()
            set_conversation_kernel(kernel)
            # Wire the kernel to the EventBus so speak-tool Utterance events reach
            # local TTS. This was never called in production, leaving narration mute.
            kernel.subscribe_to_event_bus()
            logger.info("[iris_gateway] ConversationKernel instantiated and wired")
            kernel_ok = True

            # Issue C.2: forward agent speech (utterances) to external channels
            # (Telegram, MCP-connected integrations).  Non-fatal if it fails.
            try:
                from backend.agent.tools.speak_broadcaster import get_speak_broadcaster

                get_speak_broadcaster()
                logger.info("[iris_gateway] SpeakBroadcaster initialized")
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[iris_gateway] SpeakBroadcaster init failed (non-fatal): %s", exc
                )
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
        payload = message.get("payload", {}) or {}
        payload_keys = list(payload.keys()) if isinstance(payload, dict) else []
        conversation_id = payload.get("conversation_id") if isinstance(payload, dict) else None
        self._logger.info(
            f"[VoiceMSG] type={msg_type} session={session_id} client={client_id} "
            f"conv={conversation_id} auto_stop={auto_stop} payload_keys={payload_keys}"
        )

        try:
            if msg_type == "voice_command_start":
                self._logger.info(f"[Session: {session_id}] Voice command start")
                # Enable conversation mode — will auto-relisten after each TTS response
                self._conversation_sessions.add(session_id)
                # A wake word / new voice command clears any prior low-power sleep
                self._sleeping_sessions.discard(session_id)

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
                    if conversation_id:
                        self._active_conversation_id[session_id] = conversation_id
                        set_active_conversation(session_id, conversation_id)
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

    # ------------------------------------------------------------------ #
    # "Stop listening" voice command — hands-free low-power listen.       #
    # Detected from the transcribed speech text (NOT a wake word), so no  #
    # extra Porcupine model is required.  When matched, the VAD/recording #
    # /ASR pipeline is released but the wake word stays armed so "hey     #
    # iris" reopens the conversation.                                     #
    # ------------------------------------------------------------------ #
    _STOP_LISTENING_PHRASES = (
        "stop listening",
        "stop listening now",
        "stop listening please",
        "go to sleep",
        "go to sleep now",
        "sleep now",
        "sleep mode",
        "that's all",
        "thats all",
        "stop now",
        "pause listening",
    )
    # Leading filler words stripped before phrase matching so "hey iris stop
    # listening" or "okay go to sleep" still match.
    _STOP_LISTENING_FILLERS = (
        "hey iris",
        "hey irish",
        "ok",
        "okay",
        "please",
        "iris",
        "um",
        "uh",
        "yo",
    )

    @staticmethod
    def _normalize_for_sleep(transcript: str) -> str:
        text = (transcript or "").lower().strip()
        # Strip a single leading filler word (only once, to avoid loops).
        for filler in IRISGateway._STOP_LISTENING_FILLERS:
            if text == filler:
                return ""
            if text.startswith(filler + " "):
                text = text[len(filler) + 1:].strip()
                break
        return text

    def _matches_stop_listening(self, transcript: str) -> bool:
        norm = self._normalize_for_sleep(transcript)
        if not norm:
            return False
        return any(
            norm == phrase or norm.startswith(phrase)
            for phrase in IRISGateway._STOP_LISTENING_PHRASES
        )

    async def _enter_sleep_mode(self, session_id: str, client_id: str | None) -> None:
        """
        Release VAD/recording/ASR for a session but keep the wake word armed.
        Broadcasts listening_state "idle" (the orb's low-power / waiting-for-
        wake-word look).  Auto-relisten is suppressed via _sleeping_sessions.
        """
        self._sleeping_sessions.add(session_id)
        self._conversation_sessions.discard(session_id)
        if self._voice_handler is not None:
            try:
                self._voice_handler.cancel_recording()
            except Exception as _e:
                self._logger.warning(f"[Voice] sleep cancel_recording error: {_e}")
        try:
            await self._ws_manager.broadcast_to_session(
                session_id,
                {"type": "listening_state", "payload": {"state": "idle"}},
            )
        except Exception as _e:
            self._logger.warning(f"[Voice] sleep broadcast error: {_e}")
        self._logger.info(
            f"[Voice] Session {session_id} entered low-power listen (sleep) — "
            f"wake word stays armed"
        )

    def _should_auto_relisten(self, session_id: str, interrupted: "threading.Event") -> bool:
        """
        Decide whether _speak_response's finally block should auto-relisten
        (re-open VAD/recording) after TTS, vs. falling back to idle.

        Auto-relisten requires: conversation mode active, not interrupted, the
        session is NOT in low-power "sleep" listen, and a voice handler exists.
        """
        if session_id not in self._conversation_sessions:
            return False
        if interrupted.is_set():
            return False
        if session_id in self._sleeping_sessions:
            return False
        return self._voice_handler is not None

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
            conversation_id = result.get("conversation_id") or self._active_conversation_id.get(session_id)
            client_id = self._active_voice_client.get(session_id)

            # ── Log STT latency (Parakeet / Whisper) ──────────────────────
            # Populated by voice_command._transcribe_via_parakeet() or the
            # whisper fallback. Surface it in the log so latency regressions
            # are immediately visible alongside the existing VOICE_TIMING lines.
            stt_timing = result.get("stt_timing") or {}
            if stt_timing:
                _stt_ms = stt_timing.get("stt_latency_ms", 0.0)
                _stt_backend = stt_timing.get("stt_backend", "unknown")
                _stt_audio_s = stt_timing.get("stt_audio_seconds", 0.0)
                # Real-time factor: how many seconds of STT per second of audio
                _rtf = (_stt_ms / 1000.0) / _stt_audio_s if _stt_audio_s > 0 else 0.0
                self._logger.info(
                    f"[STT_LATENCY] backend={_stt_backend} "
                    f"latency_ms={_stt_ms:.0f} audio_s={_stt_audio_s:.2f} "
                    f"rtf={_rtf:.2f}x"
                )

            # Use the loop captured during the first async message dispatch.
            # Never call asyncio.get_event_loop() here â€” this runs in a background
            # thread and that call raises "no current event loop" on Python 3.10+.
            loop = self._main_loop
            if loop is None or not loop.is_running():
                self._logger.error(
                    "[Voice] _on_voice_result: main event loop not available"
                )
                return

            # ── "Stop listening" voice command (hands-free low-power listen) ──
            # Detected from the transcribed text — no wake word required.  When
            # matched we release VAD/recording/ASR (keep wake word armed) and
            # skip the LLM/TTS pipeline entirely.
            if transcript and self._matches_stop_listening(transcript):
                self._logger.info(
                    f"[Voice] 'stop listening' detected for session {session_id} "
                    f"(transcript={transcript!r}) — entering low-power listen"
                )
                asyncio.run_coroutine_threadsafe(
                    self._enter_sleep_mode(session_id, client_id), loop
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
                    session_id, client_id, transcript, audio_context,
                    conversation_id=conversation_id,
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
        self, session_id: str, client_id: str, transcript: str, audio_context: str,
        conversation_id: str | None = None,
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
            # ── T15 (REQ-14): pending-question awareness — a completed voice
            # transcript is a candidate answer to a pending question card. When
            # matched at/above threshold the question resolves through the SAME
            # funnel as a card click (first-wins); the transcript does not go to
            # the LLM as a new turn. Below threshold -> user asked to repeat,
            # and the utterance falls through to the normal command path (edge:
            # never swallowed). No pending question -> normal path (AC6).
            try:
                from backend.agent.tools.ask_user_tool import get_ask_user_tool
                voice = get_ask_user_tool().resolve_via_voice(transcript, session_id)
                if voice.get("handled"):
                    return  # question answered by voice; nothing to process
            except Exception as _voice_q_err:
                self._logger.warning(f"[AskUser] voice resolve failed: {_voice_q_err}")

            # ── Pillar 1A: user bubble ─────────────────────────────────────
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

            agent_kernel = get_agent_kernel(
                conversation_id or session_id, session_id
            )

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
                    _min_played = False  # guarantee >=1 full iteration before stop
                    self._logger.info("[STTPROC] Loop starting...")
                    while True:
                        _loop_count += 1
                        _sd2.play(_sttproc_data, _sttproc_sr, device=_sttproc_dev, blocking=True)
                        _min_played = True
                        # Sync: keep the "processing" chime alive UNTIL the real
                        # TTS playback actually starts (first chunk reaches the
                        # device). This ties the chime thread to the TTS thread
                        # via _playback_event so they don't drift apart — the
                        # chime no longer ends on a blind 2-iteration count while
                        # TTS is still thinking (silence gap) or clashes with it.
                        # Timeout = safety net if TTS never starts.
                        if _min_played:
                            self._playback_event.wait(timeout=4.0)
                            if _sttproc_stop.is_set() or self._playback_event.is_set():
                                # One short overlap to avoid a dead-silence gap.
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
            # Generate a stable turn_id for this TTS+text_response pair.
            # Shared between tts_started (sent immediately) and text_response
            # (sent later), so the frontend can set currentTtsMessageId early
            # and capture all tts_word events instead of missing the first N.
            from uuid import uuid4 as _uuid4
            _turn_id = str(_uuid4())

            def _execute_agent():
                _log_timing("llm_start")
                _first_chunk_seen = False
                _first_sentence_seen = False
                # D2: did ANY spoken text reach the TTS queue this turn?
                # Set at every real sentence_queue.put below (not the sentinel).
                # Without this the DER path could render a card and say nothing
                # at all — see the guaranteed-utterance block at the end of
                # this function for the full explanation.
                _spoken_queued = False

                def chunk_callback(chunk: str):
                    sentence_buf.append(chunk)
                    _text = "".join(sentence_buf)
                    # Issue C.1: structured speak/show JSON responses start with
                    # '{'. Don't stream the raw JSON to the UI or TTS — the
                    # `speak` field is spoken via the sentence_queue (after
                    # parsing at final flush) and `show` via document:render.
                    if _text.lstrip().startswith("{"):
                        return
                    if loop and loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            self._ws_manager.send_to_client(
                                client_id,
                                {
                                    "type": "chat_chunk",
                                    "payload": {"chunk": chunk, "turn_id": _turn_id},
                                },
                            ),
                            loop,
                        )

                    # Stream sentences into TTS from RESPONSE text
                    # (chunk_callback receives actual response content from the LLM,
                    #  NOT reasoning/thinking — reasoning goes through reasoning_callback).
                    nonlocal _sentence_buf_words
                    nonlocal _first_chunk_seen
                    nonlocal _first_sentence_seen
                    nonlocal _spoken_queued
                    if not _first_chunk_seen:
                        _first_chunk_seen = True
                        _log_timing("first_chunk")
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
                        # REQ-8 AC2 (T26): spoken companion-style form into TTS;
                        # the display path above still streams the raw chunk.
                        sentence_queue.put(_normalize_spoken_sentence(complete))
                        _spoken_queued = True
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
                        sentence_queue.put(_normalize_spoken_sentence(text))
                        _spoken_queued = True
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
                        conversation_id=conversation_id,
                        chunk_callback=chunk_callback,
                        reasoning_callback=reasoning_callback,
                        from_voice=True,
                    )
                    _log_timing("llm_end")
                    self._logger.info(
                        f"[DER-TTS-FIX] after process_text_message: "
                        f"sentence_buf_len={len(sentence_buf)}, "
                        f"sentence_buf_content={sentence_buf[:2]!r}"
                    )
                    # Final flush — any remaining text becomes a sentence
                    if sentence_buf:
                        _final = "".join(sentence_buf)
                        sentence_buf.clear()
                        # Issue C.1: for a structured JSON response, speak only
                        # the `speak` field (not the raw JSON). Plain responses
                        # pass through unchanged.
                        try:
                            from backend.agent.structured_response import (
                                parse_structured_response,
                            )

                            _speak, _show = parse_structured_response(_final)
                        except Exception:
                            _speak = None
                        if _speak is not None:
                            # REQ-8 AC2 (T26): spoken companion-style form.
                            sentence_queue.put(_normalize_spoken_sentence(_speak))
                            _spoken_queued = True
                        elif not _final.lstrip().startswith("{"):
                            sentence_queue.put(_normalize_spoken_sentence(_final))
                            _spoken_queued = True
                    spoken = agent_kernel.prepare_spoken_text(resp, enriched)

                    # ── D2: GUARANTEED UTTERANCE ────────────────────────────
                    # A rendered answer must never be silently unspoken.
                    #
                    # The DER path calls chunk_callback(_der_response) with the
                    # RAW response (agent_kernel.py ~:5081, before
                    # _process_structured_response runs), so for a structured
                    # reply chunk_callback sees text starting with '{' and
                    # deliberately returns early without queuing — on the
                    # promise that the final flush above will parse it and
                    # speak the `speak` field.
                    #
                    # That promise has no fallback. If parse_structured_response
                    # returns no `speak`, or raises (the except sets _speak =
                    # None), then `_speak is not None` is False AND the elif is
                    # rejected for starting with '{' — so NOTHING is queued and
                    # the turn is silent. Observed live in the T36 smoke test:
                    # der_response_len=2601, "chunk_callback invoked OK", card
                    # rendered with data, and zero SPEAK / synthesize_stream /
                    # PLAYBACK entries for the final answer.
                    #
                    # `spoken` above is the correctly normalised companion-style
                    # form and was already being computed here — it was simply
                    # returned and never queued. Use it as the backstop.
                    #
                    # Gated on _spoken_queued (set at every real put, including
                    # the streaming ones) so a normal streaming reply that
                    # already spoke its sentences is NOT repeated in full.
                    if not _spoken_queued and spoken and spoken.strip():
                        sentence_queue.put(_normalize_spoken_sentence(spoken))
                        _spoken_queued = True
                        self._logger.warning(
                            "[DER-TTS-FIX] nothing reached TTS during the turn "
                            "(resp_len=%d) — speaking the prepared text as a "
                            "backstop",
                            len(resp or ""),
                        )
                    return resp, spoken
                finally:
                    # ALWAYS put sentinel — even if agent throws, the TTS thread
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
                    self._speak_response(q, sid, _sttproc_stop=_sttproc_stop, _client_id=cid, _turn_id=_turn_id)
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
                    "turn_id": _turn_id,
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
            # ALWAYS stop STTPROC — the inner _speak_response also sets this
            # in its finally block, but this is the outer safety net.
            if _sttproc_stop is not None and not _sttproc_stop.is_set():
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

                # ── Conversational flow latency breakdown ──────────────────
                # One-line per-phase delta summary, easy to grep from logs:
                #   [FLOW_LATENCY] vad->stt=380ms stt->llm=10ms llm_first_token=620ms
                #                   tts_synth=340ms total=2380ms
                _flow_parts = []
                # STT: time from VAD end until Parakeet/Whisper returns text.
                # Approximated as vad_end -> llm_start (the agent starts only
                # after the STT result lands via _on_voice_result).
                if "llm_start" in self._voice_timing:
                    _vad_to_llm = (self._voice_timing["llm_start"] - t0) * 1000.0
                    _flow_parts.append(f"vad_to_llm={_vad_to_llm:.0f}ms")
                # LLM: llm_start -> first_chunk (time to first token)
                if "first_chunk" in self._voice_timing and "llm_start" in self._voice_timing:
                    _llm_ttft = (self._voice_timing["first_chunk"] - self._voice_timing["llm_start"]) * 1000.0
                    _flow_parts.append(f"llm_ttft={_llm_ttft:.0f}ms")
                # LLM: llm_start -> llm_end (full response generation)
                if "llm_end" in self._voice_timing and "llm_start" in self._voice_timing:
                    _llm_total = (self._voice_timing["llm_end"] - self._voice_timing["llm_start"]) * 1000.0
                    _flow_parts.append(f"llm_total={_llm_total:.0f}ms")
                # TTS synth: first_tts_synth_start -> first_audio_pushed
                if "first_tts_synth_start" in self._voice_timing and "first_audio_pushed" in self._voice_timing:
                    _tts_synth = (
                        self._voice_timing["first_audio_pushed"]
                        - self._voice_timing["first_tts_synth_start"]
                    ) * 1000.0
                    _flow_parts.append(f"tts_synth={_tts_synth:.0f}ms")
                # VAD -> first audio: total time to first audible response
                if "first_audio_pushed" in self._voice_timing:
                    _vad_to_audio = (self._voice_timing["first_audio_pushed"] - t0) * 1000.0
                    _flow_parts.append(f"vad_to_audio={_vad_to_audio:.0f}ms")
                # Full conversational flow: VAD end -> text_response_sent
                if "text_response_sent" in self._voice_timing:
                    _flow_total = (self._voice_timing["text_response_sent"] - t0) * 1000.0
                    _flow_parts.append(f"flow_total={_flow_total:.0f}ms")
                _flow_parts.append(f"wall={total * 1000.0:.0f}ms")
                self._logger.info("[FLOW_LATENCY] " + " ".join(_flow_parts))

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
        _turn_id: Optional[str] = None,
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
        # Instance attribute (not local) so the nested STTPROC chime loop
        # can reference it reliably across thread boundaries.
        self._playback_event: threading.Event = threading.Event()
        _playback_event = self._playback_event

        def _producer():
            # Wait for any in-flight agent-initiated utterance (SpeakTool /
            # fillers) to finish before we start playing the response, so the
            # response stream can't cut the agent's narration off mid-word
            # (e.g. web-search "Searching…").  Non-holding wait: we block until
            # the shared narration lock is free, then release — we do NOT hold it
            # for the whole response, so the agent can still speak during a long
            # response if needed.
            try:
                from backend.agent.conversation_kernel import narration_playback_lock

                with narration_playback_lock():
                    pass
            except Exception:  # noqa: BLE001
                pass

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
                                                # ── Log TTS synthesis latency ──────
                                                # first_tts_synth_start → first_audio_pushed
                                                # is the time Pocket-TTS took to produce
                                                # the first playable audio chunk.
                                                _synth_start = (
                                                    self._voice_timing.get("first_tts_synth_start")
                                                    if hasattr(self, "_voice_timing")
                                                    else None
                                                )
                                                _first_audio_now = _time2.monotonic()
                                                if _synth_start:
                                                    _tts_ms = (_first_audio_now - _synth_start) * 1000.0
                                                    self._logger.info(
                                                        f"[TTS_LATENCY] backend=pocket_tts "
                                                        f"synth_to_audio_ms={_tts_ms:.0f}"
                                                    )
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
                                                                    {
                                                                        "type": "tts_started",
                                                                        "turn_id": _turn_id or "",
                                                                        "total_words": len(_all_words),
                                                                    },
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
                                                                {
                                                                    "type": "tts_started",
                                                                    "turn_id": _turn_id or "",
                                                                    "total_words": len(_all_words),
                                                                },
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
                # Instance-level stop event: shared across _speak_response calls.
                # Kill any old monitor before creating a fresh event for this call.
                if self._word_monitor_stop is not None:
                    self._word_monitor_stop.set()  # signal old monitor to die
                self._word_monitor_stop = threading.Event()

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

                            # Join old monitor thread from a previous _speak_response
                            # call (e.g. barge-in killed TTS, new TTS starts immediately).
                            # Without this, two monitors broadcast concurrently.
                            if self._word_monitor_thread is not None and self._word_monitor_thread.is_alive():
                                self._logger.info("[TTS][words] Joining old monitor thread...")
                                self._word_monitor_thread.join(timeout=0.5)
                                if self._word_monitor_thread.is_alive():
                                    self._logger.warning("[TTS][words] Old monitor did not exit in 0.5s - proceeding anyway")

                            # Capture the NEW stop event at definition time so
                            # the closure holds a reference to this call's event.
                            _my_stop = self._word_monitor_stop

                            def _monitor_words():
                                # ── CONTRACT ──────────────────────────────────────
                                # The behavioral contracts below are verified by
                                # integration tests in:
                                #   tests/test_voice_pipeline.py::TestTTSWordEventIntegration
                                #
                                # DO NOT change the word monitor implementation
                                # without also updating those tests.
                                #
                                # Guarantees:
                                #   1. Every word (from every sentence) is broadcast
                                #      at least once — dynamically catches up as
                                #      the producer adds words from later sentences.
                                #   2. All expected indices appear (monotonically
                                #      non-decreasing).
                                #   3. No premature is_final (is_final=True only
                                #      after stream close, on the last event).
                                #   4. Barge-in: remaining words catch up at 30ms
                                #      intervals; is_final on the last catch-up word.
                                # ──────────────────────────────────────────────────
                                import asyncio as _aw
                                import time as _tw
                                nonlocal _last_word_idx
                                _initial_wn = len(_all_words)
                                self._logger.info(f"[TTS][words] Monitor started, {_initial_wn} words initially")

                                # Wait for first audio chunk before starting
                                while _total_written_for_words <= 0:
                                    if _my_stop.is_set():
                                        return
                                    _tw.sleep(0.05)

                                # Dynamic word broadcasting loop.
                                # Re-checks _all_words each iteration so words
                                # added by the producer from subsequent sentences
                                # are also broadcast with character-proportional
                                # timing — they don't fall through to the fallback.
                                _i = 0

                                while True:
                                    # Re-read current word count dynamically
                                    _current_wn = len(_all_words)

                                    if _i >= _current_wn:
                                        # All currently-available words broadcast.
                                        # Wait for more words from producer OR
                                        # stream close (which means all sentences
                                        # have been processed).
                                        if _my_stop.is_set():
                                            # Stream closed — send is_final on the
                                            # last word that was broadcast.
                                            if _i == 0:
                                                return  # No words broadcast at all
                                            try:
                                                _aw.run_coroutine_threadsafe(
                                                    self._ws_manager.send_to_client(
                                                        _client_id or session_id,
                                                        {
                                                            "type": "tts_word",
                                                            "payload": {
                                                                "word_index": _last_word_idx,
                                                                "total_words": _current_wn,
                                                                "is_final": True,
                                                            },
                                                        },
                                                    ),
                                                    self._main_loop,
                                                )
                                            except Exception:
                                                pass
                                            return
                                        _tw.sleep(0.05)
                                        continue

                                    # ── Broadcast word _i ────────────────────────
                                    _total_chars_now = max(1, sum(len(w) for w in _all_words))
                                    try:
                                        _aw.run_coroutine_threadsafe(
                                            self._ws_manager.send_to_client(
                                                _client_id or session_id,
                                                {
                                                    "type": "tts_word",
                                                    "payload": {
                                                        "word_index": _i,
                                                        "total_words": _current_wn,
                                                        "is_final": False,
                                                    },
                                                },
                                            ),
                                            self._main_loop,
                                        )
                                    except Exception:
                                        pass
                                    _last_word_idx = _i

                                    # Character-proportional timing sleep.
                                    # Uses 15.8 char/s estimate — tight sync
                                    # with TTS playback.  If too short, the last
                                    # word stays highlighted until audio ends.
                                    # If too long, stream close triggers catch-up.
                                    _char_prop = len(_all_words[_i]) / _total_chars_now
                                    _est_tts_dur = _total_chars_now / 15.8
                                    _word_dur = max(0.03, _est_tts_dur * _char_prop)

                                    _sleep_until = _tw.monotonic() + _word_dur
                                    while _tw.monotonic() < _sleep_until:
                                        if _my_stop.is_set():
                                            # Barge-in or stream close during sleep
                                            # — catch up ALL remaining words (even
                                            # ones the producer added since start).
                                            _catch_up_wn = len(_all_words)
                                            for _j in range(_i + 1, _catch_up_wn):
                                                try:
                                                    _aw.run_coroutine_threadsafe(
                                                        self._ws_manager.send_to_client(
                                                            _client_id or session_id,
                                                            {
                                                                "type": "tts_word",
                                                                "payload": {
                                                                    "word_index": _j,
                                                                    "total_words": _catch_up_wn,
                                                                    "is_final": _j == _catch_up_wn - 1,
                                                                },
                                                            },
                                                        ),
                                                        self._main_loop,
                                                    )
                                                except Exception:
                                                    pass
                                                _tw.sleep(0.03)
                                            return
                                        _tw.sleep(0.01)

                                    _i += 1

                            _word_monitor = threading.Thread(
                                target=_monitor_words,
                                daemon=True,
                                name="tts-words",
                            )
                            _word_monitor.start()
                            self._word_monitor_thread = _word_monitor

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
                # Signal the word monitor thread to stop — without this,
                # old monitors from previous TTS responses (killed by
                # barge-in) keep running and broadcasting stale word
                # indices, causing interleaved events on the frontend.
                if _word_monitor_started and self._word_monitor_stop is not None:
                    self._word_monitor_stop.set()

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

                # ── Wait for monitor thread to exit ──────────────────
                # The monitor's post-stream-close handling sends is_final
                # on the last word.  We just need to let it finish.
                if _word_monitor_started and self._word_monitor_thread is not None:
                    self._word_monitor_thread.join(timeout=2.0)

                # â€"â€" Word timing is handled by the streaming monitor â€"â€"â€"â€"
                # Uses character-proportional timing (see word monitor above).
                #  _sd_stream.time for real playback position).
                # The post-loop thread has been replaced â€" see line ~3089.

                producer_thread.join(timeout=5)
        except Exception as e:
            self._logger.error(f"[Voice] TTS Consumer error: {e}")
        finally:
            # ALWAYS stop STTPROC when speak_response exits — barge-in,
            # interruption, or error. Without this, the looping "processing"
            # sound keeps playing forever when the stream exits before
            # the first audio chunk pushes _sttproc_stop.
            if _sttproc_stop is not None and not _sttproc_stop.is_set():
                self._logger.info("[TTS] finally: stopping STTPROC loop")
                _sttproc_stop.set()
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

                # Conversation mode: auto-relisten unless interrupted, cancelled,
                # or the session is in low-power "sleep" listen.
                in_conversation = session_id in self._conversation_sessions
                was_interrupted = interrupted.is_set()
                if self._should_auto_relisten(session_id, interrupted):
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
                    play_beep=False,
                    flush_ms=400,
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
            # Send tts_started (NOT listening_state:speaking) so the frontend
            # orb uses its isolated playbackSpeaking state — never touches
            # voiceState and can't trigger listening/processing effects.
            total_words = len(text.split())
            await self._ws_manager.send_to_client(
                client_id,
                {"type": "tts_started", "turn_id": f"tts-play-{int(time.time())}", "total_words": total_words},
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
            # Show "listening" after TTS when the session is in conversation mode
            # OR the voice handler is actively recording for this session (the
            # audio pipeline is open and waiting for the next utterance). This
            # keeps the orb in sync with the real backend listening state
            # instead of reporting "idle" while the mic is still hot.
            _voice_active = (
                self._voice_handler is not None
                and getattr(self._voice_handler, "_active_session_id", None) == session_id
            )
            post_tts_state = (
                "listening"
                if (session_id in self._conversation_sessions or _voice_active)
                else "idle"
            )
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

    def _on_client_replace(self, client_id: str) -> None:
        """REQ-8 AC5: a stale socket for client_id was replaced by a new one.

        Soft-cancel the previously-active thread's in-flight DER loop for this
        session. The incoming sync_state will re-bind (and cancel if different).
        Called synchronously from WebSocketManager on reconnect-replacement.
        """
        try:
            session_id = f"session_{client_id}"
            prev_active = self._active_conversation_id.get(session_id)
            if not prev_active:
                return
            old_kernel = get_agent_kernel(prev_active, session_id)
            cancel_flag = getattr(old_kernel, "_cancel_requested", None)
            if cancel_flag is not None:
                cancel_flag.set()
                self._logger.info(
                    f"[Chat] client_replace cancelled in-flight thread "
                    f"{prev_active} for session {session_id}"
                )
        except Exception as exc:
            self._logger.warning(
                f"[Chat] _on_client_replace cancel failed: {exc}"
            )

    async def _handle_sync_state(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """
        Phase 4.3: re-attach the per-thread kernel after a WS reconnect (or
        when the frontend resumes an existing conversation).  Restores the
        persisted conversation context so the resumed thread continues with
        its own history instead of the session's default kernel.

        Sends a `sync_state_ack` back so the frontend knows the bind succeeded.
        """
        payload = message.get("payload", {}) or {}
        conversation_id = payload.get("conversation_id") or session_id
        try:
            kernel = get_agent_kernel(conversation_id, session_id)
            # REQ-8: re-point the session at the resumed thread. The frontend owns
            # the UI thread; the backend owns this binding (set on new_conversation /
            # switch_conversation / sync_state). Without this, a reconnect leaves
            # _active_conversation_id stale and a post-reconnect wake-word resolves
            # to the wrong thread.
            prev_active = self._active_conversation_id.get(session_id)
            if conversation_id:
                self._active_conversation_id[session_id] = conversation_id
                set_active_conversation(session_id, conversation_id)
            # REQ-8 AC3: if sync_state re-binds to a DIFFERENT thread than was
            # active, soft-cancel the previously-active thread's in-flight work.
            if prev_active and prev_active != conversation_id:
                try:
                    old_kernel = get_agent_kernel(prev_active, session_id)
                    cancel_flag = getattr(old_kernel, "_cancel_requested", None)
                    if cancel_flag is not None:
                        cancel_flag.set()
                        self._logger.info(
                            f"[Chat] sync_state re-bind cancelled old thread "
                            f"{prev_active} for session {session_id}"
                        )
                except Exception as exc:
                    self._logger.warning(
                        f"[Chat] sync_state failed to cancel old thread {prev_active}: {exc}"
                    )
            # restore_context_from_store() takes only `self` and restores the
            # kernel's own conversation_id context. Passing conversation_id as
            # a 2nd positional arg raised TypeError and broke sync_state.
            kernel.restore_context_from_store()
            self._logger.info(
                f"[Chat] sync_state attached conversation {conversation_id} "
                f"for session {session_id}"
            )
            try:
                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "sync_state_ack",
                        "payload": {
                            "conversation_id": conversation_id,
                            "current_conversation_id": conversation_id,
                            "status": "attached",
                        },
                    },
                )
            except Exception:
                pass
        except Exception as exc:
            self._logger.warning(
                f"[Chat] sync_state failed for {conversation_id}: {exc}"
            )
            try:
                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "sync_state_ack",
                        "payload": {
                            "conversation_id": conversation_id,
                            "status": "error",
                            "error": str(exc),
                        },
                    },
                )
            except Exception:
                pass

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

        # ── NARRATION ROUTING: bind the Caducean session to THIS session ────
        # ConversationKernel resolves its broadcast target via
        # session_id_getter=lambda: getattr(self, "_caducean_session_id", None)
        # (see :1985). NOTHING EVER ASSIGNED THAT ATTRIBUTE — grep found the
        # getter's own reference and no writer anywhere — so it always returned
        # None, fell through to the voice handler's _active_session_id (voice
        # turns only), and narration was broadcast to session "default" while
        # the client sat on session_iris. Every narration and listening_state
        # reset for a TEXT turn was therefore silently dropped: sent, to nobody.
        # That is why the phase stuck on WRK and why agent speech never
        # arrived. Declared-read-never-written, the same defect shape that has
        # now produced ten separate silent failures in this codebase.
        # Bind it on every chat message so the getter has a real target.
        if session_id:
            self._caducean_session_id = session_id

        if msg_type == "switch_conversation":
            new_conv_id = payload.get("conversation_id")
            old_conv_id = payload.get("old_conversation_id") or session_id
            self._logger.info(
                f"[Chat] Switching conversation from {old_conv_id} to {new_conv_id} "
                f"(session={session_id})"
            )
            # Save old context to store (best-effort) — REQ-5
            context_saved = False
            try:
                old_kernel = get_agent_kernel(old_conv_id, session_id)
                old_kernel.save_context_to_store()
                context_saved = True
            except Exception as exc:
                self._logger.warning(
                    f"[Chat] Failed to save context for {old_conv_id}: {exc}"
                )
            # REQ-6 (soft-cancel): signal the OLD thread's in-flight DER loop to
            # stop. Synchronous + non-blocking — the switch returns immediately and
            # the old loop exits at its next step boundary. SOFT cancel: an
            # in-flight tool subprocess is allowed to finish once.
            old_canceled = False
            try:
                if old_conv_id != new_conv_id:
                    old_kernel = get_agent_kernel(old_conv_id, session_id)
                    cancel_flag = getattr(old_kernel, "_cancel_requested", None)
                    if cancel_flag is not None:
                        cancel_flag.set()
                        old_canceled = True
            except Exception as exc:
                self._logger.warning(
                    f"[Chat] Failed to cancel old thread {old_conv_id}: {exc}"
                )
            # REQ-3: stop any TTS currently playing for the OLD thread BEFORE
            # re-pointing, so old-thread audio does not bleed into the new thread.
            tts_interrupted = False
            try:
                from .audio.engine import get_audio_engine
                engine = get_audio_engine()
                if engine is not None and getattr(engine, "_tts_active", False):
                    engine.interrupt_speech()
                    tts_interrupted = True
            except Exception:
                pass  # non-fatal — audio engine may not be up yet
            # Keep the wake-word voice path pointed at the switched thread.
            # _handle_voice falls back to _active_conversation_id[session_id]
            # when a voice_command_start carries no conversation_id, so without
            # this a wake-word response would land in the OLD conversation.
            if new_conv_id:
                self._active_conversation_id[session_id] = new_conv_id
                set_active_conversation(session_id, new_conv_id)
            # Acknowledge switch to frontend — REQ-4 (fix undefined conversation_id)
            try:
                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "conversation_switched",
                        "payload": {
                            "conversation_id": new_conv_id,
                            "status": "context_saved" if context_saved else "switched",
                            "old_conversation_id": old_conv_id,
                        },
                    },
                )
            except Exception:
                pass
            self._logger.info(
                f"[Chat] Switch complete session={session_id} "
                f"old={old_conv_id} new={new_conv_id} "
                f"tts_interrupted={tts_interrupted} old_canceled={old_canceled}"
            )
            return

        if msg_type == "settings_sync":
            settings_data = payload.get("settings", {})
            self._logger.info(
                f"[Chat] Settings sync for session {session_id}: "
                f"{len(settings_data)} keys"
            )
            # Re-apply settings to the agent kernel
            for key, value in settings_data.items():
                # Settings are re-applied on the next process_text_message call
                pass
            return

        if msg_type == "new_conversation":
            # Reset the agent kernel's conversation context so the next
            # voice command or text message starts fresh.  The frontend sends
            # this when the user creates a "New Conversation" in the chat UI.
            # NO `or session_id` fallback here. "New conversation" means the
            # user has left the previous thread and the next one does not exist
            # yet — the frontend deliberately sends no id, because minting one
            # client-side created an orphan namespace (see chat-view's
            # handleNewConversation). Defaulting to session_id was worse than
            # useless: it bound the session to a pseudo-thread and cleared THAT
            # kernel's context instead of the one the user was actually in,
            # leaving the real previous thread bound and live. A wake word or a
            # reconnect then resolved straight back into it — the "new
            # conversation reverts to the old one" report.
            #
            # So: with an explicit id, bind to it. Without one, DROP the binding
            # and let the first message of the new thread establish it.
            conversation_id = payload.get("conversation_id")
            if conversation_id:
                # Point the wake-word voice path at the new thread (same reason
                # as switch_conversation): _handle_voice falls back to
                # _active_conversation_id[session_id] when voice_command_start
                # carries no conversation_id.
                self._active_conversation_id[session_id] = conversation_id
                set_active_conversation(session_id, conversation_id)
            else:
                prev_conv = self._active_conversation_id.pop(session_id, None)
                set_active_conversation(session_id, None)
                self._logger.info(
                    "[Chat] new_conversation unbound session %s (was %s) — "
                    "next message establishes the thread",
                    session_id,
                    prev_conv,
                )
                # Clear the thread the user just left, not a pseudo-thread.
                if prev_conv:
                    try:
                        get_agent_kernel(prev_conv, session_id).clear_conversation(
                            prev_conv
                        )
                    except Exception as exc:
                        self._logger.warning(
                            "[Chat] Failed to clear previous conversation %s: %s",
                            prev_conv,
                            exc,
                        )
                return
            try:
                agent_kernel = get_agent_kernel(conversation_id, session_id)
                agent_kernel.clear_conversation(conversation_id)
                self._logger.info(
                    f"[Chat] Cleared conversation context for conv {conversation_id}"
                )
            except Exception as exc:
                self._logger.warning(
                    f"[Chat] Failed to clear conversation for {conversation_id}: {exc}"
                )
            return

        if msg_type == "text_message":
            conversation_id = payload.get("conversation_id") or session_id
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

                agent_kernel = get_agent_kernel(conversation_id, session_id)
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
                            conversation_id=conversation_id,
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
                # THE SPOKEN LINE IS PART OF THE MESSAGE (2026-08-17).
                #
                # This is the same text the TTS leg below speaks. It used to be
                # computed only there, so the UI never received it — and the
                # word-highlight had nothing legitimate to attach to. ChatView
                # was highlighting `message.words[i]` (words of the FULL body)
                # against word indices the backend emits for THIS summary, so on
                # a long answer the highlight crawled the first N words of the
                # body while something else entirely was being spoken.
                #
                # Sending it means: body renders in full (no highlight), the
                # spoken briefing is visible and is what the highlight tracks.
                # Computed here rather than at the TTS call so both use one value.
                try:
                    _spoken_line = (
                        getattr(agent_kernel, "_last_spoken_text", "") or ""
                    ).strip() or agent_kernel.prepare_spoken_text(response, text)
                except Exception:  # noqa: BLE001 — never fail the turn for TTS text
                    _spoken_line = ""
                _final_msg = {
                    "type": "chat_message",
                    "payload": {
                        "role": "assistant",
                        "content": response,
                        "spoken": _spoken_line or "",
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

                # ── Persist the assistant turn to conversations.db ────────────
                # The WS text_message path ran the DER turn and delivered the
                # answer, but NEVER wrote it to the persistent store — only the
                # REST /api/chat path saved assistant replies (api/chat.py:432).
                # The frontend saves the USER message via REST, so every
                # WS-driven thread accumulated exactly one message (live
                # 2026-08-12: conv-3/conv-4 held only the initial prompt, and
                # the whole thread vanished on restart). Resolve the turn's
                # conversation from the session mapping and persist here.
                try:
                    from backend.conversation_store import add_message as _store_add

                    _conv_for_turn = self._active_conversation_id.get(
                        session_id
                    ) or conversation_id
                    if _conv_for_turn and response:
                        _store_add(
                            _conv_for_turn,
                            "assistant",
                            response,
                            thinking=thinking or None,
                            turn_id=turn_id,
                            source="ws_text_message",
                        )
                        self._logger.info(
                            "[WS] persisted assistant turn to conv=%s (len=%d)",
                            _conv_for_turn, len(response),
                        )
                except Exception as _persist_exc:
                    # A persistence failure must never fail the turn or the UI
                    # update that just succeeded.
                    self._logger.warning(
                        "[WS] assistant-turn persist failed for session %s: %s",
                        session_id, _persist_exc,
                    )

                # Clear ChatView typing indicator
                await self._ws_manager.send_to_client(
                    client_id, {"type": "chat_typing", "payload": {"active": False}}
                )

                # T36-FIX (stuck WRK / spinning radial): the text-message path
                # never emitted a terminal listening_state, while tool_bridge
                # (crawler_query) pushes processing_conversation mid-turn — so
                # the frontend ContextPill stuck at WRK and the XurOrb working
                # radial kept spinning after the turn completed. The voice path
                # resets via _speak_response's finally block; the text path has
                # no such reset (it streams via chat_chunk / ConversationKernel
                # narration, neither of which guarantees a terminal idle). Emit
                # the terminal idle here so any processing_* state set during
                # the turn is cleared. Never fires for a disconnected session.
                try:
                    await self._ws_manager.broadcast_to_session(
                        session_id,
                        {"type": "listening_state", "payload": {"state": "idle"}},
                    )
                except Exception as _idle_exc:
                    self._logger.warning(
                        f"[T36] terminal listening_state idle broadcast failed: {_idle_exc}"
                    )

                # ── D2 (text path): SPEAK THE FINAL ANSWER ──────────────────
                # This app is a hands-free widget: ChatView is usually CLOSED
                # and the user is talking to the agent, which is the whole
                # reason narration exists. But the text path had NO TTS leg at
                # all — _chunk_cb above only pushes chat_chunk to the UI, so a
                # text turn rendered a card and said nothing. Observed live:
                # der_response_len=467, "chunk_callback invoked OK", and zero
                # synthesize/PLAYBACK entries for the answer; the only audio
                # was "reading…" fillers emitted by SpeakTool from the
                # crawl_planner pseudo-kernel.
                #
                # The voice path already solves this (sentence_queue + TTS
                # thread in the other _execute_agent). Rather than duplicate
                # that machinery, speak the SAME prepared text the voice path
                # speaks: prepare_spoken_text is the designed normaliser and
                # keeps the speak/show contract (spoken is a companion-style
                # subset of what is displayed, never raw markdown/JSON).
                #
                # Off-thread: _speak_response blocks on synthesis+playback and
                # must never hold the WS handler.
                try:
                    # Prefer the agent's OWN `speak` line when it supplied one
                    # (the speak/show contract). `response` now carries the FULL
                    # answer — it is no longer the short form — so deriving a
                    # summary from it is the fallback, not the primary path.
                    #
                    # Reuse the value already sent to the UI as the message's
                    # `spoken` field: what is heard and what the highlight tracks
                    # must be the SAME string, or the highlight desyncs again.
                    _spoken_text = _spoken_line
                    if _spoken_text and _spoken_text.strip():
                        self._logger.info(
                            "[D2-TEXT-TTS] speaking final answer (%d chars) for "
                            "session=%s",
                            len(_spoken_text), session_id,
                        )
                        threading.Thread(
                            target=self._speak_response,
                            args=(_spoken_text,),
                            kwargs={
                                "session_id": session_id,
                                "_client_id": client_id,
                                "_turn_id": turn_id,
                            },
                            daemon=True,
                            name="text-path-tts",
                        ).start()
                    else:
                        # Say why, rather than going quiet with no trace — a
                        # silent turn with no log line is what made this cost
                        # two live smoke runs to find.
                        self._logger.warning(
                            "[D2-TEXT-TTS] no spoken text produced for a "
                            "%d-char response — turn will be silent",
                            len(response or ""),
                        )
                except Exception as _tts_exc:  # noqa: BLE001
                    # TTS must never fail the turn: the answer is already
                    # rendered and persisted by this point.
                    self._logger.warning(
                        "[D2-TEXT-TTS] speak failed (answer still delivered): %s",
                        _tts_exc,
                    )

            except Exception as e:
                self._logger.error(f"Error processing text message: {e}", exc_info=True)
                # Clear typing indicator on error
                await self._ws_manager.send_to_client(
                    client_id, {"type": "chat_typing", "payload": {"active": False}}
                )
                # T36-FIX: also clear any processing_* listening_state set by
                # tool_bridge mid-turn so the pill/orb don't stick on error.
                try:
                    await self._ws_manager.broadcast_to_session(
                        session_id,
                        {"type": "listening_state", "payload": {"state": "idle"}},
                    )
                except Exception:
                    pass
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

        elif msg_type == "notification_response":
            # Handle permission responses from the frontend PermissionCard
            try:
                from backend.agent.permissions import get_permission_system
                perm_system = get_permission_system()
                request_id = payload.get("notification_id", "")
                action = payload.get("action", "")
                if action == "grant":
                    perm_system.respond_to_permission(request_id, approved=True)
                elif action == "deny":
                    perm_system.respond_to_permission(request_id, approved=False)
                elif action == "confirm":
                    perm_system.respond_to_permission(request_id, approved=True, confirmed=True)
            except Exception as _perm_err:
                self._logger.warning(f"[Permissions] notification_response failed: {_perm_err}")

        elif msg_type == "question_response":
            # Handle question responses from AskUserTool.
            # T3 (REQ-6 AC1/AC2): route through resolve_answer(), the SAME
            # single funnel voice uses (resolve_via_voice -> resolve_answer),
            # so a card click also resumes any parked source (AC2) and
            # shares first-wins semantics (AC3). Previously this called
            # receive_answer() directly, bypassing the funnel — that was
            # the exact defect pinned by
            # test_answer_funnel_baseline.py::test_gateway_question_response_bypasses_funnel
            # (now inverted, see that file's updated header).
            try:
                from backend.agent.tools.ask_user_tool import get_ask_user_tool
                tool = get_ask_user_tool()
                question_id = payload.get("question_id", "")
                answer = payload.get("answer", "")
                if question_id and answer:
                    resolved = tool.resolve_answer(question_id, answer)
                    # AC5: unknown or already-resolved question_id -> log,
                    # never raise. resolve_answer/receive_answer already
                    # return None for that case; this just makes it visible.
                    if resolved is None:
                        self._logger.info(
                            f"[AskUser] question_response for unknown/already-"
                            f"resolved question_id={question_id!r} (session={session_id})"
                        )
            except Exception as _q_err:
                self._logger.warning(f"[AskUser] question_response failed: {_q_err}")

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
                _raw = str(_raw_mode).lower().strip()
                inference_mode = _mode_map.get(_raw, None)
                # Resolve a provider INSTANCE id (e.g. "cerebras" / "cohere") to its
                # kind so the right model source is probed. This is the root-cause fix
                # for the wheelview showing wrong models: it sends instance ids, which
                # the old code never recognized (falling through to "lmstudio").
                _instance_provider = None
                if inference_mode is None:
                    try:
                        from backend.agent.inference.registry import (
                            get_provider_registry,
                        )
                        from backend.agent.inference.provider import ProviderKind

                        _prov = get_provider_registry().get(_raw)
                        if _prov is not None:
                            _instance_provider = _prov
                            if _prov.kind == ProviderKind.API:
                                inference_mode = "api"
                            elif _prov.kind == ProviderKind.LOCAL_OPENAI:
                                inference_mode = "lmstudio"
                            elif _prov.kind == ProviderKind.OLLAMA:
                                inference_mode = "local"
                            else:
                                inference_mode = "local"
                    except Exception:
                        inference_mode = "lmstudio"
                if inference_mode is None:
                    inference_mode = "lmstudio"
                # If an instance provider was resolved, prefer its stored credentials
                # (keyring-backed) over the session-state fields used by the type path.
                if _instance_provider is not None:
                    if getattr(_instance_provider, "api_key", None):
                        openai_api_key = _instance_provider.api_key
                    if getattr(_instance_provider, "api_base_url", None):
                        api_base_url = _instance_provider.api_base_url
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
                    async with httpx.AsyncClient(timeout=3.0, verify=get_ssl_context()) as http_client:
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
                            await self._set_ollama_loaded(
                                session_id, ollama_endpoint, loaded=True
                            )
                        else:
                            self._logger.warning(
                                f"[Session: {session_id}] Ollama returned status {r.status_code}"
                            )
                            await self._set_ollama_loaded(
                                session_id, ollama_endpoint, loaded=False
                            )
                except Exception as ollama_err:
                    self._logger.warning(
                        f"[Session: {session_id}] Ollama not reachable at {ollama_endpoint}: {ollama_err}"
                    )
                    await self._set_ollama_loaded(
                        session_id, ollama_endpoint, loaded=False
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
                    async with httpx.AsyncClient(timeout=3.0, verify=get_ssl_context()) as http_client:
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
                    from backend.agent.inference.provider_catalog import PROVIDER_MODEL_CATALOG
                    available_models = [
                        {"id": m["id"], "name": m["name"], "source": "lmstudio"}
                        for m in PROVIDER_MODEL_CATALOG.get("lmstudio", [])
                    ]
                    self._logger.info(
                        f"[Session: {session_id}] LM Studio unreachable — showing fallback model list"
                    )

            elif inference_mode == "api":
                # Query the user-configured API base URL for available models.
                models_url = f"{api_base_url.rstrip('/')}/models"
                headers = {}
                if openai_api_key:
                    headers["Authorization"] = f"Bearer {openai_api_key}"
                try:
                    async with httpx.AsyncClient(timeout=5.0, verify=get_ssl_context()) as http_client:
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

                # Fallback list — provider-aware based on api_base_url
                if not available_models:
                    from backend.agent.inference.provider_catalog import PROVIDER_MODEL_CATALOG
                    _base_lower = api_base_url.lower()
                    matched_provider = "openai"
                    for p_key in PROVIDER_MODEL_CATALOG:
                        if p_key in _base_lower or (p_key == "commandcode" and ("commandcode" in _base_lower or "command-code" in _base_lower)):
                            matched_provider = p_key
                            break
                    
                    catalog_models = PROVIDER_MODEL_CATALOG.get(matched_provider, PROVIDER_MODEL_CATALOG["openai"])
                    available_models = [
                        {"id": m["id"], "name": m["name"], "source": matched_provider}
                        for m in catalog_models
                    ]

            elif inference_mode == "vps":
                # Try to query the VPS endpoint for models
                if vps_url:
                    try:
                        async with httpx.AsyncClient(timeout=3.0, verify=get_ssl_context()) as http_client:
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
                # ── Read logs from the in-memory LogManager ──────────────────────
                # The LogManager is fed live by the LogManagerHandler bridge
                # (attached to the root logger in logging_config.setup_backend_logging),
                # so it captures ALL backend modules — including the tool-resolution
                # tree — organized by the Monitor's source buckets
                # (system / voice / mcp / agent). This no longer depends on
                # irisvoice.log existing on disk.
                import json
                system_logs = []
                error_logs = []

                try:
                    from backend.monitor.logs import get_log_manager
                    mgr = get_log_manager()
                    # get_logs returns newest-first already; pull a generous
                    # window and split into system + error streams for the UI.
                    all_logs = mgr.get_logs(limit=200)
                    for e in all_logs:
                        entry = {
                            "timestamp": e.get("timestamp", ""),
                            "level": (e.get("level") or "INFO").upper(),
                            "source": e.get("source") or "system",
                            "message": e.get("message", ""),
                        }
                        if entry["level"] in ("ERROR", "CRITICAL", "FATAL", "WARNING"):
                            if len(error_logs) < 40:
                                error_logs.append(entry)
                        elif len(system_logs) < 50:
                            system_logs.append(entry)
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
            async with httpx.AsyncClient(timeout=10.0, verify=get_ssl_context()) as client:
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
        # New SLICE 5 fields: register/configure a provider instance at runtime.
        model_provider = payload.get("model_provider")
        api_key = payload.get("api_key")
        api_base_url = payload.get("api_base_url")

        try:
            # Get AgentKernel for this session
            agent_kernel = get_agent_kernel(session_id)

            # Set model selection (forwards provider + credentials so the
            # kernel can register a live ProviderInstance in the router).
            success = agent_kernel.set_model_selection(
                reasoning_model, tool_execution_model,
                model_provider=model_provider,
                api_base_url=api_base_url,
                api_key=api_key,
            )

            if success:
                # Persist to disk via IRISConfig (single source of truth)
                try:
                    from .iris_config import with_modify_config, RoutingMode

                    def _update_model_config(cfg):
                        # Explicit Dashboard selection — this is authoritative.
                        # Write provider + model names, and keep role_bindings
                        # consistent with the selected provider so the frontend's
                        # /api/inference/state reflects the change immediately.
                        cfg.inference.provider = model_provider or ""
                        cfg.inference.reasoning_model = reasoning_model or ""
                        cfg.inference.tool_execution_model = (
                            tool_execution_model or ""
                        )
                        if model_provider:
                            # Project the LIVE router bindings, do not synthesise.
                            #
                            # This used to rebuild the list by hand as bare
                            # {"role", "instance_id"} pairs, dropping every
                            # model_override on the way through (2026-08-16: the
                            # router held cohere/command-a-plus-05-2026 while the
                            # file recorded cohere with no model). Config is the
                            # SEED that _apply_config replays at startup, so a
                            # lossy projection silently downgrades the user's
                            # model to the provider's registered default on the
                            # next restart — the same choice-losing behaviour as
                            # the reverts, just deferred until a restart.
                            #
                            # set_model_selection has already bound the roles on
                            # the process-wide table above; snapshot() is the
                            # faithful, override-carrying view of that, and the
                            # same projection _persist_and_broadcast_role_bindings
                            # writes. One shape, one writer's worth of truth.
                            _r = getattr(agent_kernel, "_router", None)
                            if _r is not None:
                                try:
                                    cfg.inference.role_bindings = _r.snapshot()[
                                        "role_bindings"
                                    ]
                                except Exception as _rb_err:
                                    self._logger.warning(
                                        "[set_model_selection] role_bindings "
                                        "projection failed, leaving config "
                                        "bindings untouched: %s", _rb_err,
                                    )
                        # Resolve api_base_url: frontend-sent > canonical preset endpoint > existing
                        if api_base_url:
                            cfg.inference.api_base_url = api_base_url
                            self._logger.info(
                                "[Session: %s] Using frontend-sent api_base_url '%s'",
                                session_id, api_base_url,
                            )
                        else:
                            from backend.agent.inference.provider import get_provider_default_endpoint
                            preset_ep = get_provider_default_endpoint(model_provider)
                            if preset_ep:
                                cfg.inference.api_base_url = preset_ep
                                self._logger.info(
                                    "[Session: %s] Using preset endpoint for '%s': %s",
                                    session_id, model_provider, preset_ep,
                                )
                            else:
                                self._logger.info(
                                    "[Session: %s] No api_base_url for provider '%s', "
                                    "keeping existing config value'",
                                    session_id, model_provider,
                                )
                        # Only write api_key when the frontend sends one
                        if api_key:
                            cfg.inference.api_key = api_key
                            self._logger.info(
                                "[Session: %s] API key updated for provider '%s'",
                                session_id, model_provider,
                            )
                        # For cloud providers (not local), switch routing mode
                        if model_provider not in ("local", "iris_local", "ollama"):
                            cfg.routing.mode = RoutingMode.SINGLE_API
                            cfg.inference.swarm_enabled = False
                            self._logger.info(
                                "[Session: %s] Routing mode set to SINGLE_API for '%s'",
                                session_id, model_provider,
                            )

                    cfg = with_modify_config(_update_model_config)
                    self._logger.info(
                        "[Session: %s] Model config persisted via IRISConfig "
                        "(provider=%s, model=%s)",
                        session_id, model_provider, reasoning_model,
                    )
                    # Broadcast the FULL inference snapshot (not just
                    # role_bindings) so every useInferenceState() instance —
                    # dashboard, ModelSwitcher, SidePanel, WheelView — gets
                    # providers + model_catalog too. A payload missing
                    # `providers` fails the frontend's guard and the whole
                    # update is silently dropped (that was the ModelSwitcher
                    # desync bug).
                    try:
                        from backend.agent.inference.snapshot import (
                            build_inference_snapshot,
                        )

                        _router = getattr(agent_kernel, "_router", None)
                        _snap = build_inference_snapshot(_router)
                        await self._ws_manager.broadcast_to_session(
                            session_id,
                            {
                                "type": "role_bindings_updated",
                                "payload": _snap,
                            },
                        )
                    except Exception as _be:
                        self._logger.warning(
                            "[Session: %s] Failed to broadcast role_bindings_updated: %s",
                            session_id, _be,
                        )
                except Exception as _e2:
                    self._logger.error(
                        "[Session: %s] Failed to persist model config via IRISConfig: %s",
                        session_id, _e2,
                        exc_info=True,
                    )

                # Persist to session state so downstream handlers
                # (e.g. get_available_models) read the correct provider
                # instead of falling back to "lmstudio".
                try:
                    _ssm = await self._state_manager._get_session_state_manager(
                        session_id
                    )
                    if _ssm:
                        _ssm.set_field_value(
                            "model_selection", "model_provider", model_provider
                        )
                        if reasoning_model:
                            _ssm.set_field_value(
                                "model_selection",
                                "reasoning_model",
                                reasoning_model,
                            )
                        if tool_execution_model:
                            _ssm.set_field_value(
                                "model_selection",
                                "tool_execution_model",
                                tool_execution_model,
                            )
                except Exception:
                    self._logger.warning(
                        "[Session: %s] Failed to persist model_selection to session state",
                        session_id,
                        exc_info=True,
                    )
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
                            "model_provider": model_provider,
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
                            "model_provider": model_provider,
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

        # Include the authoritative active conversation id so the frontend can
        # adopt it on (re)connect.  The backend owns _active_conversation_id per
        # session (updated on new_conversation / switch_conversation), so this is
        # the tiebreaker when the frontend's localStorage and the backend disagree
        # after a backend restart, drag-induced remount, or reconnect.  Without
        # this the frontend could keep its stale id while the backend is pointed
        # elsewhere, causing a wake-word response to land in the WRONG thread.
        active_cid = self._active_conversation_id.get(session_id)

        await self._ws_manager.send_to_client(
            client_id,
            {
                "type": "initial_state",
                "payload": {
                    "state": state.model_dump() if state else {},
                    "current_conversation_id": active_cid,
                },
            },
        )

        # T10c (REQ-7 AC3): surface the PERSISTED local_model_status on every
        # WS open/reconnect. T10a persists "error" to cfg.inference on a
        # failed load, but the only channel that read it back
        # (_handle_get_local_model_status) returns the LIVE manager view
        # (loaded: bool, no status/error field at all) — so a failed load
        # was invisible after a page reload no matter what the frontend did.
        # Read the persisted value DIRECTLY here (never the manager's live
        # view) and push it on the SAME `local_model_status` channel the
        # load/unload handlers already use — useIRISWebSocket.ts merges it
        # into the badge and re-dispatches `iris:local_model_status` on
        # every occurrence, not just first mount, so this covers reconnect
        # for real. Reconciling "config says loaded but nothing is
        # listening" to UNLOADED (REQ-7 edge case) stays the LIVE check's
        # job (_handle_get_local_model_status, called by the frontend on
        # mount) — this seam only supplies persisted truth, it never
        # second-guesses it. A failed config read must never propagate into
        # the WS handler (this fires on every reconnect); degrade to
        # "unloaded" and log instead.
        try:
            from .iris_config import load_config as _load_cfg_for_status

            _persisted_status = (
                getattr(
                    _load_cfg_for_status().inference, "local_model_status", "unloaded"
                )
                or "unloaded"
            )
        except Exception as _status_err:
            self._logger.warning(
                "[Session: %s] request_state: persisted local_model_status "
                "read failed, degrading to 'unloaded': %s",
                session_id, _status_err,
            )
            _persisted_status = "unloaded"

        await self._ws_manager.send_to_client(
            client_id,
            {
                "type": "local_model_status",
                "payload": {"status": _persisted_status},
            },
        )

        # Push the FULL inference snapshot (providers + role_bindings +
        # provider_presets + model_catalog) on request_state — the frontend
        # sends request_state on EVERY open and reconnect (useIRISWebSocket
        # :415, Tauri path :1954), so this single seam covers page load,
        # reconnect, remount, drag, and Tauri.  Previously the inference cards
        # depended on the frontend's one-shot mount-time REST fetch, which
        # raced backend startup and left the Provider/Model dropdowns empty
        # until a manual refresh (root-caused 2026-08-12, pin_05511443f03b).
        # peek_active_kernel NEVER constructs a kernel (71.8s cold measured),
        # and build_inference_snapshot(None) still returns the full key set
        # with static provider_presets/model_catalog, so the dropdown
        # populates even before the first kernel exists.  Reusing the SAME
        # builder as the other emission sites keeps the key-parity contract
        # (test_inference_snapshot_key_parity.py) true by construction.
        try:
            from backend.agent.inference.snapshot import build_inference_snapshot
            from backend.agent.agent_kernel import peek_active_kernel

            _kernel = peek_active_kernel(session_id)
            _router = getattr(_kernel, "_router", None) if _kernel else None
            _snap = build_inference_snapshot(_router)
            await self._ws_manager.send_to_client(
                client_id,
                {"type": "role_bindings_updated", "payload": _snap},
            )
        except Exception as _snap_err:
            self._logger.warning(
                "[Session: %s] request_state inference snapshot push failed: %s",
                session_id, _snap_err,
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

            # REQ-10 AC3: drop the session from the coupling registry so it does
            # not accumulate as a phantom partner that dilutes coupling. Guarded
            # by the same flag that gates registration (REQ-10 AC4).
            try:
                from backend.agent.coupled_registry import (
                    coupling_enabled,
                    get_coupled_registry,
                )

                if coupling_enabled():
                    get_coupled_registry().unregister_session(session_id)
            except Exception:
                pass

            # Reset per-session LFM ChatState
            try:
                from .audio.engine import get_audio_engine

                engine = get_audio_engine()
                if engine.model_manager and engine.model_manager.is_loaded:
                    engine.model_manager.reset_session(session_id)
            except Exception:
                pass

            # ── REQ-16 (T32): real session-end wiring for the outer loop. ──
            # cleanup_session is the production session boundary (WS disconnect
            # / session teardown). This is where the outer loop's observations
            # become LIVE: archive the session (record_session_exit via
            # ConversationMemory.archive_on_session_end — memory.py:342 path,
            # previously with ZERO production callers) and then fire
            # run_outer_loop — previously ZERO production call sites (REQ-16
            # Verified). Strictly off the critical path; never raises.
            try:
                from backend.agent import get_active_kernel

                _kernel = get_active_kernel(session_id)
                _mem = getattr(_kernel, "_conversation_memory", None)
                if _mem is not None and (
                    getattr(_mem, "messages", None)
                    or getattr(_mem, "task_records", None)
                ):
                    # AC2: record_session_exit from a REAL session end.
                    _archived = _mem.archive_on_session_end()
                    self._logger.info(
                        f"[Session: {session_id}] archive_on_session_end="
                        f"{_archived} (REQ-16 AC2)"
                    )
            except Exception as _arch_exc:
                self._logger.debug(
                    f"[Session: {session_id}] session-end archive failed: "
                    f"{_arch_exc}"
                )

            try:
                # AC1: the outer loop fires at a real session boundary.
                from backend.agent.outer_loop import run_outer_loop

                _ol = run_outer_loop(session_id)
                if _ol:
                    self._logger.info(
                        f"[Session: {session_id}] outer loop ran: "
                        f"applied={_ol.get('applied')} "
                        f"key={_ol.get('key')} value={_ol.get('value')}"
                    )
            except Exception as _ol_exc:
                self._logger.debug(
                    f"[Session: {session_id}] outer loop skipped: {_ol_exc}"
                )

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

    async def _resolve_vision_availability(self, session_id: str) -> bool:
        """T16: True when vision can be served RIGHT NOW at ANY tier.

        Tier 1/2 (a bound brain/tool already sees) reports available
        immediately — no server is touched, no llama-server spawned. Tier 3
        falls back to the EXISTING LFM2.5-VL llama-server health check
        (unchanged — CT-3 owns that lifecycle). A resolution failure,
        including REQ-3 AC4's "nothing fits" (``VisionModelUnavailable``),
        reports unavailable rather than raising into the WS handler.
        """
        import asyncio

        loop = asyncio.get_event_loop()
        try:
            from .agent.agent_kernel import get_agent_kernel
            from .agent.inference.router import resolve_vision_client
            from .tools.lfm_vl_provider import VisionModelUnavailable

            router = getattr(get_agent_kernel(session_id), "_router", None)
            resolution, _client = await loop.run_in_executor(
                None, resolve_vision_client, router
            )
        except VisionModelUnavailable as exc:
            self._logger.info(
                f"[Session: {session_id}] vision unavailable at any tier: {exc}"
            )
            return False
        except Exception as exc:
            self._logger.warning(
                f"[Session: {session_id}] vision hierarchy resolution failed, "
                f"falling back to tier-3 health check: {exc}"
            )
            return await loop.run_in_executor(None, self._vision_provider.health_check)

        if resolution is not None and resolution.tier in ("brain", "tool"):
            return True  # already-live provider — nothing to probe

        return await loop.run_in_executor(None, self._vision_provider.health_check)

    async def _handle_enable_vision(self, session_id: str, client_id: str) -> None:
        """
        Handle enable_vision message — resolves the vision hierarchy (T16):
        a vision-capable brain/tool already bound (tier 1/2) is available
        with no server touched; otherwise falls back to the existing
        LFM2.5-VL llama-server health check, unchanged.
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
                        "model_name": "lfm2.5-vl-3b",
                        "quantization_enabled": False,
                        "is_available": False,
                    },
                },
            )

            available = await self._resolve_vision_availability(session_id)

            status_payload = {
                "status": "enabled" if available else "error",
                "vram_usage_mb": None,
                "load_progress_percent": None,
                "error_message": None
                if available
                else f"Vision server not running on port {_VISION_PORT}. Enable Vision from the UI or run start_vl.bat.",
                "model_name": "lfm2.5-vl-3b",
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
                        "model_name": "lfm2.5-vl-3b",
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
        Handle get_vision_status message — resolves the vision hierarchy
        (T16); pings the LFM2.5-VL server only when tier 1/2 cannot see.
        """
        try:
            available = await self._resolve_vision_availability(session_id)
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
                        else f"Vision server not running on port {_VISION_PORT}",
                        "model_name": "lfm2.5-vl-3b",
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

    def _infer_local_purpose(self, session_id: str) -> str:
        """Return ``"tool"`` when a REMOTE provider already holds the reasoning
        role, else ``"chat"``.

        "chat" means the local model is (or may become) the Brain, so it needs
        its full context — a local Brain does its own tool calling. "tool" means
        an API/Ollama provider is reasoning and the local model only executes
        steps, so it can be sized down.

        Fails to ``"chat"`` on any error: over-provisioning context costs VRAM,
        under-provisioning a Brain silently truncates its window.
        """
        try:
            from .agent.agent_kernel import peek_active_kernel
            from .agent.inference.provider import ProviderKind

            kernel = peek_active_kernel(session_id)
            router = getattr(kernel, "_router", None) if kernel else None
            if router is None:
                return "chat"
            inst = router.resolve("reasoning")
            remote = {ProviderKind.API, ProviderKind.OLLAMA}
            return "tool" if getattr(inst, "kind", None) in remote else "chat"
        except Exception as exc:
            self._logger.debug(f"[LocalModel] purpose inference fell back: {exc}")
            return "chat"

    async def _handle_load_local_model(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """Spawn llama-cpp-python server subprocess for the selected GGUF."""
        from .agent.local_model_manager import get_local_model_manager

        payload = message.get("payload", message)
        model_path = payload.get("model_path", "")
        profile = payload.get("profile", "balanced")
        custom_params = payload.get("custom_params", {})
        # REQ-4 AC1/AC2, CT-5: default to attaching a matching vision
        # projector. A sender written before this key existed simply omits
        # it — `.get(..., True)` reproduces the new default for that payload
        # rather than requiring every caller to be updated in lockstep.
        with_projector = bool(payload.get("with_projector", True))

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

            # Decide what this local model is FOR before sizing it.
            #
            # If a remote provider already holds the reasoning role, the local
            # model is only ever going to turn a step into a tool call — it sees
            # tool schemas and one step, not the brain's window — so it is loaded
            # with the tool context cap and leaves VRAM free. If the local model
            # will BE the brain (reasoning unbound, or already bound to a local
            # provider) it does its own tool calling and gets the full window.
            #
            # Only one local model fits on a single consumer GPU at a time, so
            # the memory a tool-only model does not take is memory nothing else
            # can use. An explicit payload `purpose` overrides the inference.
            purpose = payload.get("purpose") or self._infer_local_purpose(session_id)
            self._logger.info(
                f"[LocalModel] loading {model_path} purpose={purpose} "
                f"profile={profile} with_projector={with_projector}"
            )

            # Only pass with_projector when the caller actually opted OUT of
            # the default. LocalModelManager.load_model()'s own default is
            # already "attach" (REQ-4 AC1), so the common case reproduces the
            # exact pre-T8 call shape — narrower callables that pre-date this
            # parameter (e.g. test doubles standing in for the manager) still
            # work unchanged, and only the opt-out path needs the new kwarg.
            _load_kwargs: Dict[str, Any] = {
                "purpose": purpose,
                "progress_cb": _progress_cb,
                "crash_cb": _crash_cb,
            }
            if not with_projector:
                _load_kwargs["with_projector"] = False
            ok = await mgr.load_model(model_path, profile, custom_params, **_load_kwargs)
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

                # Persist the loaded model to config.
                #
                # This used to write ONLY local_model_status="loaded", leaving
                # local_model_path/local_model_id empty and the provider itself
                # unpersisted — it lived on the in-memory registry and nowhere
                # else. After a restart the role_bindings entry still named
                # "local:<stem>" but no such provider existed, so resolve() fell
                # back to whatever default was around, while the config claimed
                # a model was loaded. Writing the ProviderEntry alongside the
                # path/id keeps the binding resolvable across the restart.
                try:
                    from pathlib import Path as _P

                    from .iris_config import ProviderEntry as _PE
                    from .iris_config import load_config as _lc, save_config as _sc

                    _cfg = _lc()
                    _stem_p = _P(model_path).stem
                    _cfg.inference.local_model_status = "loaded"
                    _cfg.inference.local_model_path = model_path
                    _cfg.inference.local_model_id = _stem_p
                    _cfg.inference.local_model_profile = profile
                    _inproc_p = getattr(mgr, "_llm", None) is not None
                    _cfg.inference.providers[f"local:{_stem_p}"] = _PE(
                        id=f"local:{_stem_p}",
                        label=f"Local: {_P(model_path).name}",
                        kind="INPROCESS" if _inproc_p else "LOCAL_OPENAI",
                        model=_stem_p,
                        purpose="chat",
                        endpoint="" if _inproc_p else mgr.ENDPOINT,
                        model_path=model_path,
                        profile=profile,
                    )
                    _sc(_cfg)
                except Exception as cfg_err:
                    self._logger.debug(f"[iris_local] status save skipped: {cfg_err}")

                # [SLICE 3] Register the loaded local model as a first-class
                # ProviderInstance in the InferenceRouter registry so the
                # frontend can bind roles to it and the router can route to it.
                try:
                    from pathlib import Path as _Path

                    from .agent import get_agent_kernel as _get_kernel
                    from .agent.inference.provider import (
                        ProviderInstance,
                        ProviderKind,
                    )

                    _kernel = _get_kernel(session_id)
                    _router = getattr(_kernel, "_router", None)
                    if _router is not None:
                        _inproc = getattr(mgr, "_llm", None) is not None
                        _stem = _Path(model_path).stem
                        # REQ-4 AC4 / REQ-1 AC3: read back whether --mmproj was
                        # ACTUALLY passed to the server that just came up —
                        # never inferred from a sibling projector file merely
                        # existing on disk.
                        _vision_loaded = bool(mgr.get_status().get("vision_loaded", False))
                        _local_inst = ProviderInstance(
                            id=f"local:{_stem}",
                            label=f"Local: {_Path(model_path).name}",
                            kind=(
                                ProviderKind.INPROCESS
                                if _inproc
                                else ProviderKind.LOCAL_OPENAI
                            ),
                            model=_stem,
                            api_base_url="" if _inproc else mgr.ENDPOINT,
                            loaded=True,
                            vision_loaded=_vision_loaded,
                        )
                        # Register on the process-wide registry ONCE. Every
                        # kernel shares this registry (REQ-5), so no peer
                        # fan-out loop is needed — the local provider is
                        # visible across all conversation threads
                        # automatically, including the /api/inference/state
                        # endpoint which reads the shared registry.
                        _router.add_provider(_local_inst)
                        if _inproc:
                            _router.set_inprocess_manager(mgr)
                        self._logger.info(
                            f"[SLICE3] Registered local provider 'local:{_stem}' "
                            f"(kind={_local_inst.kind.value}, session {session_id})"
                        )
                        # Send the FULL provider dict, not a hand-picked subset.
                        # The subset omitted `loaded`, and the ModelSwitcher
                        # admits a non-API provider only when `loaded` is truthy
                        # — so a model that was demonstrably resident in VRAM
                        # never appeared in the Brain/Tool dropdowns.
                        await self._ws_manager.broadcast_to_session(
                            session_id,
                            {
                                "type": "provider_added",
                                "payload": _local_inst.to_dict(),
                            },
                        )
                        # …and re-emit the whole inference snapshot, so every
                        # useInferenceState() consumer re-derives its provider
                        # list from one authoritative payload instead of
                        # patching in a single entry.
                        await self._broadcast_inference_snapshot(
                            session_id, _router
                        )
                except Exception as reg_err:
                    self._logger.warning(
                        f"[SLICE3] Local provider registration failed: {reg_err}"
                    )

                # Drive the dashboard's MODEL STATUS badge. The load path only
                # ever sent `local_model_loading` (a progress channel); the badge
                # listens on `local_model_status`, so it sat at UNLOADED even
                # after a successful load.
                # Send to the REQUESTING CLIENT as well as the session.
                # broadcast_to_session silently returns when the session lookup
                # misses, and the MODEL STATUS badge is driven only by this
                # message while the progress bar is driven by send_to_client —
                # which is why a load could complete, wire the kernel and
                # register the provider while the badge still read UNLOADED.
                # The initiator must always be told, session or no session.
                _status_msg = {
                    "type": "local_model_status",
                    "payload": {
                        "loaded": True,
                        "status": "loaded",
                        "model_path": model_path,
                        "profile": profile,
                    },
                }
                await self._ws_manager.send_to_client(client_id, _status_msg)
                await self._ws_manager.broadcast_to_session(
                    session_id, _status_msg, exclude_clients={client_id}
                )

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
            else:
                # Same badge channel on the failure path, so a load that did not
                # come up is shown as ERROR rather than left at whatever the
                # badge said before.
                _err_msg = {
                    "type": "local_model_status",
                    "payload": {
                        "loaded": False,
                        "status": "error",
                        "model_path": model_path,
                        "error": payload_out.get("error", "Model load failed"),
                    },
                }
                await self._ws_manager.send_to_client(client_id, _err_msg)
                await self._ws_manager.broadcast_to_session(
                    session_id, _err_msg, exclude_clients={client_id}
                )

                # Persist the failure to config (REQ-7 AC3/AC4, T10a). Without
                # this, a failed load left the config field exactly as it was
                # (usually "unloaded"), so after a reload ERROR was
                # indistinguishable from "never loaded". Same
                # load-config/mutate/save-config shape as the success and
                # unload branches above.
                try:
                    from .iris_config import load_config as _lc, save_config as _sc

                    _cfg = _lc()
                    _cfg.inference.local_model_status = "error"
                    _sc(_cfg)
                except Exception as cfg_err:
                    self._logger.debug(f"[iris_local] error status save skipped: {cfg_err}")
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

            # Persist unloaded status to config (parity with load handler).
            try:
                from .iris_config import load_config as _lc, save_config as _sc

                _cfg = _lc()
                _cfg.inference.local_model_status = "unloaded"
                _sc(_cfg)
            except Exception as cfg_err:
                self._logger.debug(f"[iris_local] status save skipped: {cfg_err}")

            # [10.7] De-wire the kernel â€” prevent stale requests to dead :8082 endpoint
            # AND release the in-process adapter binding so the next model load
            # starts from a clean slate.
            try:
                from .agent import get_agent_kernel

                kernel = get_agent_kernel(session_id)
                kernel.configure_openai_compat(None)
                if hasattr(kernel, "configure_inprocess_local"):
                    kernel.configure_inprocess_local(None)
                # Remove the local provider(s) from the router registry so the
                # Brain/Tool dropdowns no longer list them. The load path
                # registers a NAMESPACED id ("local:<stem>", REQ-4 AC1) — this
                # used to remove the bare literal "local", which was never
                # registered, so an unloaded model stayed in the registry with
                # loaded=True forever. Remove every local entry plus the legacy
                # bare id.
                router = getattr(kernel, "_router", None)
                if router is not None:
                    _local_ids = [
                        i.id
                        for i in router.registry.list()
                        if i.id == "local" or i.id.startswith("local:")
                    ]
                    for _lid in _local_ids:
                        router.remove_provider(_lid)
                    self._logger.info(
                        f"[iris_local] Removed local provider(s) {_local_ids} "
                        f"from registry (session {session_id})"
                    )
                self._logger.info(
                    f"[iris_local] Kernel de-wired after unload (session {session_id})"
                )
            except Exception as kw_err:
                self._logger.debug(f"[iris_local] Kernel de-wire skipped: {kw_err}")

            # Re-emit the snapshot so every model surface drops the unloaded
            # provider immediately instead of at the next system_status tick.
            await self._broadcast_inference_snapshot(session_id)

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
    async def _handle_reformat_document(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """Re-render a document in a different format on user request.

        Receives {document_id, format, turn_id, conversation_id, original_format}
        from the frontend (a format-pill click) — W5 drops the client ``content``
        so the backend retrieves the canonical data by id. Runs the reformat in
        an executor (non-blocking) and emits a document:render event with the new
        format; the frontend swaps the rendered document on that event.
        """
        payload = (message or {}).get("payload", {})
        document_id = payload.get("document_id", "")
        target_format = payload.get("format", "")
        turn_id = payload.get("turn_id")
        conversation_id = payload.get("conversation_id") or session_id
        original_format = payload.get("original_format")
        # Trust-routing W3: carry the original document's trust level through
        # reformat so a reformatted untrusted doc stays untrusted.
        trust = payload.get("trust")

        if not document_id or not target_format:
            try:
                if self._ws_manager:
                    await self._ws_manager.send_to_client(
                        client_id,
                        {
                            "type": "reformat_document_error",
                            "payload": {"error": "document_id and format are required"},
                        },
                    )
            except Exception:
                pass
            return

        # Ack immediately so the UI can show a spinner.
        try:
            if self._ws_manager:
                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "reformat_document_ack",
                        "payload": {"status": "processing", "format": target_format},
                    },
                )
        except Exception:
            pass

        try:
            kernel = get_agent_kernel(conversation_id, session_id)
            loop = asyncio.get_event_loop()

            def _do():
                return kernel.reformat_document(
                    document_id=document_id,
                    target_format=target_format,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    original_format=original_format,
                    trust=trust,
                )

            await loop.run_in_executor(None, _do)
        except Exception as exc:
            self._logger.warning("[iris_gateway] reformat_document failed: %s", exc)
            try:
                if self._ws_manager:
                    await self._ws_manager.send_to_client(
                        client_id,
                        {
                            "type": "reformat_document_error",
                            "payload": {"error": str(exc)},
                        },
                    )
            except Exception:
                pass

    async def _handle_get_documents(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """WS handler (T3, REQ-4/REQ-12): return conv-scoped rendered-document
        metadata for frontend re-hydration on resume/switch.

        Response uses the EXISTING wrapped convention
        ``{type:"documents", payload:{documents:[...]}}`` (matches
        ``reformat_document_ack``), NOT a flat shape. Scoped by
        ``conversation_id`` so other threads are never returned (REQ-12 thread
        isolation). Unknown/empty conversation -> empty list, never raises.
        """
        payload = (message or {}).get("payload", {})
        conversation_id = payload.get("conversation_id") or session_id
        documents: list = []
        try:
            if conversation_id:
                from backend.agent.agent_kernel import get_agent_kernel
                from backend.agent.document_store import DocumentDataStore

                kernel = get_agent_kernel(conversation_id, session_id)
                store = kernel._get_document_store() if kernel is not None else None
                if store is not None:
                    # metadata_only stays True. CT-DOC-1 pins this payload as
                    # metadata-only (`assert "content" not in d`) — the body is
                    # deliberately NOT carried here and is fetched on expand.
                    # The blank-card bug this looked like a fix for is handled
                    # where it belongs: the live render path keys on
                    # document_id so same-turn documents keep their own bodies,
                    # and chat-view refuses to draw a card with no body.
                    rows = store.list_for_conversation(
                        conversation_id, metadata_only=True
                    )
                    documents = [
                        {
                            "document_id": r.get("document_id"),
                            "format": r.get("format"),
                            "conversation_id": r.get("conversation_id"),
                            "sources": r.get("sources") or [],
                            "har_path": r.get("har_path"),
                            "created_at": r.get("created_at"),
                            # Which exchange produced this render. Without it the
                            # frontend cannot pair a rehydrated card with its
                            # turn, so the answer text and its card both render
                            # independently — and the agent cannot say which
                            # question a previous markdown was answering when it
                            # compares old findings against new ones.
                            "turn_id": r.get("turn_id"),
                        }
                        for r in rows
                    ]
            self._logger.info(
                "[iris_gateway] GET DOCS conv=%s returned=%d",
                conversation_id,
                len(documents),
            )
        except Exception as exc:
            self._logger.warning("[iris_gateway] get_documents failed: %s", exc)
            documents = []
        try:
            if self._ws_manager:
                await self._ws_manager.send_to_client(
                    client_id,
                    {"type": "documents", "payload": {"documents": documents}},
                )
        except Exception:
            pass

    async def _handle_get_cards(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """WS handler (T7a, REQ-4 AC2/AC4/AC5): return conv-scoped persisted
        task-card state so the frontend can rehydrate cards on a fresh
        conversation open/switch — the read half of T4/T4a's write path.

        Response uses the SAME wrapped convention as ``_handle_get_documents``
        (``{type:"cards", payload:{cards:[...]}}``), not a flat shape.
        Scoped by ``conversation_id`` so other threads are never returned
        (mirrors REQ-12 thread isolation). Unknown/empty conversation ->
        empty list, never raises.

        Cards come back through ``ConversationContextStore.get_cards_for_conversation``,
        which ALREADY resolves a card left ``terminal_state == "running"`` into
        "terminated_unknown" on read (a process that crashed mid-task never
        gets a turn to write its own terminal state) — that value is passed
        through here UNCHANGED (AC5: transport faithfully, do not
        re-decide it a second time in the gateway).
        """
        payload = (message or {}).get("payload", {})
        conversation_id = payload.get("conversation_id") or session_id
        cards: list = []
        try:
            if conversation_id:
                from backend.agent.conversation_context_store import get_context_store

                store = get_context_store()
                card_states = store.get_cards_for_conversation(conversation_id)
                cards = [c.to_dict() for c in card_states]
            self._logger.info(
                "[iris_gateway] GET CARDS conv=%s returned=%d",
                conversation_id,
                len(cards),
            )
        except Exception as exc:
            self._logger.warning("[iris_gateway] get_cards failed: %s", exc)
            cards = []
        try:
            if self._ws_manager:
                await self._ws_manager.send_to_client(
                    client_id,
                    {"type": "cards", "payload": {"cards": cards}},
                )
        except Exception:
            pass

    # ── SLICE 5: router-based role binding + swarm routing ──────────────

    async def _persist_and_broadcast_role_bindings(
        self, session_id: str, kernel: "AgentKernel"
    ) -> None:
        """Persist current router role bindings to config and broadcast them.

        Single source of truth for the frontend's provider/role selection UI.
        """
        _router = getattr(kernel, "_router", None)
        if _router is None:
            return
        from backend.agent.inference.snapshot import build_inference_snapshot

        snap = build_inference_snapshot(_router)
        try:
            from .iris_config import load_config as _lc, save_config as _sc

            _cfg = _lc()
            _cfg.inference.role_bindings = snap["role_bindings"]
            # Keep the legacy provider field consistent with the canonical
            # role_bindings (reasoning role's instance) so the config file and
            # /api/inference/state always agree with actual routing.
            try:
                _reasoning_provider = next(
                    (
                        b["instance_id"]
                        for b in snap["role_bindings"]
                        if b.get("role") == "reasoning" and b.get("instance_id")
                    ),
                    None,
                )
                if _reasoning_provider:
                    _cfg.inference.provider = _reasoning_provider
                    # Also sync the api_base_url dynamically from the canonical
                    # provider registry so the config never carries a stale
                    # endpoint (e.g. cohere's URL while provider=cerebras).
                    try:
                        from backend.agent.inference.provider import (
                            get_provider_default_endpoint,
                        )

                        _ep = get_provider_default_endpoint(_reasoning_provider)
                        if _ep:
                            _cfg.inference.api_base_url = _ep
                    except Exception:
                        pass
            except Exception:
                pass
            _sc(_cfg)
        except Exception as _pe:
            self._logger.warning(f"[SLICE5] role_bindings persist failed: {_pe}")
        await self._ws_manager.broadcast_to_session(
            session_id,
            {"type": "role_bindings_updated", "payload": snap},
        )

    async def _set_ollama_loaded(
        self, session_id: Optional[str], endpoint: str, *, loaded: bool
    ) -> None:
        """Record the probed reachability of the local Ollama server on the
        ``ollama`` provider instance and broadcast the change.

        The chat ModelSwitcher admits a non-API provider only when its
        ``loaded`` flag is set — and nothing else ever set it for ollama, so a
        running Ollama server never appeared in the switcher even after the
        Models card was applied. ``loaded`` here means exactly what the probe
        measured: the server answered ``/api/tags`` (models load lazily on the
        server at first call). On a failed probe the flag is only DOWNGRADED
        when the instance already exists — a dead server must not conjure a
        phantom provider entry. Never raises: this is a side-channel of the
        availability probe and must not break get_available_models.
        """
        try:
            from .agent import get_agent_kernel as _gk
            from .agent.inference.provider import (
                ProviderInstance,
                ProviderKind,
            )

            _kernel = _gk(session_id or "default")
            _router = getattr(_kernel, "_router", None)
            if _router is None:
                return
            _prev = _router.registry.get("ollama")
            if _prev is None and not loaded:
                return
            _router.add_provider(
                ProviderInstance(
                    id="ollama",
                    label="Ollama",
                    kind=ProviderKind.OLLAMA,
                    model=(_prev.model if _prev else None),
                    api_base_url=endpoint,
                    loaded=loaded,
                )
            )
            await self._broadcast_inference_snapshot(
                session_id, _router
            )
        except Exception as exc:
            self._logger.debug(
                "[Session: %s] ollama loaded-flag update skipped: %s",
                session_id, exc,
            )

    async def _route_kernel_to_swarm(
        self, kernel: "AgentKernel", session_id: str, cfg: Any
    ) -> None:
        """Register swarm_director + swarm_worker router instances and bind roles.

        Replaces the legacy ``configure_openai_compat`` swarm routing so all
        DER/Pacman inference paths (which call ``router.generate``) actually
        flow through the swarm endpoints instead of being silently bypassed.
        """
        from pathlib import Path as _Path

        from .agent.inference.provider import ProviderInstance, ProviderKind

        _router = getattr(kernel, "_router", None)
        if _router is None:
            return

        # Capture pre-swarm bindings so stop_swarm can restore them.
        if not hasattr(_router, "_pre_swarm_bindings"):
            _router._pre_swarm_bindings = [
                (b.role, b.instance_id, b.model_override)
                for b in _router.roles.list()
            ]

        # Director instance
        if getattr(cfg, "use_api_director", False):
            _api_base = getattr(kernel, "_api_base_url", "") or ""
            if not _api_base:
                try:
                    from .iris_config import load_config as _lc

                    _api_base = getattr(_lc().inference, "api_base_url", "") or ""
                except Exception:
                    _api_base = ""
            _dir_inst = ProviderInstance(
                id="swarm_director",
                label="Swarm Director (API)",
                kind=ProviderKind.API,
                model=getattr(kernel, "_selected_reasoning_model", None)
                or getattr(cfg, "director_model", None),
                api_base_url=_api_base,
            )
        else:
            _dir_model = (
                _Path(getattr(cfg, "director_model", "") or "").stem
                if getattr(cfg, "director_model", None)
                else "local-model"
            )
            _dir_inst = ProviderInstance(
                id="swarm_director",
                label=f"Swarm Director ({_dir_model})",
                kind=ProviderKind.LOCAL_OPENAI,
                model=_dir_model,
                api_base_url=getattr(cfg, "director_endpoint", "") or "",
            )

        _wrk_model = _Path(getattr(cfg, "worker_model", "") or "").stem or "local-model"
        _wrk_inst = ProviderInstance(
            id="swarm_worker",
            label=f"Swarm Workers ({_wrk_model})",
            kind=ProviderKind.LOCAL_OPENAI,
            model=_wrk_model,
            api_base_url=getattr(cfg, "workers_endpoint", "") or "",
        )

        _router.add_provider(_dir_inst)
        _router.add_provider(_wrk_inst)
        _router.bind_role("reasoning", "swarm_director")
        _router.bind_role("tool_execution", "swarm_worker")

        # Propagate to peer kernels so every session routes through swarm.
        try:
            from backend.agent.agent_kernel import _agent_kernel_instances

            for _sid, _k in _agent_kernel_instances.items():
                if _k is kernel:
                    continue
                _r2 = getattr(_k, "_router", None)
                if _r2 is not None:
                    try:
                        _r2.add_provider(_dir_inst)
                        _r2.add_provider(_wrk_inst)
                        _r2.bind_role("reasoning", "swarm_director")
                        _r2.bind_role("tool_execution", "swarm_worker")
                    except Exception as _pe:
                        self._logger.debug(f"[SLICE5] swarm peer propagate skipped: {_pe}")
        except Exception:
            pass

        self._logger.info(
            f"[SLICE5] Kernel routed to swarm via router: "
            f"director={_dir_inst.kind.value}@{_dir_inst.api_base_url}, "
            f"worker={_wrk_inst.api_base_url}"
        )
        await self._persist_and_broadcast_role_bindings(session_id, kernel)

    async def _unroute_kernel_from_swarm(
        self, kernel: "AgentKernel", session_id: str
    ) -> None:
        """Remove swarm instances and restore pre-swarm role bindings."""
        _router = getattr(kernel, "_router", None)
        if _router is None:
            return
        # Restore pre-swarm bindings (captured when swarm started)
        pre = getattr(_router, "_pre_swarm_bindings", None)
        for b in list(_router.roles.list()):
            try:
                _router.roles.unbind(b.role)
            except Exception:
                pass
        if pre:
            for _role, _inst, _mo in pre:
                try:
                    _router.roles.bind(_role, _inst, _mo)
                except Exception:
                    pass
        else:
            # Fallback: re-bind to the configured default provider
            try:
                from .iris_config import load_config as _lc

                _def_id = getattr(_lc().inference, "provider", None)
                if _def_id and _router.registry.get(_def_id):
                    _router.bind_role("reasoning", _def_id)
                    _router.bind_role("tool_execution", _def_id)
            except Exception:
                pass
        _router.registry.remove("swarm_director")
        _router.registry.remove("swarm_worker")
        self._logger.info(
            "[SLICE5] Kernel unrouted from swarm; roles restored to pre-swarm bindings"
        )
        await self._persist_and_broadcast_role_bindings(session_id, kernel)

    async def _handle_set_role_binding(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """Bind a capability role to a provider instance (frontend SLICE 5).

        Payload: {role, instance_id, model_override?}.
        Guards against binding a role to the local instance when no local
        model is loaded — logs and returns an error instead of a dead binding.
        """
        payload = message.get("payload", {})
        role = payload.get("role")
        instance_id = payload.get("instance_id")
        model_override = payload.get("model_override")

        if not role or not instance_id:
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "role_binding_error",
                    "payload": {
                        "error": "role and instance_id are required",
                        "role": role,
                        "instance_id": instance_id,
                    },
                },
            )
            return

        try:
            from .agent import get_agent_kernel

            kernel = get_agent_kernel(session_id)
            _router = getattr(kernel, "_router", None)
            if _router is None:
                await self._ws_manager.send_to_client(
                    client_id,
                    {
                        "type": "role_binding_error",
                        "payload": {
                            "error": "router unavailable",
                            "role": role,
                            "instance_id": instance_id,
                        },
                    },
                )
                return

            # Normalize the legacy bare "local" id to its namespaced form
            # (REQ-4 AC1) so a partially-migrated id is never a dead binding.
            if instance_id == "local":
                _local_inst = next(
                    (i for i in _router.registry.list() if i.id.startswith("local:")),
                    None,
                )
                if _local_inst is not None:
                    instance_id = _local_inst.id

            # Local-override status flag (NOT a veto, REQ-5 AC4): binding to a
            # local provider whose model is not yet loaded is ALLOWED — the
            # binding is valid and becomes live once the model loads. We only
            # surface a status flag so the UI can warn, instead of rejecting a
            # perfectly valid (future) binding. The role_binding_error channel
            # stays reserved for genuinely invalid bindings (missing role/
            # instance, router unavailable, unknown instance id).
            _binding_status = "ok"
            _inst = _router.registry.get(instance_id)
            if _inst is not None and _inst.id.startswith("local:") and not _inst.loaded:
                _binding_status = "local_not_loaded"

            # Phase 5 REQ-7 AC1: capture the PREVIOUS binding for this role
            # before it is overwritten, so a switch is diagnosable from a
            # single log line ("it switched to the wrong model"). Never a
            # credential — instance ids only (AC2).
            _prev_binding = next(
                (b for b in _router._roles.list() if b.role == role), None
            )
            _prev_instance_id = _prev_binding.instance_id if _prev_binding else None

            # Bind on this kernel's router. The registry and role table are
            # process-wide (REQ-5), so peer kernels observe the same binding
            # automatically — no fan-out loop.
            #
            # This calls the router directly and that is correct. Pins from
            # 2026-08-16 flagged it as a bypass of `AgentKernel.set_role_binding`,
            # whose legacy-field and snapshot syncs therefore never ran for real
            # UI actions. Those syncs are gone — they were copies of state that
            # is now derived — so the two paths are equivalent again, and the
            # single function that mutates a binding is `RoleBindingTable.bind`,
            # one level down, where it has always been. Routing this through the
            # kernel would only couple the gateway to an object that holds no
            # authority over the binding.
            _router.bind_role(role, instance_id, model_override)

            # REQ-7 AC1/AC3: log off the critical path — a logging failure
            # must never fail the bind. High-frequency switching still logs
            # per switch (AC edge case); volume is not a reason to log nothing.
            try:
                self._logger.info(
                    "[set_role_binding] role=%s prev_instance=%s new_instance=%s outcome=%s",
                    role, _prev_instance_id, instance_id, _binding_status,
                )
            except Exception:
                pass

            await self._persist_and_broadcast_role_bindings(session_id, kernel)

            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "role_binding_updated",
                    "payload": {
                        "success": True,
                        "role": role,
                        "instance_id": instance_id,
                        "model_override": model_override,
                        "status": _binding_status,
                        "snapshot": _router.snapshot(),
                    },
                },
            )
        except Exception as e:
            # REQ-7 AC1: outcome=error still names the role and instance ids
            # (never a credential, AC2), so a failed switch is diagnosable too.
            self._logger.error(
                "[set_role_binding] role=%s new_instance=%s outcome=error error=%s",
                role, instance_id, e, exc_info=True,
            )
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "role_binding_error",
                    "payload": {
                        "error": str(e),
                        "role": role,
                        "instance_id": instance_id,
                    },
                },
            )

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
                from .agent import get_agent_kernel

                kernel = get_agent_kernel(session_id)
                mode = cfg.inference.swarm_mode
                try:
                    worker_ctx = int(getattr(cfg.inference, "worker_context", "auto"))
                except (ValueError, TypeError):
                    worker_ctx = 2048
                cfg_swarm = mgr.apply_swarm_mode(mode, worker_ctx)
                await mgr.start_swarm()
                cfg.inference.swarm_enabled = True
                save_config(cfg)
                # SLICE 5: route kernel inference through the router so DER/Pacman
                # actually use the swarm endpoints (replaces configure_openai_compat).
                await self._route_kernel_to_swarm(kernel, session_id, cfg_swarm)
                # Notify dashboard
                await self._ws_manager.broadcast_to_session(
                    session_id,
                    {
                        "type": "swarm_status",
                        "title": "Swarm Started",
                        "message": f"Swarm active â€” {cfg.inference.swarm_worker_count} workers",
                        "progress": 100,
                        "status": "active",
                    },
                )

            elif action == "stop_swarm":
                self._logger.info(f"[Session: {session_id}] Stopping swarm")
                await mgr.stop_swarm()
                cfg.inference.swarm_enabled = False
                save_config(cfg)
                # SLICE 5: de-wire swarm from the router
                try:
                    from .agent import get_agent_kernel

                    kernel = get_agent_kernel(session_id)
                    await self._unroute_kernel_from_swarm(kernel, session_id)
                except Exception as _se:
                    self._logger.warning(f"[SLICE5] swarm unroute failed: {_se}")
                await self._ws_manager.broadcast_to_session(
                    session_id,
                    {
                        "type": "swarm_status",
                        "title": "Swarm Stopped",
                        "message": "All swarm workers terminated",
                        "status": "inactive",
                    },
                )

            else:
                self._logger.warning(
                    f"[Session: {session_id}] Unknown swarm action: {action}"
                )

        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Swarm action failed: {e}", exc_info=True
            )
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "swarm_status",
                    "title": "Swarm Error",
                    "message": str(e),
                    "status": "error",
                },
            )

    # â”€â”€ Local Model Load/Unload Handlers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

    def _ensure_vision_loop(self) -> None:
        """Capture the running event loop for thread-safe idle-stop broadcasts."""
        if getattr(self, "_vision_loop", None) is None:
            try:
                self._vision_loop = asyncio.get_running_loop()
            except RuntimeError:
                self._vision_loop = None

    def _on_vision_idle_stop(self) -> None:
        """Called by the vision idle watchdog (daemon thread) when it stops the server."""
        loop = getattr(self, "_vision_loop", None)
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._broadcast_vision_idle(), loop)
        except Exception:
            pass

    async def _broadcast_vision_idle(self) -> None:
        """Notify all clients that the vision server idled off (still enabled)."""
        try:
            from backend.tools.lfm_vl_provider import _IDLE_TIMEOUT
            await self._ws_manager.broadcast(
                {
                    "type": "vision_status",
                    "payload": {
                        "enabled": True,
                        "running": False,
                        "status": "idle_stopped",
                        "port": _VISION_PORT,
                        "idle_timeout_seconds": _IDLE_TIMEOUT,
                    },
                }
            )
        except Exception:
            pass

    async def _handle_set_vision_enabled(
        self, session_id: str, client_id: str, message: dict
    ) -> None:
        """Start or stop the LFM2.5-VL llama-server subprocess on vision_port."""
        payload = message.get("payload", message)
        enabled = bool(payload.get("enabled", False))
        try:
            from .tools.lfm_vl_provider import get_lfm_vl_provider

            from .tools.lfm_vl_provider import get_lfm_vl_provider
            from backend.tools.lfm_vl_provider import _IDLE_TIMEOUT
            vl = get_lfm_vl_provider()
            # Register idle-stop broadcaster + capture loop once
            if not getattr(self, "_vision_idle_cb_registered", False):
                try:
                    from backend.tools.lfm_vl_provider import set_vision_idle_callback
                    set_vision_idle_callback(self._on_vision_idle_stop)
                    self._vision_idle_cb_registered = True
                except Exception:
                    pass
            self._ensure_vision_loop()
            if enabled:
                # Eagerly spawn the llama-server so vision is ready immediately.
                # It will idle-stop after inactivity and restart on demand.
                started = vl.start()
                status = "running" if started else "not_started"
            else:
                # Signal the provider that vision is disabled -> stop server
                if hasattr(vl, "disable"):
                    vl.disable()
                status = "stopped"
            await self._ws_manager.send_to_client(
                client_id,
                {
                    "type": "vision_status",
                    "payload": {
                        "enabled": enabled,
                        "running": status == "running",
                        "port": _VISION_PORT,
                        "status": status,
                        "idle_timeout_seconds": _IDLE_TIMEOUT,
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

        # --- Unified path: delegate to CrawlOrchestrator (REQ-15, REQ-1) ---
        from .crawler.orchestrator import get_crawl_orchestrator, CrawlProgress

        # listening_state -> processing_tool while researching (REQ-24)
        await send({"type": "listening_state", "payload": {"state": "processing_tool"}})

        def _on_progress(progress: CrawlProgress) -> None:
            ev = progress.event
            pl = progress.payload
            if ev == "CRAWLER_STARTED":
                asyncio.ensure_future(send(
                    {"type": "crawler_started", "query": pl["query"], "url_count": pl["url_count"]}
                ))
            elif ev == "CRAWLER_PAGE_FETCHED":
                asyncio.ensure_future(send(
                    {"type": "crawler_page_fetched", "url": pl["url"],
                     "page_number": pl["page_number"], "total": pl["total"], "host": pl["host"]}
                ))
            elif ev == "OPEN_TAB":
                asyncio.ensure_future(send(
                    {"type": "open_tab", "tab_type": pl["tab_type"],
                     "id": pl["id"], "title": pl["title"], "data": pl["data"]}
                ))
            elif ev == "CRAWLER_ERROR":
                asyncio.ensure_future(send({"type": "crawler_error", "message": pl["message"]}))
            # T12/T14 (REQ-11/REQ-13): surface progress, phase, and parked-source
            # events over WS with the SAME msg_types ux_map defines for the SSE
            # path, so the two transports never diverge (REQ-31 AC4).
            elif ev == "CRAWLER_PROGRESS":
                asyncio.ensure_future(send(
                    {"type": "crawler_progress", "stage": pl.get("stage", ""),
                     "message": pl.get("message", "")}
                ))
            elif ev == "CRAWLER_PHASE":
                asyncio.ensure_future(send(
                    {"type": "task:event", "phase": pl.get("phase", ""),
                     "phase_sequence": pl.get("phase_sequence", 0)}
                ))
            elif ev == "CRAWLER_VISION_ACTION":
                vision_msg = {
                    "type": "crawler_vision_action", "job_id": pl.get("job_id", ""),
                    "url": pl.get("url", ""), "kind": pl.get("kind", ""),
                    "reason": pl.get("reason", ""),
                    "action_index": pl.get("action_index", 0),
                    "total": pl.get("total", 0),
                }
                # REQ-16 AC7: best-effort cursor coordinates for the frontend
                # particle-trail cursor mirror — only present when
                # BrowserSession captured them (click/type: x/y/viewport_w/
                # viewport_h; scroll: scroll_dx/scroll_dy). Copied over only
                # when present so an action with no point (navigate/wait/a
                # failed bounding_box) sends no stray nulls.
                # scroll_y / scroll_height are what let the panel MIRROR the
                # scroll into the iframe the user is watching; capture_page is
                # which captured frame the session is on. This whitelist is the
                # second place a new field can silently die (the other is
                # tool_bridge's _UI_EVENT_DEFAULTS, which forwards wholesale) —
                # anything added to last_action_point must be listed here too.
                for _coord_key in (
                    "x", "y", "viewport_w", "viewport_h",
                    "scroll_dx", "scroll_dy", "scroll_y", "scroll_height",
                    "capture_page",
                ):
                    if _coord_key in pl:
                        vision_msg[_coord_key] = pl[_coord_key]
                asyncio.ensure_future(send(vision_msg))
            elif ev == "CRAWLER_SOURCE_PARKED":
                asyncio.ensure_future(send(
                    {"type": "crawler_source_parked", "url": pl.get("url", ""),
                     "domain": pl.get("domain", ""), "wall_kind": pl.get("wall_kind", ""),
                     "run_id": pl.get("run_id", ""), "question_id": pl.get("question_id", "")}
                ))

        result = await get_crawl_orchestrator().research(
            query, mode="ws", session_id=session_id, on_progress=_on_progress,
        )

        if result.error:
            await send({"type": "crawler_error", "message": result.error})
            await send({"type": "listening_state", "payload": {"state": "idle"}})
            return

        dashboard_data = result.dashboard_data or {}
        cited_markdown = result.cited_markdown or ""

        # Step 6: Summary text response in ChatView + speak a short summary.
        summary = dashboard_data.get("summary", "")

        # Short spoken summary (speak/show design): TTS recites the short
        # summary, NOT the full document. Cap to a spoken length (~500 chars).
        spoken = (summary or f"Found results for: {query}").strip()
        if len(spoken) > 500:
            spoken = spoken[:497].rstrip() + "..."
        _turn_id = str(uuid.uuid4())

        await send(
            {
                "type": "text_response",
                "turn_id": _turn_id,
                "text": (
                    f"{summary or f'Found results for: {query}'} â€” see Dashboard â†’"
                ),
                "sender": "assistant",
            }
        )

        # Speak the short summary in a worker thread (synthesis blocks). The orb
        # transitions processing_conversation -> speaking -> idle are driven by
        # _speak_response; the wrapper guarantees idle even if TTS aborts early
        # (e.g. no engine.pipeline), so the orb can never get stuck.
        def _speak_then_idle(text, sid, cid, tid):
            try:
                self._speak_response(text, sid, _client_id=cid, _turn_id=tid)
            finally:
                try:
                    _loop = self._main_loop or asyncio.get_event_loop()
                    asyncio.run_coroutine_threadsafe(
                        self._ws_manager.send_to_client(
                            cid,
                            {"type": "listening_state", "payload": {"state": "idle"}},
                        ),
                        _loop,
                    )
                except Exception:
                    pass

        threading.Thread(
            target=_speak_then_idle,
            args=(spoken, session_id, client_id, _turn_id),
            daemon=True,
            name="crawler-tts",
        ).start()

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
