"""
Message Router - Handles routing of messages between different components
"""

import asyncio
import logging
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass
from datetime import datetime

from .iris_gateway import IRISGateway, GatewayMessage, MessageType


@dataclass
class RouteRule:
    """Defines a routing rule for messages"""
    message_type: MessageType
    condition: Callable[[GatewayMessage], bool]
    target_handler: Callable[[GatewayMessage], GatewayMessage]
    priority: int = 0
    description: str = ""


class MessageRouter:
    """Routes messages to appropriate handlers based on rules"""
    
    def __init__(self, gateway: IRISGateway):
        """Initialize the message router"""
        self.gateway = gateway
        self.logger = logging.getLogger(__name__)
        self._routing_rules: List[RouteRule] = []
        self._default_handlers: Dict[MessageType, Callable] = {}
        
        # Initialize default routing rules
        self._initialize_default_rules()
    
    def _initialize_default_rules(self):
        """Initialize default routing rules"""
        # Security rules (highest priority)
        self.add_rule(RouteRule(
            message_type=MessageType.SECURITY_VIOLATION,
            condition=lambda msg: True,
            target_handler=self._handle_security_violation,
            priority=100,
            description="Handle all security violations"
        ))
        
        # Session management rules
        self.add_rule(RouteRule(
            message_type=MessageType.SESSION_CREATE,
            condition=lambda msg: True,
            target_handler=self._handle_session_create,
            priority=90,
            description="Handle session creation"
        ))
        
        self.add_rule(RouteRule(
            message_type=MessageType.SESSION_DESTROY,
            condition=lambda msg: True,
            target_handler=self._handle_session_destroy,
            priority=90,
            description="Handle session destruction"
        ))
        
        # State update rules
        self.add_rule(RouteRule(
            message_type=MessageType.STATE_UPDATE,
            condition=lambda msg: msg.session_id is not None,
            target_handler=self._handle_state_update,
            priority=80,
            description="Handle state updates with session"
        ))
        
        # Vision system rules
        self.add_rule(RouteRule(
            message_type=MessageType.VISION_REQUEST,
            condition=lambda msg: msg.session_id is not None,
            target_handler=self._handle_vision_request,
            priority=70,
            description="Handle vision requests"
        ))
        
        # Audio system rules
        self.add_rule(RouteRule(
            message_type=MessageType.AUDIO_REQUEST,
            condition=lambda msg: msg.session_id is not None,
            target_handler=self._handle_audio_request,
            priority=70,
            description="Handle audio requests"
        ))
        
        # Automation rules
        self.add_rule(RouteRule(
            message_type=MessageType.AUTOMATION_REQUEST,
            condition=lambda msg: msg.session_id is not None,
            target_handler=self._handle_automation_request,
            priority=60,
            description="Handle automation requests"
        ))
        
        # System command rules
        self.add_rule(RouteRule(
            message_type=MessageType.SYSTEM_COMMAND,
            condition=lambda msg: msg.session_id is not None,
            target_handler=self._handle_system_command,
            priority=50,
            description="Handle system commands"
        ))
        
        # Error handling rules
        self.add_rule(RouteRule(
            message_type=MessageType.ERROR,
            condition=lambda msg: True,
            target_handler=self._handle_error,
            priority=40,
            description="Handle error messages"
        ))
        
        # Heartbeat rules (lowest priority)
        self.add_rule(RouteRule(
            message_type=MessageType.HEARTBEAT,
            condition=lambda msg: True,
            target_handler=self._handle_heartbeat,
            priority=10,
            description="Handle heartbeat messages"
        ))
    
    def add_rule(self, rule: RouteRule):
        """Add a routing rule"""
        self._routing_rules.append(rule)
        # Sort by priority (highest first)
        self._routing_rules.sort(key=lambda r: r.priority, reverse=True)
        self.logger.info(f"Added routing rule: {rule.description}")
    
    def remove_rule(self, rule: RouteRule):
        """Remove a routing rule"""
        if rule in self._routing_rules:
            self._routing_rules.remove(rule)
            self.logger.info(f"Removed routing rule: {rule.description}")
    
    def set_default_handler(self, message_type: MessageType, handler: Callable):
        """Set a default handler for a message type"""
        self._default_handlers[message_type] = handler
        self.logger.info(f"Set default handler for {message_type.value}")
    
    async def route_message(self, message: GatewayMessage) -> Optional[GatewayMessage]:
        """Route a message to the appropriate handler"""
        try:
            self.logger.info(f"Routing message {message.id} of type {message.type.value}")
            
            # Find matching rules
            matching_rules = [
                rule for rule in self._routing_rules
                if rule.message_type == message.type and rule.condition(message)
            ]
            
            if matching_rules:
                # Use the highest priority matching rule
                rule = matching_rules[0]
                self.logger.info(f"Using rule: {rule.description}")
                return await rule.target_handler(message)
            
            # Use default handler if available
            if message.type in self._default_handlers:
                return await self._default_handlers[message.type](message)
            
            # Fallback to gateway's default handler
            return await self.gateway.process_message(message)
            
        except Exception as e:
            self.logger.error(f"Error routing message {message.id}: {e}")
            return await self._handle_routing_error(message, str(e))
    
    async def route_batch(self, messages: List[GatewayMessage]) -> List[Optional[GatewayMessage]]:
        """Route a batch of messages"""
        results = []
        for message in messages:
            result = await self.route_message(message)
            results.append(result)
        return results
    
    # Handler methods
    
    async def _handle_session_create(self, message: GatewayMessage) -> GatewayMessage:
        """Handle session creation with enhanced routing"""
        self.logger.info(f"Routing session creation for client {message.client_id}")
        return await self.gateway.process_message(message)
    
    async def _handle_session_destroy(self, message: GatewayMessage) -> GatewayMessage:
        """Handle session destruction with cleanup"""
        self.logger.info(f"Routing session destruction for session {message.session_id}")
        return await self.gateway.process_message(message)
    
    async def _handle_state_update(self, message: GatewayMessage) -> GatewayMessage:
        """Handle state updates with validation"""
        self.logger.info(f"Routing state update for session {message.session_id}")
        
        # Validate state update payload
        state_update = message.payload.get("state_update", {})
        if not state_update:
            return GatewayMessage(
                id=f"error_{message.id}",
                type=MessageType.ERROR,
                session_id=message.session_id,
                client_id=message.client_id,
                payload={"error": "No state update provided"},
                timestamp=datetime.now()
            )
        
        return await self.gateway.process_message(message)
    
    async def _handle_vision_request(self, message: GatewayMessage) -> GatewayMessage:
        """Handle vision requests with security validation"""
        self.logger.info(f"Routing vision request for session {message.session_id}")
        
        # Additional security validation for vision requests
        vision_payload = message.payload.get("vision_request", {})
        if not vision_payload:
            return GatewayMessage(
                id=f"error_{message.id}",
                type=MessageType.ERROR,
                session_id=message.session_id,
                client_id=message.client_id,
                payload={"error": "No vision request provided"},
                timestamp=datetime.now()
            )
        
        # Validate vision action
        action = vision_payload.get("action")
        if action in ["click", "type", "scroll"]:
            # These require additional security checks
            message.security_level = "RESTRICTED"
            self.logger.warning(f"Vision action {action} requires elevated security")
        
        return await self.gateway.process_message(message)
    
    async def _handle_audio_request(self, message: GatewayMessage) -> GatewayMessage:
        """Handle audio requests"""
        self.logger.info(f"Routing audio request for session {message.session_id}")
        return await self.gateway.process_message(message)
    
    async def _handle_automation_request(self, message: GatewayMessage) -> GatewayMessage:
        """Handle automation requests with security validation"""
        self.logger.info(f"Routing automation request for session {message.session_id}")
        
        # Additional security validation for automation
        automation_payload = message.payload.get("automation_request", {})
        if not automation_payload:
            return GatewayMessage(
                id=f"error_{message.id}",
                type=MessageType.ERROR,
                session_id=message.session_id,
                client_id=message.client_id,
                payload={"error": "No automation request provided"},
                timestamp=datetime.now()
            )
        
        # Mark as restricted for security processing
        message.security_level = "RESTRICTED"
        
        return await self.gateway.process_message(message)
    
    async def _handle_system_command(self, message: GatewayMessage) -> GatewayMessage:
        """Handle system commands with validation"""
        self.logger.info(f"Routing system command for session {message.session_id}")
        
        # Additional validation for system commands
        command_payload = message.payload.get("command", {})
        if not command_payload:
            return GatewayMessage(
                id=f"error_{message.id}",
                type=MessageType.ERROR,
                session_id=message.session_id,
                client_id=message.client_id,
                payload={"error": "No command provided"},
                timestamp=datetime.now()
            )
        
        # Mark as dangerous for security processing
        message.security_level = "DANGEROUS"
        
        return await self.gateway.process_message(message)
    
    async def _handle_security_violation(self, message: GatewayMessage) -> GatewayMessage:
        """Handle security violations with logging"""
        self.logger.warning(f"Routing security violation for session {message.session_id}")
        
        # Log detailed violation information
        violation_details = message.payload.get("violation", {})
        self.logger.error(f"Security violation: {violation_details}")
        
        return await self.gateway.process_message(message)
    
    async def _handle_error(self, message: GatewayMessage) -> GatewayMessage:
        """Handle error messages with logging"""
        error_details = message.payload.get("error", {})
        self.logger.error(f"Routing error message: {error_details}")
        
        return await self.gateway.process_message(message)
    
    async def _handle_heartbeat(self, message: GatewayMessage) -> GatewayMessage:
        """Handle heartbeat messages"""
        self.logger.debug(f"Routing heartbeat for session {message.session_id}")
        return await self.gateway.process_message(message)
    
    async def _handle_routing_error(self, message: GatewayMessage, error: str) -> GatewayMessage:
        """Handle routing errors"""
        self.logger.error(f"Routing error for message {message.id}: {error}")
        
        return GatewayMessage(
            id=f"routing_error_{message.id}",
            type=MessageType.ERROR,
            session_id=message.session_id,
            client_id=message.client_id,
            payload={
                "error": "Routing failed",
                "details": error,
                "original_message_id": message.id
            },
            timestamp=datetime.now()
        )
    
    def get_routing_stats(self) -> Dict[str, Any]:
        """Get routing statistics"""
        return {
            "total_rules": len(self._routing_rules),
            "default_handlers": len(self._default_handlers),
            "rule_priorities": [rule.priority for rule in self._routing_rules],
            "message_types_covered": list(set(rule.message_type.value for rule in self._routing_rules))
        }