"""Unit tests: vision target fast path (REQ-10, T13).

AC10.1  a click/tap/press goal with a quoted target (or "the X button") fills
        the element target in 0ms with ZERO LLM tokens.
AC10.2  no pattern match → the LLM resolution runs unchanged (this layer
        returns None and the caller keeps its existing path).
Edge    an empty or >120-char target is NOT a fast path.
"""

from __future__ import annotations

from backend.agent.decision_engine import DecisionEngine, EngineConfig

TOOL = "vision_detect_element"
SCHEMA = {"properties": {"description": {"type": "string"}}}


def _engine() -> DecisionEngine:
    """No backend needed: fast_path_args is pure (no model, no I/O)."""
    return DecisionEngine(config=EngineConfig())


class TestRegexTargetZeroTokens:
    def test_regex_target_zero_tokens(self):
        """AC10.1: every documented pattern fills the target directly."""
        cases = [
            ('click "Submit Order"', "Submit Order", "quoted_target"),
            ("tap 'Save As'", "Save As", "quoted_target"),
            ('press "OK"', "OK", "quoted_target"),
            ("click the Login button", "Login", "the_x_button"),
            ("press the Save As button", "Save As", "the_x_button"),
            ("Click “Agree”", "Agree", "quoted_target"),
        ]
        for goal, expected, pattern in cases:
            ar = _engine().fast_path_args(TOOL, SCHEMA, {"goal": goal})
            assert ar is not None, f"no fast path for {goal!r}"
            assert ar.args == {"description": expected}, goal
            assert ar.fast_path == pattern, goal
            assert ar.retried is False

    def test_fast_path_never_reaches_the_llm(self):
        """AC10.1: '0 LLM tokens' — the generation path is never entered."""
        engine = _engine()

        def _boom(*a, **kw):
            raise AssertionError(
                "generate_args was reached on a matched target — that is the "
                "LLM call AC10.1 removes"
            )

        engine.generate_args = _boom  # type: ignore[method-assign]
        ar = engine.fast_path_args(TOOL, SCHEMA, {"goal": 'click "Deploy"'})
        assert ar is not None and ar.args == {"description": "Deploy"}


class TestFallbackOnNoMatch:
    def test_fallback_on_no_match(self):
        """AC10.2: anything not matching returns None, so the caller's existing
        LLM resolution is untouched."""
        no_match = [
            "click the thing over there",     # no quotes, no "... button"
            "read the readme file",           # not a click verb
            'click ""',                       # edge: empty quoted target
            'click "' + "x" * 130 + '"',      # edge: > 120 chars
            "",                               # edge: empty goal
        ]
        for goal in no_match:
            assert _engine().fast_path_args(TOOL, SCHEMA, {"goal": goal}) is None, goal

    def test_fallback_when_the_schema_lacks_the_target_param(self):
        """The fast path never fabricates a parameter the schema does not
        declare — an unknown shape goes to the LLM path."""
        other = {"properties": {"element": {"type": "string"}}}
        assert _engine().fast_path_args(
            TOOL, other, {"goal": 'click "Deploy"'}) is None

    def test_fast_path_does_not_leak_into_other_tools(self):
        """The vision pattern must not fill args for a different tool."""
        assert _engine().fast_path_args(
            "read_file", SCHEMA, {"goal": 'click "Deploy"'}) is None
