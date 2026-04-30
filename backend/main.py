# main.py
# IRISVOICE/backend/main.py - Audio Engine Initialization Diagnostic Logging

import asyncio
import json
import logging
import os
import subprocess
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
        # AUDIO SUBSYSTEM — lazy / on-demand start
        #
        # Audio is skipped at startup when:
        #   1. IRIS_SKIP_AUDIO=1 environment variable is set, OR
        #   2. iris_config.json has "voice_disabled": true, OR
        #   3. Running inside WSL (no real audio hardware — Porcupine/PortAudio
        #      would spin a callback loop against a virtual device burning CPU)
        #
        # Voice can be enabled at runtime via POST /api/audio/start.
        # This eliminates the sustained CPU spike that occurs when the PortAudio
        # stream polls at 31 Hz on a system with no real microphone.
        # ==========================================================================
        def _is_wsl() -> bool:
            try:
                with open("/proc/version", "r") as _f:
                    return "microsoft" in _f.read().lower()
            except OSError:
                return False

        _early_cfg = _load_iris_config()
        _skip_audio = (
            os.environ.get("IRIS_SKIP_AUDIO", "").strip() == "1"
            or bool(_early_cfg.get("voice_disabled", False))
            or (_is_wsl() and os.environ.get("IRIS_FORCE_AUDIO", "").strip() != "1")
        )

        app.state.audio_engine = None
        app.state.voice_handler = None
        audio_engine = None
        voice_handler = None

        if _skip_audio:
            _reason = (
                "IRIS_SKIP_AUDIO=1" if os.environ.get("IRIS_SKIP_AUDIO") == "1"
                else "voice_disabled in config" if _early_cfg.get("voice_disabled")
                else "WSL detected (set IRIS_FORCE_AUDIO=1 to override)"
            )
            logger.info(f"  - [AUDIO SUBSYSTEM] Skipped at startup — {_reason}")
            logger.info("    [~] Voice / wake word unavailable until POST /api/audio/start is called")
        else:
            logger.info("  - Initializing audio engine...")
            start_time = datetime.now()
            try:
                audio_engine = get_audio_engine()
                app.state.audio_engine = audio_engine
            except Exception as e:
                logger.error(f"    [x] [AUDIO ENGINE] Failed to create instance: {e}")
                audio_engine = None

            if audio_engine is not None:
                try:
                    from backend.audio.voice_command import VoiceCommandHandler
                    voice_handler = VoiceCommandHandler(audio_engine)
                    app.state.voice_handler = voice_handler
                except Exception as e:
                    logger.warning(f"    [~] [VOICE HANDLER] Failed (non-fatal): {e}")

                try:
                    _main_loop = asyncio.get_running_loop()
                    audio_engine.set_wake_word_callback(
                        lambda word: asyncio.run_coroutine_threadsafe(on_wake_word(word), _main_loop)
                    )
                except Exception as e:
                    logger.warning(f"    [~] [WAKE WORD] Callback registration failed (non-fatal): {e}")

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
                except Exception as e:
                    logger.warning(f"    [~] [WAKE WORD] Discovery failed (non-fatal): {e}")

                try:
                    audio_engine.initialize_porcupine()
                except Exception as e:
                    logger.warning(f"    [~] [PORCUPINE] Init failed (non-fatal): {e}")

                try:
                    from backend.agent.wake_config import get_wake_config
                    get_wake_config().register_change_callback(audio_engine.reinitialize_porcupine)
                except Exception as e:
                    logger.warning(f"    [~] [PORCUPINE] Live update callback failed (non-fatal): {e}")

                if not audio_engine.start():
                    logger.warning("    [x] [AUDIO ENGINE] Failed to start (mic may be unavailable)")
                else:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    logger.info(f"    [+] [AUDIO ENGINE] Started in {elapsed:.3f}s — wake word active")

        # ==========================================================================
        # IRIS GATEWAY — always initialized (needed for chat, settings, WebSocket)
        # ==========================================================================
        logger.info("  - Initializing IRIS Gateway...")
        try:
            from backend.iris_gateway import get_iris_gateway, IRISGateway
            iris_gateway = get_iris_gateway()
            app.state.iris_gateway = iris_gateway
            iris_gateway.set_main_loop(asyncio.get_running_loop())
            if voice_handler is not None:
                iris_gateway.set_voice_handler(voice_handler)
            logger.info("    [+] [IRIS GATEWAY] Ready")
        except Exception as e:
            logger.error(f"    [x] [IRIS GATEWAY] Failed to create: {e}")
            raise

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

        # Pre-warm the GGUF file metadata cache in the background (filesystem
        # scan only — no model weights loaded, no CUDA initialization).
        # This means the first ModelsScreen open returns instantly instead of
        # re-parsing GGUF binary headers on demand.
        #
        # INTENTIONALLY does NOT call get_hardware_info() here — that function
        # can trigger CUDA driver init (via torch or llama_cpp) which causes a
        # visible memory spike on startup before the user has done anything.
        # Hardware info is fetched lazily when the user first opens ModelsScreen.
        async def _prewarm_model_cache() -> None:
            # Delay 30 s so this I/O-heavy scan doesn't race with the Next.js
            # dev-server compilation that peaks RAM immediately after startup.
            await asyncio.sleep(30)
            try:
                from backend.agent.local_model_manager import get_local_model_manager
                import asyncio as _asyncio
                mgr = get_local_model_manager()
                loop = _asyncio.get_event_loop()
                await loop.run_in_executor(None, mgr.scan_models)
                logger.info("  [LocalModel] GGUF metadata cache pre-warmed (filesystem scan only)")
            except Exception as _pw_err:
                logger.debug(f"  [LocalModel] Pre-warm skipped: {_pw_err}")

        asyncio.ensure_future(_prewarm_model_cache())

    except Exception as e:
        app.state.ready = False
        logger.error(f"[ERROR] Failed to initialize backend: {e}")
        import traceback
        traceback.print_exc()
    
    yield
    
    # ------------------------------------------------------------------
    # SHUTDOWN — capture pending diffs + notify Launcher BEFORE closing
    # connections, so the DiffReviewPage can still be reached on restart.
    # ------------------------------------------------------------------
    logger.info("IRIS Backend shutting down...")
    try:
        # If developer mode with active worktree, capture the diff and
        # broadcast session_end so the Launcher knows to show DiffReviewPage.
        try:
            from backend.dev_worktree import get_active as _wt_active, get_pending_diff as _wt_diff
            wt = _wt_active()
            if wt is not None:
                _capture_pending_diff()
                diff_result = _wt_diff()
                pending_count = len(_pending_diff_cache)
                try:
                    ws_manager = get_websocket_manager()
                    await ws_manager.broadcast({
                        "type": "session_end",
                        "mode": "developer",
                        "pending_writes": pending_count,
                        "branch": diff_result.get("branch", ""),
                    })
                    logger.info(f"[Shutdown] session_end broadcast with {pending_count} pending writes")
                except Exception as _be:
                    logger.debug(f"[Shutdown] session_end broadcast failed: {_be}")
        except Exception as _de:
            logger.debug(f"[Shutdown] Diff capture skipped: {_de}")

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

    # ------------------------------------------------------------------
    # Worktree isolation (developer mode only)
    # ------------------------------------------------------------------
    try:
        from backend.dev_worktree import setup as _wt_setup, get_active as _wt_get_active
        if mode == "developer":
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            _wt_setup(project_root)
            logger.info(f"[Mode] Worktree isolation active at {project_root}/dev_worktree")
        else:
            # Switching away from developer to personal.
            # Capture the pending diff into the in-memory cache BEFORE
            # doing anything with the worktree so the Launcher DiffReviewPage
            # can show it.  Do NOT tear down here — approve/reject endpoints
            # handle the actual teardown (merge or discard).
            if _wt_get_active() is not None:
                _capture_pending_diff()
                logger.info("[Mode] Switching away from developer — diff captured, worktree kept alive for review")
    except Exception as wt_exc:
        logger.warning(f"[Mode] Worktree setup/teardown failed (non-fatal): {wt_exc}")

    # Broadcast mode_changed + session_end (when leaving developer mode)
    # to all connected WebSocket clients so the IRISVOICE frontend and
    # Launcher can react immediately without polling.
    try:
        ws_manager = get_websocket_manager()
        await ws_manager.broadcast({"type": "mode_changed", "mode": mode})

        # When switching away from developer, also send session_end so the
        # Launcher auto-opens DiffReviewPage.
        if mode == "personal":
            try:
                from backend.dev_worktree import get_active as _wt_get_active_session
                from backend.dev_worktree import get_pending_diff as _wt_pending_diff
                wt = _wt_get_active_session()
                pending_count = len(_pending_diff_cache)
                diff_result = _wt_pending_diff() if wt else {"active": False}
                await ws_manager.broadcast({
                    "type": "session_end",
                    "mode": mode,
                    "pending_writes": pending_count,
                    "branch": diff_result.get("branch", ""),
                })
                logger.info(f"[Mode] Sent session_end event with {pending_count} pending writes")
            except Exception as _se_exc:
                logger.debug(f"[Mode] session_end broadcast failed (non-fatal): {_se_exc}")
    except Exception as exc:
        logger.debug(f"[Mode] WS broadcast skipped (no clients?): {exc}")

    return {"mode": mode, "status": "ok"}


@app.get("/api/mode")
async def get_launcher_mode():
    """Returns the currently configured launch mode."""
    cfg = _load_iris_config()
    mode = cfg.get("mode", None)
    return {"mode": mode}


# ============================================================================
# Git + Diff API (Launcher GitPage / DiffReviewPage)
# ============================================================================

def _git_cwd():
    """Return the directory git commands should run in: active worktree or project root."""
    try:
        from backend.dev_worktree import get_active as _get_wt
        wt = _get_wt()
        if wt:
            return wt.get_path()
    except Exception:
        pass
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_git(*args):
    cmd = ["git", *args]
    result = subprocess.run(cmd, cwd=_git_cwd(), capture_output=True, text=True)
    return result


@app.get("/api/git/status")
async def git_status():
    """Short git status + branch info."""
    result = _run_git("status", "--short", "--branch")
    return {
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


@app.get("/api/git/log")
async def git_log(n: int = 10):
    """Recent commit history (oneline)."""
    result = _run_git("log", f"-{n}", "--oneline", "--decorate")
    return {
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


@app.post("/api/git/commit")
async def git_commit(request: dict):
    """Stage all changes and commit."""
    message = (request.get("message") or "").strip()
    if not message:
        from fastapi import Response as FastAPIResponse
        return FastAPIResponse(
            content=json.dumps({"error": "Commit message is required"}),
            status_code=422,
            media_type="application/json",
        )
    add_res = _run_git("add", "-A")
    if add_res.returncode != 0:
        return {"success": False, "error": add_res.stderr}
    commit_res = _run_git("commit", "-m", message)
    return {
        "success": commit_res.returncode == 0,
        "stdout": commit_res.stdout,
        "stderr": commit_res.stderr,
    }


@app.post("/api/git/rollback")
async def git_rollback():
    """Hard reset to HEAD (discard all uncommitted changes)."""
    result = _run_git("reset", "--hard", "HEAD")
    return {
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


# ---------------------------------------------------------------------------
# In-memory pending-diff queue — survives worktree teardown so the
# Launcher DiffReviewPage can show diffs even after the backend restarts.
# ---------------------------------------------------------------------------
_pending_diff_cache: list[dict] = []


def _parse_diff_into_writes(diff_text: str) -> list[dict]:
    """
    Parse a unified git diff into per-file PendingWrite items.

    Returns a list of {id, path, diff, description, timestamp} dicts
    suitable for the frontend PendingWrite interface.
    """
    if not diff_text.strip():
        return []

    import hashlib
    from datetime import datetime, timezone

    writes: list[dict] = []
    current_file: str | None = None
    current_lines: list[str] = []
    timestamp = datetime.now(timezone.utc).isoformat()

    for line in diff_text.split("\n"):
        if line.startswith("diff --git "):
            # Flush previous file
            if current_file and current_lines:
                file_diff = "\n".join(current_lines)
                file_id = hashlib.md5(current_file.encode()).hexdigest()[:12]
                # Count additions and deletions for the description
                adds = sum(1 for l in current_lines if l.startswith("+") and not l.startswith("+++"))
                dels = sum(1 for l in current_lines if l.startswith("-") and not l.startswith("---"))
                desc_parts = []
                if adds:
                    desc_parts.append(f"+{adds}")
                if dels:
                    desc_parts.append(f"-{dels}")
                desc = f"{' '.join(desc_parts)} lines" if desc_parts else "modified"
                writes.append({
                    "id": file_id,
                    "path": current_file,
                    "diff": file_diff,
                    "description": desc,
                    "timestamp": timestamp,
                })

            # Start new file
            parts = line[len("diff --git "):].split()
            if parts:
                current_file = parts[0][2:] if parts[0].startswith("a/") else parts[0]  # strip a/ prefix
            else:
                current_file = "unknown"
            current_lines = [line]
            continue

        # Accumulate lines belonging to the current file
        if current_file is not None:
            current_lines.append(line)

    # Flush final file
    if current_file and current_lines:
        file_diff = "\n".join(current_lines)
        file_id = hashlib.md5(current_file.encode()).hexdigest()[:12]
        adds = sum(1 for l in current_lines if l.startswith("+") and not l.startswith("+++"))
        dels = sum(1 for l in current_lines if l.startswith("-") and not l.startswith("---"))
        desc_parts = []
        if adds:
            desc_parts.append(f"+{adds}")
        if dels:
            desc_parts.append(f"-{dels}")
        desc = f"{' '.join(desc_parts)} lines" if desc_parts else "modified"
        writes.append({
            "id": file_id,
            "path": current_file,
            "diff": file_diff,
            "description": desc,
            "timestamp": timestamp,
        })

    return writes


def _capture_pending_diff() -> list[dict]:
    """
    Read diff from active worktree, parse into PendingWrite items,
    and store in the in-memory cache. Returns the parsed items.
    """
    global _pending_diff_cache
    try:
        from backend.dev_worktree import get_pending_diff
        result = get_pending_diff()
        if result.get("active") and result.get("diff"):
            _pending_diff_cache = _parse_diff_into_writes(result["diff"])
            logger.info(f"[Diff] Captured {len(_pending_diff_cache)} pending writes for review")
            return _pending_diff_cache
    except Exception as exc:
        logger.warning(f"[Diff] Failed to capture pending diff: {exc}")
    return []


@app.get("/api/diff/pending")
async def diff_pending():
    """
    Return pending writes from the in-memory cache (survives worktree teardown)
    or fall back to live worktree diff.
    """
    global _pending_diff_cache
    # If we have a cached diff, return it
    if _pending_diff_cache:
        return {"pending": _pending_diff_cache, "source": "cache"}
    # Otherwise try live worktree
    try:
        from backend.dev_worktree import get_pending_diff
        result = get_pending_diff()
        if result.get("active") and result.get("diff"):
            writes = _parse_diff_into_writes(result["diff"])
            return {"pending": writes, "source": "live"}
        return {"pending": [], "source": "live", "branch": result.get("branch")}
    except Exception as exc:
        # Fallback to plain git diff in project root
        result = _run_git("diff")
        if result.stdout.strip():
            writes = _parse_diff_into_writes(result.stdout)
            return {"pending": writes, "source": "fallback", "error": str(exc)}
        return {"pending": [], "source": "fallback", "error": str(exc)}


@app.post("/api/diff/approve")
async def diff_approve():
    """
    Approve all pending changes:
      1. Commit in the worktree (or from project root if no worktree)
      2. Merge the agent branch into main (if worktree active)
      3. Tear down the worktree
      4. Clear the in-memory pending diff cache
    """
    global _pending_diff_cache
    try:
        from backend.dev_worktree import get_active as _get_wt, teardown as _wt_teardown

        wt = _get_wt()
        if wt is None:
            # No active worktree — commit from project root
            add_res = _run_git("add", "-A")
            if add_res.returncode != 0:
                return {"status": "commit_failed", "error": add_res.stderr}
            commit_res = _run_git("commit", "-m", "IRIS agent session changes (direct)")
            _pending_diff_cache = []
            return {
                "status": "ok",
                "commit_success": commit_res.returncode == 0,
                "stdout": commit_res.stdout,
                "stderr": commit_res.stderr,
            }

        # Commit any pending changes in worktree
        commit_res = _run_git("add", "-A")
        if commit_res.returncode != 0:
            return {"status": "commit_failed", "error": commit_res.stderr}
        commit_res = _run_git("commit", "-m", "IRIS agent session changes")
        # returncode may be 1 if nothing to commit — that's ok

        # Merge + teardown
        result = _wt_teardown(merge=True)
        _pending_diff_cache = []
        logger.info("[Diff] Approved — worktree merged and torn down")
        return result
    except Exception as exc:
        logger.error(f"[Diff] Approve failed: {exc}")
        return {"status": "error", "error": str(exc)}


@app.post("/api/diff/reject")
async def diff_reject():
    """
    Discard all pending changes and tear down the worktree.
    Clear the in-memory pending diff cache.
    """
    global _pending_diff_cache
    try:
        from backend.dev_worktree import get_active as _get_wt, teardown as _wt_teardown

        wt = _get_wt()
        if wt is None:
            # No worktree — just clear cache
            _pending_diff_cache = []
            return {"status": "ok", "note": "no worktree active, cache cleared"}

        result = _wt_teardown(merge=False)
        _pending_diff_cache = []
        logger.info("[Diff] Rejected — worktree torn down, changes discarded")
        return result
    except Exception as exc:
        logger.error(f"[Diff] Reject failed: {exc}")
        return {"status": "error", "error": str(exc)}


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


# ============================================================================
# Model Config API — launcher settings page reads/writes provider + credentials
# ============================================================================

@app.get("/api/model-config")
async def get_model_config():
    """Return current inference provider config for the launcher settings page."""
    cfg = _load_iris_config()
    kernel = getattr(app.state, "agent_kernel", None)
    if kernel is not None:
        provider = getattr(kernel, "_model_provider", cfg.get("model_provider", "uninitialized"))
        api_key_raw = getattr(kernel, "_api_key", "")
        api_base_url = getattr(kernel, "_api_base_url", cfg.get("api_base_url", "https://api.openai.com/v1"))
    else:
        provider = cfg.get("model_provider", "uninitialized")
        api_key_raw = cfg.get("api_key", "")
        api_base_url = cfg.get("api_base_url", "https://api.openai.com/v1")
    return {
        "model_provider": provider,
        "api_key_set": bool(api_key_raw),
        "api_base_url": api_base_url,
    }


@app.post("/api/model-config")
async def set_model_config(request: dict):
    """Apply inference provider config from the launcher settings page."""
    provider = request.get("model_provider", "")
    api_key = request.get("api_key", "")
    api_base_url = request.get("api_base_url", "https://api.openai.com/v1") or "https://api.openai.com/v1"

    # Persist to iris_config.json (api_key intentionally omitted from disk for security)
    cfg = _load_iris_config()
    cfg["model_provider"] = provider
    cfg["api_base_url"] = api_base_url
    if api_key:
        cfg["api_key"] = api_key
    _save_iris_config(cfg)

    # Apply to live kernel
    kernel = getattr(app.state, "agent_kernel", None)
    if kernel is not None:
        try:
            if provider == "api":
                kernel.configure_api(api_key or getattr(kernel, "_api_key", ""), api_base_url)
            elif provider == "iris_local":
                mgr = getattr(app.state, "local_model_manager", None)
                if mgr is not None:
                    kernel.configure_inprocess_local(mgr)
                else:
                    kernel._model_provider = "iris_local"
            elif provider == "lmstudio":
                kernel.configure_lmstudio(api_base_url)
            elif provider == "local":
                kernel.configure_ollama(api_base_url or "http://localhost:11434")
            logger.info(f"[ModelConfig] Provider set to {provider!r} via launcher settings")
        except Exception as exc:
            logger.warning(f"[ModelConfig] Failed to apply to kernel: {exc}")
            return {"ok": False, "error": str(exc)}

    return {"ok": True, "model_provider": provider}


@app.post("/api/test-connection")
async def test_connection_rest(request: dict):
    """Lightweight connection test for the launcher settings page."""
    api_key = request.get("api_key", "")
    api_url = request.get("api_url", "https://api.openai.com/v1") or "https://api.openai.com/v1"

    # If no key provided, fall back to kernel's stored key
    if not api_key:
        kernel = getattr(app.state, "agent_kernel", None)
        if kernel is not None:
            api_key = getattr(kernel, "_api_key", "")

    if not api_key:
        return {"ok": False, "error": "API key is required"}

    try:
        from .utils.openai_connection_test import test_openai_connection
        success, msg = await test_openai_connection(api_key, api_url)
        return {"ok": success, "message": msg}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


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
# Audio Engine On-Demand Control
# Allows the launcher to start/stop the audio pipeline without restarting the
# backend — important on WSL where audio is skipped at startup by default.
# ============================================================================

@app.get("/api/audio/status")
async def get_audio_status():
    """Return current audio pipeline state."""
    engine = getattr(app.state, "audio_engine", None)
    cfg = _load_iris_config()
    return {
        "running": engine is not None and getattr(engine, "_is_running", False),
        "available": engine is not None,
        "voice_disabled": bool(cfg.get("voice_disabled", False)),
    }


@app.post("/api/audio/start")
async def start_audio():
    """Start the audio pipeline on-demand (e.g. when user enables voice mode)."""
    engine = getattr(app.state, "audio_engine", None)
    if engine is None:
        # First-time init — create engine now
        try:
            engine = get_audio_engine()
            app.state.audio_engine = engine
        except Exception as exc:
            return {"ok": False, "error": f"Audio engine unavailable: {exc}"}

    if getattr(engine, "_is_running", False):
        return {"ok": True, "message": "Already running"}

    try:
        ok = engine.start()
        if ok:
            cfg = _load_iris_config()
            cfg["voice_disabled"] = False
            _save_iris_config(cfg)
        return {"ok": ok, "message": "Started" if ok else "Failed to start (check microphone)"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/audio/stop")
async def stop_audio():
    """Stop the audio pipeline to free CPU/mic when voice is not needed."""
    engine = getattr(app.state, "audio_engine", None)
    if engine is None or not getattr(engine, "_is_running", False):
        return {"ok": True, "message": "Already stopped"}
    try:
        engine.stop()
        cfg = _load_iris_config()
        cfg["voice_disabled"] = True
        _save_iris_config(cfg)
        return {"ok": True, "message": "Stopped"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ============================================================================
# GitHub OAuth Endpoints
# ============================================================================

@app.get("/api/auth/github/start")
async def github_auth_start():
    """
    Start GitHub OAuth flow.
    Returns the GitHub authorization URL for the frontend to open.
    """
    try:
        from backend.integrations.github_oauth import get_auth_url, GitHubAuthError
        auth_url, state = get_auth_url()
        return {"auth_url": auth_url, "state": state}
    except GitHubAuthError as e:
        from fastapi import Response as FastAPIResponse
        return FastAPIResponse(
            content=json.dumps({"error": str(e)}),
            status_code=500,
            media_type="application/json",
        )


@app.get("/api/auth/github/callback")
async def github_auth_callback(code: str, state: str):
    """
    Handle GitHub OAuth callback.
    GitHub redirects here after user authorizes the app.
    """
    try:
        from backend.integrations.github_oauth import exchange_code, GitHubAuthError
        access_token = await exchange_code(code, state)
        return {
            "status": "ok",
            "message": "GitHub authentication successful",
        }
    except GitHubAuthError as e:
        from fastapi import Response as FastAPIResponse
        return FastAPIResponse(
            content=json.dumps({"error": str(e)}),
            status_code=400,
            media_type="application/json",
        )


@app.get("/api/auth/github/status")
async def github_auth_status():
    """Check whether GitHub is authenticated."""
    from backend.integrations.github_oauth import is_connected, get_user, GitHubAuthError
    connected = await is_connected()
    if not connected:
        return {"connected": False}
    try:
        user = await get_user()
        return {
            "connected": True,
            "username": user.get("login"),
            "avatar_url": user.get("avatar_url"),
            "name": user.get("name"),
        }
    except GitHubAuthError:
        return {"connected": False}


@app.post("/api/auth/github/disconnect")
async def github_auth_disconnect():
    """Disconnect from GitHub (wipe stored credentials)."""
    from backend.integrations.github_oauth import disconnect
    success = await disconnect()
    return {"status": "ok" if success else "error"}


@app.get("/api/github/repos")
async def github_repos():
    """List repositories for the authenticated GitHub user."""
    from backend.integrations.github_oauth import get_repos, GitHubAuthError
    try:
        repos = await get_repos()
        return {"repos": repos}
    except GitHubAuthError as e:
        from fastapi import Response as FastAPIResponse
        return FastAPIResponse(
            content=json.dumps({"error": str(e)}),
            status_code=401 if "Not authenticated" in str(e) else 400,
            media_type="application/json",
        )


@app.get("/api/github/ssh-keys")
async def github_ssh_keys():
    """List SSH keys for the authenticated GitHub user."""
    from backend.integrations.github_oauth import list_ssh_keys, GitHubAuthError
    try:
        keys = await list_ssh_keys()
        return {"keys": keys}
    except GitHubAuthError as e:
        from fastapi import Response as FastAPIResponse
        return FastAPIResponse(
            content=json.dumps({"error": str(e)}),
            status_code=401 if "Not authenticated" in str(e) else 400,
            media_type="application/json",
        )


@app.post("/api/github/ssh-keys")
async def github_create_ssh_key(request: dict):
    """Add an SSH public key to the authenticated GitHub user."""
    from backend.integrations.github_oauth import create_ssh_key, GitHubAuthError
    try:
        title = request.get("title", "IRIS Key")
        public_key = request.get("public_key", "")
        if not public_key:
            from fastapi import Response as FastAPIResponse
            return FastAPIResponse(
                content=json.dumps({"error": "public_key is required"}),
                status_code=422,
                media_type="application/json",
            )
        key = await create_ssh_key(title, public_key)
        return {"key": key}
    except GitHubAuthError as e:
        from fastapi import Response as FastAPIResponse
        return FastAPIResponse(
            content=json.dumps({"error": str(e)}),
            status_code=401 if "Not authenticated" in str(e) else 400,
            media_type="application/json",
        )


@app.delete("/api/github/ssh-keys/{key_id}")
async def github_delete_ssh_key(key_id: str):
    """Delete an SSH key from the authenticated GitHub user."""
    from backend.integrations.github_oauth import delete_ssh_key, GitHubAuthError
    try:
        await delete_ssh_key(key_id)
        return {"status": "ok"}
    except GitHubAuthError as e:
        from fastapi import Response as FastAPIResponse
        return FastAPIResponse(
            content=json.dumps({"error": str(e)}),
            status_code=401 if "Not authenticated" in str(e) else 400,
            media_type="application/json",
        )


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
