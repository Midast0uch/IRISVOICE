"""
Tests for authentication handlers.
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

import pytest

from ..auth_handlers import (
    OAuth2Handler,
    TelegramMTProtoHandler,
    CredentialsHandler,
    OAuthTokenResponse,
    AuthError,
    AuthTimeoutError,
    get_auth_handler,
)
from ..models import AuthType, IntegrationConfig


class TestOAuthTokenResponse:
    """Tests for OAuthTokenResponse."""
    
    def test_expires_at_calculation(self):
        """Test expires_at property."""
        response = OAuthTokenResponse(
            access_token="test",
            expires_in=3600,
        )
        
        expected_expires = int(time.time()) + 3600
        assert abs(response.expires_at - expected_expires) < 2
    
    def test_to_credential_payload(self):
        """Test conversion to credential payload."""
        response = OAuthTokenResponse(
            access_token="access123",
            refresh_token="refresh456",
            expires_in=3600,
            scope="read write",
            token_type="Bearer",
        )
        
        payload = response.to_credential_payload(
            integration_id="gmail",
            revoke_url="https://example.com/revoke",
        )
        
        assert payload["integration_id"] == "gmail"
        assert payload["auth_type"] == "oauth2"
        assert payload["access_token"] == "access123"
        assert payload["refresh_token"] == "refresh456"
        assert payload["scope"] == "read write"
        assert payload["revocable"] is True
        assert payload["revoke_url"] == "https://example.com/revoke"
        assert "created_at" in payload


class TestOAuth2Handler:
    """Tests for OAuth2Handler."""
    
    @pytest.fixture
    def handler(self):
        return OAuth2Handler()
    
    @pytest.fixture
    def mock_config(self):
        return IntegrationConfig(
            id="gmail",
            name="Gmail",
            category="email",
            auth_type=AuthType.OAUTH2,
            icon="gmail.svg",
            oauth={
                "provider": "google",
                "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
                "client_id_env": "GOOGLE_CLIENT_ID",
                "redirect_uri": "iris://oauth/callback/gmail",
            },
            mcp_server={},
            permissions_summary="Gmail access",
            enabled_by_default=False,
        )
    
    def test_generate_pkce(self, handler):
        """Test PKCE generation."""
        verifier, challenge = handler._generate_pkce()
        
        assert len(verifier) > 40
        assert len(challenge) > 40
        assert verifier != challenge
    
    def test_get_oauth_config(self, handler, mock_config):
        """Test OAuth config extraction."""
        config = handler._get_oauth_config(mock_config)
        
        assert config["provider"] == "google"
        assert "scopes" in config
    
    def test_get_endpoints(self, handler):
        """Test endpoint retrieval."""
        google = handler._get_endpoints("google")
        assert "auth_url" in google
        assert "token_url" in google
        
        unknown = handler._get_endpoints("unknown")
        assert unknown["auth_url"] is None
    
    @pytest.mark.asyncio
    async def test_handle_callback_success(self, handler):
        """Test handling OAuth callback."""
        # Setup pending state
        future = asyncio.get_event_loop().create_future()
        handler._pending_states["test_state"] = future
        
        callback_url = "iris://oauth/callback/gmail?code=auth_code&state=test_state"
        
        result = await handler.handle_callback(callback_url)
        
        assert result is True
        assert future.done()
        assert (await future)["code"] == "auth_code"
    
    @pytest.mark.asyncio
    async def test_handle_callback_missing_state(self, handler):
        """Test callback with missing state."""
        callback_url = "iris://oauth/callback/gmail?code=auth_code"
        
        result = await handler.handle_callback(callback_url)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_handle_callback_unknown_state(self, handler):
        """Test callback with unknown state."""
        callback_url = "iris://oauth/callback/gmail?code=auth_code&state=unknown"
        
        result = await handler.handle_callback(callback_url)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_handle_callback_error(self, handler):
        """Test handling error callback."""
        future = asyncio.get_event_loop().create_future()
        handler._pending_states["test_state"] = future
        
        callback_url = "iris://oauth/callback/gmail?error=access_denied&state=test_state"
        
        result = await handler.handle_callback(callback_url)
        
        assert result is True
        result_data = await future
        assert result_data["error"] == "access_denied"
    
    @pytest.mark.asyncio
    async def test_exchange_code_success(self, handler):
        """Test token exchange."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "access_token": "access123",
            "refresh_token": "refresh456",
            "expires_in": 3600,
            "scope": "read",
            "token_type": "Bearer",
        })
        
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.post = MagicMock(return_value=mock_response)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        
        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await handler._exchange_code(
                token_url="https://example.com/token",
                code="auth_code",
                code_verifier="verifier",
                client_id="client123",
                client_secret="secret456",
                redirect_uri="iris://callback",
            )
        
        assert result.access_token == "access123"
        assert result.refresh_token == "refresh456"
        assert result.expires_in == 3600


class TestCredentialsHandler:
    """Tests for CredentialsHandler."""
    
    @pytest.fixture
    def handler(self):
        handler = CredentialsHandler()
        handler.credential_store = MagicMock()
        handler.credential_store.save = AsyncMock()
        return handler
    
    @pytest.fixture
    def mock_config(self):
        return IntegrationConfig(
            id="imap_smtp",
            name="IMAP/SMTP",
            category="email",
            auth_type=AuthType.CREDENTIALS,
            icon="email.svg",
            credentials={
                "fields": [
                    {"key": "email", "label": "Email", "type": "email"},
                    {"key": "password", "label": "Password", "type": "password"},
                ],
            },
            mcp_server={},
            permissions_summary="Email access",
            enabled_by_default=False,
        )
    
    @pytest.mark.asyncio
    async def test_authenticate_success(self, handler, mock_config):
        """Test successful credential authentication."""
        credentials = {
            "email": "test@example.com",
            "password": "secret123",
        }
        
        result = await handler.authenticate("imap_smtp", mock_config, credentials)
        
        assert result is True
        handler.credential_store.save.assert_called_once()
        
        call_args = handler.credential_store.save.call_args
        assert call_args[0][0] == "imap_smtp"
        assert call_args[0][1]["auth_type"] == "credentials"
        assert call_args[0][1]["credentials"] == credentials
    
    @pytest.mark.asyncio
    async def test_authenticate_missing_required_field(self, handler, mock_config):
        """Test authentication with missing required field."""
        credentials = {
            "email": "test@example.com",
            # Missing password
        }
        
        with pytest.raises(AuthError) as exc_info:
            await handler.authenticate("imap_smtp", mock_config, credentials)
        
        assert "password" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_authenticate_with_test_connection_success(self, handler, mock_config):
        """Test authentication with successful connection test."""
        async def test_conn(creds):
            return True
        
        credentials = {
            "email": "test@example.com",
            "password": "secret123",
        }
        
        result = await handler.authenticate(
            "imap_smtp", mock_config, credentials, test_connection=test_conn
        )
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_authenticate_with_test_connection_failure(self, handler, mock_config):
        """Test authentication with failed connection test."""
        async def test_conn(creds):
            return False
        
        credentials = {
            "email": "test@example.com",
            "password": "secret123",
        }
        
        with pytest.raises(AuthError) as exc_info:
            await handler.authenticate(
                "imap_smtp", mock_config, credentials, test_connection=test_conn
            )
        
        assert "Connection test failed" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_refresh(self, handler):
        """Test credential refresh (no-op)."""
        result = await handler.refresh("imap_smtp", mock_config)
        assert result is True


class TestAuthHandlerFactory:
    """Tests for auth handler factory."""
    
    def test_get_oauth2_handler(self):
        """Test getting OAuth2 handler."""
        handler = get_auth_handler(AuthType.OAUTH2)
        assert isinstance(handler, OAuth2Handler)
    
    def test_get_credentials_handler(self):
        """Test getting credentials handler."""
        handler = get_auth_handler(AuthType.CREDENTIALS)
        assert isinstance(handler, CredentialsHandler)
    
    def test_get_telegram_handler(self):
        """Test getting Telegram handler."""
        handler = get_auth_handler(AuthType.TELEGRAM_MTPROTO)
        assert isinstance(handler, TelegramMTProtoHandler)
    
    def test_get_unknown_handler(self):
        """Test getting handler for unknown type."""
        with pytest.raises(ValueError):
            get_auth_handler("unknown")
    
    def test_register_custom_handler(self):
        """Test registering custom handler."""
        class CustomHandler:
            pass
        
        from ..auth_handlers import register_auth_handler
        register_auth_handler("custom", CustomHandler)
        
        handler = get_auth_handler("custom")
        assert isinstance(handler, CustomHandler)
