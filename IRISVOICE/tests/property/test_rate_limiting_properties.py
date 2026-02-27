"""
Property-based tests for tool execution rate limiting.
Tests that the SecurityFilter enforces rate limits on tool executions.
"""
import pytest
import asyncio
from hypothesis import given, settings, strategies as st, seed, HealthCheck
from datetime import datetime, timedelta
import sys
import os

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.gateway.security_filter import SecurityFilter
from backend.security.mcp_security import MCPSecurityManager
from backend.security.audit_logger import SecurityAuditLogger


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
def tool_names(draw):
    """Generate tool names."""
    return draw(st.sampled_from([
        "file_manager", "gui_automation", "system", 
        "web_browser", "clipboard", "screen_capture",
        "vision_system", "app_launcher"
    ]))


@st.composite
def tool_execution_sequences(draw):
    """Generate sequences of tool execution requests."""
    num_requests = draw(st.integers(min_value=1, max_value=20))
    session_id = draw(session_ids())
    tool_name = draw(tool_names())
    
    return {
        "session_id": session_id,
        "tool_name": tool_name,
        "num_requests": num_requests
    }


@st.composite
def multi_session_sequences(draw):
    """Generate tool execution sequences across multiple sessions."""
    num_sessions = draw(st.integers(min_value=2, max_value=5))
    sequences = []
    used_session_ids = set()
    
    # Use the same tool for all sessions to test session isolation
    tool_name = draw(tool_names())
    
    for _ in range(num_sessions):
        # Generate unique session IDs
        session_id = draw(session_ids())
        while session_id in used_session_ids:
            session_id = draw(session_ids())
        used_session_ids.add(session_id)
        
        num_requests = draw(st.integers(min_value=5, max_value=15))
        
        sequences.append({
            "session_id": session_id,
            "tool_name": tool_name,
            "num_requests": num_requests
        })
    
    return sequences


@st.composite
def multi_tool_sequences(draw):
    """Generate tool execution sequences across multiple tools in the same session."""
    session_id = draw(session_ids())
    num_tools = draw(st.integers(min_value=2, max_value=4))
    sequences = []
    used_tools = set()
    
    for _ in range(num_tools):
        # Generate unique tool names
        tool_name = draw(tool_names())
        while tool_name in used_tools:
            tool_name = draw(tool_names())
        used_tools.add(tool_name)
        
        num_requests = draw(st.integers(min_value=5, max_value=15))
        
        sequences.append({
            "session_id": session_id,
            "tool_name": tool_name,
            "num_requests": num_requests
        })
    
    return sequences


# ============================================================================
# Property 61: Tool Execution Rate Limiting
# Feature: irisvoice-backend-integration, Property 61: Tool Execution Rate Limiting
# Validates: Requirements 24.6
# ============================================================================

class TestToolExecutionRateLimiting:
    """
    Property 61: Tool Execution Rate Limiting
    
    For any sequence of tool executions, the SecurityFilter shall enforce
    a rate limit of maximum 10 executions per minute per session and tool.
    """
    
    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        sequence=tool_execution_sequences()
    )
    async def test_first_10_requests_within_minute_are_allowed(self, sequence):
        """
        Property: For any sequence of tool execution requests,
        the first 10 requests within a minute are allowed.
        
        # Feature: irisvoice-backend-integration, Property 61: Tool Execution Rate Limiting
        """
        # Create security filter
        security_filter = SecurityFilter()
        
        session_id = sequence["session_id"]
        tool_name = sequence["tool_name"]
        num_requests = min(sequence["num_requests"], 10)
        
        # Execute first 10 requests
        for i in range(num_requests):
            is_rate_limited = security_filter.check_tool_execution_rate_limit(
                session_id=session_id,
                tool_name=tool_name
            )
            
            # Verify request is not rate limited
            assert not is_rate_limited, \
                f"Request {i+1} of {num_requests} should not be rate limited (within first 10)"
    
    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None)
    @seed(42)
    @given(
        session_id=session_ids(),
        tool_name=tool_names()
    )
    async def test_11th_request_within_minute_is_blocked(self, session_id, tool_name):
        """
        Property: For any tool execution, the 11th request within the same minute
        is blocked by rate limiting.
        
        # Feature: irisvoice-backend-integration, Property 61: Tool Execution Rate Limiting
        """
        # Create security filter
        security_filter = SecurityFilter()
        
        # Execute 10 requests (should all succeed)
        for i in range(10):
            is_rate_limited = security_filter.check_tool_execution_rate_limit(
                session_id=session_id,
                tool_name=tool_name
            )
            assert not is_rate_limited, f"Request {i+1} should not be rate limited"
        
        # Execute 11th request (should be rate limited)
        is_rate_limited = security_filter.check_tool_execution_rate_limit(
            session_id=session_id,
            tool_name=tool_name
        )
        
        # Verify 11th request is rate limited
        assert is_rate_limited, \
            "11th request within the same minute should be rate limited"
    
    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None)
    @seed(42)
    @given(
        session_id=session_ids(),
        tool_name=tool_names(),
        num_excess_requests=st.integers(min_value=1, max_value=10)
    )
    async def test_subsequent_requests_within_minute_are_blocked(
        self, session_id, tool_name, num_excess_requests
    ):
        """
        Property: For any tool execution, all requests beyond the 10th within
        the same minute are blocked by rate limiting.
        
        # Feature: irisvoice-backend-integration, Property 61: Tool Execution Rate Limiting
        """
        # Create security filter
        security_filter = SecurityFilter()
        
        # Execute 10 requests (should all succeed)
        for i in range(10):
            is_rate_limited = security_filter.check_tool_execution_rate_limit(
                session_id=session_id,
                tool_name=tool_name
            )
            assert not is_rate_limited, f"Request {i+1} should not be rate limited"
        
        # Execute additional requests (should all be rate limited)
        for i in range(num_excess_requests):
            is_rate_limited = security_filter.check_tool_execution_rate_limit(
                session_id=session_id,
                tool_name=tool_name
            )
            
            assert is_rate_limited, \
                f"Request {11+i} within the same minute should be rate limited"
    
    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.large_base_example])
    @seed(42)
    @given(
        sequences=multi_session_sequences()
    )
    async def test_rate_limits_are_tracked_per_session(self, sequences):
        """
        Property: For any tool executions across multiple sessions,
        rate limits are tracked independently per session.
        
        # Feature: irisvoice-backend-integration, Property 61: Tool Execution Rate Limiting
        """
        # Create security filter
        security_filter = SecurityFilter()
        
        # Execute requests for each session
        for sequence in sequences:
            session_id = sequence["session_id"]
            tool_name = sequence["tool_name"]
            num_requests = min(sequence["num_requests"], 10)
            
            # Each session should be able to make 10 requests
            for i in range(num_requests):
                is_rate_limited = security_filter.check_tool_execution_rate_limit(
                    session_id=session_id,
                    tool_name=tool_name
                )
                
                assert not is_rate_limited, \
                    f"Session {session_id} request {i+1} should not be rate limited " \
                    f"(sessions have independent rate limits)"
    
    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.large_base_example])
    @seed(42)
    @given(
        sequences=multi_tool_sequences()
    )
    async def test_rate_limits_are_tracked_per_tool(self, sequences):
        """
        Property: For any tool executions of different tools in the same session,
        rate limits are tracked independently per tool.
        
        # Feature: irisvoice-backend-integration, Property 61: Tool Execution Rate Limiting
        """
        # Create security filter
        security_filter = SecurityFilter()
        
        # Execute requests for each tool
        for sequence in sequences:
            session_id = sequence["session_id"]
            tool_name = sequence["tool_name"]
            num_requests = min(sequence["num_requests"], 10)
            
            # Each tool should have its own rate limit
            for i in range(num_requests):
                is_rate_limited = security_filter.check_tool_execution_rate_limit(
                    session_id=session_id,
                    tool_name=tool_name
                )
                
                assert not is_rate_limited, \
                    f"Tool {tool_name} request {i+1} should not be rate limited " \
                    f"(tools have independent rate limits)"
    
    @pytest.mark.asyncio
    @settings(max_examples=50, deadline=None)
    @seed(42)
    @given(
        session_id=session_ids(),
        tool_name=tool_names()
    )
    async def test_rate_limit_resets_after_time_window(self, session_id, tool_name):
        """
        Property: For any tool execution that hits the rate limit,
        the rate limit resets after the time window expires.
        
        # Feature: irisvoice-backend-integration, Property 61: Tool Execution Rate Limiting
        
        Note: This test simulates time window expiration by manually resetting
        the rate limit, as waiting 60 seconds would make tests too slow.
        """
        # Create security filter
        security_filter = SecurityFilter()
        
        # Execute 10 requests (should all succeed)
        for i in range(10):
            is_rate_limited = security_filter.check_tool_execution_rate_limit(
                session_id=session_id,
                tool_name=tool_name
            )
            assert not is_rate_limited, f"Request {i+1} should not be rate limited"
        
        # 11th request should be rate limited
        is_rate_limited = security_filter.check_tool_execution_rate_limit(
            session_id=session_id,
            tool_name=tool_name
        )
        assert is_rate_limited, "11th request should be rate limited"
        
        # Simulate time window expiration by resetting rate limit
        key = f"tool_execution_{session_id}_{tool_name}"
        security_filter.reset_rate_limit(key)
        
        # After reset, requests should be allowed again
        for i in range(10):
            is_rate_limited = security_filter.check_tool_execution_rate_limit(
                session_id=session_id,
                tool_name=tool_name
            )
            assert not is_rate_limited, \
                f"Request {i+1} after reset should not be rate limited"
    
    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None)
    @seed(42)
    @given(
        session_id=session_ids(),
        tool_name=tool_names()
    )
    async def test_rate_limit_status_can_be_queried(self, session_id, tool_name):
        """
        Property: For any tool execution, the rate limit status can be queried
        to get current count, limit, and remaining requests.
        
        # Feature: irisvoice-backend-integration, Property 61: Tool Execution Rate Limiting
        """
        # Create security filter
        security_filter = SecurityFilter()
        
        key = f"tool_execution_{session_id}_{tool_name}"
        
        # Execute at least one request to initialize the rate limit tracking
        security_filter.check_tool_execution_rate_limit(
            session_id=session_id,
            tool_name=tool_name
        )
        
        # Query status after initialization
        status = security_filter.get_rate_limit_status(key)
        assert status["current_count"] >= 1, "Count should be at least 1 after first request"
        assert status["limit"] == 10, "Limit should be 10"
        assert status["remaining"] <= 9, "Remaining should be at most 9 after first request"
        
        # Execute 4 more requests (total 5)
        for i in range(4):
            security_filter.check_tool_execution_rate_limit(
                session_id=session_id,
                tool_name=tool_name
            )
        
        # Query status after 5 requests
        status = security_filter.get_rate_limit_status(key)
        assert status["current_count"] == 5, "Count should be 5 after 5 requests"
        assert status["remaining"] == 5, "Remaining should be 5 after 5 requests"
        
        # Execute 5 more requests (total 10)
        for i in range(5):
            security_filter.check_tool_execution_rate_limit(
                session_id=session_id,
                tool_name=tool_name
            )
        
        # Query status after 10 requests
        status = security_filter.get_rate_limit_status(key)
        assert status["current_count"] == 10, "Count should be 10 after 10 requests"
        assert status["remaining"] == 0, "Remaining should be 0 after 10 requests"
    
    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None)
    @seed(42)
    @given(
        session_id=session_ids(),
        tool_name=tool_names(),
        num_requests_first_batch=st.integers(min_value=1, max_value=10),
        num_requests_second_batch=st.integers(min_value=1, max_value=10)
    )
    async def test_rate_limit_status_reflects_current_window(
        self, session_id, tool_name, num_requests_first_batch, num_requests_second_batch
    ):
        """
        Property: For any tool execution, the rate limit status accurately
        reflects the number of requests in the current time window.
        
        # Feature: irisvoice-backend-integration, Property 61: Tool Execution Rate Limiting
        """
        # Create security filter
        security_filter = SecurityFilter()
        
        key = f"tool_execution_{session_id}_{tool_name}"
        
        # Execute first batch of requests
        for i in range(num_requests_first_batch):
            security_filter.check_tool_execution_rate_limit(
                session_id=session_id,
                tool_name=tool_name
            )
        
        # Query status
        status = security_filter.get_rate_limit_status(key)
        assert status["current_count"] == num_requests_first_batch, \
            f"Count should be {num_requests_first_batch}"
        assert status["remaining"] == max(0, 10 - num_requests_first_batch), \
            f"Remaining should be {max(0, 10 - num_requests_first_batch)}"
        
        # Execute second batch (may exceed limit)
        total_requests = num_requests_first_batch + num_requests_second_batch
        for i in range(num_requests_second_batch):
            security_filter.check_tool_execution_rate_limit(
                session_id=session_id,
                tool_name=tool_name
            )
        
        # Query status again
        status = security_filter.get_rate_limit_status(key)
        expected_count = min(total_requests, 10)
        assert status["current_count"] == expected_count, \
            f"Count should be {expected_count}"
        assert status["remaining"] == max(0, 10 - expected_count), \
            f"Remaining should be {max(0, 10 - expected_count)}"
    
    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None)
    @seed(42)
    @given(
        session_id=session_ids(),
        tool_name=tool_names()
    )
    async def test_rate_limit_enforces_exactly_10_per_minute(self, session_id, tool_name):
        """
        Property: For any tool execution, exactly 10 requests are allowed
        per minute, no more, no less.
        
        # Feature: irisvoice-backend-integration, Property 61: Tool Execution Rate Limiting
        """
        # Create security filter
        security_filter = SecurityFilter()
        
        allowed_count = 0
        blocked_count = 0
        
        # Try to execute 15 requests
        for i in range(15):
            is_rate_limited = security_filter.check_tool_execution_rate_limit(
                session_id=session_id,
                tool_name=tool_name
            )
            
            if not is_rate_limited:
                allowed_count += 1
            else:
                blocked_count += 1
        
        # Verify exactly 10 were allowed
        assert allowed_count == 10, \
            f"Exactly 10 requests should be allowed, got {allowed_count}"
        
        # Verify remaining 5 were blocked
        assert blocked_count == 5, \
            f"Exactly 5 requests should be blocked, got {blocked_count}"
    
    @pytest.mark.asyncio
    @settings(max_examples=50, deadline=None)
    @seed(42)
    @given(
        session_id=session_ids(),
        tool_name=tool_names()
    )
    async def test_rate_limit_status_includes_reset_time(self, session_id, tool_name):
        """
        Property: For any tool execution that has been rate limited,
        the status includes a reset_at timestamp indicating when the limit will reset.
        
        # Feature: irisvoice-backend-integration, Property 61: Tool Execution Rate Limiting
        """
        # Create security filter
        security_filter = SecurityFilter()
        
        key = f"tool_execution_{session_id}_{tool_name}"
        
        # Execute 10 requests to hit the limit
        for i in range(10):
            security_filter.check_tool_execution_rate_limit(
                session_id=session_id,
                tool_name=tool_name
            )
        
        # Query status
        status = security_filter.get_rate_limit_status(key)
        
        # Verify reset_at is present and is a valid timestamp
        assert "reset_at" in status, "Status should include reset_at"
        assert status["reset_at"] is not None, "reset_at should not be None after requests"
        
        # Verify reset_at is in the future (within reasonable bounds)
        if status["reset_at"]:
            # Parse ISO format timestamp
            from datetime import datetime
            reset_time = datetime.fromisoformat(status["reset_at"])
            now = datetime.now()
            
            # Reset time should be in the future but within 60 seconds
            time_diff = (reset_time - now).total_seconds()
            assert 0 <= time_diff <= 60, \
                f"Reset time should be within 60 seconds, got {time_diff}s"
    
    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None)
    @seed(42)
    @given(
        session_id=session_ids()
    )
    async def test_different_tools_have_independent_rate_limits(self, session_id):
        """
        Property: For any session, different tools have independent rate limits.
        Hitting the rate limit for one tool does not affect other tools.
        
        # Feature: irisvoice-backend-integration, Property 61: Tool Execution Rate Limiting
        """
        # Create security filter
        security_filter = SecurityFilter()
        
        tool1 = "file_manager"
        tool2 = "gui_automation"
        
        # Execute 10 requests for tool1 (hit the limit)
        for i in range(10):
            is_rate_limited = security_filter.check_tool_execution_rate_limit(
                session_id=session_id,
                tool_name=tool1
            )
            assert not is_rate_limited, f"Tool1 request {i+1} should not be rate limited"
        
        # Verify tool1 is now rate limited
        is_rate_limited = security_filter.check_tool_execution_rate_limit(
            session_id=session_id,
            tool_name=tool1
        )
        assert is_rate_limited, "Tool1 should be rate limited after 10 requests"
        
        # Execute 10 requests for tool2 (should all succeed)
        for i in range(10):
            is_rate_limited = security_filter.check_tool_execution_rate_limit(
                session_id=session_id,
                tool_name=tool2
            )
            assert not is_rate_limited, \
                f"Tool2 request {i+1} should not be rate limited " \
                f"(tool2 has independent rate limit from tool1)"
    
    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None)
    @seed(42)
    @given(
        tool_name=tool_names()
    )
    async def test_different_sessions_have_independent_rate_limits(self, tool_name):
        """
        Property: For any tool, different sessions have independent rate limits.
        Hitting the rate limit in one session does not affect other sessions.
        
        # Feature: irisvoice-backend-integration, Property 61: Tool Execution Rate Limiting
        """
        # Create security filter
        security_filter = SecurityFilter()
        
        session1 = "session_1"
        session2 = "session_2"
        
        # Execute 10 requests for session1 (hit the limit)
        for i in range(10):
            is_rate_limited = security_filter.check_tool_execution_rate_limit(
                session_id=session1,
                tool_name=tool_name
            )
            assert not is_rate_limited, f"Session1 request {i+1} should not be rate limited"
        
        # Verify session1 is now rate limited
        is_rate_limited = security_filter.check_tool_execution_rate_limit(
            session_id=session1,
            tool_name=tool_name
        )
        assert is_rate_limited, "Session1 should be rate limited after 10 requests"
        
        # Execute 10 requests for session2 (should all succeed)
        for i in range(10):
            is_rate_limited = security_filter.check_tool_execution_rate_limit(
                session_id=session2,
                tool_name=tool_name
            )
            assert not is_rate_limited, \
                f"Session2 request {i+1} should not be rate limited " \
                f"(session2 has independent rate limit from session1)"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
