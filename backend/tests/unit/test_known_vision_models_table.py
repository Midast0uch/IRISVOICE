"""Tests for `AgentKernel._KNOWN_VISION_MODELS` (specs/unified-vision-routing
T2, REQ-1 AC2), exercised through the REAL production resolver.

This table is DATA ONLY — the resolution logic lives in
`backend.agent.inference.router.supports_vision()` (T5). These tests pin the
table's SHAPE and CONTENT, and exercise the (provider_id, model_substring)
matching RULE — case-insensitive substring, first match wins, mirroring
`_KNOWN_CONTEXT_WINDOWS` — by calling `supports_vision()` against a minimal
`ProviderInstance(kind=API)` built from each (provider, model) pair. T5
repointed this file at production code and deleted the test-local
`_lookup()` helper that used to re-implement the matching rule itself.
"""

from __future__ import annotations

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.router import supports_vision


def _lookup(provider: str, model: str) -> bool:
    """Drive the real `supports_vision()` resolver for an API instance.

    An empty `model` cannot be represented on a real `ProviderInstance`
    (its `.model` field is `Optional[str]`, and `supports_vision` treats
    falsy/whitespace-only model strings as "no model" — same as the table's
    own `not model` guard), so an empty/whitespace string is passed through
    unchanged and still exercises that guard.
    """
    inst = ProviderInstance(
        id=provider, label=provider, kind=ProviderKind.API, model=model,
    )
    return supports_vision(inst)


class TestKnownVisionModelsTableShape:
    def test_table_exists_as_a_list_of_two_tuples(self):
        table = AgentKernel._KNOWN_VISION_MODELS
        assert isinstance(table, list)
        assert len(table) > 0
        for row in table:
            assert isinstance(row, tuple)
            assert len(row) == 2, f"row {row} is not (provider_id, model_substring)"
            provider, substring = row
            assert isinstance(provider, str) and provider
            assert isinstance(substring, str) and substring

    def test_no_duplicate_rows(self):
        table = AgentKernel._KNOWN_VISION_MODELS
        assert len(table) == len(set(table)), "duplicate (provider, substring) row"

    def test_table_is_a_class_level_constant_not_mutated_by_instances(self):
        """No shared mutable state across sessions (CLAUDE.md quality check):
        the table is defined once on the class and must not be an instance
        attribute that a session could accidentally mutate at runtime."""
        assert "_KNOWN_VISION_MODELS" in AgentKernel.__dict__
        assert isinstance(AgentKernel.__dict__["_KNOWN_VISION_MODELS"], list)


class TestKnownVisionModelsTableContent:
    """REQ-1 AC2 names GPT-4o, Claude, and Gemini families explicitly."""

    @pytest.mark.parametrize(
        "provider,model",
        [
            ("openai", "gpt-4o"),
            ("openai", "gpt-4o-2024-11-20"),
            ("openai", "gpt-4o-mini"),
            ("anthropic", "claude-3-5-sonnet-20241022"),
            ("anthropic", "claude-opus-5"),
            ("anthropic", "claude-sonnet-5"),
            ("anthropic", "claude-haiku-4-5-20251001"),
            ("gemini", "gemini-2.0-flash-001"),
        ],
    )
    def test_known_multimodal_model_is_present(self, provider, model):
        assert _lookup(provider, model) is True, (
            f"{provider}/{model} expected to match _KNOWN_VISION_MODELS "
            f"(substring version suffixes must still hit)"
        )

    @pytest.mark.parametrize(
        "provider,model",
        [
            ("openai", "gpt-3.5-turbo"),
            ("openai", "o1-mini"),
            ("cerebras", "gemma-4-31b"),
            ("cohere", "command-r-plus"),
            ("deepseek", "deepseek-chat"),
            ("unknown-provider", "gpt-4o"),  # right model, wrong provider
            ("openai", ""),
        ],
    )
    def test_unknown_or_text_only_model_is_absent(self, provider, model):
        assert _lookup(provider, model) is False

    def test_provider_match_is_exact_not_substring(self):
        """A provider id must match exactly — 'open' must not match 'openai'
        the way model substrings match within a model id."""
        assert _lookup("open", "gpt-4o") is False

    def test_lookup_never_raises_on_empty_or_odd_input(self):
        """REQ-1 AC5: unknown input yields False, never a raise."""
        assert _lookup("", "") is False
        assert _lookup("openai", "   ") is False
