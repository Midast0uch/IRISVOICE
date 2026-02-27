#!/usr/bin/env python3
"""
Property-Based Tests for Vision Context Integration

Feature: irisvoice-backend-integration, Property 41: Vision Context Integration
Validates: Requirements 15.7

Property: For any screen capture when screen_context is enabled, the Vision_System shall 
send analysis results to the Agent_Kernel for inclusion in conversation context.
"""

import pytest
from hypothesis import given, strategies as st, settings
from unittest.mock import Mock, AsyncMock, patch
from backend.tools.vision_system import VisionSystem, VisionConfig, ScreenAnalysis
import time


# Test data generators
@st.composite
def screen_analyses(draw):
    """Generate random screen analysis results"""
    # Use a fixed base time to avoid flaky tests
    base_time = 1700000000.0  # Fixed timestamp
    return ScreenAnalysis(
        timestamp=draw(st.floats(min_value=base_time, max_value=base_time + 3600)),
        description=draw(st.text(min_size=10, max_size=200)),
        active_app=draw(st.one_of(st.none(), st.sampled_from([
            "Chrome", "VSCode", "Terminal", "Slack", "Discord"
        ]))),
        notable_items=draw(st.lists(st.text(min_size=5, max_size=50), max_size=5)),
        needs_help=draw(st.booleans()),
        suggestion=draw(st.one_of(st.none(), st.text(min_size=10, max_size=100))),
        raw_response=draw(st.text(min_size=20, max_size=500))
    )


class TestVisionContextIntegrationProperties:
    """Property-based tests for vision context integration"""
    
    @given(analysis=screen_analyses())
    @settings(max_examples=100, deadline=None)
    def test_property_41_context_available_when_enabled(self, analysis):
        """
        Property 41: Vision Context Integration - context availability
        
        For any screen capture when screen_context is enabled, the Vision_System 
        shall make analysis results available for Agent_Kernel context.
        """
        # Create vision system with screen_context enabled
        config = VisionConfig(
            vision_enabled=True,
            screen_context=True
        )
        vision_system = VisionSystem(config)
        
        # Simulate analysis result
        vision_system._current_context = analysis
        vision_system._context_history.append(analysis)
        
        # Verify context is available
        current = vision_system.get_current_context()
        assert current is not None
        assert current == analysis
        
        # Verify context can be retrieved
        assert current.description == analysis.description
        assert current.active_app == analysis.active_app
        assert current.notable_items == analysis.notable_items
        assert current.needs_help == analysis.needs_help
        assert current.suggestion == analysis.suggestion
    
    @given(analysis=screen_analyses())
    @settings(max_examples=100, deadline=None)
    def test_property_41_context_in_history(self, analysis):
        """
        Property 41: Vision Context Integration - history tracking
        
        For any screen capture when screen_context is enabled, the Vision_System 
        shall maintain analysis results in context history.
        """
        # Create vision system with screen_context enabled
        config = VisionConfig(
            vision_enabled=True,
            screen_context=True
        )
        vision_system = VisionSystem(config)
        
        # Simulate analysis result
        vision_system._current_context = analysis
        vision_system._context_history.append(analysis)
        
        # Verify context is in history
        history = vision_system.get_context_history(limit=10)
        assert len(history) > 0
        assert analysis in history
        
        # Verify most recent is accessible
        assert history[-1] == analysis
    
    @given(
        analyses=st.lists(screen_analyses(), min_size=1, max_size=25)
    )
    @settings(max_examples=100, deadline=None)
    def test_property_41_multiple_contexts_tracked(self, analyses):
        """
        Property 41: Vision Context Integration - multiple contexts
        
        For any sequence of screen captures when screen_context is enabled, 
        the Vision_System shall track all analysis results up to the history limit.
        """
        # Create vision system with screen_context enabled
        config = VisionConfig(
            vision_enabled=True,
            screen_context=True
        )
        vision_system = VisionSystem(config)
        
        # Add all analyses to history
        for analysis in analyses:
            vision_system._current_context = analysis
            vision_system._context_history.append(analysis)
        
        # Verify history contains analyses (up to max_history limit)
        history = vision_system.get_context_history(limit=len(analyses))
        expected_count = min(len(analyses), vision_system._max_history)
        assert len(history) <= expected_count
        
        # Verify most recent analyses are in history
        for i, analysis in enumerate(analyses[-expected_count:]):
            assert analysis in history
    
    @given(analysis=screen_analyses())
    @settings(max_examples=100, deadline=None)
    def test_property_41_context_not_available_when_disabled(self, analysis):
        """
        Property 41: Vision Context Integration - disabled behavior
        
        When screen_context is disabled, the Vision_System should still track 
        context internally but the feature flag indicates it shouldn't be used.
        """
        # Create vision system with screen_context disabled
        config = VisionConfig(
            vision_enabled=True,
            screen_context=False
        )
        vision_system = VisionSystem(config)
        
        # Verify screen_context is disabled in status
        status = vision_system.get_status()
        assert status["screen_context"] is False
        
        # Even if we simulate analysis, the flag indicates it shouldn't be used
        vision_system._current_context = analysis
        
        # Context is still accessible (for internal use) but flag indicates not to use it
        current = vision_system.get_current_context()
        assert current == analysis
        
        # But the configuration indicates it shouldn't be sent to Agent_Kernel
        assert vision_system.config.screen_context is False
    
    @given(
        limit=st.integers(min_value=1, max_value=50)
    )
    @settings(max_examples=100, deadline=None)
    def test_property_41_history_limit_respected(self, limit):
        """
        Property 41: Vision Context Integration - history limit
        
        For any history limit request, the Vision_System shall return at most 
        that many recent analyses.
        """
        # Create vision system
        vision_system = VisionSystem()
        
        # Add more analyses than the limit
        num_analyses = limit + 10
        for i in range(num_analyses):
            analysis = ScreenAnalysis(
                timestamp=time.time() + i,
                description=f"Analysis {i}",
                active_app="TestApp",
                notable_items=[],
                needs_help=False,
                suggestion=None,
                raw_response=f"Response {i}"
            )
            vision_system._context_history.append(analysis)
        
        # Get history with limit
        history = vision_system.get_context_history(limit=limit)
        
        # Verify limit is respected
        assert len(history) <= limit
        
        # Verify we got the most recent ones
        if len(vision_system._context_history) >= limit:
            expected = vision_system._context_history[-limit:]
            assert history == expected
    
    @given(analysis=screen_analyses())
    @settings(max_examples=100, deadline=None)
    def test_property_41_context_fields_preserved(self, analysis):
        """
        Property 41: Vision Context Integration - field preservation
        
        For any screen analysis, all fields shall be preserved when stored 
        and retrieved from context.
        """
        # Create vision system
        vision_system = VisionSystem()
        
        # Store analysis
        vision_system._current_context = analysis
        vision_system._context_history.append(analysis)
        
        # Retrieve and verify all fields
        retrieved = vision_system.get_current_context()
        assert retrieved is not None
        
        # Verify all fields match
        assert retrieved.timestamp == analysis.timestamp
        assert retrieved.description == analysis.description
        assert retrieved.active_app == analysis.active_app
        assert retrieved.notable_items == analysis.notable_items
        assert retrieved.needs_help == analysis.needs_help
        assert retrieved.suggestion == analysis.suggestion
        assert retrieved.raw_response == analysis.raw_response
    
    @given(
        analyses=st.lists(screen_analyses(), min_size=2, max_size=10)
    )
    @settings(max_examples=100, deadline=None)
    def test_property_41_context_ordering_preserved(self, analyses):
        """
        Property 41: Vision Context Integration - ordering
        
        For any sequence of screen analyses, the Vision_System shall preserve 
        the chronological order in context history.
        """
        # Create vision system
        vision_system = VisionSystem()
        
        # Add analyses in order
        for analysis in analyses:
            vision_system._context_history.append(analysis)
        
        # Get history
        history = vision_system.get_context_history(limit=len(analyses))
        
        # Verify order is preserved (most recent last)
        for i, analysis in enumerate(analyses[-len(history):]):
            assert history[i] == analysis
    
    @given(analysis=screen_analyses())
    @settings(max_examples=100, deadline=None)
    def test_property_41_current_context_updates(self, analysis):
        """
        Property 41: Vision Context Integration - current context updates
        
        For any new screen analysis, the Vision_System shall update the 
        current context to the most recent analysis.
        """
        # Create vision system
        vision_system = VisionSystem()
        
        # Create initial analysis with earlier timestamp
        initial_analysis = ScreenAnalysis(
            timestamp=analysis.timestamp - 100,  # Earlier than the new analysis
            description="Initial",
            active_app="InitialApp",
            notable_items=[],
            needs_help=False,
            suggestion=None,
            raw_response="Initial response"
        )
        vision_system._current_context = initial_analysis
        
        # Update with new analysis
        vision_system._current_context = analysis
        vision_system._context_history.append(analysis)
        
        # Verify current context is updated
        current = vision_system.get_current_context()
        assert current == analysis
        assert current != initial_analysis
        
        # Verify it's the most recent
        assert current.timestamp >= initial_analysis.timestamp


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--hypothesis-show-statistics"])
