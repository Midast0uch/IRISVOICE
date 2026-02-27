"""
Property-based tests for wake word configuration.
Tests universal properties that should hold for wake word configuration updates,
including wake phrase, detection sensitivity, and activation sound settings.
"""
import pytest
from hypothesis import given, settings, strategies as st, seed
import sys
import os
from unittest.mock import Mock, patch, MagicMock

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.agent.lfm_audio_manager import LFMAudioManager


# ============================================================================
# Test Data Generators (Hypothesis Strategies)
# ============================================================================

@st.composite
def wake_phrase_generator(draw):
    """Generate valid wake phrases."""
    return draw(st.sampled_from([
        "jarvis", "hey computer", "computer", "bumblebee", "porcupine", "hey iris"
    ]))


@st.composite
def invalid_wake_phrase_generator(draw):
    """Generate invalid wake phrases."""
    return draw(st.text(min_size=1, max_size=50).filter(
        lambda x: x not in ["jarvis", "hey computer", "computer", "bumblebee", "porcupine", "hey iris"]
    ))


@st.composite
def detection_sensitivity_generator(draw):
    """Generate valid detection sensitivity values (0-100)."""
    return draw(st.integers(min_value=0, max_value=100))


@st.composite
def invalid_detection_sensitivity_generator(draw):
    """Generate invalid detection sensitivity values."""
    return draw(st.one_of(
        st.integers(max_value=-1),
        st.integers(min_value=101)
    ))


@st.composite
def config_generator(draw):
    """Generate LFM audio manager configuration."""
    return {
        "lfm_model_path": "",
        "device": "cpu",
        "wake_phrase": draw(wake_phrase_generator()),
        "detection_sensitivity": draw(detection_sensitivity_generator()),
        "activation_sound": draw(st.booleans()),
        "tts_voice": "Nova",
        "speaking_rate": 1.0
    }


# ============================================================================
# Property 12: Wake Word Configuration
# Feature: irisvoice-backend-integration, Property 12: Wake Word Configuration
# Validates: Requirement 4.4
# ============================================================================

class TestWakeWordConfiguration:
    """
    Property 12: Wake Word Configuration
    
    For any configured wake phrase in the agent.wake.wake_phrase field,
    the Voice_Pipeline uses that phrase for detection.
    
    This tests:
    - Requirement 4.4: LFM_Audio_Model uses configured wake phrase
    """
    
    @settings(max_examples=10, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        wake_phrase=wake_phrase_generator(),
        detection_sensitivity=detection_sensitivity_generator(),
        activation_sound=st.booleans()
    )
    def test_wake_phrase_configuration_is_applied(
        self, wake_phrase, detection_sensitivity, activation_sound
    ):
        """
        Property: For any valid wake phrase configuration, the manager uses that phrase.
        
        # Feature: irisvoice-backend-integration, Property 12: Wake Word Configuration
        **Validates: Requirement 4.4**
        """
        # Setup: Create manager with specific configuration
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": wake_phrase,
            "detection_sensitivity": detection_sensitivity,
            "activation_sound": activation_sound,
            "tts_voice": "Nova",
            "speaking_rate": 1.0
        }
        
        manager = LFMAudioManager(config)
        
        # Verify: Configuration is applied
        assert manager.wake_phrase == wake_phrase, \
            f"Manager should use configured wake phrase '{wake_phrase}'"
        assert manager.detection_sensitivity == detection_sensitivity, \
            f"Manager should use configured sensitivity {detection_sensitivity}"
        assert manager.activation_sound == activation_sound, \
            f"Manager should use configured activation_sound {activation_sound}"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        initial_config=config_generator(),
        new_wake_phrase=wake_phrase_generator()
    )
    def test_wake_phrase_can_be_updated(self, initial_config, new_wake_phrase):
        """
        Property: For any wake phrase update, the configuration is changed.
        
        # Feature: irisvoice-backend-integration, Property 12: Wake Word Configuration
        **Validates: Requirement 4.4**
        """
        # Setup: Create manager with initial configuration
        manager = LFMAudioManager(initial_config)
        initial_phrase = manager.wake_phrase
        
        # Execute: Update wake phrase
        manager.update_wake_config(wake_phrase=new_wake_phrase)
        
        # Verify: Configuration is updated
        assert manager.wake_phrase == new_wake_phrase, \
            f"Wake phrase should be updated to '{new_wake_phrase}'"
        
        # If the new phrase is different, verify it changed
        if new_wake_phrase != initial_phrase:
            assert manager.wake_phrase != initial_phrase, \
                "Wake phrase should have changed"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        initial_config=config_generator(),
        new_sensitivity=detection_sensitivity_generator()
    )
    def test_detection_sensitivity_can_be_updated(self, initial_config, new_sensitivity):
        """
        Property: For any detection sensitivity update, the configuration is changed.
        
        # Feature: irisvoice-backend-integration, Property 12: Wake Word Configuration
        **Validates: Requirement 4.5**
        """
        # Setup: Create manager with initial configuration
        manager = LFMAudioManager(initial_config)
        initial_sensitivity = manager.detection_sensitivity
        
        # Execute: Update detection sensitivity
        manager.update_wake_config(detection_sensitivity=new_sensitivity)
        
        # Verify: Configuration is updated
        assert manager.detection_sensitivity == new_sensitivity, \
            f"Detection sensitivity should be updated to {new_sensitivity}"
        
        # If the new sensitivity is different, verify it changed
        if new_sensitivity != initial_sensitivity:
            assert manager.detection_sensitivity != initial_sensitivity, \
                "Detection sensitivity should have changed"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        initial_config=config_generator(),
        new_activation_sound=st.booleans()
    )
    def test_activation_sound_can_be_updated(self, initial_config, new_activation_sound):
        """
        Property: For any activation sound update, the configuration is changed.
        
        # Feature: irisvoice-backend-integration, Property 12: Wake Word Configuration
        **Validates: Requirement 4.6**
        """
        # Setup: Create manager with initial configuration
        manager = LFMAudioManager(initial_config)
        initial_sound = manager.activation_sound
        
        # Execute: Update activation sound
        manager.update_wake_config(activation_sound=new_activation_sound)
        
        # Verify: Configuration is updated
        assert manager.activation_sound == new_activation_sound, \
            f"Activation sound should be updated to {new_activation_sound}"
        
        # If the new setting is different, verify it changed
        if new_activation_sound != initial_sound:
            assert manager.activation_sound != initial_sound, \
                "Activation sound should have changed"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        config=config_generator(),
        invalid_phrase=invalid_wake_phrase_generator()
    )
    def test_invalid_wake_phrase_is_rejected(self, config, invalid_phrase):
        """
        Property: For any invalid wake phrase, the configuration is not changed.
        
        # Feature: irisvoice-backend-integration, Property 12: Wake Word Configuration
        **Validates: Requirement 4.4**
        """
        # Setup: Create manager with valid configuration
        manager = LFMAudioManager(config)
        original_phrase = manager.wake_phrase
        
        # Execute: Try to update with invalid wake phrase
        manager.update_wake_config(wake_phrase=invalid_phrase)
        
        # Verify: Configuration is not changed
        assert manager.wake_phrase == original_phrase, \
            f"Wake phrase should remain '{original_phrase}' when invalid phrase provided"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        config=config_generator(),
        invalid_sensitivity=invalid_detection_sensitivity_generator()
    )
    def test_invalid_detection_sensitivity_is_rejected(self, config, invalid_sensitivity):
        """
        Property: For any invalid detection sensitivity, the configuration is not changed.
        
        # Feature: irisvoice-backend-integration, Property 12: Wake Word Configuration
        **Validates: Requirement 4.5**
        """
        # Setup: Create manager with valid configuration
        manager = LFMAudioManager(config)
        original_sensitivity = manager.detection_sensitivity
        
        # Execute: Try to update with invalid sensitivity
        manager.update_wake_config(detection_sensitivity=invalid_sensitivity)
        
        # Verify: Configuration is not changed
        assert manager.detection_sensitivity == original_sensitivity, \
            f"Detection sensitivity should remain {original_sensitivity} when invalid value provided"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        wake_phrase=wake_phrase_generator(),
        detection_sensitivity=detection_sensitivity_generator(),
        activation_sound=st.booleans()
    )
    def test_multiple_config_updates_at_once(
        self, wake_phrase, detection_sensitivity, activation_sound
    ):
        """
        Property: For any multiple configuration updates, all are applied correctly.
        
        # Feature: irisvoice-backend-integration, Property 12: Wake Word Configuration
        **Validates: Requirement 4.4, 4.5, 4.6**
        """
        # Setup: Create manager with default configuration
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": "jarvis",
            "detection_sensitivity": 50,
            "activation_sound": True,
            "tts_voice": "Nova",
            "speaking_rate": 1.0
        }
        manager = LFMAudioManager(config)
        
        # Execute: Update all wake configuration at once
        manager.update_wake_config(
            wake_phrase=wake_phrase,
            detection_sensitivity=detection_sensitivity,
            activation_sound=activation_sound
        )
        
        # Verify: All configurations are updated
        assert manager.wake_phrase == wake_phrase, \
            f"Wake phrase should be '{wake_phrase}'"
        assert manager.detection_sensitivity == detection_sensitivity, \
            f"Detection sensitivity should be {detection_sensitivity}"
        assert manager.activation_sound == activation_sound, \
            f"Activation sound should be {activation_sound}"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        invalid_phrase=invalid_wake_phrase_generator()
    )
    def test_invalid_wake_phrase_in_constructor_uses_default(self, invalid_phrase):
        """
        Property: For any invalid wake phrase in constructor, default is used.
        
        # Feature: irisvoice-backend-integration, Property 12: Wake Word Configuration
        **Validates: Requirement 4.4**
        """
        # Setup: Create manager with invalid wake phrase
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": invalid_phrase,
            "detection_sensitivity": 50,
            "activation_sound": True,
            "tts_voice": "Nova",
            "speaking_rate": 1.0
        }
        
        manager = LFMAudioManager(config)
        
        # Verify: Default wake phrase is used
        assert manager.wake_phrase == "jarvis", \
            "Invalid wake phrase should default to 'jarvis'"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        invalid_sensitivity=invalid_detection_sensitivity_generator()
    )
    def test_invalid_sensitivity_in_constructor_uses_default(self, invalid_sensitivity):
        """
        Property: For any invalid detection sensitivity in constructor, default is used.
        
        # Feature: irisvoice-backend-integration, Property 12: Wake Word Configuration
        **Validates: Requirement 4.5**
        """
        # Setup: Create manager with invalid sensitivity
        config = {
            "lfm_model_path": "",
            "device": "cpu",
            "wake_phrase": "jarvis",
            "detection_sensitivity": invalid_sensitivity,
            "activation_sound": True,
            "tts_voice": "Nova",
            "speaking_rate": 1.0
        }
        
        manager = LFMAudioManager(config)
        
        # Verify: Default sensitivity is used
        assert manager.detection_sensitivity == 50, \
            "Invalid detection sensitivity should default to 50"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        config=config_generator()
    )
    def test_wake_config_persists_across_operations(self, config):
        """
        Property: For any wake configuration, it persists across operations.
        
        # Feature: irisvoice-backend-integration, Property 12: Wake Word Configuration
        **Validates: Requirement 4.4**
        """
        # Setup: Create manager with configuration
        manager = LFMAudioManager(config)
        
        # Store original configuration
        original_phrase = manager.wake_phrase
        original_sensitivity = manager.detection_sensitivity
        original_sound = manager.activation_sound
        
        # Execute: Perform some operations (that don't change config)
        # Simulate some internal operations
        manager.wake_word_active = True
        manager.wake_word_active = False
        
        # Verify: Configuration persists
        assert manager.wake_phrase == original_phrase, \
            "Wake phrase should persist across operations"
        assert manager.detection_sensitivity == original_sensitivity, \
            "Detection sensitivity should persist across operations"
        assert manager.activation_sound == original_sound, \
            "Activation sound should persist across operations"
