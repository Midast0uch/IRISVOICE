"""Contract: tool schemas sent to ANY provider must be valid JSON Schema.

Observed live 2026-08-16, Brain+Tool both bound to Cohere::

    [TOOL_DECISION_FAIL] API returned 422: invalid type: parameter
    'tools.function.parameters.description' is of type object but should be of
    type string

The routing was correct — the request reached Cohere with the right binding.
What Cohere rejected was the SHAPE of the tool definitions.

IRIS's internal descriptor puts parameters in a bare property map::

    {"name": "vision_detect_element",
     "parameters": {"description": {"type": "string", ...}}}

``description`` is a RESERVED STRING field of a JSON Schema object, so passing
that map through as ``parameters`` puts an object where a string is required.
OpenAI-compatible endpoints tolerate it; Cohere validates and refuses.

This is the failure mode a model-agnostic product cannot ship: a payload that is
valid only for the provider it was developed against. The contract is that
conversion happens for every provider, on every path, with one converter.
"""

from __future__ import annotations

import pytest

from backend.agent.tool_registry import to_function_schema

# The reserved JSON Schema keys that a bare property map can collide with.
_RESERVED_STRING_FIELDS = ("description",)
_RESERVED_KEYS = ("type", "required", "properties", "description")


def _assert_valid_function_schema(entry: dict) -> None:
    assert entry.get("type") == "function"
    fn = entry["function"]
    assert isinstance(fn.get("name"), str) and fn["name"]
    assert isinstance(fn.get("description"), str), (
        "function.description must be a string"
    )
    params = fn["parameters"]
    assert params.get("type") == "object", "parameters must be a JSON Schema object"
    assert isinstance(params.get("properties"), dict)
    assert isinstance(params.get("required"), list)
    for field in _RESERVED_STRING_FIELDS:
        if field in params:
            assert isinstance(params[field], str), (
                f"parameters.{field} must be a STRING — an object here is the "
                f"exact shape Cohere 422s on"
            )
    for pname, pspec in params["properties"].items():
        assert isinstance(pspec, dict), f"property {pname!r} must be a schema object"
        assert isinstance(pspec.get("type"), str)
        assert isinstance(pspec.get("description"), str)


class TestToolSchemaIsProviderAgnostic:
    def test_a_property_named_description_does_not_collide(self):
        """The exact tool that broke it: a property literally named 'description'.

        It must land under `properties`, never at the schema's top level.
        """
        internal = [{
            "name": "vision_detect_element",
            "description": "Detect a GUI element in a screenshot by description",
            "parameters": {
                "description": {"type": "string", "description": "Element to find"}
            },
            "category": "vision",
        }]
        out = to_function_schema(internal)
        assert len(out) == 1
        _assert_valid_function_schema(out[0])

        params = out[0]["function"]["parameters"]
        assert "description" in params["properties"], (
            "the 'description' PROPERTY was lost"
        )
        assert params["properties"]["description"]["description"] == "Element to find"
        assert "description" not in params or isinstance(params["description"], str)
        assert params["required"] == ["description"]

    @pytest.mark.parametrize("reserved", _RESERVED_KEYS)
    def test_every_reserved_key_survives_as_a_property(self, reserved):
        """`type`, `required`, `properties` and `description` are all reserved
        JSON Schema keys. A tool parameter may legitimately be named any of
        them, and none may leak to the schema's top level."""
        internal = [{
            "name": "collide",
            "description": "d",
            "parameters": {reserved: {"type": "string", "description": "x"}},
        }]
        params = to_function_schema(internal)[0]["function"]["parameters"]
        assert params["type"] == "object", (
            f"a parameter named {reserved!r} overwrote parameters.type"
        )
        assert reserved in params["properties"]
        assert isinstance(params["properties"][reserved], dict)

    def test_optional_parameters_are_not_required(self):
        internal = [{
            "name": "t", "description": "d",
            "parameters": {
                "a": {"type": "string", "description": "req"},
                "b": {"type": "string", "description": "opt", "optional": True},
            },
        }]
        params = to_function_schema(internal)[0]["function"]["parameters"]
        assert params["required"] == ["a"]
        assert set(params["properties"]) == {"a", "b"}

    def test_a_tool_with_no_parameters_still_emits_a_valid_object(self):
        out = to_function_schema([
            {"name": "vision_analyze_screen", "description": "d", "parameters": {}}
        ])
        _assert_valid_function_schema(out[0])
        assert out[0]["function"]["parameters"]["properties"] == {}
        assert out[0]["function"]["parameters"]["required"] == []

    def test_the_whole_live_registry_converts_to_valid_schema(self):
        """Every tool IRIS actually exposes must be sendable to a strict
        provider. This is the test that would have caught the Cohere break
        without a live API call."""
        # Read the registry as-is. Calling register_builtin_tools() here would
        # mutate the module-global _REGISTRY and break
        # test_tool_registry.py::test_register_tool_is_idempotent, which counts
        # entries — the builtins are already registered at import.
        from backend.agent.tool_registry import get_registry_tools

        tools = get_registry_tools()
        if not tools:
            pytest.skip("tool registry empty in this configuration")
        for entry in to_function_schema(tools):
            _assert_valid_function_schema(entry)

    def test_raw_internal_descriptors_would_have_been_rejected(self):
        """Guard the premise: the UNCONVERTED shape really is invalid.

        If this ever stops holding, the internal format changed and the
        converter's reason for existing should be re-examined rather than
        assumed.
        """
        raw = {
            "name": "vision_detect_element",
            "parameters": {
                "description": {"type": "string", "description": "Element to find"}
            },
        }
        params = raw["parameters"]
        assert not isinstance(params.get("description"), str), (
            "the raw internal descriptor no longer collides — re-check whether "
            "conversion is still required"
        )
