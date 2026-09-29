"""Regression (execution audit B15, 2026-09-29): the provider schema keeps the
constraints a model needs to form a valid call.

to_function_schema copied only type + description, so enums were lost and an
array parameter arrived with no `items` (strict providers reject that). Fails
on the old converter.
"""

from backend.agent.tool_registry import to_function_schema


def _props():
    schema = to_function_schema([{
        "name": "demo",
        "description": "d",
        "parameters": {
            "priority": {"type": "string", "enum": ["low", "high"], "description": "p"},
            "ids": {"type": "array", "description": "ids"},
            "tags": {"type": "array", "items": {"type": "integer"}, "description": "t"},
            "count": {"type": "integer", "minimum": 1, "maximum": 5, "optional": True},
        },
    }])
    return schema[0]["function"]["parameters"]


def test_enum_is_kept():
    assert _props()["properties"]["priority"]["enum"] == ["low", "high"]


def test_every_array_has_items():
    props = _props()["properties"]
    assert props["ids"]["items"] == {"type": "string"}
    assert props["tags"]["items"] == {"type": "integer"}


def test_bounds_and_optional_are_respected():
    params = _props()
    assert params["properties"]["count"]["minimum"] == 1
    assert params["properties"]["count"]["maximum"] == 5
    assert "count" not in params["required"]
