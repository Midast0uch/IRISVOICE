"""
IRIS Gateway - Main gateway implementation for centralized message routing and security
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, Callable, Set
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum

from ..sessions import SessionManager, get_session_manager
from ..security.mcp_security import MCPSecurityManager
from ..security.audit_logger import SecurityAuditLogger
from ..security.security_types import SecurityContext
from ..models import IRISState


class MessageType(Enum):
    """Supported message types in the gateway"""
    STATE_UPDATE = "state_update"
    SESSION_CREATE = "session_create"
    SESSION_DESTROY = "session_destroy"
    SECURITY_VIOLATION = "security_violation"
    VISION_REQUEST = "vision_request"
    AUDIO_REQUEST = "audio_request"
    AUTOMATION_REQUEST = "automation_request"
    SYSTEM_COMMAND = "system_command"
    ERROR = "error"
    HEARTBEAT = "heartbeat"


@dataclass
class GatewayMessage:
    """Standardized message format for gateway communication"""
    id: str
    type: MessageType
    session_id: Optional[str]
    client_id: Optional[str]
    payload: Dict[str, Any]
    timestamp: datetime
    security_level: str = "SAFE"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary for JSON serialization"""
        return {
            "id": self.id,
            "type": self.type.value,
            "session_id": self.session_id,
            "client_id": self.client_id,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
            "security_level": self.security_level
        }


class IRISGateway:
    """Central gateway for IRISVOICE system"""
    
    def __init__(self, 
                 session_manager: Optional[SessionManager] = None,
                 security_manager: Optional[MCPSecurityManager] = None,
                 audit_logger: Optional[SecurityAuditLogger] = None):
        """Initialize the gateway with optional components"""
        self.session_manager = session_manager or get_session_manager()
        self.security_manager = security_manager or MCPSecurityManager()
        self.audit_logger = audit_logger or SecurityAuditLogger()
        
        self.logger = logging.getLogger(__name__)
        self._message_handlers: Dict[MessageType, Callable] = {}
        self._active_connections: Set[str] = set()
        self._connection_metadata: Dict[str, Dict[str, Any]] = {}
        
        # Initialize default message handlers
        self._register_default_handlers()
    
    def _register_default_handlers(self):
        """Register default message handlers"""
        self.register_handler(MessageType.SESSION_CREATE, self._handle_session_create)
        self.register_handler(MessageType.SESSION_DESTROY, self._handle_session_destroy)
        self.register_handler(MessageType.STATE_UPDATE, self._handle_state_update)
        self.register_handler(MessageType.SECURITY_VIOLATION, self._handle_security_violation)
        self.register_handler(MessageType.ERROR, self._handle_error)
        self.register_handler(MessageType.HEARTBEAT, self._handle_heartbeat)
    
    def register_handler(self, message_type: MessageType, handler: Callable):
        """Register a handler for a specific message type"""
        self._message_handlers[message_type] = handler
        self.logger.info(f"Registered handler for {message_type.value}")
    
    async def process_message(self, message: GatewayMessage) -> Optional[GatewayMessage]:
        """Process a message through the gateway"""
        try:
            # Validate message
            if not self._validate_message(message):
                return self._create_error_response(message, "Invalid message format")
            
            # Security check
            security_result = await self._security_check(message)
            if not security_result.allowed:
                message.security_level = "BLOCKED"
                await self.audit_logger.log_security_violation(
                    validation_result=security_result,
                    context=self._create_security_context(message),
                    tool_name=message.payload.get("tool"),
                    operation_type=message.payload.get("command"),
                    sanitized_args=security_result.sanitized_args
                )
                return self._create_security_violation_response(message, security_result.reason)
            
            # Route message to appropriate handler
            handler = self._message_handlers.get(message.type)
            if handler:
                return await handler(message)
            else:
                return self._create_error_response(message, f"No handler for message type {message.type.value}")
                
        except Exception as e:
            self.logger.error(f"Error processing message {message.id}: {e}")
            return self._create_error_response(message, f"Processing error: {str(e)}")
    
    def _validate_message(self, message: GatewayMessage) -> bool:
        """Validate message format and required fields"""
        if not message.id or not message.type:
            return False
        
        # Validate message type
        if not isinstance(message.type, MessageType):
            return False
        
        # Session validation for session-specific messages
        if message.session_id and message.type not in [MessageType.SESSION_CREATE]:
            session = self.session_manager.get_session(message.session_id)
            if not session:
                return False
        
        return True

    def _create_security_context(self, message: GatewayMessage) -> SecurityContext:
        """Create a security context from a gateway message."""
        return SecurityContext(
            session_id=message.session_id,
            user_id=message.client_id, # Or map client_id to a user_id
            source_ip=None, # Would need to be passed in from the ws connection
            user_agent=None, # Would need to be passed in from the ws connection
            tool_name=message.payload.get("tool"),
            operation_type=message.payload.get("command"),
            correlation_id=message.id
        )

    
    async def _security_check(self, message: GatewayMessage):
        """Perform security validation on the message"""
        # First, validate the gateway message itself to ensure the message type is allowed.
        gateway_validation = await self.security_manager.validate_tool_operation(
            tool_name="gateway_message",
            operation=message.type.value,
            arguments={} # Don't check payload here, we do it below.
        )

        if not gateway_validation.allowed:
            return gateway_validation

        # If the payload contains a nested tool command, validate it specifically.
        if isinstance(message.payload, dict):
            inner_tool = message.payload.get("tool")
            inner_command = message.payload.get("command")
            inner_params = message.payload.get("parameters")

            if inner_tool and inner_command:
                self.logger.info(f"Performing nested security check for tool '{inner_tool}'")
                # Validate the inner tool call
                inner_validation = await self.security_manager.validate_tool_operation(
                    tool_name=inner_tool,
                    operation=inner_command,
                    arguments=inner_params if inner_params is not None else {}
                )
                return inner_validation

        # If no inner tool, fall back to checking the whole payload for dangerous patterns.
        return await self.security_manager.validate_tool_operation(
            tool_name="gateway_message",
            operation=message.type.value,
            arguments=message.payload
        )
    
    async def _handle_session_create(self, message: GatewayMessage) -> GatewayMessage:
        """Handle session creation"""
        try:
            session_id = await self.session_manager.create_session(
                client_id=message.client_id
            )
            
            response_payload = {
                "session_id": session_id,
                "status": "created"
            }
            
            return GatewayMessage(
                id=f"session_created_{message.id}",
                type=MessageType.SESSION_CREATE,
                session_id=session_id,
                client_id=message.client_id,
                payload=response_payload,
                timestamp=datetime.now()
            )
            
        except Exception as e:
            self.logger.error(f"Error creating session: {e}")
            return self._create_error_response(message, f"Session creation failed: {str(e)}")
    
    async def _handle_session_destroy(self, message: GatewayMessage) -> GatewayMessage:
        """Handle session destruction"""
        if not message.session_id:
            return self._create_error_response(message, "Session ID required")
        
        try:
            success = await self.session_manager.destroy_session(message.session_id)
            
            response_payload = {
                "session_id": message.session_id,
                "status": "destroyed" if success else "not_found"
            }
            
            return GatewayMessage(
                id=f"response_{message.id}",
                type=MessageType.SESSION_DESTROY,
                session_id=message.session_id,
                client_id=message.client_id,
                payload=response_payload,
                timestamp=datetime.now()
            )
            
        except Exception as e:
            self.logger.error(f"Error destroying session: {e}")
            return self._create_error_response(message, f"Session destruction failed: {str(e)}")
    
    async def _handle_state_update(self, message: GatewayMessage) -> GatewayMessage:
        """Handle state update requests"""
        if not message.session_id:
            return self._create_error_response(message, "Session ID required")
        
        try:
            session = self.session_manager.get_session(message.session_id)
            if not session:
                return self._create_error_response(message, "Session not found")
            
            # Extract state update from payload
            state_update = message.payload.get("state_update", {})
            
            # Apply state updates
            if "category" in state_update:
                await session.state_manager.set_category(state_update["category"])
            
            if "subnode" in state_update:
                await session.state_manager.set_subnode(state_update["subnode"])
            
            if "fields" in state_update:
                for field_update in state_update["fields"]:
                    await session.state_manager.update_field(
                        field_update["subnode"],
                        field_update["field"],
                        field_update["value"]
                    )
            
            # Get updated state
            current_state = await session.state_manager.get_state_copy()
            
            response_payload = {
                "status": "updated",
                "state": current_state.dict() if current_state else {}
            }
            
            return GatewayMessage(
                id=f"response_{message.id}",
                type=MessageType.STATE_UPDATE,
                session_id=message.session_id,
                client_id=message.client_id,
                payload=response_payload,
                timestamp=datetime.now()
            )
            
        except Exception as e:
            self.logger.error(f"Error updating state: {e}")
            return self._create_error_response(message, f"State update failed: {str(e)}")
    
    async def _handle_security_violation(self, message: GatewayMessage) -> GatewayMessage:
        """Handle security violation reports"""
        violation_details = message.payload.get("violation", {})
        
        await self.audit_logger.log_security_violation(
            violation_type="gateway_reported",
            details={
                "session_id": message.session_id,
                "client_id": message.client_id,
                "violation": violation_details
            }
        )
        
        return GatewayMessage(
            id=f"response_{message.id}",
            type=MessageType.SECURITY_VIOLATION,
            session_id=message.session_id,
            client_id=message.client_id,
            payload={"status": "logged"},
            timestamp=datetime.now()
        )
    
    async def _handle_error(self, message: GatewayMessage) -> GatewayMessage:
        """Handle error messages"""
        error_details = message.payload.get("error", {})
        
        self.logger.error(f"Gateway error: {error_details}")
        
        # Log to audit system
        await self.audit_logger.log_security_event(
            event_type="gateway_error",
            details={
                "session_id": message.session_id,
                "client_id": message.client_id,
                "error": error_details
            }
        )
        
        return GatewayMessage(
            id=f"response_{message.id}",
            type=MessageType.ERROR,
            session_id=message.session_id,
            client_id=message.client_id,
            payload={"status": "acknowledged"},
            timestamp=datetime.now()
        )
    
    async def _handle_heartbeat(self, message: GatewayMessage) -> GatewayMessage:
        """Handle heartbeat messages"""
        return GatewayMessage(
            id=f"response_{message.id}",
            type=MessageType.HEARTBEAT,
            session_id=message.session_id,
            client_id=message.client_id,
            payload={"status": "alive", "timestamp": datetime.now().isoformat()},
            timestamp=datetime.now()
        )
    
    def _create_error_response(self, original_message: GatewayMessage, error_message: str) -> GatewayMessage:
        """Create an error response message"""
        return GatewayMessage(
            id=f"error_{original_message.id}",
            type=MessageType.ERROR,
            session_id=original_message.session_id,
            client_id=original_message.client_id,
            payload={"error": error_message},
            timestamp=datetime.now()
        )
    
    def _create_security_violation_response(self, original_message: GatewayMessage, reason: str) -> GatewayMessage:
        """Create a security violation response message"""
        return GatewayMessage(
            id=f"violation_{original_message.id}",
            type=MessageType.SECURITY_VIOLATION,
            session_id=original_message.session_id,
            client_id=original_message.client_id,
            payload={"reason": reason},
            timestamp=datetime.now(),
            security_level="BLOCKED"
        )
    
    def register_connection(self, connection_id: str, metadata: Dict[str, Any] = None):
        """Register a new connection"""
        self._active_connections.add(connection_id)
        self._connection_metadata[connection_id] = metadata or {}
        self.logger.info(f"Registered connection {connection_id}")
    
    def unregister_connection(self, connection_id: str):
        """Unregister a connection"""
        self._active_connections.discard(connection_id)
        self._connection_metadata.pop(connection_id, None)
        self.logger.info(f"Unregistered connection {connection_id}")
    
    def get_connection_info(self, connection_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a connection"""
        return self._connection_metadata.get(connection_id)
    
    def get_active_connections(self) -> Set[str]:
        """Get all active connection IDs"""
        return self._active_connections.copy()
    
    async def broadcast_message(self, message: GatewayMessage, exclude_session_id: Optional[str] = None):
        """Broadcast a message to all connections except specified session"""
        # This would be implemented with WebSocket broadcasting
        # For now, just log the broadcast
        self.logger.info(f"Broadcasting message {message.id} of type {message.type.value}")
        
        # Log to audit system
        await self.audit_logger.log_security_event(
            event_type="gateway_broadcast",
            details={
                "message_id": message.id,
                "message_type": message.type.value,
                "exclude_session": exclude_session_id
            }
        )
    
    async def get_gateway_status(self) -> Dict[str, Any]:
        """Get current gateway status"""
        return {
            "active_connections": len(self._active_connections),
            "active_sessions": len(self.session_manager.sessions),
            "registered_handlers": len(self._message_handlers),
            "uptime": "running",
            "security_status": "active"
        }