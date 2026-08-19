"""Unit tests for `_resolve_effective_key` — the credential-resolution seam
in `set_model_selection`.

Root cause (2026-08-15): the kernel's `_api_key` is a SINGLE shared field
holding the last applied key regardless of provider. `set_model_selection`
used it as a blanket fallback when no new key was supplied, so switching
providers (e.g. Cerebras -> Cohere) attached the previous provider's key to
the new provider's instance. The registry then reported the wrong key as
valid and every call 401'd even though the keyring held the correct value.

The invariant: **a credential is only meaningful next to the provider it was
chosen for.** A provider switch without a fresh key must yield NO key, never
the previous provider's.
"""

from backend.agent.agent_kernel import _resolve_effective_key


class TestResolveEffectiveKey:
    def test_fresh_key_wins(self):
        assert (
            _resolve_effective_key(
                api_key="fresh-key",
                kernel_key="old-key",
                kernel_key_provider="cerebras",
                model_provider="cohere",
            )
            == "fresh-key"
        )

    def test_kernel_key_reused_only_for_same_provider(self):
        # Kernel key belongs to cohere and we're configuring cohere -> reuse.
        assert (
            _resolve_effective_key(
                api_key=None,
                kernel_key="cohere-key",
                kernel_key_provider="cohere",
                model_provider="cohere",
            )
            == "cohere-key"
        )

    def test_kernel_key_never_crosses_providers(self):
        # Kernel key belongs to cerebras but we're configuring cohere -> the
        # Cerebras key must NOT leak into the cohere instance.
        assert (
            _resolve_effective_key(
                api_key=None,
                kernel_key="cerebras-key",
                kernel_key_provider="cerebras",
                model_provider="cohere",
            )
            == ""
        )

    def test_no_key_no_provider_tracking_yields_empty(self):
        # Kernel key exists but its owning provider is unknown -> cannot prove
        # it belongs to the target provider -> do not reuse.
        assert (
            _resolve_effective_key(
                api_key=None,
                kernel_key="some-key",
                kernel_key_provider="",
                model_provider="cohere",
            )
            == ""
        )

    def test_empty_everything_yields_empty(self):
        assert (
            _resolve_effective_key(
                api_key=None,
                kernel_key="",
                kernel_key_provider="",
                model_provider="cohere",
            )
            == ""
        )