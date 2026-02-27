"""
Unit tests for PersonalityManager
"""
import pytest
from backend.agent.personality import (
    PersonalityManager,
    PersonalityProfile,
    get_personality_manager,
    ALLOWED_TONES,
    ALLOWED_FORMALITY,
    ALLOWED_VERBOSITY,
    ALLOWED_HUMOR,
    ALLOWED_EMPATHY
)


class TestPersonalityProfile:
    """Test PersonalityProfile dataclass"""
    
    def test_default_values(self):
        """Test default personality profile values"""
        profile = PersonalityProfile()
        assert profile.assistant_name == "IRIS"
        assert profile.tone == "friendly"
        assert profile.formality == "neutral"
        assert profile.verbosity == "balanced"
        assert profile.humor == "subtle"
        assert profile.empathy == "moderate"
        assert profile.knowledge == "general"


class TestPersonalityManager:
    """Test PersonalityManager class"""
    
    def setup_method(self):
        """Reset singleton before each test"""
        PersonalityManager._instance = None
        PersonalityManager._initialized = False
    
    def test_singleton_pattern(self):
        """Test that PersonalityManager is a singleton"""
        manager1 = PersonalityManager()
        manager2 = PersonalityManager()
        assert manager1 is manager2
    
    def test_get_personality_manager(self):
        """Test get_personality_manager helper function"""
        manager = get_personality_manager()
        assert isinstance(manager, PersonalityManager)
    
    def test_initial_profile(self):
        """Test initial personality profile"""
        manager = PersonalityManager()
        profile = manager.get_profile()
        assert profile["assistant_name"] == "IRIS"
        assert profile["tone"] == "friendly"
        assert profile["formality"] == "neutral"
    
    def test_update_profile_valid(self):
        """Test updating profile with valid values"""
        manager = PersonalityManager()
        manager.update_profile(
            assistant_name="TestBot",
            tone="professional",
            formality="formal",
            verbosity="concise",
            humor="none",
            empathy="high"
        )
        
        profile = manager.get_profile()
        assert profile["assistant_name"] == "TestBot"
        assert profile["tone"] == "professional"
        assert profile["formality"] == "formal"
        assert profile["verbosity"] == "concise"
        assert profile["humor"] == "none"
        assert profile["empathy"] == "high"
    
    def test_update_profile_invalid_tone(self):
        """Test updating profile with invalid tone"""
        manager = PersonalityManager()
        with pytest.raises(ValueError, match="Invalid tone"):
            manager.update_profile(tone="invalid_tone")
    
    def test_update_profile_invalid_formality(self):
        """Test updating profile with invalid formality"""
        manager = PersonalityManager()
        with pytest.raises(ValueError, match="Invalid formality"):
            manager.update_profile(formality="invalid_formality")
    
    def test_update_profile_invalid_verbosity(self):
        """Test updating profile with invalid verbosity"""
        manager = PersonalityManager()
        with pytest.raises(ValueError, match="Invalid verbosity"):
            manager.update_profile(verbosity="invalid_verbosity")
    
    def test_update_profile_invalid_humor(self):
        """Test updating profile with invalid humor"""
        manager = PersonalityManager()
        with pytest.raises(ValueError, match="Invalid humor"):
            manager.update_profile(humor="invalid_humor")
    
    def test_update_profile_invalid_empathy(self):
        """Test updating profile with invalid empathy"""
        manager = PersonalityManager()
        with pytest.raises(ValueError, match="Invalid empathy"):
            manager.update_profile(empathy="invalid_empathy")
    
    def test_update_profile_unknown_attribute(self):
        """Test updating profile with unknown attribute"""
        manager = PersonalityManager()
        with pytest.raises(ValueError, match="Unknown personality attribute"):
            manager.update_profile(unknown_field="value")
    
    def test_load_from_config_valid(self):
        """Test loading configuration from agent.identity fields"""
        manager = PersonalityManager()
        config = {
            "identity": {
                "assistant_name": "CustomBot",
                "tone": "Professional",
                "formality": "Formal",
                "verbosity": "Detailed",
                "humor": "Moderate",
                "empathy": "High",
                "knowledge": "Technical"
            }
        }
        
        manager.load_from_config(config)
        profile = manager.get_profile()
        
        assert profile["assistant_name"] == "CustomBot"
        assert profile["tone"] == "professional"
        assert profile["formality"] == "formal"
        assert profile["verbosity"] == "detailed"
        assert profile["humor"] == "moderate"
        assert profile["empathy"] == "high"
        assert profile["knowledge"] == "technical"
    
    def test_load_from_config_partial(self):
        """Test loading partial configuration"""
        manager = PersonalityManager()
        config = {
            "identity": {
                "assistant_name": "PartialBot",
                "tone": "Casual"
            }
        }
        
        manager.load_from_config(config)
        profile = manager.get_profile()
        
        assert profile["assistant_name"] == "PartialBot"
        assert profile["tone"] == "casual"
        # Other fields should remain default
        assert profile["formality"] == "neutral"
        assert profile["verbosity"] == "balanced"
    
    def test_load_from_config_empty(self):
        """Test loading empty configuration"""
        manager = PersonalityManager()
        original_profile = manager.get_profile()
        
        config = {"identity": {}}
        manager.load_from_config(config)
        
        # Profile should remain unchanged
        assert manager.get_profile() == original_profile
    
    def test_load_from_config_invalid_tone(self):
        """Test loading configuration with invalid tone"""
        manager = PersonalityManager()
        config = {
            "identity": {
                "tone": "invalid_tone"
            }
        }
        
        with pytest.raises(ValueError, match="Invalid tone"):
            manager.load_from_config(config)
    
    def test_load_from_config_case_insensitive(self):
        """Test that configuration loading is case-insensitive"""
        manager = PersonalityManager()
        config = {
            "identity": {
                "tone": "PROFESSIONAL",
                "formality": "FORMAL",
                "verbosity": "CONCISE"
            }
        }
        
        manager.load_from_config(config)
        profile = manager.get_profile()
        
        assert profile["tone"] == "professional"
        assert profile["formality"] == "formal"
        assert profile["verbosity"] == "concise"
    
    def test_get_system_prompt_default(self):
        """Test system prompt generation with default settings"""
        manager = PersonalityManager()
        prompt = manager.get_system_prompt()
        
        assert "IRIS" in prompt
        assert "friendly" in prompt.lower() or "warm" in prompt.lower()
        assert "neutral" in prompt.lower() or "balance" in prompt.lower()
        assert "balanced" in prompt.lower() or "concise" in prompt.lower()
    
    def test_get_system_prompt_custom(self):
        """Test system prompt generation with custom settings"""
        manager = PersonalityManager()
        manager.update_profile(
            assistant_name="CustomBot",
            tone="professional",
            formality="formal",
            verbosity="concise",
            humor="none",
            empathy="low"
        )
        
        prompt = manager.get_system_prompt()
        
        assert "CustomBot" in prompt
        assert "professional" in prompt.lower()
        assert "formal" in prompt.lower()
        assert "concise" in prompt.lower() or "brief" in prompt.lower()
    
    def test_system_prompt_caching(self):
        """Test that system prompt is cached"""
        manager = PersonalityManager()
        prompt1 = manager.get_system_prompt()
        prompt2 = manager.get_system_prompt()
        
        # Should return same cached prompt
        assert prompt1 is prompt2
    
    def test_system_prompt_cache_invalidation(self):
        """Test that cache is invalidated on profile update"""
        manager = PersonalityManager()
        prompt1 = manager.get_system_prompt()
        
        manager.update_profile(tone="professional")
        prompt2 = manager.get_system_prompt()
        
        # Should generate new prompt
        assert prompt1 != prompt2
        assert "professional" in prompt2.lower()
    
    def test_validate_personality_config_valid(self):
        """Test validation of valid personality configuration"""
        manager = PersonalityManager()
        config = {
            "identity": {
                "tone": "professional",
                "formality": "formal",
                "verbosity": "concise",
                "humor": "none",
                "empathy": "moderate"
            }
        }
        
        errors = manager.validate_personality_config(config)
        assert len(errors) == 0
    
    def test_validate_personality_config_invalid(self):
        """Test validation of invalid personality configuration"""
        manager = PersonalityManager()
        config = {
            "identity": {
                "tone": "invalid_tone",
                "formality": "invalid_formality",
                "verbosity": "invalid_verbosity"
            }
        }
        
        errors = manager.validate_personality_config(config)
        assert "tone" in errors
        assert "formality" in errors
        assert "verbosity" in errors
    
    def test_validate_personality_config_partial_invalid(self):
        """Test validation with mix of valid and invalid values"""
        manager = PersonalityManager()
        config = {
            "identity": {
                "tone": "professional",  # valid
                "formality": "invalid_formality",  # invalid
                "verbosity": "concise"  # valid
            }
        }
        
        errors = manager.validate_personality_config(config)
        assert len(errors) == 1
        assert "formality" in errors
        assert "tone" not in errors
        assert "verbosity" not in errors
    
    def test_all_allowed_tones(self):
        """Test that all allowed tones can be set"""
        manager = PersonalityManager()
        for tone in ALLOWED_TONES:
            manager.update_profile(tone=tone)
            assert manager.get_profile()["tone"] == tone
    
    def test_all_allowed_formality(self):
        """Test that all allowed formality levels can be set"""
        manager = PersonalityManager()
        for formality in ALLOWED_FORMALITY:
            manager.update_profile(formality=formality)
            assert manager.get_profile()["formality"] == formality
    
    def test_all_allowed_verbosity(self):
        """Test that all allowed verbosity levels can be set"""
        manager = PersonalityManager()
        for verbosity in ALLOWED_VERBOSITY:
            manager.update_profile(verbosity=verbosity)
            assert manager.get_profile()["verbosity"] == verbosity
    
    def test_all_allowed_humor(self):
        """Test that all allowed humor levels can be set"""
        manager = PersonalityManager()
        for humor in ALLOWED_HUMOR:
            manager.update_profile(humor=humor)
            assert manager.get_profile()["humor"] == humor
    
    def test_all_allowed_empathy(self):
        """Test that all allowed empathy levels can be set"""
        manager = PersonalityManager()
        for empathy in ALLOWED_EMPATHY:
            manager.update_profile(empathy=empathy)
            assert manager.get_profile()["empathy"] == empathy
    
    def test_format_response(self):
        """Test response formatting (currently pass-through)"""
        manager = PersonalityManager()
        text = "This is a test response"
        formatted = manager.format_response(text)
        assert formatted == text


class TestBackwardCompatibility:
    """Test backward compatibility aliases"""
    
    def test_personality_engine_alias(self):
        """Test PersonalityEngine alias"""
        from backend.agent.personality import PersonalityEngine
        assert PersonalityEngine is PersonalityManager
    
    def test_get_personality_engine_alias(self):
        """Test get_personality_engine alias"""
        from backend.agent.personality import get_personality_engine
        manager = get_personality_engine()
        assert isinstance(manager, PersonalityManager)
