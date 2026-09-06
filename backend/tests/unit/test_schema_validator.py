"""Unit tests for the 12-keyword schema allowlist (REQ-21, T3)."""

import pytest

from backend.vision.schema_validator import (
    ALLOWED_KEYWORDS,
    SchemaValidationError,
    is_supported_keyword,
    validate_schema,
    validate_schema_strict,
)


def test_allowlist_has_exactly_twelve_keywords():
    assert len(ALLOWED_KEYWORDS) == 12
    assert {"type", "properties", "required", "propertyOrdering"} <= ALLOWED_KEYWORDS


def test_valid_extraction_schema_passes():
    schema = {
        "type": "object",
        "properties": {
            "price": {"type": "number", "minimum": 0, "nullable": True},
            "sizes": {"type": "array", "items": {"type": "string"},
                      "minItems": 1, "maxItems": 10},
            "condition": {"type": "string", "enum": ["new", "refurbished"],
                          "format": "text"},
        },
        "required": ["price"],
        "propertyOrdering": ["price", "sizes", "condition"],
    }
    assert validate_schema(schema) == []
    assert validate_schema_strict(schema) is schema


@pytest.mark.parametrize("keyword", ["oneOf", "additionalProperties", "const", "allOf", "$ref"])
def test_explicitly_rejected_keywords_fail_with_400(keyword):
    """AC21.2: unsupported keywords are rejected before execution."""
    schema = {"type": "object", "properties": {"x": {"type": "string", keyword: 1}}}
    errors = validate_schema(schema)
    assert any(keyword in e for e in errors), errors
    with pytest.raises(SchemaValidationError) as exc_info:
        validate_schema_strict(schema)
    assert exc_info.value.status_code == 400
    assert not is_supported_keyword(keyword)


def test_nested_rejection_reports_location():
    errors = validate_schema({
        "type": "object",
        "properties": {"a": {"type": "object",
                             "properties": {"b": {"type": "string", "const": "x"}}}},
    })
    assert len(errors) == 1
    assert "properties.a.properties.b.const" in errors[0]


def test_top_level_must_be_object():
    errors = validate_schema({"type": "array", "items": {"type": "string"}})
    assert any("top-level" in e for e in errors)
    assert validate_schema("price") == ["output_schema must be an object, got str"]
    assert validate_schema(None) != []
