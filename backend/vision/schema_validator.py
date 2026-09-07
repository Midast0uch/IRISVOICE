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


def validate_instance(payload: Any, schema: Any) -> List[str]:
    """Validate an extracted payload against an allowlisted output_schema.

    Covers exactly the 12 allowlist keywords (REQ-25 AC25.1, T38). Unknown
    payload keys are IGNORED here — strict projection drops them upstream
    (der_loop.StepFindingsAccumulator.add keeps goal fields only), so this
    checker judges declared fields only. ``propertyOrdering`` is schema-level
    display metadata with no instance semantics — accepted, never constrains.
    Never raises: returns violation strings (empty == valid). Stdlib only.
    """
    errors: List[str] = []
    _check_instance(payload, schema, "root", errors)
    return errors


def _check_instance(value: Any, schema: Any, path: str, errors: List[str]) -> None:
    """Recursive instance check; ``$path`` tracks location like _walk."""
    if not isinstance(schema, dict):
        return  # schema already validated upstream; nothing to check against
    if value is None:
        if schema.get("nullable") is True:
            return
        errors.append(f"{path}: null value but schema is not nullable")
        return
    _type = schema.get("type")
    if _type is not None:
        if not _matches_type(value, _type):
            errors.append(
                f"{path}: expected type {_type!r}, got {type(value).__name__}"
            )
            return  # wrong-typed: deeper keywords cannot meaningfully apply
    if "enum" in schema and isinstance(schema["enum"], list):
        if value not in schema["enum"]:
            errors.append(f"{path}: {value!r} not in enum {schema['enum']!r}")
    if "format" in schema and not isinstance(value, str):
        errors.append(f"{path}: format {schema['format']!r} requires a string")
    if isinstance(value, dict):
        _props = schema.get("properties")
        if isinstance(_props, dict):
            for field_name, subschema in _props.items():
                if field_name in value:
                    _check_instance(value[field_name], subschema,
                                    f"{path}.{field_name}", errors)
        for req in schema.get("required") or []:
            if req not in value:
                errors.append(f"{path}: required field {req!r} is missing")
    if isinstance(value, list):
        _items = schema.get("items")
        if _items is not None:
            for i, element in enumerate(value):
                _check_instance(element, _items, f"{path}[{i}]", errors)
        _min_items = schema.get("minItems")
        if isinstance(_min_items, int) and len(value) < _min_items:
            errors.append(
                f"{path}: {len(value)} items < minItems {_min_items}"
            )
        _max_items = schema.get("maxItems")
        if isinstance(_max_items, int) and len(value) > _max_items:
            errors.append(
                f"{path}: {len(value)} items > maxItems {_max_items}"
            )
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        _minimum = schema.get("minimum")
        if isinstance(_minimum, (int, float)) and value < _minimum:
            errors.append(f"{path}: {value!r} < minimum {_minimum!r}")
        _maximum = schema.get("maximum")
        if isinstance(_maximum, (int, float)) and value > _maximum:
            errors.append(f"{path}: {value!r} > maximum {_maximum!r}")


def _matches_type(value: Any, type_name: Any) -> bool:
    """JSON-schema type test with Python gotchas handled (bool is not a number)."""
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "integer":
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        return isinstance(value, float) and value.is_integer()
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "null":
        return value is None
    return True  # unknown type name: schema validated upstream; stay lenient


def rejected_keyword_names() -> Tuple[str, ...]:
    """The explicitly-rejected keywords named by AC21.2 (documentation aid)."""
    return _EXPLICITLY_REJECTED
