"""Strict JSON-schema allowlist validator (vision-goal-directed-search REQ-21, T3).

Only 12 keywords are permitted anywhere in an ``output_schema``:
type, properties, required, items, enum, format, minItems, maxItems,
minimum, maximum, nullable, propertyOrdering.

Anything else (oneOf, additionalProperties, const, allOf, $ref, ...) is
rejected with a descriptive error BEFORE tool execution (AC21.2), so
extraction output needs no post-hoc parsing (AC21.1). Top-level schema
must be an object.

Stdlib only. No backend imports (this module must stay import-light:
it runs on the validation hot path before every extraction).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

ALLOWED_KEYWORDS = frozenset({
    "type",
    "properties",
    "required",
    "items",
    "enum",
    "format",
    "minItems",
    "maxItems",
    "minimum",
    "maximum",
    "nullable",
    "propertyOrdering",
})

# Unsupported keywords called out explicitly in AC21.2 (non-exhaustive:
# anything outside ALLOWED_KEYWORDS is rejected).
_EXPLICITLY_REJECTED = ("oneOf", "additionalProperties", "const", "allOf", "$ref")


class SchemaValidationError(ValueError):
    """Raised when an output_schema violates the allowlist (HTTP 400 semantics)."""

    status_code = 400

    def __init__(self, errors: List[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def _walk(node: Any, path: str, errors: List[str]) -> None:
    """Recursively reject non-allowlisted keywords; $path tracks location.

    `properties` maps field-NAME -> subschema: field names are data, not
    keywords, so only each field's subschema is walked.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            where = f"{path}.{key}" if path else key
            if key not in ALLOWED_KEYWORDS:
                errors.append(
                    f"unsupported keyword {key!r} at {where or 'root'}: "
                    f"allowed keywords are {sorted(ALLOWED_KEYWORDS)}"
                )
                continue
            if key == "properties" and isinstance(value, dict):
                for field_name, subschema in value.items():
                    _walk(subschema, f"{where}.{field_name}", errors)
            elif key == "items":
                _walk(value, where, errors)
        return
    if isinstance(node, list):
        for i, value in enumerate(node):
            _walk(value, f"{path}[{i}]", errors)


def validate_schema(schema: Any) -> List[str]:
    """Return a list of descriptive violations (empty == valid).

    Never raises: use the return value for reporting, or validate_schema_strict
    to fail fast with SchemaValidationError.
    """
    errors: List[str] = []
    if not isinstance(schema, dict):
        return [f"output_schema must be an object, got {type(schema).__name__}"]
    if schema.get("type", "object") != "object":
        errors.append(
            f"top-level output_schema type must be 'object', "
            f"got {schema.get('type')!r}"
        )
    _walk(schema, "", errors)
    return errors


def validate_schema_strict(schema: Any) -> Dict[str, Any]:
    """Validate and return the schema, or raise SchemaValidationError (AC21.2)."""
    errors = validate_schema(schema)
    if errors:
        raise SchemaValidationError(errors)
    assert isinstance(schema, dict)  # narrowed by validate_schema
    return schema


def is_supported_keyword(keyword: str) -> bool:
    """True when a single keyword is in the 12-keyword allowlist."""
    return keyword in ALLOWED_KEYWORDS


def rejected_keyword_names() -> Tuple[str, ...]:
    """The explicitly-rejected keywords named by AC21.2 (documentation aid)."""
    return _EXPLICITLY_REJECTED
