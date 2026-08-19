"""
Contract test: /api/config/save must route api_key to the OS keyring, never
the config file.

Regression guard for the recurring cerebras<->cohere cross-contamination:
the kernel's fallback (agent_kernel._resolve_effective_key) reads
cfg.inference.api_key and serves it to any provider whose id matches
cfg.inference.provider, so a stale value persisted there by the HTTP
config-save path 401s the wrong provider (the cerebras-key-sent-to-cohere
bug, 2026-08-16). The handler must:

  1. write the key to the keyring under the provider id (the same store
     set_model_selection uses), and
  2. clear the legacy cfg.inference.api_key field so the fallback can
     never serve an outdated credential.

Run with: pytest backend/tests/contract/test_config_save_key_routing.py -v
"""

import pytest

from backend.iris_config import load_config as _real_load_config


@pytest.fixture
def config_save_env(monkeypatch):
    """Patch the handler's config + keyring dependencies; capture writes."""
    captured = {}

    def fake_save_config(cfg):
        captured["cfg"] = cfg

    monkeypatch.setattr("backend.iris_config.save_config", fake_save_config)
    monkeypatch.setattr("backend.iris_config.load_config", _real_load_config)

    written = {}

    def fake_set_secret(provider_id, key):
        written[provider_id] = key

    monkeypatch.setattr(
        "backend.agent.inference.keyring.set_secret", fake_set_secret
    )

    return captured, written


async def _call(body):
    from backend.main import api_config_save

    return await api_config_save(body)


class TestConfigSaveKeyRouting:
    async def test_api_key_routes_to_keyring_and_clears_config_field(
        self, config_save_env
    ):
        captured, written = config_save_env
        result = await _call(
            {
                "section_id": "model_selection",
                "values": {
                    "model_provider": "cohere",
                    "api_key": "test-key-123",
                },
            }
        )
        assert result["status"] == "ok"
        # The key lands in the keyring under the provider id...
        assert written.get("cohere") == "test-key-123"
        # ...and NEVER in the config file's legacy field.
        assert captured["cfg"].inference.api_key == ""

    async def test_api_key_without_provider_is_not_written_anywhere(
        self, config_save_env
    ):
        captured, written = config_save_env
        result = await _call(
            {
                "section_id": "model_selection",
                "values": {"api_key": "test-key-123"},
            }
        )
        assert result["status"] == "ok"
        assert written == {}
        assert captured["cfg"].inference.api_key == ""

    async def test_no_api_key_leaves_config_field_untouched(self, config_save_env):
        captured, _ = config_save_env
        result = await _call(
            {
                "section_id": "model_selection",
                "values": {"model_provider": "cohere"},
            }
        )
        assert result["status"] == "ok"
        # No key in the payload: the legacy field must NOT be cleared or set.
        assert (
            captured["cfg"].inference.api_key
            == _real_load_config().inference.api_key
        )