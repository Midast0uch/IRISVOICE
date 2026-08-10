"""
Type Safety Tests for Pydantic Models

Validates:
- Pydantic model instantiation and validation
- Type coercion and conversion
- Enum validation
- Model serialization/deserialization
- Tool execution with typed models
"""

import pytest
from datetime import datetime
from typing import Dict, Any

from backend.core.models import (
    ToolDefinition, ToolParameter, ToolRequest, ToolResponse,
    ToolCategory, VisionStatus, VoiceState, VoiceStatus,
    AgentStatus, WebSocketMessage, TextMessage, ThemeSettings,
    ValidationError, ValidationResult, SessionState,
    ExecutionContext, ErrorResponse,
    to_json_dict, from_json_dict, validate_tool_parameters
)


class TestToolModels:
    """Test Tool-related Pydantic models."""
    
    def test_tool_parameter_creation(self):
        """Test ToolParameter model creation."""
        param = ToolParameter(
            name="filename",
            type="string",
            description="The file to read",
            required=True,
            min_length=1,
            max_length=255
        )
        
        assert param.name == "filename"
        assert param.type == "string"
        assert param.required is True
        assert param.min_length == 1
    
    def test_tool_definition_creation(self):
        """Test ToolDefinition model creation."""
        tool = ToolDefinition(
            name="read_file",
            description="Read a file's contents",
            category=ToolCategory.FILE_MANAGEMENT,
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="File path",
                    required=True
                )
            ],
            required_params=["path"]
        )
        
        assert tool.name == "read_file"
        assert tool.category == ToolCategory.FILE_MANAGEMENT
        assert len(tool.parameters) == 1
        assert "path" in tool.required_params
    
    def test_tool_request_creation(self):
        """Test ToolRequest model creation."""
        request = ToolRequest(
            tool_name="read_file",
            parameters={"path": "/tmp/test.txt"},
            context={"session_id": "test123"},
            session_id="test123"
        )
        
        assert request.tool_name == "read_file"
        assert request.parameters["path"] == "/tmp/test.txt"
        assert isinstance(request.timestamp, datetime)
    
    def test_tool_response_creation(self):
        """Test ToolResponse model creation."""
        response = ToolResponse(
            success=True,
            tool_name="read_file",
            output="file contents here",
            execution_time_ms=150.5
        )
        
        assert response.success is True
        assert response.tool_name == "read_file"
        assert response.execution_time_ms == 150.5
        assert isinstance(response.timestamp, datetime)
    
    def test_tool_enum_validation(self):
        """Test that invalid tool categories are rejected."""
        with pytest.raises(ValueError):
            ToolDefinition(
                name="test",
                description="Test tool",
                category="invalid_category",  # Should be ToolCategory enum
                parameters=[]
            )


class TestVisionModels:
    """Test Vision-related Pydantic models."""
    
    def test_vision_status_creation(self):
        """Test VisionStatus model creation."""
        status = VisionStatus(
            status="enabled",
            vram_usage_mb=3584.5,
            model_name="minicpm-o4.5",
            is_available=True
        )
        
        assert status.status == "enabled"
        assert status.vram_usage_mb == 3584.5
        assert status.quantization_enabled is True  # Default
    
    def test_vision_status_invalid_status(self):
        """Test that invalid status values are rejected."""
        with pytest.raises(ValueError):
            VisionStatus(status="invalid_status")


class TestVoiceModels:
    """Test Voice-related Pydantic models."""
    
    def test_voice_status_creation(self):
        """Test VoiceStatus model creation."""
        status = VoiceStatus(
            state=VoiceState.LISTENING,
            audio_level=0.75,
            is_wake_word_active=True,
            current_wake_word="hey_iris"
        )
        
        assert status.state == VoiceState.LISTENING
        assert status.audio_level == 0.75
        assert status.is_wake_word_active is True
    
    def test_audio_level_validation(self):
        """Test that audio_level must be between 0 and 1."""
        # Valid values
        VoiceStatus(state=VoiceState.IDLE, audio_level=0.0)
        VoiceStatus(state=VoiceState.IDLE, audio_level=1.0)
        VoiceStatus(state=VoiceState.IDLE, audio_level=0.5)
        
        # Invalid values
        with pytest.raises(ValueError):
            VoiceStatus(state=VoiceState.IDLE, audio_level=1.5)
        
        with pytest.raises(ValueError):
            VoiceStatus(state=VoiceState.IDLE, audio_level=-0.1)


class TestAgentModels:
    """Test Agent-related Pydantic models."""
    
    def test_agent_status_creation(self):
        """Test AgentStatus model creation."""
        status = AgentStatus(
            initialized=True,
            active_skills=["file_manager", "browser"],
            available_tools=["read_file", "write_file"],
            conversation_length=42
        )
        
        assert status.initialized is True
        assert len(status.active_skills) == 2
        assert status.conversation_length == 42


class TestMessageModels:
    """Test Message-related Pydantic models."""
    
    def test_websocket_message_creation(self):
        """Test WebSocketMessage model creation."""
        msg = WebSocketMessage(
            type="text_message",
            payload={"text": "Hello"},
            session_id="test123"
        )
        
        assert msg.type == "text_message"
        assert msg.payload["text"] == "Hello"
        assert isinstance(msg.timestamp, datetime)
    
    def test_text_message_validation(self):
        """Test TextMessage validation."""
        # Valid message
        msg = TextMessage(text="Hello world", sender="user")
        assert msg.text == "Hello world"
        
        # Empty text should be rejected
        with pytest.raises(ValueError):
            TextMessage(text="", sender="user")
        
        with pytest.raises(ValueError):
            TextMessage(text="   ", sender="user")
    
    def test_text_message_whitespace_stripping(self):
        """Test that text is stripped of whitespace."""
        msg = TextMessage(text="  hello  ", sender="user")
        assert msg.text == "hello"


class TestThemeModels:
    """Test Theme-related Pydantic models."""
    
    def test_theme_settings_creation(self):
        """Test ThemeSettings model creation."""
        theme = ThemeSettings(
            primary="#00ff88",
            glow="#00ff88",
            font="#ffffff",
            listening_color="#ff0000"
        )
        
        assert theme.primary == "#00ff88"
        assert theme.listening_color == "#ff0000"
    
    def test_theme_color_validation(self):
        """Test that theme colors must be valid hex codes."""
        # Valid colors
        ThemeSettings(primary="#00ff88")
        ThemeSettings(primary="#00FF88")
        ThemeSettings(primary="#123456")
        
        # Invalid colors
        with pytest.raises(ValueError):
            ThemeSettings(primary="red")  # Not hex
        
        with pytest.raises(ValueError):
            ThemeSettings(primary="#00ff8")  # Too short
        
        with pytest.raises(ValueError):
            ThemeSettings(primary="#00ff888")  # Too long


class TestValidationModels:
    """Test Validation-related Pydantic models."""
    
    def test_validation_error_creation(self):
        """Test ValidationError model creation."""
        error = ValidationError(
            field="email",
            error_type="format",
            message="Invalid email format",
            value="not-an-email"
        )
        
        assert error.field == "email"
        assert error.error_type == "format"
    
    def test_validation_result_creation(self):
        """Test ValidationResult model creation."""
        result = ValidationResult(
            valid=False,
            errors=[
                ValidationError(
                    field="name",
                    error_type="required",
                    message="Name is required"
                )
            ]
        )
        
        assert result.is_valid is False
        assert len(result.errors) == 1
    
    def test_validation_result_valid(self):
        """Test ValidationResult with no errors."""
        result = ValidationResult(valid=True, errors=[])
        assert result.is_valid is True


class TestSessionModels:
    """Test Session-related Pydantic models."""
    
    def test_session_state_creation(self):
        """Test SessionState model creation."""
        state = SessionState(
            session_id="test123",
            category="file_management",
            section="read_file",
            field_values={
                "path": "/tmp/test.txt"
            }
        )
        
        assert state.session_id == "test123"
        assert state.category == "file_management"
        assert isinstance(state.created_at, datetime)


class TestExecutionContext:
    """Test ExecutionContext model."""
    
    def test_execution_context_creation(self):
        """Test ExecutionContext model creation."""
        context = ExecutionContext(
            session_id="test123",
            user_id="user456",
            source="voice",
            permissions=["read", "write"]
        )
        
        assert context.session_id == "test123"
        assert context.source == "voice"
        assert "read" in context.permissions
    
    def test_execution_context_invalid_source(self):
        """Test that invalid source values are rejected."""
        with pytest.raises(ValueError):
            ExecutionContext(source="invalid_source")


class TestSerialization:
    """Test model serialization and deserialization."""
    
    def test_to_json_dict(self):
        """Test to_json_dict utility function."""
        tool = ToolDefinition(
            name="test_tool",
            description="A test tool",
            category=ToolCategory.CUSTOM,
            parameters=[]
        )
        
        json_dict = to_json_dict(tool)
        
        assert json_dict["name"] == "test_tool"
        assert json_dict["category"] == "custom"
        assert "description" in json_dict
    
    def test_from_json_dict(self):
        """Test from_json_dict utility function."""
        data = {
            "name": "test_tool",
            "description": "A test tool",
            "category": "custom",
            "parameters": [],
            "required_params": []
        }
        
        tool = from_json_dict(data, ToolDefinition)
        
        assert tool.name == "test_tool"
        assert tool.category == ToolCategory.CUSTOM
    
    def test_round_trip_serialization(self):
        """Test round-trip serialization (to_dict -> from_dict)."""
        original = ToolRequest(
            tool_name="read_file",
            parameters={"path": "/tmp/test.txt"},
            session_id="test123"
        )
        
        json_dict = to_json_dict(original)
        restored = from_json_dict(json_dict, ToolRequest)
        
        assert restored.tool_name == original.tool_name
        assert restored.parameters == original.parameters
        assert restored.session_id == original.session_id


class TestToolParameterValidation:
    """Test validate_tool_parameters function."""
    
    def test_validate_required_parameters(self):
        """Test validation of required parameters."""
        tool_def = ToolDefinition(
            name="test_tool",
            description="Test tool",
            category=ToolCategory.CUSTOM,
            parameters=[
                ToolParameter(name="required_param", type="string", description="Required", required=True),
                ToolParameter(name="optional_param", type="string", description="Optional", required=False)
            ],
            required_params=["required_param"]
        )
        
        # Valid - has required param
        result = validate_tool_parameters(
            {"required_param": "value"},
            tool_def
        )
        assert result.is_valid is True
        
        # Invalid - missing required param
        result = validate_tool_parameters(
            {"optional_param": "value"},
            tool_def
        )
        assert result.is_valid is False
        assert any(e.field == "required_param" for e in result.errors)
    
    def test_validate_type_parameters(self):
        """Test validation of parameter types."""
        tool_def = ToolDefinition(
            name="test_tool",
            description="Test tool",
            category=ToolCategory.CUSTOM,
            parameters=[
                ToolParameter(name="count", type="integer", description="Count"),
                ToolParameter(name="name", type="string", description="Name")
            ]
        )
        
        # Valid types
        result = validate_tool_parameters(
            {"count": 42, "name": "test"},
            tool_def
        )
        assert result.is_valid is True
        
        # Invalid types
        result = validate_tool_parameters(
            {"count": "not an integer", "name": 123},
            tool_def
        )
        assert result.is_valid is False
        assert len(result.errors) == 2
    
    def test_validate_range_parameters(self):
        """Test validation of parameter ranges."""
        tool_def = ToolDefinition(
            name="test_tool",
            description="Test tool",
            category=ToolCategory.CUSTOM,
            parameters=[
                ToolParameter(
                    name="age",
                    type="integer",
                    description="Age",
                    minimum=0,
                    maximum=150
                ),
                ToolParameter(
                    name="username",
                    type="string",
                    description="Username",
                    min_length=3,
                    max_length=20
                )
            ]
        )
        
        # Valid ranges
        result = validate_tool_parameters(
            {"age": 25, "username": "john_doe"},
            tool_def
        )
        assert result.is_valid is True
        
        # Invalid ranges
        result = validate_tool_parameters(
            {"age": 200, "username": "ab"},
            tool_def
        )
        assert result.is_valid is False
        assert len(result.errors) == 2
    
    def test_validate_enum_parameters(self):
        """Test validation of enum parameters."""
        tool_def = ToolDefinition(
            name="test_tool",
            description="Test tool",
            category=ToolCategory.CUSTOM,
            parameters=[
                ToolParameter(
                    name="color",
                    type="string",
                    description="Color",
                    enum=["red", "green", "blue"]
                )
            ]
        )
        
        # Valid enum value
        result = validate_tool_parameters({"color": "red"}, tool_def)
        assert result.is_valid is True
        
        # Invalid enum value
        result = validate_tool_parameters({"color": "yellow"}, tool_def)
        assert result.is_valid is False


class TestModelValidationEdgeCases:
    """Test edge cases and validation boundaries."""
    
    def test_empty_strings_rejected(self):
        """Test that empty strings are rejected where appropriate."""
        with pytest.raises(ValueError):
            ToolDefinition(
                name="",
                description="Test",
                category=ToolCategory.CUSTOM,
                parameters=[]
            )
    
    def test_nested_model_validation(self):
        """Test validation of nested models."""
        session = SessionState(
            session_id="test",
            theme=ThemeSettings(
                primary="#00ff88",
                glow="#00ff88",
                font="#ffffff"
            )
        )
        
        assert session.theme.primary == "#00ff88"
    
    def test_datetime_auto_generation(self):
        """Test that datetime fields are auto-generated."""
        msg1 = WebSocketMessage(type="test")
        msg2 = WebSocketMessage(type="test")
        
        # Both should have timestamps
        assert isinstance(msg1.timestamp, datetime)
        assert isinstance(msg2.timestamp, datetime)
        
        # Timestamps should be different (or at least not identical)
        assert msg1.timestamp <= msg2.timestamp


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
