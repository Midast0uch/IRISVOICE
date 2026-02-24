import asyncio
import json
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

"""
IRIS FastAPI Backend Server (Session-Aware)
Main application entry point with WebSocket endpoint and session management.
"""

logger.info("  - Importing FastAPI and middleware...")
# Add parent directory to path to allow absolute imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import os

# CORS configuration - restrict origins in production
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

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
    get_subnodes_for_category,
    SUBNODE_CONFIGS
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

async def initialize_models_in_background():
    """Load all required models in the background."""
    state_manager = get_state_manager()
    await state_manager.update_app_state(IRISState.LOADING_MODELS)
    
    logger.info("\n[BACKGROUND] Starting model initialization...")
    try:
        audio_engine = get_audio_engine()
        await audio_engine.lfm_audio_manager.initialize()
        
        # You can add other model initializations here
        # For example, initializing the personality engine
        # get_personality_engine().initialize()
        
        logger.info("[BACKGROUND] All models initialized successfully.")
        await state_manager.update_app_state(IRISState.READY)
        
    except asyncio.CancelledError:
        logger.warning("[BACKGROUND] Model loading was cancelled.")
        await state_manager.update_app_state(IRISState.ERROR)
        
    except Exception as e:
        logger.error(f"\n[BACKGROUND_ERROR] Error during model initialization: {e}")
        import traceback
        traceback.print_exc()
        await state_manager.update_app_state(IRISState.ERROR)


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
        
        logger.info("  - Initializing voice command handler...")
        voice_handler = VoiceCommandHandler(audio_engine)
        app.state.voice_handler = voice_handler

        logger.info("  - Initializing agent kernel...")
        try:
            from backend.agent import get_agent_kernel
            agent_kernel = get_agent_kernel()
            app.state.agent_kernel = agent_kernel
            logger.info("  - Agent kernel initialized successfully.")
        except Exception as e:
            logger.warning(f"  - Warning: Failed to initialize agent kernel: {e}")
            logger.info("  - Agent functionality will be unavailable.")
        
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

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        # Send initial state to the newly connected client
        state_manager = get_state_manager()
        current_state = await state_manager.get_state(active_session_id)
        if current_state:
            await ws_manager.send_to_client(client_id, {
                "type": "full_state",
                "state": current_state.model_dump()
            })
        
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
    except Exception as e:
        logger.error(f"Error in WebSocket for client {client_id}: {e}")
    finally:
        ws_manager.disconnect(client_id)


# ============================================================================
# Message Handler
# ============================================================================

async def handle_message(client_id: str, session_id: str, message: dict):
    """Process incoming messages from clients, now with session context."""
    state_manager = get_state_manager()
    ws_manager = get_websocket_manager()
    
    msg_type = message.get("type")
    logger.info(f"[Session: {session_id}] Received message type: {msg_type}")

    # Pass session_id to all state manager calls
    if msg_type == "set_category":
        category = message.get("category")
        await state_manager.set_category(session_id, category)
        subnodes = get_subnodes_for_category(category)
        await ws_manager.send_to_client(client_id, {"type": "subnodes", "subnodes": [s.model_dump() for s in subnodes]})

    elif msg_type == "set_subnode":
        subnode_id = message.get("subnode")
        await state_manager.set_subnode(session_id, subnode_id)

    elif msg_type == "go_back":
        await state_manager.go_back(session_id)

    elif msg_type == "collapse_to_idle":
        await state_manager.collapse_to_idle(session_id)

    elif msg_type == "update_theme":
        glow_color = message.get("payload", {}).get("glow_color")
        font_color = message.get("payload", {}).get("font_color")
        state_colors = message.get("payload", {}).get("state_colors")
        await state_manager.update_theme(session_id, glow_color, font_color, state_colors)
        await ws_manager.send_to_client(client_id, {
            "type": "theme_updated",
            "glow": glow_color,
            "font": font_color
        })

    elif msg_type == "request_state":
        current_state = await state_manager.get_state(session_id)
        await ws_manager.send_to_client(client_id, {
            "type": "full_state",
            "state": current_state.model_dump() if current_state else {}
        })

    elif msg_type == "ping":
        await ws_manager.send_to_client(client_id, {"type": "pong"})

    elif msg_type == "expand_to_main":
        # Handle expand to main category view
        await ws_manager.send_to_client(client_id, {
            "type": "category_expanded"
        })

    elif msg_type == "clear_chat":
        # Clear agent conversation history
        agent_kernel = getattr(app.state, 'agent_kernel', None)
        if agent_kernel and agent_kernel.conversation:
            agent_kernel.conversation.clear_history()
        await ws_manager.send_to_client(client_id, {
            "type": "chat_cleared"
        })

    elif msg_type == "reload_skills":
        # Reload skills configuration
        try:
            from backend.agent.skills import get_skills_loader
            loader = get_skills_loader()
            loader.reload()
            await ws_manager.send_to_client(client_id, {
                "type": "skills_reloaded",
                "payload": {"skills": loader.list_skills()}
            })
        except Exception as e:
            await ws_manager.send_to_client(client_id, {
                "type": "skills_error",
                "error": str(e)
            })

    elif msg_type == "update_field":
        subnode_id = message.get("subnode_id")
        field_id = message.get("field_id")
        value = message.get("value")
        
        success = await state_manager.update_field(session_id, subnode_id, field_id, value)
        if success:
            await ws_manager.send_to_client(client_id, {
                "type": "field_updated",
                "subnode_id": subnode_id,
                "field_id": field_id,
                "value": value
            })

    # Example for voice command, passing session_id
    elif msg_type == "voice_command":
        voice_handler = app.state.voice_handler
        if voice_handler:
            await voice_handler.handle_command(session_id, message)

    # Handle text messages from chat interface
    elif msg_type == "text_message":
        text = message.get("payload", {}).get("text")
        if text:
            agent_kernel = getattr(app.state, 'agent_kernel', None)
            
            if agent_kernel:
                try:
                    # Generate response using the agent kernel
                    response_text = await agent_kernel.process_text_message_async(text)
                except Exception as e:
                    response_text = f"Error processing message: {str(e)}"
                    logger.error(f"[text_message] Error: {e}")
            else:
                response_text = "Agent kernel is not available. Please restart the backend."
            
            # Send response back to client
            await ws_manager.send_to_client(client_id, {
                "type": "text_response",
                "payload": {
                    "text": response_text,
                    "sender": "assistant"
                }
            })

    # Get agent kernel status
    elif msg_type == "agent_status":
        agent_kernel = getattr(app.state, 'agent_kernel', None)
        if agent_kernel:
            status = {
                "ready": True,
                "models_loaded": len([m for m in (agent_kernel.model_router.models.values() if agent_kernel.model_router else []) if m.is_loaded()]) if agent_kernel.model_router else 0,
                "total_models": len(agent_kernel.model_router.models) if agent_kernel.model_router else 0,
                "tool_bridge_available": agent_kernel.tool_bridge is not None,
            }
            if agent_kernel.model_router:
                status["models"] = agent_kernel.model_router.get_all_models_status()
        else:
            status = {"ready": False, "error": "Agent kernel not available"}
        
        await ws_manager.send_to_client(client_id, {
            "type": "agent_status",
            "payload": status
        })

    # Get available tools from agent
    elif msg_type == "agent_tools":
        agent_kernel = getattr(app.state, 'agent_kernel', None)
        if agent_kernel and agent_kernel.tool_bridge:
            tools = agent_kernel.tool_bridge.get_available_tools()
            await ws_manager.send_to_client(client_id, {
                "type": "agent_tools",
                "payload": {"tools": tools}
            })
        else:
            await ws_manager.send_to_client(client_id, {
                "type": "agent_tools",
                "payload": {"tools": [], "error": "Tool bridge not available"}
            })

    # Execute a specific tool directly
    elif msg_type == "execute_tool":
        tool_name = message.get("payload", {}).get("tool_name")
        parameters = message.get("payload", {}).get("parameters", {})
        
        agent_kernel = getattr(app.state, 'agent_kernel', None)
        if agent_kernel and agent_kernel.tool_bridge:
            try:
                result = await agent_kernel.tool_bridge.execute_tool(tool_name, parameters)
                await ws_manager.send_to_client(client_id, {
                    "type": "tool_result",
                    "payload": {"tool": tool_name, "result": result}
                })
            except Exception as e:
                await ws_manager.send_to_client(client_id, {
                    "type": "tool_result",
                    "payload": {"tool": tool_name, "error": str(e)}
                })
        else:
            await ws_manager.send_to_client(client_id, {
                "type": "tool_result",
                "payload": {"tool": tool_name, "error": "Tool bridge not available"}
            })

    # Broadcast state changes to the relevant session
    updated_state = await state_manager.get_state(session_id)
    if updated_state:
        await ws_manager.broadcast_to_session(session_id, {
            "type": "state_update",
            "state": updated_state.model_dump()
        }, exclude_clients={client_id})


# ============================================================================
# Configuration Helpers (No change needed here, but shown for context)

# _resolve_device_value, apply_voice_config, apply_agent_config, etc.
# These helpers will be called from handle_message and will now operate
# on a state that is implicitly session-specific because the initial call
# to state_manager used the session_id.


# Module-Level Variables
voice_handler: Optional[VoiceCommandHandler] = None


