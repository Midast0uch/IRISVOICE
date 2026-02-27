#!/usr/bin/env python3
"""
Property-Based Tests for Vision System Configuration

Feature: irisvoice-backend-integration, Property 39: Vision System Configuration
Validates: Requirements 15.1, 15.2, 15.3

Property: For any change to automate.vision settings (vision_enabled, screen_context, 
proactive_monitor), the Vision_System shall apply the new configuration.
"""

import pytest
from hypothesis import given, strategies as st, settings
from backend.tools.vision_system import VisionSystem, VisionConfig, VisionModel


# Test data generators
@st.composite
def vision_configs(draw):
    """Generate random vision configurations"""
    return {
        "vision_enabled": draw(st.booleans()),
        "screen_context": draw(st.booleans()),
        "proactive_monitor": draw(st.booleans()),
        "ollama_endpoint": draw(st.sampled_from([
            "http://localhost:11434",
            "http://127.0.0.1:11434",
            "http://192.168.1.100:11434"
        ])),
        "vision_model": draw(st.sampled_from([
            "minicpm-o4.5",
            "llava",
            "bakllava"
        ])),
        "monitor_interval": draw(st.integers(min_value=5, max_value=120))
    }


@st.composite
def config_updates(draw):
    """Generate random configuration updates"""
    updates = {}
    
    # Randomly include each field
    if draw(st.booleans()):
        updates["vision_enabled"] = draw(st.booleans())
    if draw(st.booleans()):
        updates["screen_context"] = draw(st.booleans())
    if draw(st.booleans()):
        updates["proactive_monitor"] = draw(st.booleans())
    if draw(st.booleans()):
        updates["monitor_interval"] = draw(st.integers(min_value=5, max_value=120))
    
    return updates


class TestVisionSystemConfigurationProperties:
    """Property-based tests for vision system configuration"""
    
    @given(config=vision_configs())
    @settings(max_examples=100, deadline=None)
    def test_property_39_vision_enabled_configuration(self, config):
        """
        Property 39: Vision System Configuration - vision_enabled
        
        For any change to vision_enabled setting, the Vision_System shall 
        apply the new configuration.
        """
        # Create vision system with initial config
        initial_config = VisionConfig(
            vision_enabled=not config["vision_enabled"]  # Opposite of target
        )
        vision_system = VisionSystem(initial_config)
        
        # Verify initial state
        assert vision_system.config.vision_enabled == (not config["vision_enabled"])
        
        # Update configuration
        vision_system.update_config(vision_enabled=config["vision_enabled"])
        
        # Verify configuration applied
        assert vision_system.config.vision_enabled == config["vision_enabled"]
        
        # Verify status reflects configuration
        status = vision_system.get_status()
        assert status["vision_enabled"] == config["vision_enabled"]
    
    @given(config=vision_configs())
    @settings(max_examples=100, deadline=None)
    def test_property_39_screen_context_configuration(self, config):
        """
        Property 39: Vision System Configuration - screen_context
        
        For any change to screen_context setting, the Vision_System shall 
        apply the new configuration.
        """
        # Create vision system with initial config
        initial_config = VisionConfig(
            screen_context=not config["screen_context"]  # Opposite of target
        )
        vision_system = VisionSystem(initial_config)
        
        # Verify initial state
        assert vision_system.config.screen_context == (not config["screen_context"])
        
        # Update configuration
        vision_system.update_config(screen_context=config["screen_context"])
        
        # Verify configuration applied
        assert vision_system.config.screen_context == config["screen_context"]
        
        # Verify status reflects configuration
        status = vision_system.get_status()
        assert status["screen_context"] == config["screen_context"]
    
    @given(config=vision_configs())
    @settings(max_examples=100, deadline=None)
    def test_property_39_proactive_monitor_configuration(self, config):
        """
        Property 39: Vision System Configuration - proactive_monitor
        
        For any change to proactive_monitor setting, the Vision_System shall 
        apply the new configuration.
        """
        # Create vision system with initial config
        initial_config = VisionConfig(
            proactive_monitor=not config["proactive_monitor"]  # Opposite of target
        )
        vision_system = VisionSystem(initial_config)
        
        # Verify initial state
        assert vision_system.config.proactive_monitor == (not config["proactive_monitor"])
        
        # Update configuration
        vision_system.update_config(proactive_monitor=config["proactive_monitor"])
        
        # Verify configuration applied
        assert vision_system.config.proactive_monitor == config["proactive_monitor"]
        
        # Verify status reflects configuration
        status = vision_system.get_status()
        assert status["proactive_monitor"] == config["proactive_monitor"]
    
    @given(updates=config_updates())
    @settings(max_examples=100, deadline=None)
    def test_property_39_multiple_settings_update(self, updates):
        """
        Property 39: Vision System Configuration - multiple settings
        
        For any combination of vision setting changes, the Vision_System shall 
        apply all new configurations correctly.
        """
        # Skip if no updates
        if not updates:
            return
        
        # Create vision system with default config
        vision_system = VisionSystem()
        
        # Store initial values
        initial_values = {
            key: getattr(vision_system.config, key)
            for key in updates.keys()
        }
        
        # Update configuration
        vision_system.update_config(**updates)
        
        # Verify all configurations applied
        for key, value in updates.items():
            if key == "vision_model":
                # Convert string to enum for comparison
                expected = VisionModel(value) if isinstance(value, str) else value
                assert vision_system.config.vision_model == expected
            else:
                assert getattr(vision_system.config, key) == value
        
        # Verify status reflects all configurations
        status = vision_system.get_status()
        for key, value in updates.items():
            if key in status:
                if key == "model":
                    # Status uses "model" key for vision_model
                    expected = value if isinstance(value, str) else value.value
                    assert status["model"] == expected
                else:
                    assert status[key] == value
    
    @given(
        interval=st.integers(min_value=-100, max_value=200)
    )
    @settings(max_examples=100, deadline=None)
    def test_property_39_monitor_interval_bounds(self, interval):
        """
        Property 39: Vision System Configuration - monitor_interval bounds
        
        For any monitor_interval value, the Vision_System shall clamp it to 
        the valid range (5-120 seconds).
        """
        # Create vision system
        vision_system = VisionSystem()
        
        # Update with potentially out-of-bounds interval
        vision_system.update_config(monitor_interval=interval)
        
        # Verify interval is clamped to valid range
        actual_interval = vision_system.config.monitor_interval
        assert 5 <= actual_interval <= 120
        
        # Verify clamping logic
        if interval < 5:
            assert actual_interval == 5
        elif interval > 120:
            assert actual_interval == 120
        else:
            assert actual_interval == interval
    
    @given(
        model_str=st.sampled_from(["minicpm-o4.5", "llava", "bakllava"])
    )
    @settings(max_examples=100, deadline=None)
    def test_property_39_vision_model_string_conversion(self, model_str):
        """
        Property 39: Vision System Configuration - vision_model string conversion
        
        For any valid vision_model string, the Vision_System shall convert it 
        to the appropriate enum value.
        """
        # Create vision system
        vision_system = VisionSystem()
        
        # Update with string model name
        vision_system.update_config(vision_model=model_str)
        
        # Verify model is converted to enum
        assert isinstance(vision_system.config.vision_model, VisionModel)
        assert vision_system.config.vision_model.value == model_str
        
        # Verify status reflects model
        status = vision_system.get_status()
        assert status["model"] == model_str
    
    @given(config=vision_configs())
    @settings(max_examples=100, deadline=None)
    def test_property_39_configuration_persistence(self, config):
        """
        Property 39: Vision System Configuration - persistence
        
        For any configuration update, the Vision_System shall maintain the 
        configuration across multiple get_status() calls.
        """
        # Create vision system
        vision_system = VisionSystem()
        
        # Update configuration
        vision_system.update_config(**config)
        
        # Get status multiple times
        status1 = vision_system.get_status()
        status2 = vision_system.get_status()
        status3 = vision_system.get_status()
        
        # Verify configuration is consistent
        assert status1["vision_enabled"] == status2["vision_enabled"] == status3["vision_enabled"]
        assert status1["screen_context"] == status2["screen_context"] == status3["screen_context"]
        assert status1["proactive_monitor"] == status2["proactive_monitor"] == status3["proactive_monitor"]
        assert status1["monitor_interval"] == status2["monitor_interval"] == status3["monitor_interval"]
        assert status1["model"] == status2["model"] == status3["model"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--hypothesis-show-statistics"])
