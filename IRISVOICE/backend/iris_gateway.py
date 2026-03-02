"""
IRIS Gateway - WebSocket Message Router
Routes incoming WebSocket messages to appropriate handlers based on message type.
"""

import json
import logging
import time
from typing import Dict, Any, Optional

from .ws_manager import WebSocketManager, get_websocket_manager
from .state_manager import StateManager, get_state_manager
from .core_models import Category, get_subnodes_for_category
from .agent import get_agent_kernel, get_lfm_audio_manager
from .voice.voice_pipeline import get_voice_pipeline, VoiceState
from .voice.wake_word_discovery import WakeWordDiscovery
from .audio.pipeline import AudioPipeline
from .tools.cleanup_analyzer import CleanupAnalyzer
from .vision.vision_service import VisionService, get_vision_service

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
        
        # Initialize vision service (lazy loading - model not loaded until enabled)
        self._vision_service = get_vision_service()
        self._logger.info("[IRISGateway] Vision service initialized (lazy loading)")
    
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
            # GAP-02 FIX: Support both select_* (new) and set_* (legacy) message types
            if msg_type in ["select_category", "select_subnode", "go_back", "set_category", "set_subnode"]:
                await self._handle_navigation(session_id, client_id, message)
            
            elif msg_type in ["update_field", "update_theme", "confirm_mini_node"]:
                await self._handle_settings(session_id, client_id, message)
            
            elif msg_type == "set_model_selection":
                await self._handle_set_model_selection(session_id, client_id, message)
            
            elif msg_type in ["voice_command_start", "voice_command_end", "voice_command"]:
                await self._handle_voice(session_id, client_id, message)
            
            elif msg_type in ["get_wake_words", "select_wake_word"]:
                if msg_type == "get_wake_words":
                    await self._handle_get_wake_words(session_id, client_id)
                else:
                    await self._handle_select_wake_word(session_id, client_id, message)
            
            elif msg_type in ["get_cleanup_report", "execute_cleanup"]:
                if msg_type == "get_cleanup_report":
                    await self._handle_get_cleanup_report(session_id, client_id, message)
                else:
                    await self._handle_execute_cleanup(session_id, client_id, message)
            
            elif msg_type in ["text_message", "clear_chat"]:
                await self._handle_chat(session_id, client_id, message)
            
            elif msg_type in ["get_agent_status", "get_agent_tools", "agent_status", "agent_tools"]:
                await self._handle_status(session_id, client_id, message)
            
            elif msg_type == "get_available_models":
                await self._handle_get_available_models(session_id, client_id, message)
            
            elif msg_type == "get_audio_devices":
                await self._handle_get_audio_devices(session_id, client_id)
            
            elif msg_type == "test_connection":
                await self._handle_test_connection(session_id, client_id, message)
            
            # GAP-01 FIX: Additional message types from main.py
            elif msg_type == "collapse_to_idle":
                await self._handle_collapse_to_idle(session_id, client_id, message)
            
            elif msg_type == "expand_to_main":
                await self._handle_expand_to_main(session_id, client_id, message)
            
            elif msg_type == "reload_skills":
                await self._handle_reload_skills(session_id, client_id, message)
            
            elif msg_type == "execute_tool":
                await self._handle_execute_tool(session_id, client_id, message)
            
            elif msg_type == "ping":
                await self._ws_manager.send_to_client(client_id, {"type": "pong", "payload": {}})
            
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
        GAP-02 FIX: Supports both select_* (new) and set_* (legacy) message types.
        
        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary
        """
        msg_type = message.get("type")
        
        # GAP-02: Handle both select_category and set_category (legacy)
        if msg_type in ["select_category", "set_category"]:
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
        
        # GAP-02: Handle both select_subnode and set_subnode (legacy)
        elif msg_type in ["select_subnode", "set_subnode"]:
            # GAP-02: Support both subnode_id (new) and subnode (legacy) field names
            subnode_id = (message.get("subnode_id") or 
                         message.get("subnode") or 
                         message.get("payload", {}).get("subnode_id") or
                         message.get("payload", {}).get("subnode"))
            
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
                
                # Apply model selection if reasoning_model or tool_execution_model fields are updated
                if field_id in ["reasoning_model", "tool_execution_model"]:
                    try:
                        from .agent.agent_kernel import get_agent_kernel
                        
                        # Get the AgentKernel for this session
                        agent_kernel = get_agent_kernel(session_id)
                        
                        # Get current state to retrieve both model selections
                        state = await self._state_manager.get_state(session_id)
                        if state:
                            # Update the state with the new model selection
                            if field_id == "reasoning_model":
                                state.selected_reasoning_model = value
                            elif field_id == "tool_execution_model":
                                state.selected_tool_execution_model = value
                            
                            # Apply both model selections to AgentKernel
                            success_apply = agent_kernel.set_model_selection(
                                reasoning_model=state.selected_reasoning_model,
                                tool_execution_model=state.selected_tool_execution_model
                            )
                            
                            if success_apply:
                                self._logger.info(f"[Session: {session_id}] Applied model selection: "
                                                f"{field_id}={value}")
                            else:
                                self._logger.warning(f"[Session: {session_id}] Failed to apply model selection: "
                                                   f"{field_id}={value}. Model may not be available.")
                    except Exception as e:
                        self._logger.error(f"[Session: {session_id}] Error applying model selection: {e}")
                
                # Mask API keys in the response
                response_value = value
                if field_id == "openai_api_key" and value:
                    from ..utils.encryption import mask_api_key
                    response_value = mask_api_key(value)
                
                # Send confirmation with timestamp
                await self._ws_manager.send_to_client(client_id, {
                    "type": "field_updated",
                    "payload": {
                        "subnode_id": subnode_id,
                        "field_id": field_id,
                        "value": response_value,
                        "valid": True,
                        "timestamp": update_timestamp
                    }
                })
                
                # Broadcast to other clients in session with timestamp (also masked)
                await self._ws_manager.broadcast_to_session(
                    session_id,
                    {
                        "type": "field_updated",
                        "payload": {
                            "subnode_id": subnode_id,
                            "field_id": field_id,
                            "value": response_value,
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
        GAP-02 FIX: Also supports voice_command (legacy from main.py).
        
        Routes voice commands to VoicePipeline and broadcasts state updates to all clients.
        Sends audio level updates during listening state.
        
        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary
        """
        msg_type = message.get("type")
        
        # GAP-02: Handle legacy voice_command type by treating it as voice_command_start
        if msg_type == "voice_command":
            msg_type = "voice_command_start"
        
        try:
            if msg_type == "voice_command_start":
                self._logger.info(f"[Session: {session_id}] Starting voice command")
                
                # Start listening through VoicePipeline
                success = await self._voice_pipeline.start_listening(session_id)
                
                if success:
                    # BUG-03 FIX: Register async callbacks properly
                    # Before: sync lambdas wrapping async methods - coroutine never awaited
                    # After: async functions that properly await the async methods
                    async def state_change_callback(state: VoiceState) -> None:
                        await self._on_voice_state_change(session_id, state)
                    
                    async def audio_level_callback(level: float) -> None:
                        await self._on_audio_level_update(session_id, level)
                    
                    self._voice_pipeline.register_state_callback(
                        session_id,
                        state_change_callback
                    )
                    self._voice_pipeline.register_audio_level_callback(
                        session_id,
                        audio_level_callback
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
                
                # Wire tool bridge if not already set (enables real tool execution)
                from backend.agent.tool_bridge import get_agent_tool_bridge
                if agent_kernel._tool_bridge is None:
                    agent_kernel._tool_bridge = get_agent_tool_bridge()
                
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
        
        # GAP-02: Support both get_agent_tools (new) and agent_tools (legacy)
        elif msg_type in ["get_agent_tools", "agent_tools"]:
            # Tool bridge not yet integrated, send empty tools list
            # TODO: Integrate with AgentToolBridge when available
            await self._ws_manager.send_to_client(client_id, {
                "type": "agent_tools",
                "payload": {
                    "tools": []
                }
            })
    
    async def _handle_get_available_models(self, session_id: str, client_id: str, message: dict) -> None:
        """
        Handle get_available_models message - return list of available models from all inference sources.
        
        Args:
            session_id: Session ID
            client_id: Client ID
            message: Message dictionary
        """
        try:
            # Get AgentKernel for this session
            agent_kernel = get_agent_kernel(session_id)
            
            # Get available models from ModelRouter
            if agent_kernel._model_router:
                available_models = agent_kernel._model_router.get_available_models()
                
                await self._ws_manager.send_to_client(client_id, {
                    "type": "available_models",
                    "payload": {
                        "models": available_models
                    }
                })
            else:
                # No model router available - return empty list (model-agnostic)
                await self._ws_manager.send_to_client(client_id, {
                    "type": "available_models",
                    "payload": {
                        "models": []
                    }
                })
                
        except Exception as e:
            self._logger.error(f"Error getting available models: {e}", exc_info=True)
            await self._ws_manager.send_to_client(client_id, {
                "type": "available_models",
                "payload": {
                    "models": [],
                    "error": f"Failed to get available models: {str(e)}"
                }
            })
    
    async def _handle_set_model_selection(self, session_id: str, client_id: str, message: dict) -> None:
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
            success = agent_kernel.set_model_selection(reasoning_model, tool_execution_model)
            
            if success:
                # Update state manager with model selection
                state = await self._state_manager.get_state(session_id)
                if state:
                    state.selected_reasoning_model = reasoning_model
                    state.selected_tool_execution_model = tool_execution_model
                    # State manager will auto-save
                
                # Send confirmation to client
                await self._ws_manager.send_to_client(client_id, {
                    "type": "model_selection_updated",
                    "payload": {
                        "reasoning_model": reasoning_model,
                        "tool_execution_model": tool_execution_model,
                        "success": True
                    }
                })
                
                # Broadcast to other clients in session
                await self._ws_manager.broadcast_to_session(
                    session_id,
                    {
                        "type": "model_selection_updated",
                        "payload": {
                            "reasoning_model": reasoning_model,
                            "tool_execution_model": tool_execution_model,
                            "success": True
                        }
                    },
                    exclude_clients={client_id}
                )
            else:
                # Send error
                await self._send_error(client_id, "Failed to set model selection - models may not be available")
                
        except Exception as e:
            self._logger.error(f"Error setting model selection: {e}", exc_info=True)
            await self._send_error(client_id, f"Failed to set model selection: {str(e)}")
    
    async def _handle_test_connection(self, session_id: str, client_id: str, message: dict) -> None:
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
                    state_manager = await self._state_manager._get_session_state_manager(session_id)
                    if state_manager:
                        api_key = await state_manager.get_decrypted_field_value("model", "openai_api_key")
                
                if not api_url:
                    state_manager = await self._state_manager._get_session_state_manager(session_id)
                    if state_manager:
                        api_url = await state_manager.get_field_value("model", "openai_api_url")
                
                # Use default URL if not provided
                if not api_url:
                    api_url = "https://api.openai.com/v1"
                
                if not api_key:
                    await self._ws_manager.send_to_client(client_id, {
                        "type": "connection_test_result",
                        "payload": {
                            "connection_type": "openai",
                            "success": False,
                            "message": "API key is required",
                            "tested_url": api_url
                        }
                    })
                    return
                
                # Test the connection
                from ..utils.openai_connection_test import test_openai_connection
                success, message = await test_openai_connection(api_key, api_url)
                
                # Send result to client
                await self._ws_manager.send_to_client(client_id, {
                    "type": "connection_test_result",
                    "payload": {
                        "connection_type": "openai",
                        "success": success,
                        "message": message,
                        "tested_url": api_url
                    }
                })
            else:
                await self._send_error(client_id, f"Unknown connection type: {connection_type}")
                
        except Exception as e:
            self._logger.error(f"Error testing connection: {e}", exc_info=True)
            await self._ws_manager.send_to_client(client_id, {
                "type": "connection_test_result",
                "payload": {
                    "connection_type": connection_type,
                    "success": False,
                    "message": f"Error testing connection: {str(e)}"
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
    
    async def _handle_get_wake_words(self, session_id: str, client_id: str) -> None:
        """
        Handle get_wake_words message - return discovered wake word files.
        
        Args:
            session_id: Session ID
            client_id: Client ID
        """
        try:
            self._logger.info(
                f"[Session: {session_id}] Processing get_wake_words request",
                extra={"session_id": session_id, "client_id": client_id}
            )
            
            # Get discovered wake word files
            discovered_files = self._wake_word_discovery.get_discovered_files()
            
            # Convert to serializable format
            wake_words_list = [
                {
                    "filename": wf.filename,
                    "display_name": wf.display_name,
                    "platform": wf.platform,
                    "version": wf.version
                }
                for wf in discovered_files
            ]
            
            self._logger.info(
                f"[Session: {session_id}] Returning {len(wake_words_list)} wake word file(s)",
                extra={"session_id": session_id, "client_id": client_id, "count": len(wake_words_list)}
            )
            
            # Send response to client
            await self._ws_manager.send_to_client(client_id, {
                "type": "wake_words_list",
                "payload": {
                    "wake_words": wake_words_list,
                    "count": len(wake_words_list)
                }
            })
            
        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error handling get_wake_words: {e}",
                exc_info=True,
                extra={"session_id": session_id, "client_id": client_id, "error": str(e)}
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
                extra={"session_id": session_id, "client_id": client_id}
            )
            
            # Get available audio devices
            devices = AudioPipeline.list_devices()
            
            # Separate input and output devices
            input_devices = [
                {
                    "index": d["index"],
                    "name": d["name"],
                    "sample_rate": d["sample_rate"]
                }
                for d in devices if d["input"]
            ]
            output_devices = [
                {
                    "index": d["index"],
                    "name": d["name"],
                    "sample_rate": d["sample_rate"]
                }
                for d in devices if d["output"]
            ]
            
            self._logger.info(
                f"[Session: {session_id}] Returning {len(input_devices)} input device(s) and {len(output_devices)} output device(s)",
                extra={"session_id": session_id, "client_id": client_id, "input_count": len(input_devices), "output_count": len(output_devices)}
            )
            
            # Send response to client
            await self._ws_manager.send_to_client(client_id, {
                "type": "audio_devices",
                "payload": {
                    "input_devices": input_devices,
                    "output_devices": output_devices,
                    "input_count": len(input_devices),
                    "output_count": len(output_devices)
                }
            })
            
        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error handling get_audio_devices: {e}",
                exc_info=True,
                extra={"session_id": session_id, "client_id": client_id, "error": str(e)}
            )
            await self._send_error(client_id, f"Error retrieving audio devices: {str(e)}")
    
    async def _handle_select_wake_word(self, session_id: str, client_id: str, message: dict) -> None:
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
                    extra={"session_id": session_id, "client_id": client_id}
                )
                await self._send_error(client_id, "No filename provided")
                return
            
            self._logger.info(
                f"[Session: {session_id}] Processing select_wake_word: {filename}",
                extra={"session_id": session_id, "client_id": client_id, "wake_word_filename": filename}
            )
            
            # Look up wake word file
            wake_word_file = self._wake_word_discovery.get_file_by_filename(filename)
            
            if not wake_word_file:
                self._logger.warning(
                    f"[Session: {session_id}] Wake word file not found: {filename}",
                    extra={"session_id": session_id, "client_id": client_id, "wake_word_filename": filename}
                )
                await self._send_error(client_id, f"Wake word file not found: {filename}")
                return
            
            # TODO: Load wake word file into PorcupineDetector
            # This will be implemented when PorcupineDetector integration is ready
            # For now, just acknowledge the selection
            self._logger.info(
                f"[Session: {session_id}] Wake word selected: {wake_word_file.display_name} "
                f"(file: {wake_word_file.filename})",
                extra={
                    "session_id": session_id,
                    "client_id": client_id,
                    "wake_word_filename": wake_word_file.filename,
                    "display_name": wake_word_file.display_name,
                    "platform": wake_word_file.platform
                }
            )
            
            # Broadcast selection to all clients in session
            await self._ws_manager.broadcast_to_session(session_id, {
                "type": "wake_word_selected",
                "payload": {
                    "filename": wake_word_file.filename,
                    "display_name": wake_word_file.display_name,
                    "platform": wake_word_file.platform,
                    "version": wake_word_file.version
                }
            })
            
        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error handling select_wake_word: {e}",
                exc_info=True,
                extra={"session_id": session_id, "client_id": client_id, "error": str(e)}
            )
            await self._send_error(client_id, f"Error selecting wake word: {str(e)}")
    
    async def _handle_get_cleanup_report(self, session_id: str, client_id: str, message: dict) -> None:
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
                extra={"session_id": session_id, "client_id": client_id, "dry_run": dry_run}
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
                        "reason": f.reason
                    }
                    for f in report.unused_models
                ],
                "unused_dependencies": [
                    {
                        "name": d.name,
                        "version": d.version,
                        "install_size_bytes": d.install_size_bytes,
                        "reason": d.reason
                    }
                    for d in report.unused_dependencies
                ],
                "unused_wake_words": [
                    {
                        "path": f.path,
                        "size_bytes": f.size_bytes,
                        "last_accessed": f.last_accessed.isoformat(),
                        "reason": f.reason
                    }
                    for f in report.unused_wake_words
                ],
                "unused_configs": [
                    {
                        "path": f.path,
                        "size_bytes": f.size_bytes,
                        "last_accessed": f.last_accessed.isoformat(),
                        "reason": f.reason
                    }
                    for f in report.unused_configs
                ],
                "total_size_bytes": report.total_size_bytes,
                "total_count": report.total_count,
                "warnings": report.warnings,
                "timestamp": report.timestamp.isoformat()
            }
            
            self._logger.info(
                f"[Session: {session_id}] Cleanup report generated: "
                f"{report.total_count} items, {report.total_size_bytes / (1024*1024):.2f} MB",
                extra={
                    "session_id": session_id,
                    "total_count": report.total_count,
                    "total_size_mb": report.total_size_bytes / (1024*1024)
                }
            )
            
            # Send report to client
            await self._ws_manager.send_to_client(client_id, {
                "type": "cleanup_report",
                "payload": report_dict
            })
            
        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error generating cleanup report: {e}",
                exc_info=True,
                extra={"session_id": session_id, "client_id": client_id, "error": str(e)}
            )
            await self._send_error(client_id, f"Error generating cleanup report: {str(e)}")
    
    async def _handle_execute_cleanup(self, session_id: str, client_id: str, message: dict) -> None:
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
                extra={"session_id": session_id, "client_id": client_id, "item_count": len(items)}
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
                "backup_path": result.backup_path
            }
            
            self._logger.info(
                f"[Session: {session_id}] Cleanup executed: "
                f"success={result.success}, freed {result.freed_bytes / (1024*1024):.2f} MB",
                extra={
                    "session_id": session_id,
                    "success": result.success,
                    "freed_mb": result.freed_bytes / (1024*1024),
                    "removed_files": len(result.removed_files),
                    "removed_deps": len(result.removed_dependencies),
                    "errors": len(result.errors)
                }
            )
            
            # Send result to client
            await self._ws_manager.send_to_client(client_id, {
                "type": "cleanup_result",
                "payload": result_dict
            })
            
        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error executing cleanup: {e}",
                exc_info=True,
                extra={"session_id": session_id, "client_id": client_id, "error": str(e)}
            )
            await self._send_error(client_id, f"Error executing cleanup: {str(e)}")
    
    # ============================================================================
    # GAP-01 FIX: Additional handlers from main.py
    # ============================================================================
    
    async def _handle_collapse_to_idle(self, session_id: str, client_id: str, message: dict) -> None:
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
                extra={"session_id": session_id, "client_id": client_id}
            )
            
            await self._state_manager.collapse_to_idle(session_id)
            await self._broadcast_state_update(session_id, exclude_client=client_id)
            
        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error collapsing to idle: {e}",
                exc_info=True,
                extra={"session_id": session_id, "client_id": client_id, "error": str(e)}
            )
            await self._send_error(client_id, f"Error collapsing to idle: {str(e)}")
    
    async def _handle_expand_to_main(self, session_id: str, client_id: str, message: dict) -> None:
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
                extra={"session_id": session_id, "client_id": client_id}
            )
            
            # Send confirmation to client
            await self._ws_manager.send_to_client(client_id, {
                "type": "category_expanded",
                "payload": {}
            })
            
        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error expanding to main: {e}",
                exc_info=True,
                extra={"session_id": session_id, "client_id": client_id, "error": str(e)}
            )
            await self._send_error(client_id, f"Error expanding to main: {str(e)}")
    
    async def _handle_reload_skills(self, session_id: str, client_id: str, message: dict) -> None:
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
                extra={"session_id": session_id, "client_id": client_id}
            )
            
            from backend.agent.skills import get_skills_loader
            loader = get_skills_loader()
            loader.reload()
            
            await self._ws_manager.send_to_client(client_id, {
                "type": "skills_reloaded",
                "payload": {"skills": loader.list_skills()}
            })
            
        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error reloading skills: {e}",
                exc_info=True,
                extra={"session_id": session_id, "client_id": client_id, "error": str(e)}
            )
            await self._ws_manager.send_to_client(client_id, {
                "type": "skills_error",
                "payload": {"error": str(e)}
            })
    
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
            
            # Clean up voice pipeline callbacks
            if self._voice_pipeline:
                self._voice_pipeline.cleanup_session(session_id)
            
            self._logger.info(f"[Session: {session_id}] Session cleanup completed")
            
        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error during session cleanup: {e}",
                exc_info=True,
                extra={"session_id": session_id, "error": str(e)}
            )
    
    async def _handle_execute_tool(self, session_id: str, client_id: str, message: dict) -> None:
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
                await self._send_validation_error(client_id, "tool_name", "Tool name is required")
                return
            
            self._logger.info(
                f"[Session: {session_id}] Executing tool: {tool_name}",
                extra={"session_id": session_id, "client_id": client_id, "tool": tool_name}
            )
            
            # Get agent kernel from app state via global
            from backend.agent import get_agent_kernel
            agent_kernel = get_agent_kernel()
            
            if agent_kernel and agent_kernel.tool_bridge:
                try:
                    result = await agent_kernel.tool_bridge.execute_tool(tool_name, parameters)
                    await self._ws_manager.send_to_client(client_id, {
                        "type": "tool_result",
                        "payload": {"tool": tool_name, "result": result}
                    })
                except Exception as e:
                    await self._ws_manager.send_to_client(client_id, {
                        "type": "tool_result",
                        "payload": {"tool": tool_name, "error": str(e)}
                    })
            else:
                await self._ws_manager.send_to_client(client_id, {
                    "type": "tool_result",
                    "payload": {"tool": tool_name, "error": "Tool bridge not available"}
                })
                
        except Exception as e:
            self._logger.error(
                f"[Session: {session_id}] Error executing tool: {e}",
                exc_info=True,
                extra={"session_id": session_id, "client_id": client_id, "error": str(e)}
            )
            await self._send_error(client_id, f"Error executing tool: {str(e)}")
    
    async def _handle_enable_vision(self, session_id: str, client_id: str) -> None:
        """
        Handle enable_vision message - loads the vision model with 4-bit quantization.
        
        Args:
            session_id: Session ID
            client_id: Client ID
        """
        try:
            self._logger.info(f"[Session: {session_id}] Enabling vision service")
            
            # Send loading status
            await self._ws_manager.send_to_client(client_id, {
                "type": "vision_status",
                "payload": {
                    "status": "loading",
                    "vram_usage_mb": None,
                    "load_progress_percent": 0,
                    "error_message": None,
                    "model_name": self._vision_service.model_name,
                    "quantization_enabled": self._vision_service.use_quantization,
                    "is_available": True
                }
            })
            
            # Enable vision service (lazy loading with quantization)
            success = await self._vision_service.enable()
            
            if success:
                status = self._vision_service.get_status()
                await self._ws_manager.send_to_client(client_id, {
                    "type": "enable_vision",
                    "payload": {
                        "success": True,
                        "vram_usage_mb": status.get("vram_usage_mb"),
                        "quantization_enabled": status.get("quantization_enabled")
                    }
                })
                # Broadcast updated status to all clients
                await self._ws_manager.broadcast_to_session(session_id, {
                    "type": "vision_status",
                    "payload": status
                })
            else:
                await self._ws_manager.send_to_client(client_id, {
                    "type": "enable_vision",
                    "payload": {
                        "success": False,
                        "error": "Failed to enable vision service"
                    }
                })
                
        except Exception as e:
            self._logger.error(f"[Session: {session_id}] Error enabling vision: {e}", exc_info=True)
            await self._ws_manager.send_to_client(client_id, {
                "type": "enable_vision",
                "payload": {
                    "success": False,
                    "error": str(e)
                }
            })
    
    async def _handle_disable_vision(self, session_id: str, client_id: str) -> None:
        """
        Handle disable_vision message - unloads the vision model and frees VRAM.
        
        Args:
            session_id: Session ID
            client_id: Client ID
        """
        try:
            self._logger.info(f"[Session: {session_id}] Disabling vision service")
            
            # Disable vision service
            await self._vision_service.disable()
            
            await self._ws_manager.send_to_client(client_id, {
                "type": "disable_vision",
                "payload": {"success": True}
            })
            
            # Broadcast updated status to all clients
            status = self._vision_service.get_status()
            await self._ws_manager.broadcast_to_session(session_id, {
                "type": "vision_status",
                "payload": status
            })
            
        except Exception as e:
            self._logger.error(f"[Session: {session_id}] Error disabling vision: {e}", exc_info=True)
            await self._ws_manager.send_to_client(client_id, {
                "type": "disable_vision",
                "payload": {
                    "success": False,
                    "error": str(e)
                }
            })
    
    async def _handle_get_vision_status(self, session_id: str, client_id: str) -> None:
        """
        Handle get_vision_status message - returns current vision service status.
        
        Args:
            session_id: Session ID
            client_id: Client ID
        """
        try:
            status = self._vision_service.get_status()
            await self._ws_manager.send_to_client(client_id, {
                "type": "vision_status",
                "payload": status
            })
        except Exception as e:
            self._logger.error(f"[Session: {session_id}] Error getting vision status: {e}", exc_info=True)
            await self._send_error(client_id, f"Error getting vision status: {str(e)}")
    
    async def _broadcast_state_update(self, session_id: str, exclude_client: Optional[str] = None) -> None:
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
                {
                    "type": "state_sync",
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
        GAP-09 FIX: Uses flat payload structure for consistency.
        
        Args:
            client_id: Client ID
            field_id: Field ID that failed validation
            error_message: Error message
        """
        await self._ws_manager.send_to_client(client_id, {
            "type": "validation_error",
            "field_id": field_id,
            "error": error_message
        })


# Global instance
_iris_gateway: Optional[IRISGateway] = None


def get_iris_gateway() -> IRISGateway:
    """Get or create the singleton IRISGateway."""
    global _iris_gateway
    if _iris_gateway is None:
        _iris_gateway = IRISGateway()
    return _iris_gateway

