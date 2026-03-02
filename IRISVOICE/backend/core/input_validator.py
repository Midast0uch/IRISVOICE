"""
Input Validation & Sanitization Module

Provides JSON Schema-based validation and input sanitization for:
- Tool parameters
- WebSocket messages
- API inputs
- User-generated content

Uses jsonschema for validation and bleach for HTML sanitization.
"""

import re
import html
import json
import logging
from typing import Any, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

# Try to import jsonschema, fall back to basic validation if not available
try:
    from jsonschema import validate, ValidationError, Draft7Validator
    from jsonschema.exceptions import best_match
    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False
    logger.warning("jsonschema not available, using basic validation only")

# Try to import bleach for HTML sanitization
try:
    import bleach
    BLEACH_AVAILABLE = True
except ImportError:
    BLEACH_AVAILABLE = False
    logger.warning("bleach not available, using basic HTML escaping only")


class ValidationErrorType(Enum):
    """Types of validation errors."""
    REQUIRED = "required"
    TYPE = "type"
    FORMAT = "format"
    RANGE = "range"
    PATTERN = "pattern"
    ENUM = "enum"
    SANITIZATION = "sanitization"
    CUSTOM = "custom"


@dataclass
class ValidationError:
    """Structured validation error."""
    field: str
    error_type: ValidationErrorType
    message: str
    value: Any = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field,
            "error_type": self.error_type.value,
            "message": self.message,
            "value": str(self.value) if self.value is not None else None
        }


@dataclass
class ValidationResult:
    """Result of validation operation."""
    valid: bool
    errors: List[ValidationError]
    sanitized_data: Optional[Dict[str, Any]] = None
    
    @property
    def is_valid(self) -> bool:
        return self.valid and len(self.errors) == 0
    
    def get_error_messages(self) -> List[str]:
        return [e.message for e in self.errors]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.is_valid,
            "errors": [e.to_dict() for e in self.errors],
            "sanitized_data": self.sanitized_data
        }


class InputValidator:
    """
    JSON Schema-based input validator with sanitization.
    
    Features:
    - JSON Schema validation (Draft 7)
    - Type checking and coercion
    - String sanitization (HTML escaping, trimming)
    - Pattern validation (regex)
    - Range validation (min/max for numbers)
    - Enum validation
    - Custom validation rules
    """
    
    # Common regex patterns
    PATTERNS = {
        "email": r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$",
        "url": r"^https?://[^\s/$.?#].[^\s]*$",
        "filename": r"^[^<>:\"/\\|?*\x00-\x1f]+$",
        "uuid": r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        "alphanumeric": r"^[a-zA-Z0-9_]+$",
        "safe_text": r"^[\w\s\-.,:;!?()[\]'\"]+$",
    }
    
    # Default sanitization config
    DEFAULT_SANITIZE_CONFIG = {
        "strip_html": True,
        "escape_html": True,
        "trim_whitespace": True,
        "normalize_newlines": True,
        "max_length": None,
    }
    
    def __init__(self):
        self._validators: Dict[str, Draft7Validator] = {}
        self._custom_validators: Dict[str, callable] = {}
    
    def register_schema(self, name: str, schema: Dict[str, Any]) -> None:
        """
        Register a JSON Schema for validation.
        
        Args:
            name: Schema identifier
            schema: JSON Schema dict
        """
        if JSONSCHEMA_AVAILABLE:
            try:
                self._validators[name] = Draft7Validator(schema)
            except Exception as e:
                logger.error(f"Failed to register schema '{name}': {e}")
                raise
        else:
            # Store schema for basic validation
            self._validators[name] = schema
    
    def register_custom_validator(self, name: str, validator: callable) -> None:
        """
        Register a custom validation function.
        
        Args:
            name: Validator name
            validator: Function that takes (value, field_name) and returns (valid, error_msg)
        """
        self._custom_validators[name] = validator
    
    def validate(
        self,
        data: Dict[str, Any],
        schema_name: str,
        sanitize: bool = True,
        sanitize_config: Optional[Dict[str, Any]] = None
    ) -> ValidationResult:
        """
        Validate data against a registered schema.
        
        Args:
            data: Data to validate
            schema_name: Name of registered schema
            sanitize: Whether to sanitize string inputs
            sanitize_config: Custom sanitization config
            
        Returns:
            ValidationResult with validation status and errors
        """
        errors: List[ValidationError] = []
        sanitized_data = dict(data) if sanitize else None
        
        # Get schema
        schema = self._validators.get(schema_name)
        if not schema:
            logger.error(f"Schema '{schema_name}' not found")
            return ValidationResult(
                valid=False,
                errors=[ValidationError(
                    field="_schema",
                    error_type=ValidationErrorType.CUSTOM,
                    message=f"Schema '{schema_name}' not found"
                )],
                sanitized_data=None
            )
        
        # Sanitize first if requested
        if sanitize and JSONSCHEMA_AVAILABLE:
            sanitized_data = self._sanitize_data(
                data,
                schema.schema if hasattr(schema, 'schema') else schema,
                sanitize_config or self.DEFAULT_SANITIZE_CONFIG
            )
        elif sanitize:
            sanitized_data = self._basic_sanitize(data, sanitize_config or self.DEFAULT_SANITIZE_CONFIG)
        
        # Validate with jsonschema if available
        if JSONSCHEMA_AVAILABLE and isinstance(schema, Draft7Validator):
            validation_errors = list(schema.iter_errors(sanitized_data or data))
            for error in validation_errors:
                errors.append(self._convert_jsonschema_error(error))
        else:
            # Basic validation fallback
            errors = self._basic_validate(sanitized_data or data, schema)
        
        # Run custom validators
        for validator_name, validator in self._custom_validators.items():
            try:
                valid, error_msg = validator(sanitized_data or data, schema_name)
                if not valid:
                    errors.append(ValidationError(
                        field="_custom",
                        error_type=ValidationErrorType.CUSTOM,
                        message=f"{validator_name}: {error_msg}"
                    ))
            except Exception as e:
                logger.error(f"Custom validator '{validator_name}' failed: {e}")
        
        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            sanitized_data=sanitized_data if sanitize else None
        )
    
    def validate_field(
        self,
        value: Any,
        field_name: str,
        field_schema: Dict[str, Any],
        sanitize: bool = True
    ) -> ValidationResult:
        """
        Validate a single field against a schema.
        
        Args:
            value: Field value
            field_name: Field name
            field_schema: JSON Schema for this field
            sanitize: Whether to sanitize
            
        Returns:
            ValidationResult
        """
        data = {field_name: value}
        schema = {
            "type": "object",
            "properties": {field_name: field_schema},
            "required": [field_name]
        }
        
        # Create temporary validator
        if JSONSCHEMA_AVAILABLE:
            validator = Draft7Validator(schema)
            errors = list(validator.iter_errors(data))
            validation_errors = [self._convert_jsonschema_error(e) for e in errors]
        else:
            validation_errors = self._basic_validate(data, schema)
        
        # Sanitize if needed
        sanitized = None
        if sanitize and isinstance(value, str):
            sanitized = {field_name: self._sanitize_string(value)}
        
        return ValidationResult(
            valid=len(validation_errors) == 0,
            errors=validation_errors,
            sanitized_data=sanitized
        )
    
    def _sanitize_data(
        self,
        data: Dict[str, Any],
        schema: Dict[str, Any],
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Sanitize data according to schema and config."""
        sanitized = {}
        properties = schema.get("properties", {})
        
        for key, value in data.items():
            prop_schema = properties.get(key, {})
            
            if isinstance(value, str):
                sanitized[key] = self._sanitize_string(value, config, prop_schema)
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_data(value, prop_schema, config)
            elif isinstance(value, list):
                sanitized[key] = [
                    self._sanitize_string(item, config, prop_schema) if isinstance(item, str)
                    else item
                    for item in value
                ]
            else:
                sanitized[key] = value
        
        return sanitized
    
    def _sanitize_string(
        self,
        value: str,
        config: Dict[str, Any] = None,
        schema: Dict[str, Any] = None
    ) -> str:
        """Sanitize a string value."""
        config = config or self.DEFAULT_SANITIZE_CONFIG
        
        if not isinstance(value, str):
            return value
        
        result = value
        
        # Trim whitespace
        if config.get("trim_whitespace", True):
            result = result.strip()
        
        # Normalize newlines
        if config.get("normalize_newlines", True):
            result = result.replace("\r\n", "\n").replace("\r", "\n")
        
        # Strip HTML tags
        if config.get("strip_html", True):
            if BLEACH_AVAILABLE:
                # Allow only specific safe tags if needed
                allowed_tags = schema.get("x-allowed-html-tags", []) if schema else []
                allowed_attrs = schema.get("x-allowed-html-attrs", {}) if schema else {}
                result = bleach.clean(result, tags=allowed_tags, attributes=allowed_attrs, strip=True)
            else:
                # Basic HTML tag removal
                result = re.sub(r'<[^>]+>', '', result)
        
        # Escape HTML entities
        if config.get("escape_html", True) and not config.get("strip_html", True):
            result = html.escape(result)
        
        # Enforce max length
        max_length = config.get("max_length") or (schema.get("maxLength") if schema else None)
        if max_length and len(result) > max_length:
            result = result[:max_length]
        
        return result
    
    def _basic_sanitize(self, data: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        """Basic sanitization without jsonschema."""
        sanitized = {}
        for key, value in data.items():
            if isinstance(value, str):
                sanitized[key] = self._sanitize_string(value, config)
            elif isinstance(value, dict):
                sanitized[key] = self._basic_sanitize(value, config)
            else:
                sanitized[key] = value
        return sanitized
    
    def _basic_validate(
        self,
        data: Dict[str, Any],
        schema: Dict[str, Any]
    ) -> List[ValidationError]:
        """Basic validation without jsonschema library."""
        errors = []
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        
        # Check required fields
        for field in required:
            if field not in data or data[field] is None:
                errors.append(ValidationError(
                    field=field,
                    error_type=ValidationErrorType.REQUIRED,
                    message=f"Field '{field}' is required"
                ))
        
        # Validate field types
        for field, value in data.items():
            if field not in properties:
                continue
            
            prop_schema = properties[field]
            field_errors = self._validate_field_type(field, value, prop_schema)
            errors.extend(field_errors)
        
        return errors
    
    def _validate_field_type(
        self,
        field: str,
        value: Any,
        schema: Dict[str, Any]
    ) -> List[ValidationError]:
        """Validate a single field's type and constraints."""
        errors = []
        
        expected_type = schema.get("type")
        if not expected_type:
            return errors
        
        # Type checking
        type_valid = True
        if expected_type == "string" and not isinstance(value, str):
            type_valid = False
        elif expected_type == "integer" and not isinstance(value, int):
            type_valid = False
        elif expected_type == "number" and not isinstance(value, (int, float)):
            type_valid = False
        elif expected_type == "boolean" and not isinstance(value, bool):
            type_valid = False
        elif expected_type == "array" and not isinstance(value, list):
            type_valid = False
        elif expected_type == "object" and not isinstance(value, dict):
            type_valid = False
        
        if not type_valid:
            errors.append(ValidationError(
                field=field,
                error_type=ValidationErrorType.TYPE,
                message=f"Field '{field}' must be of type {expected_type}",
                value=value
            ))
            return errors
        
        # String validations
        if expected_type == "string" and isinstance(value, str):
            # Min/max length
            min_len = schema.get("minLength")
            max_len = schema.get("maxLength")
            
            if min_len is not None and len(value) < min_len:
                errors.append(ValidationError(
                    field=field,
                    error_type=ValidationErrorType.RANGE,
                    message=f"Field '{field}' must be at least {min_len} characters",
                    value=value
                ))
            
            if max_len is not None and len(value) > max_len:
                errors.append(ValidationError(
                    field=field,
                    error_type=ValidationErrorType.RANGE,
                    message=f"Field '{field}' must be at most {max_len} characters",
                    value=value
                ))
            
            # Pattern validation
            pattern = schema.get("pattern")
            if pattern and not re.match(pattern, value):
                errors.append(ValidationError(
                    field=field,
                    error_type=ValidationErrorType.PATTERN,
                    message=f"Field '{field}' does not match required pattern",
                    value=value
                ))
            
            # Enum validation
            enum_values = schema.get("enum")
            if enum_values and value not in enum_values:
                errors.append(ValidationError(
                    field=field,
                    error_type=ValidationErrorType.ENUM,
                    message=f"Field '{field}' must be one of {enum_values}",
                    value=value
                ))
            
            # Format validation (basic)
            format_type = schema.get("format")
            if format_type and format_type in self.PATTERNS:
                if not re.match(self.PATTERNS[format_type], value):
                    errors.append(ValidationError(
                        field=field,
                        error_type=ValidationErrorType.FORMAT,
                        message=f"Field '{field}' must be a valid {format_type}",
                        value=value
                    ))
        
        # Number validations
        if expected_type in ("integer", "number") and isinstance(value, (int, float)):
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            
            if minimum is not None and value < minimum:
                errors.append(ValidationError(
                    field=field,
                    error_type=ValidationErrorType.RANGE,
                    message=f"Field '{field}' must be at least {minimum}",
                    value=value
                ))
            
            if maximum is not None and value > maximum:
                errors.append(ValidationError(
                    field=field,
                    error_type=ValidationErrorType.RANGE,
                    message=f"Field '{field}' must be at most {maximum}",
                    value=value
                ))
        
        return errors
    
    def _convert_jsonschema_error(self, error) -> ValidationError:
        """Convert jsonschema ValidationError to our ValidationError."""
        field = ".".join(str(p) for p in error.path) if error.path else "_root"
        
        # Map jsonschema error types to our types
        validator = error.validator
        type_map = {
            "required": ValidationErrorType.REQUIRED,
            "type": ValidationErrorType.TYPE,
            "format": ValidationErrorType.FORMAT,
            "minimum": ValidationErrorType.RANGE,
            "maximum": ValidationErrorType.RANGE,
            "minLength": ValidationErrorType.RANGE,
            "maxLength": ValidationErrorType.RANGE,
            "pattern": ValidationErrorType.PATTERN,
            "enum": ValidationErrorType.ENUM,
        }
        
        error_type = type_map.get(validator, ValidationErrorType.CUSTOM)
        
        return ValidationError(
            field=field,
            error_type=error_type,
            message=error.message,
            value=error.instance
        )


# Global instance
_input_validator: Optional[InputValidator] = None


def get_input_validator() -> InputValidator:
    """Get or create the singleton InputValidator instance."""
    global _input_validator
    if _input_validator is None:
        _input_validator = InputValidator()
    return _input_validator


def reset_input_validator() -> None:
    """Reset the singleton (useful for testing)."""
    global _input_validator
    _input_validator = None
