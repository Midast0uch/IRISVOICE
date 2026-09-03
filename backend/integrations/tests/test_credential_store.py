"""
Tests for CredentialStore

Validates: Requirements 2.1, 2.2, 2.6, 2.7
"""
import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path

from backend.integrations.credential_store import CredentialStore, CredentialStoreError
from backend.integrations.models import CredentialPayload


class TestCredentialStore:
    """Test suite for CredentialStore"""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test credentials"""
        temp_path = tempfile.mkdtemp()
        yield Path(temp_path)
        shutil.rmtree(temp_path)

    @pytest.fixture
    def store(self, temp_dir):
        """Create a CredentialStore with temp directory"""
        return CredentialStore(credentials_dir=temp_dir)

    @pytest.fixture
    def sample_credential(self):
        """Create a sample credential payload"""
        return CredentialPayload(
            integration_id="test-gmail",
            auth_type="oauth2",
            access_token="test_access_token_123",
            refresh_token="test_refresh_token_456",
            expires_at=1700000000,
            scope="https://www.googleapis.com/auth/gmail.modify",
            revocable=True,
            revoke_url="https://oauth2.googleapis.com/revoke"
        )

    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(self, store, sample_credential):
        """Verify encryption/decryption preserves data"""
        # Save credential
        await store.save(sample_credential.integration_id, sample_credential)

        # Load credential
        loaded = await store.load(sample_credential.integration_id)

        # Verify all fields match
        assert loaded.integration_id == sample_credential.integration_id
        assert loaded.auth_type == sample_credential.auth_type
        assert loaded.access_token == sample_credential.access_token
        assert loaded.refresh_token == sample_credential.refresh_token
        assert loaded.expires_at == sample_credential.expires_at
        assert loaded.scope == sample_credential.scope
        assert loaded.revocable == sample_credential.revocable
        assert loaded.revoke_url == sample_credential.revoke_url

    @pytest.mark.asyncio
    async def test_exists_returns_true_after_save(self, store, sample_credential):
        """Verify exists() returns True after saving"""
        # Initially should not exist
        assert await store.exists(sample_credential.integration_id) == False

        # Save credential
        await store.save(sample_credential.integration_id, sample_credential)

        # Should exist now
        assert await store.exists(sample_credential.integration_id) == True

    @pytest.mark.asyncio
    async def test_exists_returns_false_for_missing(self, store):
        """Verify exists() returns False for non-existent credential"""
        assert await store.exists("non-existent-integration") == False

    @pytest.mark.asyncio
    async def test_wipe_removes_credential(self, store, sample_credential):
        """Verify wipe deletes credential file and key"""
        # Save credential
        await store.save(sample_credential.integration_id, sample_credential)
        assert await store.exists(sample_credential.integration_id) == True

        # Wipe credential
        await store.wipe(sample_credential.integration_id, revoke_token=False)

        # Should not exist anymore
        assert await store.exists(sample_credential.integration_id) == False

    @pytest.mark.asyncio
    async def test_load_raises_error_for_missing(self, store):
        """Verify load raises CredentialStoreError for missing credential"""
        with pytest.raises(CredentialStoreError) as exc_info:
            await store.load("non-existent-integration")

        assert "No credential found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_telegram_credentials_roundtrip(self, store):
        """Verify Telegram MTProto credentials work correctly"""
        credential = CredentialPayload(
            integration_id="test-telegram",
            auth_type="telegram_mtproto",
            session_string="test_session_string_abc123",
        )

        await store.save(credential.integration_id, credential)
        loaded = await store.load(credential.integration_id)

        assert loaded.integration_id == credential.integration_id
        assert loaded.auth_type == "telegram_mtproto"
        assert loaded.session_string == credential.session_string

    @pytest.mark.asyncio
    async def test_imap_credentials_roundtrip(self, store):
        """Verify IMAP/SMTP credentials work correctly"""
        credential = CredentialPayload(
            integration_id="test-imap",
            auth_type="credentials",
            imap_host="imap.example.com",
            imap_port=993,
            smtp_host="smtp.example.com",
            smtp_port=587,
            email="user@example.com",
            password="app_password_123",
        )

        await store.save(credential.integration_id, credential)
        loaded = await store.load(credential.integration_id)

        assert loaded.imap_host == credential.imap_host
        assert loaded.imap_port == credential.imap_port
        assert loaded.smtp_host == credential.smtp_host
        assert loaded.smtp_port == credential.smtp_port
        assert loaded.email == credential.email
        assert loaded.password == credential.password

    @pytest.mark.asyncio
    async def test_multiple_credentials_independent(self, store):
        """Verify multiple credentials are stored independently"""
        cred1 = CredentialPayload(
            integration_id="test-gmail",
            auth_type="oauth2",
            access_token="gmail_token",
        )
        cred2 = CredentialPayload(
            integration_id="test-outlook",
            auth_type="oauth2",
            access_token="outlook_token",
        )

        await store.save(cred1.integration_id, cred1)
        await store.save(cred2.integration_id, cred2)

        loaded1 = await store.load(cred1.integration_id)
        loaded2 = await store.load(cred2.integration_id)

        assert loaded1.access_token == "gmail_token"
        assert loaded2.access_token == "outlook_token"

    @pytest.mark.asyncio
    async def test_update_existing_credential(self, store, sample_credential):
        """Verify updating an existing credential works"""
        # Save initial credential
        await store.save(sample_credential.integration_id, sample_credential)

        # Create updated credential with same ID
        updated = CredentialPayload(
            integration_id=sample_credential.integration_id,
            auth_type="oauth2",
            access_token="new_access_token",
            refresh_token="new_refresh_token",
        )

        await store.save(updated.integration_id, updated)
        loaded = await store.load(updated.integration_id)

        assert loaded.access_token == "new_access_token"
        assert loaded.refresh_token == "new_refresh_token"


class TestCredentialStoreEncryption:
    """Test encryption-specific behavior"""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test credentials"""
        temp_path = tempfile.mkdtemp()
        yield Path(temp_path)
        shutil.rmtree(temp_path)

    @pytest.fixture
    def store(self, temp_dir):
        """Create a CredentialStore with temp directory"""
        return CredentialStore(credentials_dir=temp_dir)

    @pytest.mark.asyncio
    async def test_encrypted_file_format(self, store, temp_dir):
        """Verify encrypted file has correct structure"""
        import json

        credential = CredentialPayload(
            integration_id="test-format",
            auth_type="oauth2",
            access_token="test_token",
        )

        await store.save(credential.integration_id, credential)

        # Read the encrypted file
        credential_path = temp_dir / "test-format.enc"
        with open(credential_path, 'r') as f:
            encrypted = json.load(f)

        # Verify structure
        assert "iv" in encrypted
        assert "tag" in encrypted
        assert "data" in encrypted
        assert "version" in encrypted
        assert encrypted["version"] == 1

        # Verify hex format
        assert all(c in '0123456789abcdef' for c in encrypted["iv"])
        assert all(c in '0123456789abcdef' for c in encrypted["tag"])
        assert all(c in '0123456789abcdef' for c in encrypted["data"])


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
