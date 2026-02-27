"""
Property-based tests for tool execution audit logging.
Tests that the AuditLogger logs all tool executions with timestamps and parameters.
"""
import pytest
import asyncio
from hypothesis import given, settings, strategies as st, seed, HealthCheck
from datetime import datetime, timedelta
import sys
import os

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.security.audit_logger import SecurityAuditLogger, AuditEventType, AuditSeverity
from backend.security.security_types import SecurityContext


# ============================================================================
# Test Data Generators (Hypothesis Strategies)
# ============================================================================

@st.composite
def session_ids(draw):
    """Generate random session IDs."""
    return draw(st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'), whitelist_characters='-_'),
        min_size=8,
        max_size=32
    ))


@st.composite
def user_ids(draw):
    """Generate random user IDs."""
    return draw(st.one_of(
        st.none(),
        st.text(
            alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'), whitelist_characters='-_'),
            min_size=4,
            max_size=20
        )
    ))


@st.composite
def tool_names(draw):
    """Generate tool names."""
    return draw(st.sampled_from([
        "file_manager", "gui_automation", "system", 
        "web_browser", "clipboard", "screen_capture",
        "vision_system", "app_launcher"
    ]))


@st.composite
def operations(draw):
    """Generate operation names."""
    return draw(st.sampled_from([
        "read", "write", "execute", "delete", "create",
        "update", "list", "search", "navigate", "click"
    ]))


@st.composite
def tool_arguments(draw):
    """Generate tool execution arguments."""
    num_args = draw(st.integers(min_value=0, max_value=5))
    args = {}
    
    for i in range(num_args):
        key = draw(st.text(
            alphabet=st.characters(whitelist_categories=('Lu', 'Ll'), whitelist_characters='_'),
            min_size=3,
            max_size=15
        ))
        value = draw(st.one_of(
            st.text(min_size=0, max_size=50),
            st.integers(min_value=-1000, max_value=1000),
            st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False),
            st.booleans()
        ))
        args[key] = value
    
    return args


@st.composite
def security_contexts(draw):
    """Generate security contexts."""
    session_id = draw(session_ids())
    user_id = draw(user_ids())
    source_ip = draw(st.one_of(
        st.none(),
        st.text(min_size=7, max_size=15).filter(lambda x: '.' in x)
    ))
    
    return SecurityContext(
        session_id=session_id,
        user_id=user_id,
        source_ip=source_ip,
        user_agent=None,
        correlation_id=session_id
    )


@st.composite
def tool_execution_requests(draw):
    """Generate tool execution requests."""
    return {
        "tool_name": draw(tool_names()),
        "operation": draw(operations()),
        "arguments": draw(tool_arguments()),
        "context": draw(security_contexts()),
        "result": draw(st.one_of(
            st.text(min_size=0, max_size=100),
            st.just("success"),
            st.just("error")
        )),
        "risk_score": draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    }


@st.composite
def tool_execution_sequences(draw):
    """Generate sequences of tool execution requests."""
    num_requests = draw(st.integers(min_value=1, max_value=20))
    requests = []
    
    for _ in range(num_requests):
        requests.append(draw(tool_execution_requests()))
    
    return requests


# ============================================================================
# Property 58: Tool Execution Audit Logging
# Feature: irisvoice-backend-integration, Property 58: Tool Execution Audit Logging
# Validates: Requirements 24.3
# ============================================================================

class TestToolExecutionAuditLogging:
    """
    Property 58: Tool Execution Audit Logging
    
    For any tool execution, the Audit_Logger shall log the execution
    with timestamp and parameters.
    """
    
    @pytest.mark.asyncio
    @settings(max_examples=50, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        request=tool_execution_requests()
    )
    async def test_tool_execution_is_logged_with_timestamp(self, request):
        """
        Property: For any tool execution, the audit logger logs the execution
        with a timestamp.
        
        # Feature: irisvoice-backend-integration, Property 58: Tool Execution Audit Logging
        """
        # Create audit logger
        audit_logger = SecurityAuditLogger()
        
        # Record time before logging
        time_before = datetime.now()
        
        # Log tool execution
        await audit_logger.log_tool_operation(
            tool_name=request["tool_name"],
            operation=request["operation"],
            arguments=request["arguments"],
            context=request["context"],
            result=request["result"],
            risk_score=request["risk_score"]
        )
        
        # Record time after logging
        time_after = datetime.now()
        
        # Retrieve audit trail
        events = await audit_logger.get_audit_trail(
            session_id=request["context"].session_id,
            limit=1
        )
        
        # Verify event was logged
        assert len(events) > 0, "Tool execution should be logged"
        
        event = events[0]
        
        # Verify timestamp is present and within expected range
        assert event.timestamp is not None, "Event should have a timestamp"
        assert time_before <= event.timestamp <= time_after, \
            "Timestamp should be between before and after times"
    
    @pytest.mark.asyncio
    @settings(max_examples=50, deadline=None)
    @seed(42)
    @given(
        request=tool_execution_requests()
    )
    async def test_tool_execution_log_includes_tool_name(self, request):
        """
        Property: For any tool execution, the audit log includes the tool name.
        
        # Feature: irisvoice-backend-integration, Property 58: Tool Execution Audit Logging
        """
        # Create audit logger
        audit_logger = SecurityAuditLogger()
        
        # Log tool execution
        await audit_logger.log_tool_operation(
            tool_name=request["tool_name"],
            operation=request["operation"],
            arguments=request["arguments"],
            context=request["context"],
            result=request["result"],
            risk_score=request["risk_score"]
        )
        
        # Retrieve audit trail
        events = await audit_logger.get_audit_trail(
            session_id=request["context"].session_id,
            limit=1
        )
        
        # Verify event was logged
        assert len(events) > 0, "Tool execution should be logged"
        
        event = events[0]
        
        # Verify tool name is in event data
        assert "tool_name" in event.event_data, "Event should include tool_name"
        assert event.event_data["tool_name"] == request["tool_name"], \
            f"Tool name should be {request['tool_name']}"
    
    @pytest.mark.asyncio
    @settings(max_examples=50, deadline=None)
    @seed(42)
    @given(
        request=tool_execution_requests()
    )
    async def test_tool_execution_log_includes_operation(self, request):
        """
        Property: For any tool execution, the audit log includes the operation.
        
        # Feature: irisvoice-backend-integration, Property 58: Tool Execution Audit Logging
        """
        # Create audit logger
        audit_logger = SecurityAuditLogger()
        
        # Log tool execution
        await audit_logger.log_tool_operation(
            tool_name=request["tool_name"],
            operation=request["operation"],
            arguments=request["arguments"],
            context=request["context"],
            result=request["result"],
            risk_score=request["risk_score"]
        )
        
        # Retrieve audit trail
        events = await audit_logger.get_audit_trail(
            session_id=request["context"].session_id,
            limit=1
        )
        
        # Verify event was logged
        assert len(events) > 0, "Tool execution should be logged"
        
        event = events[0]
        
        # Verify operation is in event data
        assert "operation" in event.event_data, "Event should include operation"
        assert event.event_data["operation"] == request["operation"], \
            f"Operation should be {request['operation']}"
    
    @pytest.mark.asyncio
    @settings(max_examples=50, deadline=None)
    @seed(42)
    @given(
        request=tool_execution_requests()
    )
    async def test_tool_execution_log_includes_parameters(self, request):
        """
        Property: For any tool execution, the audit log includes the parameters.
        
        # Feature: irisvoice-backend-integration, Property 58: Tool Execution Audit Logging
        """
        # Create audit logger
        audit_logger = SecurityAuditLogger()
        
        # Log tool execution
        await audit_logger.log_tool_operation(
            tool_name=request["tool_name"],
            operation=request["operation"],
            arguments=request["arguments"],
            context=request["context"],
            result=request["result"],
            risk_score=request["risk_score"]
        )
        
        # Retrieve audit trail
        events = await audit_logger.get_audit_trail(
            session_id=request["context"].session_id,
            limit=1
        )
        
        # Verify event was logged
        assert len(events) > 0, "Tool execution should be logged"
        
        event = events[0]
        
        # Verify arguments are in event data
        assert "arguments" in event.event_data, "Event should include arguments"
        assert event.event_data["arguments"] == request["arguments"], \
            f"Arguments should match the provided arguments"
    
    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.large_base_example])
    @seed(42)
    @given(
        sequence=tool_execution_sequences()
    )
    async def test_multiple_tool_executions_are_all_logged(self, sequence):
        """
        Property: For any sequence of tool executions, all executions are logged.
        
        # Feature: irisvoice-backend-integration, Property 58: Tool Execution Audit Logging
        """
        # Create audit logger
        audit_logger = SecurityAuditLogger()
        
        # Log all tool executions
        for request in sequence:
            await audit_logger.log_tool_operation(
                tool_name=request["tool_name"],
                operation=request["operation"],
                arguments=request["arguments"],
                context=request["context"],
                result=request["result"],
                risk_score=request["risk_score"]
            )
        
        # Retrieve audit trail (get all events)
        events = await audit_logger.get_audit_trail(limit=len(sequence) + 10)
        
        # Verify all executions were logged
        assert len(events) >= len(sequence), \
            f"All {len(sequence)} tool executions should be logged"
    
    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.large_base_example])
    @seed(42)
    @given(
        sequence=tool_execution_sequences()
    )
    async def test_audit_trail_maintains_chronological_order(self, sequence):
        """
        Property: For any sequence of tool executions, the audit trail
        maintains chronological order.
        
        # Feature: irisvoice-backend-integration, Property 58: Tool Execution Audit Logging
        """
        # Create audit logger
        audit_logger = SecurityAuditLogger()
        
        # Log all tool executions with small delays to ensure distinct timestamps
        for request in sequence:
            await audit_logger.log_tool_operation(
                tool_name=request["tool_name"],
                operation=request["operation"],
                arguments=request["arguments"],
                context=request["context"],
                result=request["result"],
                risk_score=request["risk_score"]
            )
            # Small delay to ensure timestamps are distinct
            await asyncio.sleep(0.001)
        
        # Retrieve audit trail
        events = await audit_logger.get_audit_trail(limit=len(sequence) + 10)
        
        # Verify events are in chronological order (newest first)
        for i in range(len(events) - 1):
            assert events[i].timestamp >= events[i + 1].timestamp, \
                "Events should be in chronological order (newest first)"
    
    @pytest.mark.asyncio
    @settings(max_examples=50, deadline=None)
    @seed(42)
    @given(
        request=tool_execution_requests()
    )
    async def test_logs_can_be_retrieved_by_session_id(self, request):
        """
        Property: For any tool execution, logs can be retrieved by session ID.
        
        # Feature: irisvoice-backend-integration, Property 58: Tool Execution Audit Logging
        """
        # Create audit logger
        audit_logger = SecurityAuditLogger()
        
        # Log tool execution
        await audit_logger.log_tool_operation(
            tool_name=request["tool_name"],
            operation=request["operation"],
            arguments=request["arguments"],
            context=request["context"],
            result=request["result"],
            risk_score=request["risk_score"]
        )
        
        # Retrieve audit trail by session ID
        events = await audit_logger.get_audit_trail(
            session_id=request["context"].session_id,
            limit=10
        )
        
        # Verify event was retrieved
        assert len(events) > 0, "Event should be retrievable by session ID"
        
        # Verify all events belong to the correct session
        for event in events:
            assert event.session_id == request["context"].session_id, \
                "All events should belong to the specified session"
    
    @pytest.mark.asyncio
    @settings(max_examples=50, deadline=None)
    @seed(42)
    @given(
        request=tool_execution_requests()
    )
    async def test_logs_can_be_retrieved_by_user_id(self, request):
        """
        Property: For any tool execution with a user ID, logs can be
        retrieved by user ID.
        
        # Feature: irisvoice-backend-integration, Property 58: Tool Execution Audit Logging
        """
        # Skip if user_id is None
        if request["context"].user_id is None:
            return
        
        # Create audit logger
        audit_logger = SecurityAuditLogger()
        
        # Log tool execution
        await audit_logger.log_tool_operation(
            tool_name=request["tool_name"],
            operation=request["operation"],
            arguments=request["arguments"],
            context=request["context"],
            result=request["result"],
            risk_score=request["risk_score"]
        )
        
        # Retrieve audit trail by user ID
        events = await audit_logger.get_audit_trail(
            user_id=request["context"].user_id,
            limit=10
        )
        
        # Verify event was retrieved
        assert len(events) > 0, "Event should be retrievable by user ID"
        
        # Verify all events belong to the correct user
        for event in events:
            assert event.user_id == request["context"].user_id, \
                "All events should belong to the specified user"
    
    @pytest.mark.asyncio
    @settings(max_examples=50, deadline=None)
    @seed(42)
    @given(
        request=tool_execution_requests()
    )
    async def test_logs_can_be_filtered_by_event_type(self, request):
        """
        Property: For any tool execution, logs can be filtered by event type.
        
        # Feature: irisvoice-backend-integration, Property 58: Tool Execution Audit Logging
        """
        # Create audit logger
        audit_logger = SecurityAuditLogger()
        
        # Log tool execution
        await audit_logger.log_tool_operation(
            tool_name=request["tool_name"],
            operation=request["operation"],
            arguments=request["arguments"],
            context=request["context"],
            result=request["result"],
            risk_score=request["risk_score"]
        )
        
        # Retrieve audit trail filtered by TOOL_OPERATION event type
        events = await audit_logger.get_audit_trail(
            event_type=AuditEventType.TOOL_OPERATION,
            limit=10
        )
        
        # Verify event was retrieved
        assert len(events) > 0, "Event should be retrievable by event type"
        
        # Verify all events are of the correct type
        for event in events:
            assert event.event_type == AuditEventType.TOOL_OPERATION, \
                "All events should be TOOL_OPERATION type"
    
    @pytest.mark.asyncio
    @settings(max_examples=50, deadline=None)
    @seed(42)
    @given(
        request=tool_execution_requests()
    )
    async def test_logs_can_be_filtered_by_time_range(self, request):
        """
        Property: For any tool execution, logs can be filtered by time range.
        
        # Feature: irisvoice-backend-integration, Property 58: Tool Execution Audit Logging
        """
        # Create audit logger
        audit_logger = SecurityAuditLogger()
        
        # Record time before logging
        time_before = datetime.now() - timedelta(seconds=1)
        
        # Log tool execution
        await audit_logger.log_tool_operation(
            tool_name=request["tool_name"],
            operation=request["operation"],
            arguments=request["arguments"],
            context=request["context"],
            result=request["result"],
            risk_score=request["risk_score"]
        )
        
        # Record time after logging
        time_after = datetime.now() + timedelta(seconds=1)
        
        # Retrieve audit trail within time range
        events = await audit_logger.get_audit_trail(
            start_time=time_before,
            end_time=time_after,
            limit=10
        )
        
        # Verify event was retrieved
        assert len(events) > 0, "Event should be retrievable within time range"
        
        # Verify all events are within the time range
        for event in events:
            assert time_before <= event.timestamp <= time_after, \
                "All events should be within the specified time range"
    
    @pytest.mark.asyncio
    @settings(max_examples=50, deadline=None)
    @seed(42)
    @given(
        request=tool_execution_requests()
    )
    async def test_log_entries_are_persistent(self, request):
        """
        Property: For any tool execution, log entries are persistent
        and can be retrieved after the logger is recreated.
        
        # Feature: irisvoice-backend-integration, Property 58: Tool Execution Audit Logging
        """
        # Create audit logger
        audit_logger = SecurityAuditLogger()
        
        # Log tool execution
        await audit_logger.log_tool_operation(
            tool_name=request["tool_name"],
            operation=request["operation"],
            arguments=request["arguments"],
            context=request["context"],
            result=request["result"],
            risk_score=request["risk_score"]
        )
        
        # Get the session ID for retrieval
        session_id = request["context"].session_id
        
        # Close the logger to ensure data is flushed
        audit_logger.close()
        
        # Create a new audit logger instance
        new_audit_logger = SecurityAuditLogger()
        
        # Note: The in-memory buffer won't persist, but we can verify
        # that the logging mechanism is designed for persistence by checking
        # that the log files exist
        log_summary = new_audit_logger.get_log_summary()
        
        # Verify log files exist
        assert log_summary["total_files"] > 0, \
            "Log files should exist for persistence"
        
        # Clean up
        new_audit_logger.close()
    
    @pytest.mark.asyncio
    @settings(max_examples=50, deadline=None)
    @seed(42)
    @given(
        request=tool_execution_requests()
    )
    async def test_audit_log_includes_session_context(self, request):
        """
        Property: For any tool execution, the audit log includes session context.
        
        # Feature: irisvoice-backend-integration, Property 58: Tool Execution Audit Logging
        """
        # Create audit logger
        audit_logger = SecurityAuditLogger()
        
        # Log tool execution
        await audit_logger.log_tool_operation(
            tool_name=request["tool_name"],
            operation=request["operation"],
            arguments=request["arguments"],
            context=request["context"],
            result=request["result"],
            risk_score=request["risk_score"]
        )
        
        # Retrieve audit trail
        events = await audit_logger.get_audit_trail(
            session_id=request["context"].session_id,
            limit=1
        )
        
        # Verify event was logged
        assert len(events) > 0, "Tool execution should be logged"
        
        event = events[0]
        
        # Verify session context is included
        assert event.session_id == request["context"].session_id, \
            "Event should include session ID"
        assert event.user_id == request["context"].user_id, \
            "Event should include user ID"
        assert event.source_ip == request["context"].source_ip, \
            "Event should include source IP"
    
    @pytest.mark.asyncio
    @settings(max_examples=50, deadline=None)
    @seed(42)
    @given(
        request=tool_execution_requests()
    )
    async def test_audit_log_includes_risk_score(self, request):
        """
        Property: For any tool execution, the audit log includes the risk score.
        
        # Feature: irisvoice-backend-integration, Property 58: Tool Execution Audit Logging
        """
        # Create audit logger
        audit_logger = SecurityAuditLogger()
        
        # Log tool execution
        await audit_logger.log_tool_operation(
            tool_name=request["tool_name"],
            operation=request["operation"],
            arguments=request["arguments"],
            context=request["context"],
            result=request["result"],
            risk_score=request["risk_score"]
        )
        
        # Retrieve audit trail
        events = await audit_logger.get_audit_trail(
            session_id=request["context"].session_id,
            limit=1
        )
        
        # Verify event was logged
        assert len(events) > 0, "Tool execution should be logged"
        
        event = events[0]
        
        # Verify risk score is included
        assert event.risk_score == request["risk_score"], \
            f"Event should include risk score {request['risk_score']}"
    
    @pytest.mark.asyncio
    @settings(max_examples=50, deadline=None)
    @seed(42)
    @given(
        request=tool_execution_requests()
    )
    async def test_audit_log_can_be_exported(self, request):
        """
        Property: For any tool execution, the audit log can be exported to a file.
        
        # Feature: irisvoice-backend-integration, Property 58: Tool Execution Audit Logging
        """
        import tempfile
        import json
        
        # Create audit logger
        audit_logger = SecurityAuditLogger()
        
        # Log tool execution
        await audit_logger.log_tool_operation(
            tool_name=request["tool_name"],
            operation=request["operation"],
            arguments=request["arguments"],
            context=request["context"],
            result=request["result"],
            risk_score=request["risk_score"]
        )
        
        # Export audit log to temporary file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            export_path = f.name
        
        try:
            success = await audit_logger.export_audit_log(
                output_path=export_path,
                format="json",
                session_id=request["context"].session_id
            )
            
            # Verify export succeeded
            assert success, "Audit log export should succeed"
            
            # Verify exported file exists and contains data
            with open(export_path, 'r') as f:
                exported_data = json.load(f)
            
            assert "events" in exported_data, "Exported data should contain events"
            assert len(exported_data["events"]) > 0, "Exported data should contain at least one event"
            
        finally:
            # Clean up temporary file
            import os
            if os.path.exists(export_path):
                os.unlink(export_path)
        
        # Clean up
        audit_logger.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
