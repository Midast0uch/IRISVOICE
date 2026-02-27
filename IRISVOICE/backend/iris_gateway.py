"""
IRIS Gateway - WebSocket Message Router
Routes incoming WebSocket messages to appropriate handlers based on message type.
"""

import json
import logging
from typing import Dict, Any, Optional

from .ws_manager import WebSocketManager, get_websocket_manager
from .state_manager import StateManager, get_state_manager
from .core_models import Category, get_subnodes_for_category
from .agent import get_agent_kernel, get_lfm_audio_manager
from .voice.voice_pipeline import get_voice_pipeline, VoiceState

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
        self._voice_pipeline = get_voice_pipeline()
        self._logger = logging.getLogger(__name__)
    
    async def handle_message(self, client_id: str, message: dict) -> None:
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
        
        Raises:
            ValueError: If message format is invalid
        """
        try:
            # Validate message format
            if not isinstance(message, dict):
                self._logger.error(
                    f"Invalid message format from client {client_id}: not a dict",
                    extra={"client_id": client_id, "message_type": type(message).__name__}
                )
                await self._send_error(client_id, "Invalid message format: expected dict")
                return
            
            msg_type = message.get("type")
            if not msg_type:
                self._logger.error(
                    f"Missing message type from client {client_id}",
                    extra={"client_id": client_id, "raw_message": str(message)[:200]}
                )
                await self._send_error(client_id, "Invalid message format: missing 'type' field")
                return
            
            # Get session ID for this client
            session_id = self._ws_manager.get_session_id_for_client(client_id)
            if not session_id:
                self._logger.error(
                    f"No session found for client {client_id}",
                    extra={"client_id": client_id, "message_type": msg_type}
                )
                await self._send_error(client_id, "No active session")
                return
            
            self._logger.info(
                f"[Session: {session_id}] Processing message type: {msg_type}",
                extra={"session_id": session_id, "client_id": client_id, "message_type": msg_type}
            )
            
            # Route to appropriate handler based on message type
            if msg_type in ["select_category", "select_subnode", "go_back"]:
                await self._handle_navigation(session_id, client_id, message)
            
            elif msg_type in ["update_field", "update_theme", "confirm_mini_node"]:
                await self._handle_settings(session_id, client_id, message)
            
            elif msg_type in ["voice_command_start", "voice_command_end"]:
                await self._handle_voice(session_id, client_id, message)
            
            elif msg_type in ["text_message", "clear_chat"]:
                await self._handle_chat(session_id, client_id, message)
            
            elif msg_type in ["get_agent_status", "get_agent_tools"]:
                await self._handle_status(session_id, client_id, message)
            
            elif msg_type == "ping":
                await self._ws_manager.send_to_client(client_id, {"type": "pong", "payload": {}})
            
            elif msg_type == "pong":
                await self._ws_manager.handle_pong(client_id)
            
            elif msg_type == "request_state":
                await self._handle_request_state(session_id, client_id)
            
            else:
                self._logger.warning(
                    f"Unknown message type: {msg_type}",
                    extra={"session_id": session_id, "client_id": client_id, "message_type": msg_type}
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
            msg_type = message.get("type", "unknown") if isinstance(message, dict) else "unknown"
            self._logger.error(
                f"Error handling message type {msg_type} from client {client_id}: {e}",
                exc_info=True,
                extra={"client_id": client_id, "message_type": msg_type, "error": str(e)}
            )
            await self._send_error(client_id, f"Error processing message: {str(e)}")
    
    async def _handle_navigation(self, session_id: str, client_id: str, message: dict) -> None:
        """
        Handle navigation messages: select_category, select_subnode, go_back.
        
        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary
        """
        msg_type = message.get("type")
        
        if msg_type == "select_category":
            category = message.get("category") or message.get("payload", {}).get("category")
            
            if not category:
                await self._send_validation_error(client_id, "category", "Category is required")
                return
            
            # Validate category
            try:
                category_enum = Category(category) if isinstance(category, str) else category
            except ValueError:
                await self._send_validation_error(client_id, "category", f"Invalid category: {category}")
                return
            
            # Update state
            await self._state_manager.set_category(session_id, category_enum)
            
            # Get subnodes for this category
            subnodes = get_subnodes_for_category(category_enum)
            
            # Send confirmation with subnodes
            await self._ws_manager.send_to_client(client_id, {
                "type": "category_changed",
                "payload": {
                    "category": category,
                    "subnodes": [s.model_dump() for s in subnodes]
                }
            })
            
            # Broadcast state update to other clients in session
            await self._broadcast_state_update(session_id, exclude_client=client_id)
        
        elif msg_type == "select_subnode":
            subnode_id = message.get("subnode_id") or message.get("payload", {}).get("subnode_id")
            
            if not subnode_id:
                await self._send_validation_error(client_id, "subnode_id", "Subnode ID is required")
                return
            
            # Update state
            await self._state_manager.set_subnode(session_id, subnode_id)
            
            # Send confirmation
            await self._ws_manager.send_to_client(client_id, {
                "type": "subnode_changed",
                "payload": {
                    "subnode_id": subnode_id
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
        Handle settings messages: update_field, update_theme, confirm_mini_node.
        
        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary
        """
        msg_type = message.get("type")
        payload = message.get("payload", {})
        
        if msg_type == "update_field":
            subnode_id = message.get("subnode_id") or payload.get("subnode_id")
            field_id = message.get("field_id") or payload.get("field_id")
            value = message.get("value") if "value" in message else payload.get("value")
            timestamp = payload.get("timestamp")  # Optional timestamp from client
            
            if not subnode_id or not field_id:
                await self._send_validation_error(
                    client_id,
                    "field",
                    "Both subnode_id and field_id are required"
                )
                return
            
            # Update field value with timestamp handling
            success, update_timestamp = await self._state_manager.update_field(
                session_id, subnode_id, field_id, value, timestamp
            )
            
            if success:
                # Apply TTS configuration if agent.speech fields are updated
                if subnode_id == "speech":
                    try:
                        lfm_audio_manager = get_lfm_audio_manager()
                        if field_id == "tts_voice":
                            lfm_audio_manager.update_voice_config(tts_voice=value)
                            self._logger.info(f"[Session: {session_id}] Updated TTS voice to {value}")
                        elif field_id == "speaking_rate":
                            lfm_audio_manager.update_voice_config(speaking_rate=value)
                            self._logger.info(f"[Session: {session_id}] Updated speaking rate to {value}")
                    except Exception as e:
                        self._logger.error(f"[Session: {session_id}] Error updating TTS configuration: {e}")
                
                # Send confirmation with timestamp
                await self._ws_manager.send_to_client(client_id, {
                    "type": "field_updated",
                    "payload": {
                        "subnode_id": subnode_id,
                        "field_id": field_id,
                        "value": value,
                        "valid": True,
                        "timestamp": update_timestamp
                    }
                })
                
                # Broadcast to other clients in session with timestamp
                await self._ws_manager.broadcast_to_session(
                    session_id,
                    {
                        "type": "field_updated",
                        "payload": {
                            "subnode_id": subnode_id,
                            "field_id": field_id,
                            "value": value,
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
                # Send confirmation to all clients in session
                await self._ws_manager.broadcast_to_session(
                    session_id,
                    {
                        "type": "theme_updated",
                        "payload": {
                            "active_theme": state.active_theme.model_dump()
                        }
                    }
                )
        
        elif msg_type == "confirm_mini_node":
            subnode_id = payload.get("subnode_id")
            values = payload.get("values", {})
            
            if not subnode_id:
                await self._send_validation_error(client_id, "subnode_id", "Subnode ID is required")
                return
            
            # Get current category
            state = await self._state_manager.get_state(session_id)
            if not state or not state.current_category:
                await self._send_error(client_id, "No active category")
                return
            
            # Confirm subnode
            orbit_angle = await self._state_manager.confirm_subnode(
                session_id,
                state.current_category.value,
                subnode_id,
                values
            )
            
            if orbit_angle is not None:
                # Send confirmation
                await self._ws_manager.send_to_client(client_id, {
                    "type": "mini_node_confirmed",
                    "payload": {
                        "subnode_id": subnode_id,
                        "orbit_angle": orbit_angle
                    }
                })
                
                # Broadcast state update
                await self._broadcast_state_update(session_id, exclude_client=client_id)
            else:
                await self._send_error(client_id, "Failed to confirm mini node")
    
    async def _handle_voice(self, session_id: str, client_id: str, message: dict) -> None:
        """
        Handle voice messages: voice_command_start, voice_command_end.
        
        Routes voice commands to VoicePipeline and broadcasts state updates to all clients.
        Sends audio level updates during listening state.
        
        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary
        """
        msg_type = message.get("type")
        
        try:
            if msg_type == "voice_command_start":
                self._logger.info(f"[Session: {session_id}] Starting voice command")
                
                # Start listening through VoicePipeline
                success = await self._voice_pipeline.start_listening(session_id)
                
                if success:
                    # Register callbacks for state and audio level updates
                    self._voice_pipeline.register_state_callback(
                        session_id,
                        lambda state: self._on_voice_state_change(session_id, state)
                    )
                    self._voice_pipeline.register_audio_level_callback(
                        session_id,
                        lambda level: self._on_audio_level_update(session_id, level)
                    )
                    
                    # Send listening state to all clients
                    await self._ws_manager.broadcast_to_session(
                        session_id,
                        {
                            "type": "listening_state",
                            "payload": {
                                "state": "listening"
                            }
                        }
                    )
                else:
                    # Send error state
                    await self._ws_manager.broadcast_to_session(
                        session_id,
                        {
                            "type": "listening_state",
                            "payload": {
                                "state": "error"
                            }
                        }
                    )
                    await self._send_error(client_id, "Failed to start voice command")
            
            elif msg_type == "voice_command_end":
                self._logger.info(f"[Session: {session_id}] Ending voice command")
                
                # Stop listening through VoicePipeline
                success = await self._voice_pipeline.stop_listening(session_id)
                
                if success:
                    # Send processing state to all clients
                    await self._ws_manager.broadcast_to_session(
                        session_id,
                        {
                            "type": "listening_state",
                            "payload": {
                                "state": "processing_conversation"
                            }
                        }
                    )
                else:
                    # Send error state
                    await self._ws_manager.broadcast_to_session(
                        session_id,
                        {
                            "type": "listening_state",
                            "payload": {
                                "state": "error"
                            }
                        }
                    )
                    await self._send_error(client_id, "Failed to stop voice command")
        
        except Exception as e:
            self._logger.error(f"Error handling voice command: {e}", exc_info=True)
            await self._ws_manager.broadcast_to_session(
                session_id,
                {
                    "type": "listening_state",
                    "payload": {
                        "state": "error"
                    }
                }
            )
            await self._send_error(client_id, f"Voice command error: {str(e)}")
    
    async def _on_voice_state_change(self, session_id: str, state: VoiceState) -> None:
        """
        Callback for voice state changes
        
        Args:
            session_id: Session ID
            state: New voice state
        """
        # Broadcast state change to all clients in session
        await self._ws_manager.broadcast_to_session(
            session_id,
            {
                "type": "listening_state",
                "payload": {
                    "state": state.value
                }
            }
        )
    
    async def _on_audio_level_update(self, session_id: str, level: float) -> None:
        """
        Callback for audio level updates
        
        Args:
            session_id: Session ID
            level: Audio level (0.0 to 1.0)
        """
        # Broadcast audio level to all clients in session
        await self._ws_manager.broadcast_to_session(
            session_id,
            {
                "type": "audio_level",
                "payload": {
                    "level": level
                }
            }
        )
    
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
                agent_kernel = get_agent_kernel(session_id)
                
                # Process message synchronously (AgentKernel.process_text_message is sync)
                # Run in executor to avoid blocking the event loop
                import asyncio
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    agent_kernel.process_text_message,
                    text,
                    session_id
                )
                
                # Send response to client
                await self._ws_manager.send_to_client(client_id, {
                    "type": "text_response",
                    "payload": {
                        "text": response,
                        "sender": "assistant"
                    }
                })
                
            except Exception as e:
                self._logger.error(f"Error processing text message: {e}", exc_info=True)
                await self._send_error(client_id, f"Agent kernel error: {str(e)}")
        
        elif msg_type == "clear_chat":
            # Get AgentKernel for this session and clear conversation
            try:
                agent_kernel = get_agent_kernel(session_id)
                agent_kernel.clear_conversation()
                
                self._logger.info(f"Conversation cleared for session {session_id}")
                
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
        
        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary
        """
        msg_type = message.get("type")
        
        if msg_type == "get_agent_status":
            # Get AgentKernel status for this session
            try:
                agent_kernel = get_agent_kernel(session_id)
                status = agent_kernel.get_status()
                
                await self._ws_manager.send_to_client(client_id, {
                    "type": "agent_status",
                    "payload": status
                })
                
            except Exception as e:
                self._logger.error(f"Error getting agent status: {e}", exc_info=True)
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
        
        elif msg_type == "get_agent_tools":
            # Tool bridge not yet integrated, send empty tools list
            # TODO: Integrate with AgentToolBridge when available
            await self._ws_manager.send_to_client(client_id, {
                "type": "agent_tools",
                "payload": {
                    "tools": []
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
    
    async def _broadcast_state_update(self, session_id: str, exclude_client: Optional[str] = None) -> None:
        """
        Broadcast state update to all clients in a session.
        
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
                    "type": "state_update",
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
        
        Args:
            client_id: Client ID
            field_id: Field ID that failed validation
            error_message: Error message
        """
        await self._ws_manager.send_to_client(client_id, {
            "type": "validation_error",
            "payload": {
                "field_id": field_id,
                "error": error_message
            }
        })


# Global instance
_iris_gateway: Optional[IRISGateway] = None


def get_iris_gateway() -> IRISGateway:
    """Get or create the singleton IRISGateway."""
    global _iris_gateway
    if _iris_gateway is None:
        _iris_gateway = IRISGateway()
    return _iris_gateway
