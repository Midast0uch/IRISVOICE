"""
Tests for IRIS Gateway components
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, AsyncMock

from ..gateway import IRISGateway, MessageRouter, SecurityFilter
from ..gateway.iris_gateway import GatewayMessage, MessageType


class TestIRISGateway:
    """Test IRIS Gateway functionality"""
    
    @pytest.fixture
    def gateway(self):
        """Create a test gateway instance"""
        gateway = IRISGateway()
        return gateway
    
    @pytest.fixture
    def sample_message(self):
        """Create a sample test message"""
        return GatewayMessage(
            id="test_message_1",
            type=MessageType.HEARTBEAT,
            session_id=None,
            client_id="test_client",
            payload={"status": "test"},
            timestamp=datetime.now()
        )
    
    @pytest.mark.asyncio
    async def test_gateway_initialization(self, gateway):
        """Test gateway initialization"""
        assert gateway.session_manager is not None
        assert gateway.security_manager is not None
        assert gateway.audit_logger is not None
        assert len(gateway._message_handlers) > 0
    
    @pytest.mark.asyncio
    async def test_message_validation(self, gateway, sample_message):
        """Test message validation"""
        # Valid message
        assert gateway._validate_message(sample_message)
        
        # Invalid message - missing ID
        invalid_message = GatewayMessage(
            id="",
            type=MessageType.HEARTBEAT,
            session_id=None,
            client_id="test_client",
            payload={},
            timestamp=datetime.now()
        )
        assert not gateway._validate_message(invalid_message)
    
    @pytest.mark.asyncio
    async def test_heartbeat_handler(self, gateway, sample_message):
        """Test heartbeat message handling"""
        response = await gateway.process_message(sample_message)
        
        assert response is not None
        assert response.type == MessageType.HEARTBEAT
        assert response.payload["status"] == "alive"
    
    @pytest.mark.asyncio
    async def test_session_create_handler(self, gateway):
        """Test session creation handling"""
        create_message = GatewayMessage(
            id="create_session_1",
            type=MessageType.SESSION_CREATE,
            session_id=None,
            client_id="test_client",
            payload={},
            timestamp=datetime.now()
        )
        
        response = await gateway.process_message(create_message)
        
        assert response is not None
        assert response.type == MessageType.SESSION_CREATE
        assert "session_id" in response.payload
        assert response.payload["status"] == "created"
    
    @pytest.mark.asyncio
    async def test_session_destroy_handler(self, gateway):
        """Test session destruction handling"""
        # First create a session
        create_message = GatewayMessage(
            id="create_session_2",
            type=MessageType.SESSION_CREATE,
            session_id=None,
            client_id="test_client",
            payload={},
            timestamp=datetime.now()
        )
        
        create_response = await gateway.process_message(create_message)
        session_id = create_response.payload["session_id"]
        
        # Now destroy it
        destroy_message = GatewayMessage(
            id="destroy_session_1",
            type=MessageType.SESSION_DESTROY,
            session_id=session_id,
            client_id="test_client",
            payload={},
            timestamp=datetime.now()
        )
        
        destroy_response = await gateway.process_message(destroy_message)
        
        assert destroy_response is not None
        assert destroy_response.type == MessageType.SESSION_DESTROY
        assert destroy_response.payload["session_id"] == session_id
        assert destroy_response.payload["status"] == "destroyed"
    
    @pytest.mark.asyncio
    async def test_state_update_handler(self, gateway):
        """Test state update handling"""
        # Create a session first
        create_message = GatewayMessage(
            id="create_session_3",
            type=MessageType.SESSION_CREATE,
            session_id=None,
            client_id="test_client",
            payload={},
            timestamp=datetime.now()
        )
        
        create_response = await gateway.process_message(create_message)
        session_id = create_response.payload["session_id"]
        
        # Update state
        state_update_message = GatewayMessage(
            id="state_update_1",
            type=MessageType.STATE_UPDATE,
            session_id=session_id,
            client_id="test_client",
            payload={
                "state_update": {
                    "category": "voice",
                    "fields": [
                        {"subnode": "main", "field": "test_field", "value": "test_value"}
                    ]
                }
            },
            timestamp=datetime.now()
        )
        
        response = await gateway.process_message(state_update_message)
        
        assert response is not None
        assert response.type == MessageType.STATE_UPDATE
        assert response.payload["status"] == "updated"
        assert "state" in response.payload
    
    @pytest.mark.asyncio
    async def test_connection_management(self, gateway):
        """Test connection registration and management"""
        # Register connection
        gateway.register_connection("conn_1", {"client_type": "test"})
        
        assert "conn_1" in gateway.get_active_connections()
        assert gateway.get_connection_info("conn_1")["client_type"] == "test"
        
        # Unregister connection
        gateway.unregister_connection("conn_1")
        
        assert "conn_1" not in gateway.get_active_connections()
        assert gateway.get_connection_info("conn_1") is None
    
    @pytest.mark.asyncio
    async def test_gateway_status(self, gateway):
        """Test gateway status reporting"""
        status = await gateway.get_gateway_status()
        
        assert "active_connections" in status
        assert "active_sessions" in status
        assert "registered_handlers" in status
        assert "uptime" in status
        assert "security_status" in status


class TestMessageRouter:
    """Test Message Router functionality"""
    
    @pytest.fixture
    def gateway(self):
        """Create a test gateway instance"""
        return IRISGateway()
    
    @pytest.fixture
    def router(self, gateway):
        """Create a test router instance"""
        return MessageRouter(gateway)
    
    @pytest.fixture
    def sample_message(self):
        """Create a sample test message"""
        return GatewayMessage(
            id="test_message_1",
            type=MessageType.HEARTBEAT,
            session_id=None,
            client_id="test_client",
            payload={"status": "test"},
            timestamp=datetime.now()
        )
    
    @pytest.mark.asyncio
    async def test_router_initialization(self, router):
        """Test router initialization"""
        assert router.gateway is not None
        assert len(router._routing_rules) > 0
        assert len(router._default_handlers) == 0
    
    @pytest.mark.asyncio
    async def test_heartbeat_routing(self, router, sample_message):
        """Test heartbeat message routing"""
        response = await router.route_message(sample_message)
        
        assert response is not None
        assert response.type == MessageType.HEARTBEAT
        assert response.payload["status"] == "alive"
    
    @pytest.mark.asyncio
    async def test_session_create_routing(self, router):
        """Test session creation routing"""
        create_message = GatewayMessage(
            id="create_session_1",
            type=MessageType.SESSION_CREATE,
            session_id=None,
            client_id="test_client",
            payload={},
            timestamp=datetime.now()
        )
        
        response = await router.route_message(create_message)
        
        assert response is not None
        assert response.type == MessageType.SESSION_CREATE
        assert "session_id" in response.payload
    
    @pytest.mark.asyncio
    async def test_routing_error_handling(self, router):
        """Test routing error handling"""
        # Create a message that will cause routing error
        error_message = GatewayMessage(
            id="error_message_1",
            type=MessageType.ERROR,
            session_id=None,
            client_id="test_client",
            payload={"error": "test error"},
            timestamp=datetime.now()
        )
        
        response = await router.route_message(error_message)
        
        assert response is not None
        assert response.type == MessageType.ERROR
    
    @pytest.mark.asyncio
    async def test_batch_routing(self, router):
        """Test batch message routing"""
        messages = [
            GatewayMessage(
                id=f"batch_{i}",
                type=MessageType.HEARTBEAT,
                session_id=None,
                client_id="test_client",
                payload={"batch_index": i},
                timestamp=datetime.now()
            )
            for i in range(3)
        ]
        
        responses = await router.route_batch(messages)
        
        assert len(responses) == 3
        for i, response in enumerate(responses):
            assert response is not None
            assert response.type == MessageType.HEARTBEAT
    
    @pytest.mark.asyncio
    async def test_routing_stats(self, router):
        """Test routing statistics"""
        stats = router.get_routing_stats()
        
        assert "total_rules" in stats
        assert "default_handlers" in stats
        assert "rule_priorities" in stats
        assert "message_types_covered" in stats
        assert stats["total_rules"] > 0


class TestSecurityFilter:
    """Test Security Filter functionality"""
    
    @pytest.fixture
    def security_filter(self):
        """Create a test security filter instance"""
        return SecurityFilter()
    
    @pytest.fixture
    def sample_message(self):
        """Create a sample test message"""
        return GatewayMessage(
            id="test_message_1",
            type=MessageType.HEARTBEAT,
            session_id=None,
            client_id="test_client",
            payload={"status": "test"},
            timestamp=datetime.now()
        )
    
    @pytest.mark.asyncio
    async def test_filter_initialization(self, security_filter):
        """Test security filter initialization"""
        assert security_filter.security_manager is not None
        assert security_filter.audit_logger is not None
        assert len(security_filter._filter_rules) > 0
        assert len(security_filter._blocked_patterns) > 0
    
    @pytest.mark.asyncio
    async def test_safe_message_filtering(self, security_filter, sample_message):
        """Test filtering of safe messages"""
        result = await security_filter.apply_filters(sample_message)
        
        assert result.allowed
        assert "No matching filter rules" in result.reason
    
    @pytest.mark.asyncio
    async def test_dangerous_command_filtering(self, security_filter):
        """Test filtering of dangerous commands"""
        dangerous_message = GatewayMessage(
            id="dangerous_command_1",
            type=MessageType.SYSTEM_COMMAND,
            session_id=None,
            client_id="test_client",
            payload={"command": {"action": "rm -rf /"}},
            timestamp=datetime.now()
        )
        
        result = await security_filter.apply_filters(dangerous_message)
        
        assert not result.allowed
        assert "block_dangerous_commands" in result.rule_name
    
    @pytest.mark.asyncio
    async def test_automation_without_session_filtering(self, security_filter):
        """Test filtering of automation requests without session"""
        automation_message = GatewayMessage(
            id="automation_no_session_1",
            type=MessageType.AUTOMATION_REQUEST,
            session_id=None,  # No session ID
            client_id="test_client",
            payload={"automation_request": {"action": "click"}},
            timestamp=datetime.now()
        )
        
        result = await security_filter.apply_filters(automation_message)
        
        assert not result.allowed
        assert "block_automation_without_session" in result.rule_name
    
    @pytest.mark.asyncio
    async def test_suspicious_vision_filtering(self, security_filter):
        """Test filtering of suspicious vision requests"""
        suspicious_message = GatewayMessage(
            id="suspicious_vision_1",
            type=MessageType.VISION_REQUEST,
            session_id="test_session",
            client_id="test_client",
            payload={"vision_request": {"target": "password field"}},
            timestamp=datetime.now()
        )
        
        result = await security_filter.apply_filters(suspicious_message)
        
        assert not result.allowed
        assert "block_suspicious_vision" in result.rule_name
    
    @pytest.mark.asyncio
    async def test_rate_limiting(self, security_filter):
        """Test rate limiting functionality"""
        # Create multiple session creation messages
        messages = [
            GatewayMessage(
                id=f"session_create_{i}",
                type=MessageType.SESSION_CREATE,
                session_id=None,
                client_id="test_client",
                payload={},
                timestamp=datetime.now()
            )
            for i in range(10)  # Exceed the rate limit
        ]
        
        # Apply filters to all messages
        results = []
        for message in messages:
            result = await security_filter.apply_filters(message)
            results.append(result)
        
        # Some should be rate limited
        rate_limited_results = [r for r in results if not r.allowed and "rate_limit" in r.rule_name]
        assert len(rate_limited_results) > 0
    
    @pytest.mark.asyncio
    async def test_filter_stats(self, security_filter):
        """Test filter statistics"""
        stats = security_filter.get_filter_stats()
        
        assert "total_rules" in stats
        assert "rate_limit_keys" in stats
        assert "blocked_patterns" in stats
        assert "rule_priorities" in stats
        assert "message_types_covered" in stats
        assert stats["total_rules"] > 0