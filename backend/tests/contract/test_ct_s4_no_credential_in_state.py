"""Contract test CT-S4 (specs/phase-5-switcher/design.md).

"`/api/inference/state`: No credential or fragment anywhere in the payload
(REQ-2 AC8)."

Drives the REAL `ProviderInstance.to_dict()` — the serializer `/api/inference/
state` uses to build each provider entry — with a provider that HAS a real
key attached, and asserts the emitted dict can never leak it: only the
`has_key` boolean crosses the boundary (D-4).
"""

from __future__ import annotations

from backend.agent.inference.provider import ProviderInstance, ProviderKind


REAL_LOOKING_KEY = "FAKETESTCRED-live-abcdef0123456789ABCDEF0123"


class TestCTS4NoCredentialInProviderPayload:
    def test_to_dict_never_includes_the_raw_key(self):
        inst = ProviderInstance(
            id="cerebras",
            label="Cerebras",
            kind=ProviderKind.API,
            model="gemma-4-31b",
            api_base_url="https://api.cerebras.ai/v1",
            api_key=REAL_LOOKING_KEY,
        )
        payload = inst.to_dict()

        assert REAL_LOOKING_KEY not in str(payload.values()), (
            "the raw API key leaked into the serialized provider payload"
        )
        assert "api_key" not in payload, "api_key field must never be serialized"

    def test_to_dict_never_includes_a_masked_or_partial_fragment(self):
        """Not just the full key — no truncated/masked form either (D-4:
        'A masked key is still a fragment leaving the backend')."""
        inst = ProviderInstance(
            id="cerebras",
            label="Cerebras",
            kind=ProviderKind.API,
            model="gemma-4-31b",
            api_key=REAL_LOOKING_KEY,
        )
        payload = inst.to_dict()
        serialized = str(payload)
        # Neither the raw key nor any 6+ char substring of it should appear
        # (catches "sk-live-abcd...6789"-style masking, not just the exact key).
        for start in range(0, len(REAL_LOOKING_KEY) - 6, 6):
            fragment = REAL_LOOKING_KEY[start : start + 6]
            assert fragment not in serialized, (
                f"a key fragment ({fragment!r}) leaked into the provider payload"
            )

    def test_availability_crosses_the_boundary_as_a_boolean_only(self):
        inst = ProviderInstance(
            id="cerebras",
            label="Cerebras",
            kind=ProviderKind.API,
            model="gemma-4-31b",
            api_key=REAL_LOOKING_KEY,
        )
        payload = inst.to_dict()
        assert payload["has_key"] is True
        assert isinstance(payload["has_key"], bool)

    def test_no_key_configured_reports_has_key_false(self, monkeypatch):
        # to_dict() falls back to the OS keyring for a legacy-persisted key
        # when api_key is empty (provider.py:66-70) — isolate from whatever
        # secrets happen to be configured on the machine running this test
        # so the assertion is deterministic, not environment-dependent.
        monkeypatch.setattr(
            "backend.agent.inference.keyring.get_secret", lambda provider_id: None
        )
        inst = ProviderInstance(
            id="openai", label="OpenAI", kind=ProviderKind.API, model="gpt-4",
        )
        payload = inst.to_dict()
        assert payload["has_key"] is False
