"""
Property-based tests for agent personality configuration.
Tests universal properties that should hold for all personality configuration scenarios.
"""
import pytest
from hypothesis import given, settings, strategies as st, seed
import sys
import os

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.agent.personality import (
    PersonalityManager,
    ALLOWED_TONES,
    ALLOWED_FORMALITY,
    ALLOWED_VERBOSITY,
    ALLOWED_HUMOR,
    ALLOWED_EMPATHY
)


# ============================================================================
# Test Data Generators (Hypothesis Strategies)
# ============================================================================

@st.composite
def valid_personality_configs(draw):
    """Generate valid personality configurations."""
    config = {"identity": {}}
    
    # Randomly include each field
    if draw(st.booleans()):
        config["identity"]["assistant_name"] = draw(st.text(min_size=1, max_size=50))
    
    if draw(st.booleans()):
        config["identity"]["tone"] = draw(st.sampled_from(list(ALLOWED_TONES)))
    
    if draw(st.booleans()):
        config["identity"]["formality"] = draw(st.sampled_from(list(ALLOWED_FORMALITY)))
    
    if draw(st.booleans()):
        config["identity"]["verbosity"] = draw(st.sampled_from(list(ALLOWED_VERBOSITY)))
    
    if draw(st.booleans()):
        config["identity"]["humor"] = draw(st.sampled_from(list(ALLOWED_HUMOR)))
    
    if draw(st.booleans()):
        config["identity"]["empathy"] = draw(st.sampled_from(list(ALLOWED_EMPATHY)))
    
    if draw(st.booleans()):
        config["identity"]["knowledge"] = draw(st.sampled_from(["general", "technical", "creative", "analytical"]))
    
    return config


@st.composite
def invalid_personality_configs(draw):
    """Generate invalid personality configurations."""
    config = {"identity": {}}
    
    # Include at least one invalid field
    invalid_field = draw(st.sampled_from(["tone", "formality", "verbosity", "humor", "empathy"]))
    
    if invalid_field == "tone":
        config["identity"]["tone"] = draw(st.text(min_size=1, max_size=20).filter(lambda x: x.lower() not in ALLOWED_TONES))
    elif invalid_field == "formality":
        config["identity"]["formality"] = draw(st.text(min_size=1, max_size=20).filter(lambda x: x.lower() not in ALLOWED_FORMALITY))
    elif invalid_field == "verbosity":
        config["identity"]["verbosity"] = draw(st.text(min_size=1, max_size=20).filter(lambda x: x.lower() not in ALLOWED_VERBOSITY))
    elif invalid_field == "humor":
        config["identity"]["humor"] = draw(st.text(min_size=1, max_size=20).filter(lambda x: x.lower() not in ALLOWED_HUMOR))
    elif invalid_field == "empathy":
        config["identity"]["empathy"] = draw(st.text(min_size=1, max_size=20).filter(lambda x: x.lower() not in ALLOWED_EMPATHY))
    
    return config


@st.composite
def personality_updates(draw):
    """Generate personality profile updates."""
    updates = {}
    
    # Randomly include each field
    if draw(st.booleans()):
        updates["assistant_name"] = draw(st.text(min_size=1, max_size=50))
    
    if draw(st.booleans()):
        updates["tone"] = draw(st.sampled_from(list(ALLOWED_TONES)))
    
    if draw(st.booleans()):
        updates["formality"] = draw(st.sampled_from(list(ALLOWED_FORMALITY)))
    
    if draw(st.booleans()):
        updates["verbosity"] = draw(st.sampled_from(list(ALLOWED_VERBOSITY)))
    
    if draw(st.booleans()):
        updates["humor"] = draw(st.sampled_from(list(ALLOWED_HUMOR)))
    
    if draw(st.booleans()):
        updates["empathy"] = draw(st.sampled_from(list(ALLOWED_EMPATHY)))
    
    if draw(st.booleans()):
        updates["knowledge"] = draw(st.sampled_from(["general", "technical", "creative", "analytical"]))
    
    # Ensure at least one field is present
    if not updates:
        updates["tone"] = draw(st.sampled_from(list(ALLOWED_TONES)))
    
    return updates


# ============================================================================
# Property 34: Agent Personality Configuration
# Feature: irisvoice-backend-integration, Property 34: Agent Personality Configuration
# Validates: Requirements 13.1, 13.2, 13.3, 13.4
# ============================================================================

class TestAgentPersonalityConfiguration:
    """
    Property 34: Agent Personality Configuration
    
    For any change to agent.identity fields (assistant_name, personality, knowledge), 
    the Agent_Kernel shall apply the new configuration to subsequent messages.
    """
    
    def setup_method(self):
        """Reset singleton before each test"""
        PersonalityManager._instance = None
        PersonalityManager._initialized = False
    
    @settings(max_examples=10, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(config=valid_personality_configs())
    def test_valid_configuration_applies_successfully(self, config):
        """
        Property: For any valid personality configuration, the PersonalityManager 
        shall load and apply the configuration without errors.
        
        # Feature: irisvoice-backend-integration, Property 34: Agent Personality Configuration
        **Validates: Requirements 13.1, 13.2**
        """
        # Setup
        manager = PersonalityManager()
        
        # Execute: Load configuration
        manager.load_from_config(config)
        
        # Verify: Configuration was applied
        profile = manager.get_profile()
        identity = config.get("identity", {})
        
        # Check each field that was in the config
        for field, value in identity.items():
            if field in profile:
                # Values should match (case-insensitive for enum fields)
                if field in ["tone", "formality", "verbosity", "humor", "empathy", "knowledge"]:
                    assert profile[field] == value.lower(), \
                        f"Field '{field}' should be '{value.lower()}', got '{profile[field]}'"
                else:
                    assert profile[field] == value, \
                        f"Field '{field}' should be '{value}', got '{profile[field]}'"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(config=invalid_personality_configs())
    def test_invalid_configuration_raises_error(self, config):
        """
        Property: For any invalid personality configuration, the PersonalityManager 
        shall reject the configuration and raise a ValueError.
        
        # Feature: irisvoice-backend-integration, Property 34: Agent Personality Configuration
        **Validates: Requirements 13.4**
        """
        # Setup
        manager = PersonalityManager()
        
        # Execute & Verify: Should raise ValueError
        with pytest.raises(ValueError):
            manager.load_from_config(config)
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(updates=personality_updates())
    def test_configuration_updates_apply_to_system_prompt(self, updates):
        """
        Property: For any personality configuration update, the system prompt 
        shall reflect the new configuration.
        
        # Feature: irisvoice-backend-integration, Property 34: Agent Personality Configuration
        **Validates: Requirements 13.1, 13.3**
        """
        # Setup
        manager = PersonalityManager()
        
        # Get initial prompt
        initial_prompt = manager.get_system_prompt()
        
        # Execute: Update profile
        manager.update_profile(**updates)
        
        # Get updated prompt
        updated_prompt = manager.get_system_prompt()
        
        # Verify: Prompt changed if any meaningful field was updated
        meaningful_fields = ["assistant_name", "tone", "formality", "verbosity", "humor", "empathy", "knowledge"]
        if any(field in updates for field in meaningful_fields):
            assert updated_prompt != initial_prompt, \
                "System prompt should change when personality configuration is updated"
        
        # Verify: Updated values appear in the prompt
        if "assistant_name" in updates:
            assert updates["assistant_name"] in updated_prompt, \
                f"Assistant name '{updates['assistant_name']}' should appear in system prompt"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        config1=valid_personality_configs(),
        config2=valid_personality_configs()
    )
    def test_configuration_changes_are_idempotent(self, config1, config2):
        """
        Property: For any sequence of personality configuration changes, applying 
        the same configuration twice produces the same result.
        
        # Feature: irisvoice-backend-integration, Property 34: Agent Personality Configuration
        **Validates: Requirements 13.1, 13.2**
        """
        # Setup
        manager = PersonalityManager()
        
        # Execute: Apply config1, then config2, then config2 again
        manager.load_from_config(config1)
        manager.load_from_config(config2)
        profile_after_first = manager.get_profile()
        
        manager.load_from_config(config2)
        profile_after_second = manager.get_profile()
        
        # Verify: Profile should be identical after applying same config twice
        assert profile_after_first == profile_after_second, \
            "Applying the same configuration twice should produce identical results"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(config=valid_personality_configs())
    def test_partial_configuration_preserves_other_fields(self, config):
        """
        Property: For any partial personality configuration, fields not specified 
        in the configuration shall remain unchanged.
        
        # Feature: irisvoice-backend-integration, Property 34: Agent Personality Configuration
        **Validates: Requirements 13.1, 13.2**
        """
        # Setup
        manager = PersonalityManager()
        
        # Set initial configuration
        initial_config = {
            "identity": {
                "assistant_name": "InitialBot",
                "tone": "professional",
                "formality": "formal",
                "verbosity": "concise",
                "humor": "none",
                "empathy": "low",
                "knowledge": "technical"
            }
        }
        manager.load_from_config(initial_config)
        initial_profile = manager.get_profile()
        
        # Execute: Apply partial configuration
        manager.load_from_config(config)
        updated_profile = manager.get_profile()
        
        # Verify: Fields not in config should remain unchanged
        identity = config.get("identity", {})
        for field in ["assistant_name", "tone", "formality", "verbosity", "humor", "empathy", "knowledge"]:
            if field not in identity:
                assert updated_profile[field] == initial_profile[field], \
                    f"Field '{field}' not in config should remain unchanged"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        tone=st.sampled_from(list(ALLOWED_TONES)),
        formality=st.sampled_from(list(ALLOWED_FORMALITY)),
        verbosity=st.sampled_from(list(ALLOWED_VERBOSITY))
    )
    def test_personality_traits_affect_system_prompt(self, tone, formality, verbosity):
        """
        Property: For any combination of personality traits, the system prompt 
        shall include descriptions of those traits.
        
        # Feature: irisvoice-backend-integration, Property 34: Agent Personality Configuration
        **Validates: Requirements 13.2, 13.3**
        """
        # Setup
        manager = PersonalityManager()
        
        # Execute: Set personality traits
        manager.update_profile(tone=tone, formality=formality, verbosity=verbosity)
        
        # Get system prompt
        prompt = manager.get_system_prompt()
        
        # Verify: Prompt is not empty
        assert len(prompt) > 0, "System prompt should not be empty"
        
        # Verify: Prompt contains personality structure
        assert "Tone:" in prompt, "System prompt should include Tone section"
        assert "Formality:" in prompt, "System prompt should include Formality section"
        assert "Communication Style:" in prompt or "verbosity" in prompt.lower(), \
            "System prompt should include verbosity/communication style"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        assistant_name=st.text(min_size=1, max_size=50),
        tone=st.sampled_from(list(ALLOWED_TONES))
    )
    def test_assistant_name_changes_apply_immediately(self, assistant_name, tone):
        """
        Property: For any change to assistant_name, the PersonalityManager shall 
        use the new name in the system prompt immediately.
        
        # Feature: irisvoice-backend-integration, Property 34: Agent Personality Configuration
        **Validates: Requirements 13.1**
        """
        # Setup
        manager = PersonalityManager()
        
        # Execute: Update assistant name
        manager.update_profile(assistant_name=assistant_name, tone=tone)
        
        # Get system prompt
        prompt = manager.get_system_prompt()
        
        # Verify: New name appears in prompt
        assert assistant_name in prompt, \
            f"Assistant name '{assistant_name}' should appear in system prompt"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(config=valid_personality_configs())
    def test_configuration_validation_without_application(self, config):
        """
        Property: For any personality configuration, validation shall detect 
        errors without modifying the current configuration.
        
        # Feature: irisvoice-backend-integration, Property 34: Agent Personality Configuration
        **Validates: Requirements 13.4**
        """
        # Setup
        manager = PersonalityManager()
        
        # Set initial configuration
        initial_profile = manager.get_profile()
        
        # Execute: Validate configuration
        errors = manager.validate_personality_config(config)
        
        # Verify: Profile unchanged after validation
        current_profile = manager.get_profile()
        assert current_profile == initial_profile, \
            "Validation should not modify the current configuration"
        
        # Verify: Valid config has no errors
        assert len(errors) == 0, \
            f"Valid configuration should have no validation errors, got: {errors}"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(config=invalid_personality_configs())
    def test_validation_detects_invalid_configurations(self, config):
        """
        Property: For any invalid personality configuration, validation shall 
        return error messages for the invalid fields.
        
        # Feature: irisvoice-backend-integration, Property 34: Agent Personality Configuration
        **Validates: Requirements 13.4**
        """
        # Setup
        manager = PersonalityManager()
        
        # Execute: Validate configuration
        errors = manager.validate_personality_config(config)
        
        # Verify: Errors detected
        assert len(errors) > 0, \
            "Invalid configuration should produce validation errors"
        
        # Verify: Error messages are informative
        for field, error_msg in errors.items():
            assert len(error_msg) > 0, \
                f"Error message for field '{field}' should not be empty"
            assert "Invalid" in error_msg or "Allowed" in error_msg, \
                f"Error message should indicate what's wrong: {error_msg}"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        configs=st.lists(valid_personality_configs(), min_size=2, max_size=5)
    )
    def test_multiple_configuration_changes_maintain_consistency(self, configs):
        """
        Property: For any sequence of personality configuration changes, the 
        PersonalityManager shall maintain consistency throughout.
        
        # Feature: irisvoice-backend-integration, Property 34: Agent Personality Configuration
        **Validates: Requirements 13.3**
        """
        # Setup
        manager = PersonalityManager()
        
        # Execute: Apply multiple configurations
        for config in configs:
            manager.load_from_config(config)
            
            # Verify: Profile is always valid after each update
            profile = manager.get_profile()
            
            # Check all fields have valid values
            assert profile["tone"] in ALLOWED_TONES, \
                f"Tone should be valid after update: {profile['tone']}"
            assert profile["formality"] in ALLOWED_FORMALITY, \
                f"Formality should be valid after update: {profile['formality']}"
            assert profile["verbosity"] in ALLOWED_VERBOSITY, \
                f"Verbosity should be valid after update: {profile['verbosity']}"
            assert profile["humor"] in ALLOWED_HUMOR, \
                f"Humor should be valid after update: {profile['humor']}"
            assert profile["empathy"] in ALLOWED_EMPATHY, \
                f"Empathy should be valid after update: {profile['empathy']}"
            
            # Verify: System prompt can be generated
            prompt = manager.get_system_prompt()
            assert len(prompt) > 0, "System prompt should be generated after each update"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        tone=st.sampled_from(list(ALLOWED_TONES)),
        humor=st.sampled_from(list(ALLOWED_HUMOR)),
        empathy=st.sampled_from(list(ALLOWED_EMPATHY))
    )
    def test_personality_customization_is_flexible(self, tone, humor, empathy):
        """
        Property: For any valid combination of personality traits, the 
        PersonalityManager shall accept and apply the customization.
        
        # Feature: irisvoice-backend-integration, Property 34: Agent Personality Configuration
        **Validates: Requirements 13.4**
        """
        # Setup
        manager = PersonalityManager()
        
        # Execute: Apply customization
        manager.update_profile(tone=tone, humor=humor, empathy=empathy)
        
        # Verify: Customization applied
        profile = manager.get_profile()
        assert profile["tone"] == tone, f"Tone should be '{tone}'"
        assert profile["humor"] == humor, f"Humor should be '{humor}'"
        assert profile["empathy"] == empathy, f"Empathy should be '{empathy}'"
        
        # Verify: System prompt reflects customization
        prompt = manager.get_system_prompt()
        assert len(prompt) > 0, "System prompt should be generated with custom personality"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
