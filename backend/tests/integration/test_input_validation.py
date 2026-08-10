"""
Tests for Input Validation & Sanitization

Validates:
- JSON Schema validation with jsonschema
- Basic validation fallback (when jsonschema unavailable)
- String sanitization (HTML stripping, escaping, trimming)
- Custom validators
- Tool parameter validation integration
"""

import pytest
from typing import Dict, Any

from backend.core.input_validator import (
    InputValidator,
    ValidationResult,
    ValidationError,
    ValidationErrorType,
    get_input_validator,
    reset_input_validator
)


class TestInputValidator:
    """Test suite for InputValidator."""
    
    @pytest.fixture(autouse=True)
    def reset_validator(self):
        """Reset singleton before each test."""
        reset_input_validator()
        yield
        reset_input_validator()
    
    def test_register_and_validate_schema(self):
        """Test registering a schema and validating against it."""
        validator = InputValidator()
        
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 100},
                "age": {"type": "integer", "minimum": 0, "maximum": 150},
                "email": {"type": "string", "format": "email"}
            },
            "required": ["name", "age"]
        }
        
        validator.register_schema("person", schema)
        
        # Valid data
        result = validator.validate(
            {"name": "John", "age": 30, "email": "john@example.com"},
            "person"
        )
        assert result.is_valid
        
        # Missing required field
        result = validator.validate({"name": "John"}, "person")
        assert not result.is_valid
        assert any(e.error_type == ValidationErrorType.REQUIRED for e in result.errors)
    
    def test_string_sanitization(self):
        """Test string sanitization (HTML stripping, trimming)."""
        validator = InputValidator()
        
        schema = {
            "type": "object",
            "properties": {
                "text": {"type": "string"}
            }
        }
        
        validator.register_schema("text_test", schema)
        
        # Test HTML stripping
        result = validator.validate(
            {"text": "<script>alert('xss')</script>Hello"},
            "text_test",
            sanitize=True
        )
        assert result.is_valid
        assert "<script>" not in result.sanitized_data["text"]
        assert "alert" not in result.sanitized_data["text"]
        
        # Test trimming
        result = validator.validate(
            {"text": "  hello world  "},
            "text_test",
            sanitize=True
        )
        assert result.sanitized_data["text"] == "hello world"
    
    def test_type_validation(self):
        """Test type validation for various types."""
        validator = InputValidator()
        
        schema = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "price": {"type": "number"},
                "active": {"type": "boolean"},
                "tags": {"type": "array"},
                "metadata": {"type": "object"}
            }
        }
        
        validator.register_schema("types", schema)
        
        # Valid types
        result = validator.validate({
            "count": 42,
            "price": 19.99,
            "active": True,
            "tags": ["a", "b"],
            "metadata": {"key": "value"}
        }, "types")
        assert result.is_valid
        
        # Invalid types
        result = validator.validate({
            "count": "not an integer",
            "price": "not a number",
            "active": "not a boolean"
        }, "types")
        assert not result.is_valid
        type_errors = [e for e in result.errors if e.error_type == ValidationErrorType.TYPE]
        assert len(type_errors) >= 3
    
    def test_range_validation(self):
        """Test min/max range validation for numbers and strings."""
        validator = InputValidator()
        
        schema = {
            "type": "object",
            "properties": {
                "age": {"type": "integer", "minimum": 0, "maximum": 120},
                "username": {"type": "string", "minLength": 3, "maxLength": 20}
            }
        }
        
        validator.register_schema("ranges", schema)
        
        # Valid ranges
        result = validator.validate({"age": 25, "username": "john_doe"}, "ranges")
        assert result.is_valid
        
        # Invalid ranges
        result = validator.validate({"age": 150, "username": "ab"}, "ranges")
        assert not result.is_valid
        range_errors = [e for e in result.errors if e.error_type == ValidationErrorType.RANGE]
        assert len(range_errors) == 2
    
    def test_pattern_validation(self):
        """Test regex pattern validation."""
        validator = InputValidator()
        
        schema = {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "pattern": r"^\d{3}-\d{3}-\d{4}$"},
                "code": {"type": "string", "pattern": "^[A-Z]{3}$"}
            }
        }
        
        validator.register_schema("patterns", schema)
        
        # Valid patterns
        result = validator.validate({"phone": "123-456-7890", "code": "ABC"}, "patterns")
        assert result.is_valid
        
        # Invalid patterns
        result = validator.validate({"phone": "1234567890", "code": "abc"}, "patterns")
        assert not result.is_valid
        pattern_errors = [e for e in result.errors if e.error_type == ValidationErrorType.PATTERN]
        assert len(pattern_errors) == 2
    
    def test_enum_validation(self):
        """Test enum validation."""
        validator = InputValidator()
        
        schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["active", "inactive", "pending"]},
                "priority": {"type": "integer", "enum": [1, 2, 3]}
            }
        }
        
        validator.register_schema("enums", schema)
        
        # Valid enums
        result = validator.validate({"status": "active", "priority": 1}, "enums")
        assert result.is_valid
        
        # Invalid enums
        result = validator.validate({"status": "unknown", "priority": 5}, "enums")
        assert not result.is_valid
        enum_errors = [e for e in result.errors if e.error_type == ValidationErrorType.ENUM]
        assert len(enum_errors) == 2
    
    def test_nested_object_validation(self):
        """Test validation of nested objects."""
        validator = InputValidator()
        
        schema = {
            "type": "object",
            "properties": {
                "user": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "address": {
                            "type": "object",
                            "properties": {
                                "city": {"type": "string"},
                                "zip": {"type": "string", "pattern": "^\\d{5}$"}
                            },
                            "required": ["city", "zip"]
                        }
                    },
                    "required": ["name", "address"]
                }
            },
            "required": ["user"]
        }
        
        validator.register_schema("nested", schema)
        
        # Valid nested data
        result = validator.validate({
            "user": {
                "name": "John",
                "address": {"city": "NYC", "zip": "10001"}
            }
        }, "nested")
        assert result.is_valid
        
        # Invalid nested data
        result = validator.validate({
            "user": {
                "name": "John",
                "address": {"city": "NYC", "zip": "invalid"}
            }
        }, "nested")
        assert not result.is_valid
    
    def test_array_validation(self):
        """Test array validation."""
        validator = InputValidator()
        
        schema = {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "maxItems": 10
                }
            }
        }
        
        validator.register_schema("arrays", schema)
        
        # Valid array
        result = validator.validate({"tags": ["a", "b", "c"]}, "arrays")
        assert result.is_valid
        
        # Empty array (too few items)
        result = validator.validate({"tags": []}, "arrays")
        assert not result.is_valid
    
    def test_custom_validator(self):
        """Test custom validation function."""
        validator = InputValidator()
        
        def validate_even(data: Dict, schema_name: str):
            if "number" in data and data["number"] % 2 != 0:
                return False, "Number must be even"
            return True, None
        
        validator.register_custom_validator("even_check", validate_even)
        
        schema = {
            "type": "object",
            "properties": {
                "number": {"type": "integer"}
            }
        }
        
        validator.register_schema("even", schema)
        
        # Valid (even number)
        result = validator.validate({"number": 4}, "even")
        assert result.is_valid
        
        # Invalid (odd number)
        result = validator.validate({"number": 3}, "even")
        assert not result.is_valid
        assert any("even" in e.message.lower() for e in result.errors)
    
    def test_sanitize_without_validation(self):
        """Test sanitization without schema validation."""
        validator = InputValidator()
        
        data = {
            "name": "  <b>John</b>  ",
            "description": "<script>alert('xss')</script>Hello"
        }
        
        result = validator._basic_sanitize(data, validator.DEFAULT_SANITIZE_CONFIG)
        
        assert result["name"] == "John"
        assert "<script>" not in result["description"]
    
    def test_validation_result_helpers(self):
        """Test ValidationResult helper methods."""
        # Valid result
        result = ValidationResult(
            valid=True,
            errors=[],
            sanitized_data={"key": "value"}
        )
        assert result.is_valid
        assert result.get_error_messages() == []
        
        # Invalid result
        result = ValidationResult(
            valid=False,
            errors=[
                ValidationError("field1", ValidationErrorType.REQUIRED, "Required"),
                ValidationError("field2", ValidationErrorType.TYPE, "Wrong type")
            ],
            sanitized_data=None
        )
        assert not result.is_valid
        assert len(result.get_error_messages()) == 2
    
    def test_unknown_schema(self):
        """Test validation against unknown schema."""
        validator = InputValidator()
        
        result = validator.validate({"key": "value"}, "unknown_schema")
        
        assert not result.is_valid
        assert any("unknown_schema" in e.message for e in result.errors)


class TestToolParameterValidation:
    """Test validation in ToolExecutor context."""
    
    @pytest.fixture
    def tool_executor(self):
        """Create a ToolExecutor with registered tools."""
        from backend.agent.tool_executor import ToolExecutor, ToolCategory
        
        executor = ToolExecutor()
        
        # Register a test tool with JSON Schema
        executor.register_tool(
            name="test_tool",
            description="A test tool",
            category=ToolCategory.CUSTOM,
            parameters={
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 255,
                        "pattern": "^[\\w\\-\\.]+$"
                    },
                    "content": {
                        "type": "string",
                        "maxLength": 10000
                    },
                    "overwrite": {
                        "type": "boolean"
                    }
                }
            },
            required_params=["filename"],
            handler=lambda params, ctx: {"success": True}
        )
        
        return executor
    
    def test_tool_validation_success(self, tool_executor):
        """Test successful tool parameter validation."""
        valid, error, sanitized = tool_executor.validate_parameters(
            "test_tool",
            {"filename": "test.txt", "content": "Hello", "overwrite": True}
        )
        
        assert valid
        assert error is None
        assert sanitized is not None
    
    def test_tool_validation_missing_required(self, tool_executor):
        """Test validation with missing required parameter."""
        valid, error, sanitized = tool_executor.validate_parameters(
            "test_tool",
            {"content": "Hello"}  # Missing filename
        )
        
        assert not valid
        assert "filename" in error.lower()
    
    def test_tool_validation_invalid_pattern(self, tool_executor):
        """Test validation with invalid filename pattern."""
        valid, error, sanitized = tool_executor.validate_parameters(
            "test_tool",
            {"filename": "../../../etc/passwd"}  # Path traversal attempt
        )
        
        assert not valid
        # Should fail pattern validation
        assert "pattern" in error.lower() or "filename" in error.lower()
    
    def test_tool_validation_sanitization(self, tool_executor):
        """Test that tool parameters are sanitized."""
        valid, error, sanitized = tool_executor.validate_parameters(
            "test_tool",
            {"filename": "  test.txt  ", "content": "<script>alert('xss')</script>Hello"}
        )
        
        assert valid
        assert sanitized["filename"] == "test.txt"  # Trimmed
        assert "<script>" not in sanitized["content"]  # HTML stripped
    
    def test_tool_execution_with_validation(self, tool_executor):
        """Test full tool execution with validation."""
        import asyncio
        
        result = asyncio.run(tool_executor.execute(
            "test_tool",
            {"filename": "  test.txt  ", "content": "Hello World"}
        ))
        
        assert result.success


class TestSingleton:
    """Test singleton behavior."""
    
    def test_singleton_instance(self):
        """Test that get_input_validator returns the same instance."""
        validator1 = get_input_validator()
        validator2 = get_input_validator()
        
        assert validator1 is validator2
    
    def test_reset_singleton(self):
        """Test that reset creates a new instance."""
        validator1 = get_input_validator()
        reset_input_validator()
        validator2 = get_input_validator()
        
        assert validator1 is not validator2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
