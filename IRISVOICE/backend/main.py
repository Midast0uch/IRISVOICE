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
# Lifespan Management (Startup & Shutdown)
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
        
        logger.info("  - Initializing audio engine...")
        audio_engine = get_audio_engine()
        # audio_engine.initialize() # DISABLED - lazy init only
        logger.info("  - Audio engine created (models NOT loaded - lazy initialization active)")
        
        logger.info("  - Initializing voice command handler...")
        voice_handler = VoiceCommandHandler(audio_engine)
        app.state.voice_handler = voice_handler

        logger.info("  - Initializing IRIS Gateway...")
        iris_gateway = get_iris_gateway()
        app.state.iris_gateway = iris_gateway
        logger.info("  - IRIS Gateway initialized successfully.")

        # Wire VoiceCommandHandler → iris_gateway for 4-pillar voice processing
        iris_gateway.set_voice_handler(voice_handler)
        logger.info("  - Voice handler wired to IRIS Gateway.")

        # Wire Porcupine wake word → auto-trigger voice command
        async def on_wake_word(wake_word_name: str):
            """
            Called from AudioEngine when Porcupine detects the wake word.
            Simulates a voice_command_start on the most-recently-active session.
            """
            try:
                ws_manager = get_websocket_manager()
                active_sessions = ws_manager.get_active_session_ids()
                if not active_sessions:
                    logger.warning("[WakeWord] Wake word detected but no active sessions")
                    return
                session_id = active_sessions[0]
                client_ids = ws_manager.get_clients_for_session(session_id)
                client_id = client_ids[0] if client_ids else None
                if client_id:
                    logger.info(f"[WakeWord] '{wake_word_name}' → triggering voice for session {session_id}")
                    await iris_gateway._handle_voice(
                        session_id, client_id,
                        {"type": "voice_command_start"},
                        auto_stop=True
                    )
            except Exception as e:
                logger.error(f"[WakeWord] Error routing wake word: {e}")

        # Register wake word callback on AudioEngine.
        # IMPORTANT: asyncio.get_event_loop() must NOT be called inside the
        # lambda — that lambda fires from the sounddevice callback thread which
        # has no event loop, causing "There is no current event loop in thread
        # 'Dummy-N'" errors and the coroutine to be garbage-collected without
        # being awaited.  Capture the running loop here (in the async lifespan
        # context) and reference the closure variable instead.
        _main_loop = asyncio.get_running_loop()
        audio_engine.set_wake_word_callback(
            lambda word: asyncio.run_coroutine_threadsafe(
                on_wake_word(word),
                _main_loop
            )
        )

        # Initialize Porcupine from user's WakeConfig setting (NOT hardcoded)
        # get_wake_config().get_wake_phrase() returns user's chosen phrase from Voice > Wake Word UI
        audio_engine.initialize_porcupine()   # reads phrase + sensitivity from WakeConfig

        # Register live-update callback: when user changes wake word in settings, reinit Porcupine instantly
        from backend.agent.wake_config import get_wake_config
        get_wake_config().register_change_callback(audio_engine.reinitialize_porcupine)
        logger.info("  - Porcupine live wake-word updates registered")

        # Start the AudioEngine so Porcupine frame detection runs
        if not audio_engine.start():
            logger.warning("  - AudioEngine failed to start (mic may be unavailable)")
        else:
            logger.info("  - AudioEngine started — Porcupine wake word detection active")

        logger.info("  - Initializing agent kernel...")
        try:
            from backend.agent import get_agent_kernel
            from backend.agent.tool_bridge import get_agent_tool_bridge
            agent_kernel = get_agent_kernel()
            
            # Initialize tool bridge and wire to kernel
            agent_kernel._tool_bridge = get_agent_tool_bridge()
            
            app.state.agent_kernel = agent_kernel
            logger.info("  - Agent kernel initialized successfully.")
            logger.info("  - LAZY LOADING ACTIVE: Models will NOT be loaded automatically")
            logger.info("  - Models will load only when user selects Local Model inference mode")
        except Exception as e:
            logger.warning(f"  - Warning: Failed to initialize agent kernel: {e}")
            logger.info("  - Agent functionality will be unavailable.")
        
        # Initialize Memory Foundation (non-blocking — biometric prompt removed).
        # Encryption uses machine-derived key (hostname + UUID), no user input needed.
        # The biometric/passphrase upgrade path remains as a future frontend setting.
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

                logger.info("  - Memory system initialized successfully.")
            else:
                logger.warning("  - Memory system: no model adapter available, skipping.")
                app.state.memory = None
        except Exception as e:
            logger.warning(f"  - Memory system init failed (non-critical): {e}")
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

@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    """Root endpoint — confirms the IRIS backend is running. HEAD supported for health checks."""
    return {"status": "ok", "service": "iris-voice", "timestamp": datetime.now().isoformat()}

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Suppress browser favicon 404 noise."""
    from fastapi.responses import Response
    return Response(status_code=204)

@app.get("/api/voice/status")
async def voice_status():
    return {"status": "ok", "service": "iris-voice", "timestamp": datetime.now().isoformat()}


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
    
    # Connect client and associate with a session
    active_session_id = await ws_manager.connect(websocket, client_id, session_id)
    if not active_session_id:
        logger.warning(f"Failed to establish connection for client {client_id}")
        return

    try:
        # BUG-05 FIX: Removed proactive initial_state send here.
        # The frontend sends "request_state" on connect (useIRISWebSocket.ts onopen),
        # which is handled by iris_gateway._handle_request_state and sends initial_state.
        # Sending it here too caused a duplicate that was processed before the frontend
        # was ready to handle it.

        # Register a callback for state changes
        session = get_session_manager().get_session(active_session_id)
        if session and session.state_manager:
            async def state_change_callback(key: str, value: Any):
                """Send state changes to the client"""
                await ws_manager.send_to_client(client_id, {
                    "type": "state_update",
                    "key": key,
                    "value": value
                })
            
            # Register the callback
            session.state_manager.register_state_change_callback(state_change_callback)

        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            # Pass session_id to message handler
            await handle_message(client_id, active_session_id, message)

    except WebSocketDisconnect:
        logger.info(f"Client {client_id} disconnected.")
        # GAP-11 FIX: Clean up session resources on disconnect
        if active_session_id:
            try:
                iris_gateway = get_iris_gateway()
                await iris_gateway.cleanup_session(active_session_id)
            except Exception as cleanup_error:
                logger.error(f"Error cleaning up session {active_session_id}: {cleanup_error}")
    except Exception as e:
        logger.error(f"Error in WebSocket for client {client_id}: {e}")
    finally:
        # GAP-11 FIX: Ensure cleanup happens even on errors
        if active_session_id:
            try:
                iris_gateway = get_iris_gateway()
                await iris_gateway.cleanup_session(active_session_id)
            except Exception as cleanup_error:
                logger.error(f"Error in final cleanup for session {active_session_id}: {cleanup_error}")
        ws_manager.disconnect(client_id)


# ============================================================================
# Message Handler
# ============================================================================

async def handle_message(client_id: str, session_id: str, message: dict):
    """Process incoming messages from clients - delegates to IRISGateway for unified routing.
    
    GAP-01 FIX: All message routing now goes through iris_gateway.py to eliminate
    dual message handling systems and prevent race conditions.
    """
    msg_type = message.get("type", "")
    
    # Handle memory-related messages
    if msg_type.startswith("memory/"):
        await handle_memory_message(client_id, session_id, message)
        return
    
    # GAP-01: Delegate all other message handling to IRISGateway
    iris_gateway = get_iris_gateway()
    await iris_gateway.handle_message(client_id, message, session_id=session_id)


async def handle_memory_message(client_id: str, session_id: str, message: dict):
    """
    Handle memory-related WebSocket messages.
    
    Message types:
    - memory/get_preferences: Get user profile display entries
    - memory/forget_preference: Remove a preference
    - memory/get_stats: Get memory system statistics
    """
    msg_type = message.get("type", "")
    ws_manager = get_websocket_manager()
    
    try:
        # Get memory interface
        from backend.memory import get_memory_interface
        memory = get_memory_interface()
        
        if memory is None:
            await ws_manager.send_to_client(client_id, {
                "type": "memory/error",
                "payload": {"error": "Memory system not initialized"}
            })
            return
        
        if msg_type == "memory/get_preferences":
            # Get user-facing memory entries
            entries = memory.get_user_profile_display()
            await ws_manager.send_to_client(client_id, {
                "type": "memory/preferences",
                "payload": {"entries": entries}
            })
        
        elif msg_type == "memory/forget_preference":
            # Remove a preference
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
            # Get memory statistics
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


# ============================================================================
# Configuration Helpers (No change needed here, but shown for context)

# _resolve_device_value, apply_voice_config, apply_agent_config, etc.
# These helpers will be called from handle_message and will now operate
# on a state that is implicitly session-specific because the initial call
# to state_manager used the session_id.


# Module-Level Variables
voice_handler: Optional[VoiceCommandHandler] = None


