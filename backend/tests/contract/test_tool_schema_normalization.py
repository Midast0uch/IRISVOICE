"""Contract pin: tool definitions reach the provider as VALID JSON Schema.

MEASURED LIVE 2026-09-26. The bridge declares tools as
``parameters={"path": {"type": "string"}}`` — a property MAP, not a JSON
Schema. `_normalize_tools` passed it through, so every provider received a
`parameters` object with no ``"type": "object"`` and no ``"properties"``.
Lenient providers ignore the shape. Cohere validates the definitions and
rejects the whole request:

  422 HALLUCINATED_ALL_TOOL_CALLS   (tool_decision, twice)
  422 INVALID_TOOL_GENERATION       (source_registry topic extraction)

A tool call the model generates can never match a schema a validator cannot
read, so NO tool ever ran in a live turn — the blocker behind the missing
calibration rows. This file is the guard: it normalizes the REAL tool list and
asserts each definition is a schema a strict provider will accept.
"""

from __future__ import annotations

from backend.agent.inference.router import InferenceRouter


def _schema(params):
    return InferenceRouter._json_schema(params)


class TestTheFlatMapBecomesASchema:
    def test_a_property_map_is_wrapped(self):
        """The live defect, pinned: the property names must survive, and the
        result must declare an object with properties."""
        out = _schema({"path": {"type": "string"}})
        assert out["type"] == "object"
        assert out["properties"] == {"path": {"type": "string"}}

    def test_an_existing_schema_passes_through(self):
        """Idempotent: a real JSON Schema is not re-wrapped, or a second
        normalization pass would corrupt every tool."""
        already = {"type": "object", "properties": {"a": {"type": "string"}}}
        assert _schema(already) is already

    def test_empty_parameters_is_a_valid_empty_object(self):
        assert _schema(None) == {"type": "object", "properties": {}}
        assert _schema({}) == {"type": "object", "properties": {}}

    def test_an_explicit_required_marker_is_honoured(self):
        out = _schema({
            "path": {"type": "string", "optional": False},
            "limit": {"type": "integer"},
        })
        assert out["required"] == ["path"], (
            "a declared-required parameter must reach the provider, or the "
            "model is free to omit it"
        )

    def test_an_openai_shaped_tool_is_untouched(self):
        tool = {
            "type": "function",
            "function": {"name": "x", "description": "d",
                         "parameters": {"type": "object", "properties": {}}},
        }
        out = InferenceRouter._normalize_tools([tool])
        assert out == [tool], "an already-valid tool was rewritten"


class TestTheRealToolsAreValid:
    def test_every_shipped_tool_normalizes_to_a_valid_schema(self):
        """The guard that matters: the tools the app actually sends."""
        from backend.agent.tool_bridge import get_agent_tool_bridge

        tools = get_agent_tool_bridge().get_available_tools()
        assert tools, "no tools to check"

        normalized = InferenceRouter._normalize_tools(
            [dict(t) for t in tools]
        )
        assert normalized is not None

        for entry in normalized:
            fn = entry["function"]
            params = fn["parameters"]
            assert params.get("type") == "object", (
                f"{fn['name']}: provider got a schema with no object type — "
                "Cohere answers 422 for exactly this"
            )
            assert isinstance(params.get("properties"), dict), (
                f"{fn['name']}: provider got a schema with no properties map"
            )

    def test_the_property_names_survive_normalization(self):
        """A malformed wrap that dropped the properties would also pass the
        shape check above, so pin the CONTENT for every real tool."""
        from backend.agent.tool_bridge import get_agent_tool_bridge

        for raw in get_agent_tool_bridge().get_available_tools():
            declared = raw.get("parameters") or {}
            if not declared or "type" in declared:
                continue
            out = _schema(declared)["properties"]
            assert set(out) == set(declared), (
                f"{raw.get('name')}: parameters changed shape — "
                f"{set(declared)} -> {set(out)}"
            )
