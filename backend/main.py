# main.py
# IRISVOICE/backend/main.py - Audio Engine Initialization Diagnostic Logging

import asyncio
import json
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, Any

# Add parent directory to path to allow absolute imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure structured logging
from backend.core.logging_config import setup_backend_logging
logger = setup_backend_logging(log_level=os.environ.get("IRIS_LOG_LEVEL", "INFO"))

"""
IRIS FastAPI Backend Server (Session-Aware)
Main application entry point with WebSocket endpoint and session management.

This server provides:
- WebSocket-based real-time communication
- Session management with state isolation
- Dual-LLM agent system (lfm2-8b reasoning + lfm2.5-1.2b-instruct execution)
- Voice pipeline with wake word detection
- MCP tool integration
- Structured logging
"""

logger.info("Starting IRIS Backend initialization...")
logger.info("  - Importing FastAPI and middleware...")

# CORS configuration for Next.js and Tauri
# In development: Allow localhost origins
# In production: Restrict to specific origins
ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS",
    # port 3000/3001 = Next.js dev; 8080 = iris-launcher dev; tauri = packaged app
    "http://localhost:3000,http://localhost:3001,http://localhost:8080,tauri://localhost,https://tauri.localhost"
).split(",")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware

logger.info("  - Importing session-aware managers...")
# Session-aware managers
from backend.sessions import get_session_manager
from backend.state_manager import get_state_manager
from backend.ws_manager import get_websocket_manager

logger.info("  - Importing models...")
from backend.models import (
    Category, 
    IRISState, 
    ColorTheme, 
    get_sections_for_category,
    SECTION_CONFIGS
)

logger.info("  - Importing audio components...")
# ... other imports remain the same ...
from backend.audio import get_audio_engine
from backend.audio.pipeline import AudioPipeline
from backend.audio.voice_command import VoiceCommandHandler, VoiceState

logger.info("  - Importing agent components...")
from backend.agent import (
    get_personality_engine,
    get_tts_manager,
    get_conversation_memory,
    get_wake_config
)

logger.info("  - Importing MCP components...")
from backend.mcp import (
    get_server_manager,
    get_tool_registry,
    ServerConfig,
    BrowserServer,
    AppLauncherServer,
    SystemServer,
    FileManagerServer,
    GUIAutomationServer
)

logger.info("  - Importing system components...")
from backend.system import (
    get_power_manager,
    get_display_manager,
    get_storage_manager,
    get_network_manager
)

logger.info("  - Importing customize components...")
from backend.customize import (
    get_startup_manager,
    get_behavior_manager,
    get_notification_manager
)

logger.info("  - Importing IRIS Gateway...")
from backend.iris_gateway import get_iris_gateway, IRISGateway

logger.info("  - Importing monitor components...")
from backend.monitor import (
    get_analytics_manager,
    get_log_manager,
    get_diagnostics_manager,
    get_update_manager
)

logger.info("Finished backend.main imports.")


# ============================================================================
# Lifespan Management (Startup & Shutdown) - AUDIO ENGINE INITIALIZATION LOGGING
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown events."""
    import time as _time
    app.state.ready = False   # set True only after full startup
    app.state._started_at = _time.time()
    logger.info("IRIS Backend starting up...")
    
    try:
        # Prune stale UUID session directories older than 7 days.
        # Keeps session_iris* dirs — removes only auto-generated UUID dirs.
        try:
            import time as _cleanup_time
            from pathlib import Path as _Path
            _sessions_root = _Path(__file__).parent / "sessions"
            if _sessions_root.is_dir():
                _cutoff = _cleanup_time.time() - 7 * 86400
                _removed = 0
                for _entry in _sessions_root.iterdir():
                    if _entry.name.startswith("_") or _entry.name.startswith("session_iris"):
                        continue
                    if _entry.is_dir() and _entry.stat().st_mtime < _cutoff:
                        import shutil as _shutil
                        _shutil.rmtree(_entry, ignore_errors=True)
                        _removed += 1
                if _removed:
                    logger.info(f"  - [CLEANUP] Removed {_removed} stale session dirs")
        except Exception as _ce:
            logger.warning(f"  - [CLEANUP] Session dir cleanup failed (non-fatal): {_ce}")

        logger.info("  - Starting session manager...")
        session_manager = get_session_manager()
        await session_manager.start()

        logger.info("  - Initializing state manager...")
        state_manager = get_state_manager()
        
        # ==========================================================================
        # AUDIO ENGINE INITIALIZATION WITH COMPREHENSIVE DIAGNOSTIC LOGGING
        # ==========================================================================
        logger.info("  - Initializing audio engine...")
        start_time = datetime.now()
        
        # Step 1: Get AudioEngine instance via factory function
        try:
            audio_engine = get_audio_engine()
            logger.info(f"    [+] [AUDIO ENGINE] Instance created successfully")
        except Exception as e:
            logger.error(f"    [x] [AUDIO ENGINE] Failed to create instance: {e}")
            raise
        
        # Step 2: Log initialization progress with timestamps
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"  - [AUDIO ENGINE] Instance created in {elapsed:.3f}s")
        
        # ==========================================================================
        # VOICE COMMAND HANDLER INITIALIZATION WITH DIAGNOSTIC LOGGING
        # ==========================================================================
        logger.info("  - Initializing voice command handler...")
        start_time = datetime.now()
        try:
            from backend.audio.voice_command import VoiceCommandHandler, VoiceState
            voice_handler = VoiceCommandHandler(audio_engine)
            app.state.voice_handler = voice_handler
            logger.info(f"    [+] [VOICE HANDLER] Created successfully")
        except Exception as e:
            logger.error(f"    [x] [VOICE HANDLER] Failed to create: {e}")
            raise
        
        # faster-whisper / ctranslate2 warm-up is intentionally deferred.
        # Importing ctranslate2 allocates ~400 MB RAM and initialises a CUDA
        # context on GPU machines.  Running this at startup races with the
        # Next.js dev-server compilation and has caused OOM crashes.
        # Whisper loads lazily on the first voice command instead (~1-2 s).
        logger.info("    [+] [VOICE HANDLER] faster-whisper will load on first voice command (deferred)")
        
        # ==========================================================================
        # IRIS GATEWAY INITIALIZATION WITH DIAGNOSTIC LOGGING
        # ==========================================================================
        logger.info("  - Initializing IRIS Gateway...")
        start_time = datetime.now()
        try:
            from backend.iris_gateway import get_iris_gateway, IRISGateway
            iris_gateway = get_iris_gateway()
            app.state.iris_gateway = iris_gateway
            logger.info(f"    [+] [IRIS GATEWAY] Instance created successfully")
        except Exception as e:
            logger.error(f"    [x] [IRIS GATEWAY] Failed to create: {e}")
            raise
        
        # Step 6: Capture the running event loop for background task dispatch
        try:
            import asyncio
            iris_gateway.set_main_loop(asyncio.get_running_loop())
            logger.info("    [+] [IRIS GATEWAY] Event loop captured")
        except Exception as e:
            logger.error(f"    [x] [IRIS GATEWAY] Failed to capture event loop: {e}")
            raise
        
        # Step 7: Wire VoiceCommandHandler → iris_gateway for 4-pillar voice processing
        try:
            iris_gateway.set_voice_handler(voice_handler)
            logger.info("    [+] [IRIS GATEWAY] Voice handler wired")
        except Exception as e:
            logger.error(f"    [x] [IRIS GATEWAY] Failed to wire voice handler: {e}")
            raise
        
        # ==========================================================================
        # WAKE WORD CALLBACK REGISTRATION WITH DIAGNOSTIC LOGGING
        # ==========================================================================
        logger.info("  - Registering wake word callback...")
        try:
            _main_loop = asyncio.get_running_loop()
            audio_engine.set_wake_word_callback(
                lambda word: asyncio.run_coroutine_threadsafe(
                    on_wake_word(word),
                    _main_loop
                )
            )
            logger.info("    [+] [WAKE WORD] Callback registered")
        except Exception as e:
            logger.error(f"    [x] [WAKE WORD] Failed to register callback: {e}")
            raise
        
        # ==========================================================================
        # WAKE WORD MODEL DISCOVERY AND CONFIGURATION WITH DIAGNOSTIC LOGGING
        # ==========================================================================
        logger.info("  - Discovering wake word models...")
        try:
            from backend.agent.wake_config import get_wake_config as _get_wake_cfg
            _wake_cfg = _get_wake_cfg()
            if not _wake_cfg.get_custom_model_path():
                from backend.voice.wake_word_discovery import WakeWordDiscovery
                _discovered = WakeWordDiscovery().scan_directory()
                if _discovered:
                    _best = _discovered[0]
                    _wake_cfg.config["custom_model_path"] = _best.path
                    _wake_cfg.config["wake_phrase"] = _best.display_name.lower()
                    logger.info(f"    [+] [WAKE WORD] Auto-configured: '{_best.display_name}' -> {_best.path}")
                else:
                    logger.warning("    [~] [WAKE WORD] No wake word models found")
            else:
                logger.debug(f"    - [WAKE WORD] Using custom config: {_wake_cfg.get_custom_model_path()}")
        except Exception as e:
            logger.warning(f"    [~] [WAKE WORD] Discovery failed (non-fatal): {e}")
        
        # ==========================================================================
        # PORCUPINE WAKE WORD INITIALIZATION WITH DIAGNOSTIC LOGGING
        # Wake word failure is NON-FATAL — app still works, just no wake word.
        # A bad access key, missing model, or audio driver issue must never crash
        # the entire backend. The agent kernel, chat, and TTS all work without it.
        # ==========================================================================
        logger.info("  - Initializing Porcupine...")
        try:
            audio_engine.initialize_porcupine()   # reads phrase + sensitivity from WakeConfig
            logger.info("    [+] [PORCUPINE] Initialized with wake word config")
        except Exception as e:
            logger.warning(
                f"    [~] [PORCUPINE] Wake word init failed (non-fatal — voice activation disabled): {e}"
            )
            # Do NOT raise — the app is fully usable without wake word detection.

        # Step 8: Register live-update callback for dynamic wake word changes
        try:
            from backend.agent.wake_config import get_wake_config
            get_wake_config().register_change_callback(audio_engine.reinitialize_porcupine)
            logger.info("    [+] [PORCUPINE] Live wake-word updates registered")
        except Exception as e:
            logger.warning(f"    [~] [PORCUPINE] Wake-word update callback failed (non-fatal): {e}")
        
        # Step 9: Start the AudioEngine so Porcupine frame detection runs
        start_time = datetime.now()
        if not audio_engine.start():
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.warning(f"    [x] [AUDIO ENGINE] Failed to start in {elapsed:.3f}s (mic may be unavailable)")
        else:
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"    [+] [AUDIO ENGINE] Started successfully in {elapsed:.3f}s — Porcupine wake word detection active")
        
        # Step 10: Log overall audio subsystem initialization status
        total_elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"  - [AUDIO SUBSYSTEM] Initialization complete in {total_elapsed:.3f}s")
        logger.debug("  - Audio subsystem ready for wake word detection and voice processing")
        
        # ==========================================================================
        # AGENT KERNEL INITIALIZATION WITH DIAGNOSTIC LOGGING
        # ==========================================================================
        logger.info("  - Initializing agent kernel...")
        try:
            from backend.agent import get_agent_kernel
            from backend.agent.tool_bridge import initialize_agent_tools
            agent_kernel = get_agent_kernel()

            # Initialize tool bridge (async — calls bridge.initialize() which wires
            # all MCP servers: vision, file_manager, browser, etc.).
            # get_agent_tool_bridge() alone only creates the instance but never calls
            # initialize(), leaving _mcp_servers empty and all tool calls failing.
            tool_bridge = await initialize_agent_tools()
            agent_kernel._tool_bridge = tool_bridge

            # Capture main loop so background threads can dispatch WS broadcasts.
            agent_kernel.set_main_loop(asyncio.get_running_loop())

            app.state.agent_kernel = agent_kernel
            logger.info("    [+] [AGENT KERNEL] Initialized successfully")
            logger.info("    [+] [TOOL BRIDGE] MCP servers initialized")
            logger.info("  - LAZY LOADING ACTIVE: Models will NOT be loaded automatically")
            logger.info("  - Models will load only when user selects Local Model inference mode")
        except Exception as e:
            logger.warning(f"  - Warning: Failed to initialize agent kernel: {e}")
            logger.info("  - Agent functionality will be unavailable.")
        
        # ==========================================================================
        # MEMORY SYSTEM INITIALIZATION WITH DIAGNOSTIC LOGGING
        # ==========================================================================
        logger.info("  - Initializing memory system...")
        try:
            from backend.memory import initialise_memory
            
            # Use agent kernel's model router as adapter if available
            adapter = None
            if hasattr(app.state, 'agent_kernel') and app.state.agent_kernel:
                adapter = app.state.agent_kernel._model_router
            
            if adapter:
                memory = await initialise_memory(adapter=adapter)
                app.state.memory = memory
                
                # Wire memory to agent kernel
                if hasattr(app.state, 'agent_kernel') and app.state.agent_kernel:
                    app.state.agent_kernel.set_memory_interface(memory)
                
                logger.info("    [+] [MEMORY SYSTEM] Initialized successfully")
            else:
                logger.warning("  - Memory system: no model adapter available, skipping.")
                app.state.memory = None
        except Exception as e:
            logger.warning(f"  - Warning: Memory system init failed (non-critical): {e}")
            app.state.memory = None
        
        # Apply persisted launch mode (set by iris-launcher before first run)
        try:
            cfg = _load_iris_config()
            persisted_mode = cfg.get("mode", "personal")
            if hasattr(app.state, "agent_kernel") and app.state.agent_kernel:
                app.state.agent_kernel.set_launcher_mode(persisted_mode)
                logger.info(f"    [Mode] Launch mode loaded from config: {persisted_mode}")
        except Exception as exc:
            logger.warning(f"  - Could not apply persisted launch mode: {exc}")

        # ==========================================================================
        # MEMORY SEEDING [5.3] — transfer bootstrap landmarks to runtime Mycelium
        # ==========================================================================
        try:
            from backend.memory.bootstrap_seed import seed_mycelium_from_bootstrap
            n = seed_mycelium_from_bootstrap()
            if n > 0:
                logger.info(f"    [BootstrapSeed] Seeded {n} permanent landmarks into Mycelium")
        except Exception as _seed_err:
            logger.debug(f"  - Bootstrap seed skipped: {_seed_err}")

        app.state.ready = True
        logger.info("IRIS Backend startup completed successfully!")

        # ── Memory watchdog ────────────────────────────────────────────────
        # Graduated response to RSS growth: soft cap → GC + mycelium maint;
        # hard cap → also unload active local LLM.
        try:
            from backend.core.memory_watchdog import watchdog_loop

            async def _on_soft():
                import gc as _gc
                _gc.collect()
                try:
                    from backend.memory.interface import get_memory_interface
                    mem = get_memory_interface()
                    if mem and hasattr(mem, '_mycelium') and mem._mycelium:
                        mem._mycelium.run_maintenance()
                except Exception:
                    pass

            async def _on_hard():
                await _on_soft()
                try:
                    from backend.agent.local_model_manager import get_local_model_manager
                    mgr = get_local_model_manager()
                    if hasattr(mgr, 'unload_active_model'):
                        mgr.unload_active_model()
                except Exception:
                    pass

            app.state.watchdog_task = asyncio.create_task(
                watchdog_loop(on_soft=_on_soft, on_hard=_on_hard),
                name="iris-memory-watchdog",
            )
            logger.info("  [Watchdog] Memory watchdog started")
        except Exception as _wd_err:
            logger.warning(f"  [Watchdog] Could not start watchdog (non-fatal): {_wd_err}")

        # ── Status broadcast loop ──────────────────────────────────────────────
        # Broadcast system status updates to all connected WebSocket clients
        # at adaptive intervals (fast when active, slow when idle).
        try:
            async def _status_broadcast_loop():
                from backend.api.status_snapshot import build_snapshot
                from backend.core.idle_tracker import get_idle_tracker
                last_payload: dict | None = None
                while True:
                    try:
                        tracker = get_idle_tracker()
                        # Fast interval (1s) when user is active, slow (30s) when idle
                        interval = 1.0 if not tracker.is_idle(threshold_s=30.0) else 30.0
                        await asyncio.sleep(interval)
                        snap = await build_snapshot()
                        # Only broadcast if changed
                        if snap != last_payload:
                            last_payload = snap
                            ws_mgr = get_websocket_manager()
                            await ws_mgr.broadcast({
                                "type": "system_status",
                                "payload": snap
                            })
                    except asyncio.CancelledError:
                        return
                    except Exception as e:
                        logger.warning(f"[status_broadcast] error: {e}")

            app.state.status_broadcast_task = asyncio.create_task(
                _status_broadcast_loop(),
                name="iris-status-broadcast",
            )
            logger.info("  [StatusBroadcast] System status broadcast loop started")
        except Exception as _sb_err:
            logger.warning(f"  [StatusBroadcast] Could not start status broadcast (non-fatal): {_sb_err}")

        # Pre-warm the GGUF file metadata cache in the background (filesystem
        # scan only — no model weights loaded, no CUDA initialization).
        # This means the first ModelsScreen open returns instantly instead of
        # re-parsing GGUF binary headers on demand.
        #
        # INTENTIONALLY does NOT call get_hardware_info() here — that function
        # can trigger CUDA driver init (via torch or llama_cpp) which causes a
        # visible memory spike on startup before the user has done anything.
        # Hardware info is fetched lazily when the user first opens ModelsScreen.
        #
        # NOTE: The 30-second background GGUF scan was REMOVED (Domain 16 optimization).
        # scan_models() now runs lazily on first ModelsScreen open via get_available_models().
        # This eliminates the RSS spike at t=30s on every cold start.
        logger.info("  [LocalModel] GGUF scan deferred to first ModelsScreen open (no startup pre-warm)")

    except Exception as e:
        app.state.ready = False
        logger.error(f"[ERROR] Failed to initialize backend: {e}")
        import traceback
        traceback.print_exc()
    
    yield
    
    logger.info("IRIS Backend shutting down...")
    try:
        # Cancel status broadcast and memory watchdog first so they don't log spurious errors during teardown
        if hasattr(app.state, "status_broadcast_task") and app.state.status_broadcast_task:
            app.state.status_broadcast_task.cancel()
            try:
                await app.state.status_broadcast_task
            except asyncio.CancelledError:
                pass
        if hasattr(app.state, "watchdog_task") and app.state.watchdog_task:
            app.state.watchdog_task.cancel()
            try:
                await app.state.watchdog_task
            except asyncio.CancelledError:
                pass
        logger.info("  - Stopping session manager...")
        session_manager = get_session_manager()
        await session_manager.stop()
        
        logger.info("  - Cleaning up audio engine...")
        audio_engine = get_audio_engine()
        audio_engine.cleanup()
        
        logger.info("  - Stopping all servers...")
        server_manager = get_server_manager()
        server_manager.stop_all_servers()
        
        logger.info("IRIS Backend shutdown completed successfully!")
    except Exception as e:
        logger.error(f"[ERROR] Error during shutdown: {e}")
        import traceback
        traceback.print_exc()


# ============================================================================
# FastAPI App Initialization
# ============================================================================

app = FastAPI(
    title="IRIS Backend API",
    description="WebSocket-based backend for IRISVOICE with dual-LLM agent system",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS middleware for Next.js and Tauri integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

logger.info(f"CORS configured with allowed origins: {ALLOWED_ORIGINS}")

# Register status snapshot router
from backend.api.status_snapshot import router as status_snapshot_router
app.include_router(status_snapshot_router)


# ── Idle tracker middleware ────────────────────────────────────────────────
# Touch the idle tracker on every HTTP request so background workers
# (distillation, memory maintenance) know the user is interacting.
# Excludes health-check polls so they don't mask real idle periods.
from backend.core.idle_tracker import get_idle_tracker as _get_idle_tracker
from starlette.middleware.base import BaseHTTPMiddleware as _BaseHTTPMiddleware
from starlette.requests import Request as _Request

class _IdleTrackerMiddleware(_BaseHTTPMiddleware):
    _SKIP_PATHS = frozenset({"", "/", "/health", "/api/status"})

    async def dispatch(self, request: _Request, call_next):
        if request.url.path not in self._SKIP_PATHS:
            try:
                _get_idle_tracker().touch()
            except Exception:
                pass
        return await call_next(request)

app.add_middleware(_IdleTrackerMiddleware)


# ============================================================================
# Health Check Endpoint
# ============================================================================

@app.get("/")
@app.get("/health")
async def health_check():
    """Health check endpoint — used by the frontend WS hook before opening the socket.
    Returns 200 so the hook proceeds to connect immediately instead of retrying."""
    return {"status": "ok", "service": "IRIS Backend"}


@app.get("/ready")
async def readiness_check():
    """Readiness probe — returns 200 only after full startup (agent + memory initialized).
    Frontend or health monitors can poll this before sending the first WS message."""
    is_ready = getattr(app.state, "ready", False)
    if is_ready:
        return {"status": "ready", "service": "IRIS Backend"}
    from fastapi import Response
    return Response(
        content='{"status":"starting","service":"IRIS Backend"}',
        status_code=503,
        media_type="application/json",
    )


@app.get("/first_run")
async def first_run_check():
    """Returns whether this is a first-run install (no model configured yet).
    The frontend shows the setup wizard when first_run=true."""
    try:
        if hasattr(app.state, "agent_kernel") and app.state.agent_kernel:
            provider = getattr(app.state.agent_kernel, "_model_provider", "uninitialized")
            is_first_run = provider in (None, "uninitialized")
        else:
            is_first_run = True
        return {"first_run": is_first_run}
    except Exception:
        return {"first_run": True}


# ============================================================================
# Launcher Mode API — integration with iris-launcher
# ============================================================================

_IRIS_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "iris_config.json"
)


def _load_iris_config() -> dict:
    """Load persisted IRIS config from data/iris_config.json."""
    try:
        if os.path.exists(_IRIS_CONFIG_PATH):
            with open(_IRIS_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_iris_config(data: dict) -> None:
    """Persist IRIS config to data/iris_config.json."""
    try:
        os.makedirs(os.path.dirname(_IRIS_CONFIG_PATH), exist_ok=True)
        with open(_IRIS_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as exc:
        logger.warning(f"[Config] Failed to save iris_config.json: {exc}")


@app.post("/api/mode")
async def set_launcher_mode(request: dict):
    """
    Called by iris-launcher after mode selection.

    Body: { "mode": "personal" | "developer" }

    personal  — standard agent, curated skills, no source code access
    developer — full source access, git integration, diff review, rebuild pipeline
    """
    from fastapi import Response as FastAPIResponse
    mode = (request.get("mode") or "").strip().lower()
    if mode not in ("personal", "developer"):
        return FastAPIResponse(
            content=json.dumps({"error": f"Invalid mode: {mode!r}. Must be 'personal' or 'developer'."}),
            status_code=422,
            media_type="application/json",
        )

    # Persist to disk so the mode survives restarts
    cfg = _load_iris_config()
    cfg["mode"] = mode
    _save_iris_config(cfg)

    # Apply to live agent kernel if running
    try:
        if hasattr(app.state, "agent_kernel") and app.state.agent_kernel:
            app.state.agent_kernel.set_launcher_mode(mode)
    except Exception as exc:
        logger.warning(f"[Mode] Could not apply mode to agent kernel: {exc}")

    logger.info(f"[Mode] Launch mode set to: {mode}")

    # Broadcast mode_changed to all connected WebSocket clients so the
    # IRISVOICE frontend can react immediately without polling.
    try:
        ws_manager = get_websocket_manager()
        await ws_manager.broadcast({"type": "mode_changed", "mode": mode})
    except Exception as exc:
        logger.debug(f"[Mode] WS broadcast skipped (no clients?): {exc}")

    return {"mode": mode, "status": "ok"}


@app.get("/api/mode")
async def get_launcher_mode():
    """Returns the currently configured launch mode."""
    cfg = _load_iris_config()
    mode = cfg.get("mode", None)
    return {"mode": mode}


@app.get("/api/launcher/status")
async def get_launcher_status():
    """
    Returns live agent status for iris-launcher's dashboard.

    iris-launcher displays: activeMode, agentActive, uptime, version.
    Maps to the LauncherStatus type in mock-data.ts.
    """
    import time as _time

    cfg = _load_iris_config()
    mode = cfg.get("mode", "personal")
    agent_active = getattr(app.state, "ready", False)

    # Uptime since backend started
    started_at = getattr(app.state, "_started_at", None)
    if started_at is None:
        uptime_str = "unknown"
    else:
        elapsed = int(_time.time() - started_at)
        h, m = divmod(elapsed // 60, 60)
        uptime_str = f"{h}h {m:02d}m" if h else f"{m}m"

    return {
        "mode": mode,
        "sourceValid": True,
        "driveConnected": True,
        "agentActive": agent_active,
        "pendingWrites": 0,
        "uptime": uptime_str,
        "version": "0.3.0-alpha",
    }


@app.get("/api/projects")
async def get_projects():
    """
    Returns the list of IRIS projects known to this backend.

    iris-launcher's ProjectsPage reads this to populate the project cards.
    Projects are stored in data/iris_config.json under the "projects" key.
    If no projects are configured, returns a default entry for the current install.
    """
    cfg = _load_iris_config()
    projects = cfg.get("projects", None)

    if not projects:
        # Default: the current IRIS installation
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        mode = cfg.get("mode", "personal")
        projects = [
            {
                "id": "iris-main",
                "name": "IRIS",
                "path": project_root,
                "mode": "developer" if mode == "developer" else "standard",
                "driveType": "local",
            }
        ]

    return {"projects": projects}


@app.post("/api/projects")
async def save_projects(request: dict):
    """
    Save the project list from iris-launcher.

    Body: { "projects": [ { id, name, path, mode, driveType }, ... ] }
    """
    projects = request.get("projects", [])
    if not isinstance(projects, list):
        from fastapi import Response as FastAPIResponse
        return FastAPIResponse(
            content=json.dumps({"error": "projects must be a list"}),
            status_code=422,
            media_type="application/json",
        )
    cfg = _load_iris_config()
    cfg["projects"] = projects
    _save_iris_config(cfg)
    return {"projects": projects, "status": "ok"}


# ============================================================================
# Wake Word Handler
# ============================================================================

async def on_wake_word(wake_word_name: str):
    """
    Called from AudioEngine when Porcupine detects the wake word.
    Routes to the main IRIS UI session (not integration sessions).
    """
    try:
        ws_manager = get_websocket_manager()

        # Priority 1: canonical main-UI session for client "iris"
        session_id = ws_manager.get_session_id_for_client("iris")

        if not session_id:
            # Priority 2: any active session that is not an integration session
            active_sessions = ws_manager.get_active_session_ids()
            if not active_sessions:
                logger.warning("[WakeWord] Wake word detected but no active sessions")
                return
            session_id = next(
                (s for s in active_sessions if "integration" not in s),
                active_sessions[0]
            )

        client_ids = ws_manager.get_clients_for_session(session_id)
        client_id = client_ids[0] if client_ids else None
        if client_id:
            logger.info(f"[WakeWord] '{wake_word_name}' -> triggering voice for session {session_id}")
            iris_gateway = get_iris_gateway()
            await iris_gateway._handle_voice(
                session_id, client_id,
                {"type": "voice_command_start"},
                auto_stop=True
            )
        else:
            logger.warning(f"[WakeWord] Session {session_id} has no connected clients")
    except Exception as e:
        logger.error(f"[WakeWord] Error routing wake word: {e}")


# ============================================================================
# WebSocket Endpoint
# ============================================================================

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    client_id: str,
    session_id: Optional[str] = Query(None)
):
    """Handle WebSocket connections with session management."""
    ws_manager = get_websocket_manager()

    active_session_id = await ws_manager.connect(websocket, client_id, session_id)
    if not active_session_id:
        logger.warning(f"Failed to establish connection for client {client_id}")
        return

    try:
        session = get_session_manager().get_session(active_session_id)
        if session and session.state_manager:
            async def state_change_callback(key: str, value: Any):
                await ws_manager.send_to_client(client_id, {
                    "type": "state_update",
                    "key": key,
                    "value": value
                })
            session.state_manager.register_state_change_callback(state_change_callback)

        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            await handle_message(client_id, active_session_id, message)

    except WebSocketDisconnect:
        logger.info(f"Client {client_id} disconnected.")
    except RuntimeError as e:
        if "WebSocket is not connected" in str(e) or "accept" in str(e):
            logger.info(f"Client {client_id}: stale socket superseded by reconnect (normal)")
        else:
            logger.error(f"Error in WebSocket for client {client_id}: {e}")
    except Exception as e:
        logger.error(f"Error in WebSocket for client {client_id}: {e}")
    finally:
        owns_connection = ws_manager.active_connections.get(client_id) is websocket
        if active_session_id and owns_connection:
            try:
                iris_gateway = get_iris_gateway()
                await iris_gateway.cleanup_session(active_session_id)
            except Exception as cleanup_error:
                logger.error(f"Error cleaning up session {active_session_id}: {cleanup_error}")
        if owns_connection:
            ws_manager.disconnect(client_id)


# ============================================================================
# Message Handler
# ============================================================================

async def handle_message(client_id: str, session_id: str, message: dict):
    """Process incoming messages — delegates to IRISGateway for unified routing."""
    msg_type = message.get("type", "")

    if msg_type.startswith("memory/"):
        await handle_memory_message(client_id, session_id, message)
        return

    iris_gateway = get_iris_gateway()
    await iris_gateway.handle_message(client_id, message, session_id=session_id)


async def handle_memory_message(client_id: str, session_id: str, message: dict):
    """Handle memory-related WebSocket messages."""
    msg_type = message.get("type", "")
    ws_manager = get_websocket_manager()

    try:
        from backend.memory import get_memory_interface
        memory = get_memory_interface()

        if memory is None:
            await ws_manager.send_to_client(client_id, {
                "type": "memory/error",
                "payload": {"error": "Memory system not initialized"}
            })
            return

        if msg_type == "memory/get_preferences":
            entries = memory.get_user_profile_display()
            await ws_manager.send_to_client(client_id, {
                "type": "memory/preferences",
                "payload": {"entries": entries}
            })

        elif msg_type == "memory/forget_preference":
            key = message.get("payload", {}).get("key")
            if key:
                success = memory.forget_preference(key)
                await ws_manager.send_to_client(client_id, {
                    "type": "memory/forget_result",
                    "payload": {"key": key, "success": success}
                })
            else:
                await ws_manager.send_to_client(client_id, {
                    "type": "memory/error",
                    "payload": {"error": "No key provided"}
                })

        elif msg_type == "memory/get_stats":
            stats = memory.get_memory_stats()
            await ws_manager.send_to_client(client_id, {
                "type": "memory/stats",
                "payload": stats
            })

        else:
            await ws_manager.send_to_client(client_id, {
                "type": "memory/error",
                "payload": {"error": f"Unknown memory message type: {msg_type}"}
            })

    except Exception as e:
        logger.error(f"[Memory] Error handling memory message: {e}")
        await ws_manager.send_to_client(client_id, {
            "type": "memory/error",
            "payload": {"error": str(e)}
        })
