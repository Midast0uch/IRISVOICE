"""
IRIS FastAPI Backend Server (Session-Aware)
Main application entry point with WebSocket endpoint and session management.
"""
import asyncio
import json
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

# Add parent directory to path to allow absolute imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware

# Session-aware managers
from backend.sessions import get_session_manager
from backend.state_manager import get_state_manager
from backend.ws_manager import get_websocket_manager

from backend.models import (
    Category, 
    IRISState, 
    ColorTheme, 
    get_subnodes_for_category,
    SUBNODE_CONFIGS
)
# ... other imports remain the same ...
from backend.audio import get_audio_engine, VoiceState
from backend.audio.pipeline import AudioPipeline
from backend.audio.voice_command import VoiceCommandHandler, VoiceState as VoiceCommandState
from backend.agent import (
    get_personality_engine,
    get_tts_manager,
    get_conversation_memory,
    get_wake_config
)
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
from backend.system import (
    get_power_manager,
    get_display_manager,
    get_storage_manager,
    get_network_manager
)
from backend.customize import (
    get_startup_manager,
    get_behavior_manager,
    get_notification_manager
)
from backend.monitor import (
    get_analytics_manager,
    get_log_manager,
    get_diagnostics_manager,
    get_update_manager
)


# ============================================================================
# Lifespan Management (Startup & Shutdown)
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown events."""
    print("IRIS Backend starting up...")
    # Start the session manager
    session_manager = get_session_manager()
    await session_manager.start()
    
    # Initialize other components as before
    global voice_handler
    state_manager = get_state_manager()
    # await state_manager.load_all() # This is now session-specific
    
    audio_engine = get_audio_engine()
    audio_engine.initialize()
    
    voice_handler = VoiceCommandHandler(state_manager, get_websocket_manager())
    
    yield
    
    print("IRIS Backend shutting down...")
    # Stop the session manager
    await session_manager.stop()
    
    # Clean up other resources
    audio_engine.cleanup()
    server_manager = get_server_manager()
    server_manager.stop_all_servers()


# ============================================================================
# FastAPI App Initialization
# ============================================================================

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        print(f"Failed to establish connection for client {client_id}")
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

        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            # Pass session_id to message handler
            await handle_message(client_id, active_session_id, message)

    except WebSocketDisconnect:
        print(f"Client {client_id} disconnected.")
    except Exception as e:
        print(f"Error in WebSocket for client {client_id}: {e}")
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
    print(f"[Session: {session_id}] Received message type: {msg_type}")

    # Pass session_id to all state manager calls
    if msg_type == "set_category":
        category = message.get("category")
        await state_manager.set_category(session_id, category)
        subnodes = get_subnodes_for_category(category)
        await ws_manager.send_to_client(client_id, {"type": "subnodes", "subnodes": [s.model_dump() for s in subnodes]})

    elif msg_type == "set_subnode":
        subnode_id = message.get("subnode_id")
        await state_manager.set_subnode(session_id, subnode_id)
        # ... existing logic ...

    elif msg_type == "update_field":
        subnode_id = message.get("subnode_id")
        field_id = message.get("field_id")
        value = message.get("value")
        category = message.get("category")
        
        success = await state_manager.update_field(session_id, subnode_id, field_id, value)
        # ... existing logic ...

    # ... all other message handlers need to be updated to use session_id ...
    # This is a simplified example of the required changes.

    # Example for voice command, passing session_id
    elif msg_type == "voice_command":
        if voice_handler:
            await voice_handler.handle_command(session_id, message)

    # Broadcast state changes to the relevant session
    updated_state = await state_manager.get_state(session_id)
    if updated_state:
        await ws_manager.broadcast_to_session(session_id, {
            "type": "state_update",
            "state": updated_state.model_dump()
        }, exclude_clients={client_id})


# ============================================================================
# Configuration Helpers (No change needed here, but shown for context)
# ============================================================================

# _resolve_device_value, apply_voice_config, apply_agent_config, etc.
# These helpers will be called from handle_message and will now operate
# on a state that is implicitly session-specific because the initial call
# to state_manager used the session_id.

# Dummy voice handler for illustration
class VoiceCommandHandler:
    def __init__(self, state_manager, ws_manager):
        self._state_manager = state_manager
        self._ws_manager = ws_manager
    async def handle_command(self, session_id: str, message: dict):
        print(f"Handling voice command for session {session_id}")
        # Use session_id to get session-specific state
        current_state = await self._state_manager.get_state(session_id)
        # ... process command ...


# Module-Level Variables
voice_handler: Optional[VoiceCommandHandler] = None

