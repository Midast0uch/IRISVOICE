"""Contract (item-4, 2026-09-24): a tool that needs an argument cannot be called
without it.

Live evidence (two turns, prompt "read the file ...does_not_exist_42.txt and then
summarize what it contains"): the escalation named `ask_user_question` with NO
arguments. `validate_tool_call` passed it (it checked existence only), the call
was dispatched, and the handler refused it:

    [TOOL_DISPATCH] failure tool=ask_user_question error_type=invalid_params
                    error='Question text is required'

The step then failed and the DER grafted twice more.

The fix is enforcement only where a spec declares it: `ToolSpec.required` lists
the names a tool cannot run without, and `validate_tool_call` refuses a call that
omits one. A spec that lists nothing keeps the old behaviour exactly, so no
existing tool is newly rejected.
"""

from __future__ import annotations

from backend.agent.tool_registry import ToolSpec, resolve_tool, validate_tool_call


class TestTheDeclaration:
    def test_the_field_defaults_to_empty(self):
        spec = ToolSpec(name="x", description="y")
        assert spec.required == []

    def test_ask_user_question_requires_its_question(self):
        spec = resolve_tool("ask_user_question")
        assert spec is not None
        assert "text" in spec.required, (
            "the handler requires `text`; the spec must say so"
        )


class TestTheEnforcement:
    def test_empty_args_are_refused(self):
        ok, err = validate_tool_call("ask_user_question", {})
        assert ok is False
        assert "text" in err

    def test_blank_text_is_refused(self):
        ok, _err = validate_tool_call("ask_user_question", {"text": ""})
        assert ok is False

    def test_a_real_question_passes(self):
        ok, err = validate_tool_call(
            "ask_user_question", {"text": "Which folder should I use?"}
        )
        assert ok is True
        assert err == ""

    def test_optional_parameters_are_not_required(self):
        ok, _err = validate_tool_call(
            "ask_user_question",
            {"text": "Which one?", "options": ["a", "b"]},
        )
        assert ok is True


class TestNoBlastRadius:
    def test_a_spec_without_a_declaration_is_unchanged(self):
        spec = resolve_tool("read_file")
        assert spec is not None
        assert not getattr(spec, "required", [])
        ok, _err = validate_tool_call("read_file", {})
        assert ok is True, (
            "only a spec that declares required names may be refused for a "
            "missing argument"
        )

    def test_an_unknown_tool_is_still_refused(self):
        ok, err = validate_tool_call("no_such_tool_xyz", {})
        assert ok is False
        assert "not found" in err

    def test_non_dict_params_are_still_refused(self):
        ok, err = validate_tool_call("ask_user_question", ["text"])
        assert ok is False
        assert "dict" in err
