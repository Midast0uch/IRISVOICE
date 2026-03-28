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
    "http://localhost:3000,http://localhost:3001,tauri://localhost,https://tauri.localhost"
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
    logger.info("IRIS Backend starting up...")
    
    try:
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
            logger.debug(f"  - [AUDIO ENGINE] Factory returned AudioEngine instance")
        except Exception as e:
            logger.error(f"  - [AUDIO ENGINE] Failed to get instance: {e}")
            raise
        
        # Step 2: Create AudioEngine directly (for detailed diagnostics)
        try:
            from backend.audio.engine import AudioEngine
            audio_engine = AudioEngine()
            logger.info(f"    ✓ [AUDIO ENGINE] Instance created successfully")
        except Exception as e:
            logger.error(f"    ✗ [AUDIO ENGINE] Failed to create instance: {e}")
            raise
        
        # Step 3: Log initialization progress with timestamps
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"  - [AUDIO ENGINE] Instance created in {elapsed:.3f}s")
        
        # Step 4: Initialize audio engine internal components
        try:
            from backend.audio.engine import AudioEngine as AE
            ae = AE()
            logger.info("    ✓ [AUDIO ENGINE] Internal components initialized")
        except Exception as e:
            logger.error(f"    ✗ [AUDIO ENGINE] Failed to initialize components: {e}")
            raise
        
        # ==========================================================================
        # VOICE COMMAND HANDLER INITIALIZATION WITH DIAGNOSTIC LOGGING
        # ==========================================================================
        logger.info("  - Initializing voice command handler...")
        start_time = datetime.now()
        try:
            from backend.audio.voice_command import VoiceCommandHandler, VoiceState
            voice_handler = VoiceCommandHandler(audio_engine)
            app.state.voice_handler = voice_handler
            logger.info(f"    ✓ [VOICE HANDLER] Created successfully")
        except Exception as e:
            logger.error(f"    ✗ [VOICE HANDLER] Failed to create: {e}")
            raise
        
        # Step 5: Warm up faster-whisper in background with progress logging
        try:
            voice_handler.warm_up()
            logger.info("    ✓ [VOICE HANDLER] faster-whisper warm-up started in background")
        except Exception as e:
            logger.error(f"    ✗ [VOICE HANDLER] Warm-up failed: {e}")
            raise
        
        # ==========================================================================
        # IRIS GATEWAY INITIALIZATION WITH DIAGNOSTIC LOGGING
        # ==========================================================================
        logger.info("  - Initializing IRIS Gateway...")
        start_time = datetime.now()
        try:
            from backend.iris_gateway import get_iris_gateway, IRISGateway
            iris_gateway = get_iris_gateway()
            app.state.iris_gateway = iris_gateway
            logger.info(f"    ✓ [IRIS GATEWAY] Instance created successfully")
        except Exception as e:
            logger.error(f"    ✗ [IRIS GATEWAY] Failed to create: {e}")
            raise
        
        # Step 6: Capture the running event loop for background task dispatch
        try:
            import asyncio
            iris_gateway.set_main_loop(asyncio.get_running_loop())
            logger.info("    ✓ [IRIS GATEWAY] Event loop captured")
        except Exception as e:
            logger.error(f"    ✗ [IRIS GATEWAY] Failed to capture event loop: {e}")
            raise
        
        # Step 7: Wire VoiceCommandHandler → iris_gateway for 4-pillar voice processing
        try:
            iris_gateway.set_voice_handler(voice_handler)
            logger.info("    ✓ [IRIS GATEWAY] Voice handler wired")
        except Exception as e:
            logger.error(f"    ✗ [IRIS GATEWAY] Failed to wire voice handler: {e}")
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
            logger.info("    ✓ [WAKE WORD] Callback registered")
        except Exception as e:
            logger.error(f"    ✗ [WAKE WORD] Failed to register callback: {e}")
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
                    logger.info(f"    ✓ [WAKE WORD] Auto-configured: '{_best.display_name}' -> {_best.path}")
                else:
                    logger.warning("    ⚠ [WAKE WORD] No wake word models found")
            else:
                logger.debug(f"    - [WAKE WORD] Using custom config: {_wake_cfg.get_custom_model_path()}")
        except Exception as e:
            logger.error(f"    ✗ [WAKE WORD] Discovery failed: {e}")
            raise
        
        # ==========================================================================
        # PORCUPINE WAKE WORD INITIALIZATION WITH DIAGNOSTIC LOGGING
        # ==========================================================================
        logger.info("  - Initializing Porcupine...")
        try:
            audio_engine.initialize_porcupine()   # reads phrase + sensitivity from WakeConfig
            logger.info("    ✓ [PORCUPINE] Initialized with wake word config")
        except Exception as e:
            logger.error(f"    ✗ [PORCUPINE] Failed to initialize: {e}")
            raise
        
        # Step 8: Register live-update callback for dynamic wake word changes
        try:
            from backend.agent.wake_config import get_wake_config
            get_wake_config().register_change_callback(audio_engine.reinitialize_porcupine)
            logger.info("    ✓ [PORCUPINE] Live wake-word updates registered")
        except Exception as e:
            logger.error(f"    ✗ [PORCUPINE] Failed to register update callback: {e}")
            raise
        
        # Step 9: Start the AudioEngine so Porcupine frame detection runs
        start_time = datetime.now()
        if not audio_engine.start():
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.warning(f"    ✗ [AUDIO ENGINE] Failed to start in {elapsed:.3f}s (mic may be unavailable)")
        else:
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"    ✓ [AUDIO ENGINE] Started successfully in {elapsed:.3f}s — Porcupine wake word detection active")
        
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
            from backend.agent.tool_bridge import get_agent_tool_bridge
            agent_kernel = get_agent_kernel()
            
            # Initialize tool bridge and wire to kernel
            agent_kernel._tool_bridge = get_agent_tool_bridge()
            
            app.state.agent_kernel = agent_kernel
            logger.info("    ✓ [AGENT KERNEL] Initialized successfully")
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
                
                logger.info("    ✓ [MEMORY SYSTEM] Initialized successfully")
            else:
                logger.warning("  - Memory system: no model adapter available, skipping.")
                app.state.memory = None
        except Exception as e:
            logger.warning(f"  - Warning: Memory system init failed (non-critical): {e}")
            app.state.memory = None
        
        logger.info("IRIS Backend startup completed successfully!")
        
    except Exception as e:
        logger.error(f"[ERROR] Failed to initialize backend: {e}")
        import traceback
        traceback.print_exc()
    
    yield
    
    logger.info("IRIS Backend shutting down...")
    try:
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
