"""
Tests for RegistryLoader

Validates: Requirements 1.1, 1.2
"""
import pytest
import json
import tempfile
import shutil
from pathlib import Path

from backend.integrations.registry_loader import RegistryLoader
from backend.integrations.models import IntegrationConfig, AuthType


class TestRegistryLoader:
    """Test suite for RegistryLoader"""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test registries"""
        temp_path = tempfile.mkdtemp()
        yield Path(temp_path)
        shutil.rmtree(temp_path)

    @pytest.fixture
    def sample_bundled_registry(self, temp_dir):
        """Create a sample bundled registry"""
        bundled_path = temp_dir / "bundled_registry.json"
        data = {
            "integrations": [
                {
                    "id": "gmail",
                    "name": "Gmail",
                    "category": "email",
                    "icon": "gmail.svg",
                    "auth_type": "oauth2",
                    "oauth": {
                        "provider": "google",
                        "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
                        "client_id_env": "GOOGLE_CLIENT_ID",
                        "redirect_uri": "iris://oauth/callback/gmail"
                    },
                    "mcp_server": {
                        "binary": "iris-mcp-gmail",
                        "runtime": "node",
                        "transport": "stdio"
                    },
                    "permissions_summary": "Read your Gmail",
                    "enabled_by_default": False
                },
                {
                    "id": "telegram",
                    "name": "Telegram",
                    "category": "messaging",
                    "icon": "telegram.svg",
                    "auth_type": "telegram_mtproto",
                    "telegram": {
                        "api_id_env": "TELEGRAM_API_ID",
                        "api_hash_env": "TELEGRAM_API_HASH"
                    },
                    "mcp_server": {
                        "binary": "iris-mcp-telegram",
                        "runtime": "python",
                        "transport": "stdio"
                    },
                    "permissions_summary": "Read and send messages",
                    "enabled_by_default": False
                }
            ]
        }
        with open(bundled_path, 'w') as f:
            json.dump(data, f)
        return bundled_path

    @pytest.fixture
    def loader(self, temp_dir, sample_bundled_registry):
        """Create a RegistryLoader with temp directories"""
        return RegistryLoader(
            bundled_path=sample_bundled_registry,
            user_registry_dir=temp_dir
        )

    def test_load_bundled_registry(self, loader):
        """Verify bundled registry loads correctly"""
        integrations = loader.load_registries()

        assert len(integrations) == 2
        assert "gmail" in integrations
        assert "telegram" in integrations

        gmail = integrations["gmail"]
        assert gmail.name == "Gmail"
        assert gmail.category == "email"
        assert gmail.auth_type == AuthType.OAUTH2

    def test_user_registry_created_if_missing(self, loader, temp_dir):
        """Verify user registry is created if it doesn't exist"""
        user_registry_path = temp_dir / "user-registry.json"

        # Should not exist initially
        assert not user_registry_path.exists()

        # Load registries (should create user registry)
        loader.load_registries()

        # Should exist now
        assert user_registry_path.exists()

        # Should be valid JSON with empty integrations
        with open(user_registry_path, 'r') as f:
            data = json.load(f)
        assert data["integrations"] == []

    def test_user_registry_override_bundled(self, loader, temp_dir):
        """Verify user registry entries override bundled"""
        user_registry_path = temp_dir / "user-registry.json"

        # Create user registry with override for gmail
        user_data = {
            "integrations": [
                {
                    "id": "gmail",
                    "name": "Gmail Pro",
                    "category": "email",
                    "icon": "gmail-pro.svg",
                    "auth_type": "oauth2",
                    "oauth": {
                        "provider": "google",
                        "scopes": ["https://www.googleapis.com/auth/gmail.modify"],
                        "client_id_env": "GOOGLE_CLIENT_ID_PRO",
                        "redirect_uri": "iris://oauth/callback/gmail-pro"
                    },
                    "mcp_server": {
                        "binary": "iris-mcp-gmail-pro",
                        "runtime": "node",
                        "transport": "stdio"
                    },
                    "permissions_summary": "Read and modify Gmail",
                    "enabled_by_default": False,
                    "source": "mcp-registry"
                }
            ]
        }
        with open(user_registry_path, 'w') as f:
            json.dump(user_data, f)

        # Load registries
        integrations = loader.load_registries()

        # Gmail should be overridden
        gmail = integrations["gmail"]
        assert gmail.name == "Gmail Pro"
        assert gmail.source == "mcp-registry"

        # Telegram should still be from bundled
        telegram = integrations["telegram"]
        assert telegram.name == "Telegram"

    def test_get_integration(self, loader):
        """Verify get_integration returns correct integration"""
        loader.load_registries()

        gmail = loader.get_integration("gmail")
        assert gmail is not None
        assert gmail.name == "Gmail"

        missing = loader.get_integration("non-existent")
        assert missing is None

    def test_get_all_integrations(self, loader):
        """Verify get_all_integrations returns list"""
        all_integrations = loader.get_all_integrations()

        assert len(all_integrations) == 2
        ids = [i.id for i in all_integrations]
        assert "gmail" in ids
        assert "telegram" in ids

    def test_get_integrations_by_category(self, loader):
        """Verify filtering by category works"""
        loader.load_registries()

        email_integrations = loader.get_integrations_by_category("email")
        assert len(email_integrations) == 1
        assert email_integrations[0].id == "gmail"

        messaging_integrations = loader.get_integrations_by_category("messaging")
        assert len(messaging_integrations) == 1
        assert messaging_integrations[0].id == "telegram"

    def test_get_categories(self, loader):
        """Verify get_categories returns unique categories"""
        categories = loader.get_categories()

        assert "email" in categories
        assert "messaging" in categories
        assert len(categories) == 2

    def test_add_user_integration(self, loader, temp_dir):
        """Verify adding user integration works"""
        loader.load_registries()

        # Create new integration
        new_config = IntegrationConfig(
            id="slack",
            name="Slack",
            category="messaging",
            icon="slack.svg",
            auth_type=AuthType.OAUTH2,
            oauth={
                "provider": "slack",
                "scopes": ["chat:write", "channels:read"],
                "client_id_env": "SLACK_CLIENT_ID",
                "redirect_uri": "iris://oauth/callback/slack"
            },
            mcp_server={
                "binary": "iris-mcp-slack",
                "runtime": "node",
                "transport": "stdio"
            },
            permissions_summary="Read and send Slack messages",
            source="mcp-registry"
        )

        # Add to registry
        result = loader.add_user_integration(new_config)
        assert result is True

        # Verify it was added
        assert loader.get_integration("slack") is not None
        assert loader.get_integration("slack").name == "Slack"

        # Verify it was written to file
        user_registry_path = temp_dir / "user-registry.json"
        with open(user_registry_path, 'r') as f:
            data = json.load(f)
        assert len(data["integrations"]) == 1
        assert data["integrations"][0]["id"] == "slack"

    def test_remove_user_integration(self, loader, temp_dir):
        """Verify removing user integration works"""
        # First add an integration
        loader.load_registries()
        new_config = IntegrationConfig(
            id="slack",
            name="Slack",
            category="messaging",
            icon="slack.svg",
            auth_type=AuthType.OAUTH2,
            permissions_summary="Read and send Slack messages"
        )
        loader.add_user_integration(new_config)
        assert loader.get_integration("slack") is not None

        # Remove it
        result = loader.remove_user_integration("slack")
        assert result is True

        # Verify it was removed
        assert loader.get_integration("slack") is None

    def test_cache_works(self, loader):
        """Verify caching prevents redundant loads"""
        # First load
        integrations1 = loader.load_registries()

        # Second load (should use cache)
        integrations2 = loader.load_registries()

        # Should be same object due to caching
        assert integrations1 is integrations2

        # Force reload
        integrations3 = loader.load_registries(force_reload=True)

        # Should be different object
        assert integrations1 is not integrations3
        assert len(integrations3) == len(integrations1)


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
