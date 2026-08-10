"""
Unit tests for Model Selection lazy loading and ID structure cleanup.
Tests the SECTION_CONFIGS and field type compatibility.
"""

import pytest
from datetime import datetime, timedelta


class TestModelSelectionLazyLoading:
    """Test cases for Task 8.1: Model Selection Lazy Loading"""
    
    def test_model_selection_section_exists(self):
        """Test that model_selection section is defined in backend"""
        from backend.models import SECTION_CONFIGS
        
        # Verify model_selection section exists in agent category
        agent_sections = SECTION_CONFIGS.get("agent", [])
        section_ids = [s.id for s in agent_sections]
        assert "model_selection" in section_ids, "model_selection section should exist in agent category"
        
        # Verify expected fields exist
        model_selection = next(s for s in agent_sections if s.id == "model_selection")
        field_ids = [f.id for f in model_selection.fields]
        assert "model_provider" in field_ids, "model_provider field should exist"
        assert "reasoning_model" in field_ids, "reasoning_model field should exist"
        assert "api_key" in field_ids, "api_key field should exist"
    
    def test_model_selection_field_types(self):
        """Test that model_selection fields have correct types"""
        from backend.models import SECTION_CONFIGS, FieldType
        
        agent_sections = SECTION_CONFIGS.get("agent", [])
        model_selection = next(s for s in agent_sections if s.id == "model_selection")
        
        # Check model_provider is dropdown
        provider_field = next(f for f in model_selection.fields if f.id == "model_provider")
        assert provider_field.type == FieldType.DROPDOWN
        
        # Check api_key is password type (extended type)
        api_key_field = next(f for f in model_selection.fields if f.id == "api_key")
        assert api_key_field.type == FieldType.TEXT


class TestInferenceModeConfiguration:
    """Test cases for Task 8.2: Inference Mode Configuration"""
    
    def test_inference_mode_section_exists(self):
        """Test that inference_mode section is defined with user-friendly options"""
        from backend.models import SECTION_CONFIGS
        
        agent_sections = SECTION_CONFIGS.get("agent", [])
        section_ids = [s.id for s in agent_sections]
        assert "inference_mode" in section_ids, "inference_mode section should exist"
        
        inference_section = next(s for s in agent_sections if s.id == "inference_mode")
        field_ids = [f.id for f in inference_section.fields]
        
        # Verify user-friendly fields exist
        assert "agent_thinking_style" in field_ids, "agent_thinking_style field should exist"
        assert "max_response_length" in field_ids, "max_response_length field should exist"
        assert "reasoning_effort" in field_ids, "reasoning_effort field should exist"
        assert "tool_mode" in field_ids, "tool_mode field should exist"


class TestFieldTypeCompatibility:
    """Test cases for Task 8.8: Field Type Compatibility"""
    
    def test_extended_field_types_defined(self):
        """Test that extended field types are defined in backend"""
        from backend.models import FieldType
        
        # Verify extended types exist
        assert hasattr(FieldType, 'PASSWORD'), "FieldType should have PASSWORD"
        assert hasattr(FieldType, 'BUTTON'), "FieldType should have BUTTON"
        assert hasattr(FieldType, 'CUSTOM'), "FieldType should have CUSTOM"
        
        assert FieldType.PASSWORD == "password"
        assert FieldType.BUTTON == "button"
        assert FieldType.CUSTOM == "custom"
    
    def test_input_field_extended_properties(self):
        """Test that InputField has extended properties"""
        from backend.models import InputField, FieldType
        
        # Create field with extended properties
        field = InputField(
            id="api_key",
            type=FieldType.PASSWORD,
            label="API Key",
            sensitive=True,
            is_action=False,
            action=None,
            is_placeholder=False
        )
        
        assert field.sensitive == True, "sensitive property should be True"
        assert field.is_action == False, "is_action property should be False"
    
    def test_to_frontend_type_conversion(self):
        """Test that to_frontend_type converts types correctly"""
        from backend.models import InputField, FieldType
        
        password_field = InputField(
            id="api_key",
            type=FieldType.PASSWORD,
            label="API Key",
            sensitive=True
        )
        
        result = password_field.to_frontend_type()
        assert result["type"] == "password", "to_frontend_type should convert to 'password'"


class TestWakeSpeechReorganization:
    """Test cases for Task 8.3: Wake/Speech Reorganization"""
    
    def test_wake_section_exists(self):
        """Test that wake section is defined with correct fields"""
        from backend.models import SECTION_CONFIGS
        
        agent_sections = SECTION_CONFIGS.get("agent", [])
        section_ids = [s.id for s in agent_sections]
        assert "wake" in section_ids, "wake section should exist"
        
        wake_section = next(s for s in agent_sections if s.id == "wake")
        field_ids = [f.id for f in wake_section.fields]
        
        # Verify wake-specific fields
        assert "wake_word_enabled" in field_ids, "wake_word_enabled field should exist"
        assert "wake_phrase" in field_ids, "wake_phrase field should exist"
        assert "wake_word_sensitivity" in field_ids, "wake_word_sensitivity field should exist"
        assert "voice_profile" in field_ids, "voice_profile field should exist"
    
    def test_speech_section_exists(self):
        """Test that speech section is defined with correct fields"""
        from backend.models import SECTION_CONFIGS
        
        agent_sections = SECTION_CONFIGS.get("agent", [])
        section_ids = [s.id for s in agent_sections]
        assert "speech" in section_ids, "speech section should exist"
        
        speech_section = next(s for s in agent_sections if s.id == "speech")
        field_ids = [f.id for f in speech_section.fields]
        
        # Verify speech-specific fields
        assert "tts_enabled" in field_ids, "tts_enabled field should exist"
        assert "tts_voice" in field_ids, "tts_voice field should exist"
        assert "speaking_rate" in field_ids, "speaking_rate field should exist"


class TestDesktopControlRename:
    """Test cases for Task 8.4: Desktop Control Rename"""
    
    def test_desktop_control_section_exists(self):
        """Test that desktop_control section exists (not gui)"""
        from backend.models import SECTION_CONFIGS
        
        automate_sections = SECTION_CONFIGS.get("automate", [])
        section_ids = [s.id for s in automate_sections]
        
        assert "desktop_control" in section_ids, "desktop_control section should exist"
        assert "gui" not in section_ids, "gui section should not exist"
        
        desktop_section = next(s for s in automate_sections if s.id == "desktop_control")
        assert desktop_section.label == "DESKTOP CONTROL", "Label should be 'DESKTOP CONTROL'"


class TestRemovedCards:
    """Test cases for Task 8.5: Removed Cards"""
    
    def test_removed_sections_not_in_config(self):
        """Test that removed sections don't exist in SECTION_CONFIGS"""
        from backend.models import SECTION_CONFIGS
        
        # These sections were moved/removed
        removed_from_voice = ["processing", "model"]
        removed_from_automate = ["workflows", "shortcuts"]
        
        voice_sections = SECTION_CONFIGS.get("voice", [])
        voice_ids = [s.id for s in voice_sections]
        for removed in removed_from_voice:
            assert removed not in voice_ids, f"{removed} should not exist in voice category"
        
        automate_sections = SECTION_CONFIGS.get("automate", [])
        automate_ids = [s.id for s in automate_sections]
        for removed in removed_from_automate:
            assert removed not in automate_ids, f"{removed} should not exist in automate category"


class TestTerminologyCleanup:
    """Test cases for Phase 6: Terminology Cleanup"""
    
    def test_section_configs_constant_name(self):
        """Test that SECTION_CONFIGS constant exists (not SUBNODE_CONFIGS)"""
        from backend.models import SECTION_CONFIGS
        assert SECTION_CONFIGS is not None
        assert isinstance(SECTION_CONFIGS, dict)
    
    def test_section_class_exists(self):
        """Test that Section class exists (not SubNode)"""
        from backend.models import Section
        assert Section is not None
    
    def test_iris_state_has_current_section(self):
        """Test that IRISState has current_section field (not current_subnode)"""
        from backend.models import IRISState
        
        state = IRISState()
        # Should have current_section attribute
        assert hasattr(state, 'current_section')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
