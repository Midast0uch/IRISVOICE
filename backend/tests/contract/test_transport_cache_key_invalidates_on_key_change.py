"""Contract: transport cache must invalidate when the credential changes.

Root cause (2026-08-15): `_transport_cache_key` keyed API transports on
`(kind, api_base_url)` only. A key change via the UI (Apply Provider) updated
the keyring but NOT the cached transport, so every subsequent call sent the
stale key and 401'd even though the keyring held the correct value.

The cache key now fingerprints the KEYRING value (the exact key the transport
will use — `_build_transport` reads `get_secret(inst.id)`), so the cache
invalidates precisely when the real credential changes.
"""

from __future__ import annotations

import pytest

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.router import _transport_cache_key


class TestTransportCacheKeyInvalidatesOnKeyChange:
    def test_key_change_changes_cache_key(self, monkeypatch):
        """Two providers with the same endpoint but different keyring values
        must NOT share a cached transport."""
        inst = ProviderInstance(
            id="cohere", label="Cohere", kind=ProviderKind.API,
            model="command-a-plus-05-2026",
            api_base_url="https://api.cohere.ai/compatibility/v1",
        )
        keyring_values = iter(["old-key-AAAAAAAA", "new-key-BBBBBBBB"])

        def fake_get_secret(provider_id):
            return next(keyring_values)

        monkeypatch.setattr(
            "backend.agent.inference.keyring.get_secret", fake_get_secret
        )

        key_before = _transport_cache_key(ProviderKind.API, inst)
        key_after = _transport_cache_key(ProviderKind.API, inst)

        assert key_before != key_after, (
            "transport cache key must change when the keyring credential changes"
        )

    def test_same_key_same_cache_key(self, monkeypatch):
        """Same endpoint + same keyring value -> same cache key (cache hit)."""
        inst = ProviderInstance(
            id="cohere", label="Cohere", kind=ProviderKind.API,
            model="command-a-plus-05-2026",
            api_base_url="https://api.cohere.ai/compatibility/v1",
        )
        monkeypatch.setattr(
            "backend.agent.inference.keyring.get_secret",
            lambda provider_id: "same-key-CCCCCCCC",
        )

        k1 = _transport_cache_key(ProviderKind.API, inst)
        k2 = _transport_cache_key(ProviderKind.API, inst)
        assert k1 == k2

    def test_fingerprint_does_not_expose_secret(self, monkeypatch):
        """The cache key must not contain the raw credential."""
        inst = ProviderInstance(
            id="cohere", label="Cohere", kind=ProviderKind.API,
            model="command-a-plus-05-2026",
            api_base_url="https://api.cohere.ai/compatibility/v1",
        )
        monkeypatch.setattr(
            "backend.agent.inference.keyring.get_secret",
            lambda provider_id: "super-secret-key-12345678",
        )

        key = _transport_cache_key(ProviderKind.API, inst)
        joined = "|".join(str(part) for part in key)
        assert "super-secret-key" not in joined
        assert "12345678" in joined  # fingerprint (last 8) is present