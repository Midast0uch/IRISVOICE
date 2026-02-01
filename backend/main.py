"""
IRIS FastAPI Backend Server
Main application entry point with WebSocket endpoint
"""
import json
import os
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .models import (
    Category, 
    IRISState, 
    ColorTheme, 
    get_subnodes_for_category,
    SUBNODE_CONFIGS
)
from .state_manager import get_state_manager
from .ws_manager import get_websocket_manager


# ============================================================================
# Lifespan - Startup/Shutdown
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - load state on startup, save on shutdown"""
    # Startup
    print(">> IRIS Backend starting up...")
    state_manager = get_state_manager()
    await state_manager.load_all()
    print(f"[OK] Loaded state with theme: {state_manager.state.active_theme.glow}")
    
    yield
    
    # Shutdown
    print("\n[STOP] IRIS Backend shutting down...")
    # Save all categories
    for category in SUBNODE_CONFIGS.keys():
        await state_manager.save_category(category)
    await state_manager.save_theme()
    print("[OK] State saved")


# ============================================================================
# FastAPI App
# ============================================================================

app = FastAPI(
    title="IRIS Backend",
    description="FastAPI backend for IRIS Desktop Widget",
    version="1.0.0",
    lifespan=lifespan
)

# CORS - allow frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# HTTP Routes
# ============================================================================

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "online",
        "service": "IRIS Backend",
        "version": "1.0.0"
    }


@app.get("/api/state")
async def get_state():
    """Get current application state (for initial load or refresh)"""
    state_manager = get_state_manager()
    return {
        "status": "success",
        "state": state_manager.state.model_dump()
    }


@app.get("/api/subnodes/{category}")
async def get_subnodes(category: str):
    """Get subnode configuration for a category"""
    subnodes = get_subnodes_for_category(category)
    if not subnodes:
        return {"status": "error", "message": f"Unknown category: {category}"}
    
    # Convert to dict for JSON response
    return {
        "status": "success",
        "category": category,
        "subnodes": [s.model_dump() for s in subnodes]
    }


# ============================================================================
# WebSocket Handler
# ============================================================================

async def handle_message(websocket: WebSocket, client_id: str, message: dict) -> None:
    """
    Process incoming WebSocket messages.
    Routes to appropriate handler based on message type.
    """
    msg_type = message.get("type")
    payload = message.get("payload", {})
    
    state_manager = get_state_manager()
    ws_manager = get_websocket_manager()
    
    # ------------------------------------------------------------------------
    # select_category: Switch to a main category view
    # ------------------------------------------------------------------------
    if msg_type == "select_category":
        category_str = payload.get("category")
        if category_str:
            try:
                category = Category(category_str)
                state_manager.set_category(category)
                
                # Get subnodes for this category
                subnodes = get_subnodes_for_category(category_str)
                
                # Send confirmation to client
                await ws_manager.send_to_client(client_id, {
                    "type": "category_changed",
                    "category": category_str,
                    "subnodes": [s.model_dump() for s in subnodes]
                })
                
                # Broadcast to other clients
                await ws_manager.broadcast({
                    "type": "state_sync",
                    "state": state_manager.state.model_dump()
                }, exclude={client_id})
                
            except ValueError:
                await ws_manager.send_error(client_id, f"Invalid category: {category_str}")
    
    # ------------------------------------------------------------------------
    # select_subnode: Activate a subnode (show mini-nodes)
    # ------------------------------------------------------------------------
    elif msg_type == "select_subnode":
        subnode_id = payload.get("subnode_id")
        if subnode_id:
            state_manager.set_subnode(subnode_id)
            
            await ws_manager.send_to_client(client_id, {
                "type": "subnode_changed",
                "subnode_id": subnode_id
            })
    
    # ------------------------------------------------------------------------
    # field_update: Update a field value (with validation)
    # ------------------------------------------------------------------------
    elif msg_type == "field_update":
        category = payload.get("category")
        field_id = payload.get("field_id")
        value = payload.get("value")
        
        if all([category, field_id is not None, value is not None]):
            valid = state_manager.update_field(category, field_id, value)
            
            if valid:
                await ws_manager.send_to_client(client_id, {
                    "type": "field_updated",
                    "category": category,
                    "field_id": field_id,
                    "value": value,
                    "valid": True
                })
                
                # Auto-save after field update
                await state_manager.save_category(category)
                
                # Broadcast theme update if it's a color field
                if field_id == "glow_color" and isinstance(value, str):
                    await ws_manager.broadcast({
                        "type": "theme_updated",
                        "glow": value,
                        "font": state_manager.state.active_theme.font,
                        "primary": value
                    })
                    
            else:
                await ws_manager.send_error(
                    client_id, 
                    f"Invalid value for {field_id}",
                    field_id=field_id
                )
    
    # ------------------------------------------------------------------------
    # confirm_mini_node: Confirm a mini-node (add to orbit)
    # ------------------------------------------------------------------------
    elif msg_type == "confirm_mini_node":
        category = payload.get("category")
        subnode_id = payload.get("subnode_id")
        values = payload.get("values", {})
        
        if all([category, subnode_id]):
            # Update theme if glow_color in values
            if "glow_color" in values and isinstance(values["glow_color"], str):
                state_manager.update_theme(glow_color=values["glow_color"])
            
            # Confirm the subnode
            orbit_angle = state_manager.confirm_subnode(category, subnode_id, values)
            
            # Save state
            await state_manager.save_category(category)
            await state_manager.save_theme()
            
            await ws_manager.send_to_client(client_id, {
                "type": "mini_node_confirmed",
                "subnode_id": subnode_id,
                "orbit_angle": orbit_angle
            })
            
            # Broadcast state sync
            await ws_manager.broadcast({
                "type": "state_sync",
                "state": state_manager.state.model_dump()
            }, exclude={client_id})
    
    # ------------------------------------------------------------------------
    # update_theme: Update theme colors directly
    # ------------------------------------------------------------------------
    elif msg_type == "update_theme":
        glow_color = payload.get("glow_color")
        font_color = payload.get("font_color")
        
        state_manager.update_theme(
            glow_color=glow_color,
            font_color=font_color
        )
        
        await state_manager.save_theme()
        
        # Broadcast theme change to all clients
        await ws_manager.broadcast({
            "type": "theme_updated",
            "glow": state_manager.state.active_theme.glow,
            "font": state_manager.state.active_theme.font,
            "primary": state_manager.state.active_theme.primary
        })
    
    # ------------------------------------------------------------------------
    # request_state: Send full current state
    # ------------------------------------------------------------------------
    elif msg_type == "request_state":
        await ws_manager.send_to_client(client_id, {
            "type": "initial_state",
            "state": state_manager.state.model_dump()
        })
    
    # ------------------------------------------------------------------------
    # ping/pong: Keep connection alive
    # ------------------------------------------------------------------------
    elif msg_type == "ping":
        await ws_manager.send_to_client(client_id, {"type": "pong"})
    
    # ------------------------------------------------------------------------
    # Unknown message type
    # ------------------------------------------------------------------------
    else:
        await ws_manager.send_error(client_id, f"Unknown message type: {msg_type}")


# ============================================================================
# WebSocket Endpoint
# ============================================================================

@app.websocket("/ws/iris")
async def websocket_endpoint(websocket: WebSocket):
    """
    Main WebSocket endpoint for IRIS.
    Handles connection, message loop, and disconnection.
    """
    # Generate unique client ID
    client_id = str(uuid.uuid4())[:8]
    ws_manager = get_websocket_manager()
    state_manager = get_state_manager()
    
    # Accept connection
    connected = await ws_manager.connect(websocket, client_id)
    if not connected:
        return
    
    try:
        # Send initial state
        await ws_manager.send_to_client(client_id, {
            "type": "initial_state",
            "state": state_manager.state.model_dump()
        })
        
        # Message loop
        while True:
            try:
                # Receive message
                data = await websocket.receive_text()
                
                try:
                    message = json.loads(data)
                except json.JSONDecodeError:
                    await ws_manager.send_error(client_id, "Invalid JSON")
                    continue
                
                # Handle message
                await handle_message(websocket, client_id, message)
                
            except WebSocketDisconnect:
                break
            except Exception as e:
                print(f"Error processing message from {client_id}: {e}")
                await ws_manager.send_error(client_id, f"Server error: {str(e)}")
    
    except Exception as e:
        print(f"WebSocket error for {client_id}: {e}")
    
    finally:
        # Clean up
        ws_manager.disconnect(client_id)


# ============================================================================
# Startup
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    # Get port from environment or default to 8000
    port = int(os.environ.get("IRIS_PORT", 8000))
    host = os.environ.get("IRIS_HOST", "127.0.0.1")
    
    print(f"""
╔══════════════════════════════════════════╗
║            IRIS Backend Server           ║
╠══════════════════════════════════════════╣
║  WebSocket: ws://{host}:{port}/ws/iris    ║
║  HTTP API:  http://{host}:{port}/         ║
╚══════════════════════════════════════════╝
    """)
    
    uvicorn.run(
        "backend.main:app",
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )
