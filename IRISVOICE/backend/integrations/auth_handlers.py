"""
Authentication Handlers

Handles OAuth2 flows, Telegram MTProto, and credential-based authentication.
Integrates with the OS for deep link handling.
"""

import asyncio
import json
import logging
import secrets
import time
import urllib.parse
import webbrowser
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

import aiohttp

from .credential_store import CredentialStore, get_credential_store
from .models import AuthType, IntegrationConfig, OAuthConfig

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """Raised when authentication fails."""
    pass


class AuthTimeoutError(AuthError):
    """Raised when authentication times out."""
    pass


class AuthCancelledError(AuthError):
    """Raised when user cancels authentication."""
    pass


@dataclass
class OAuthTokenResponse:
    """OAuth2 token response."""
    access_token: str
    refresh_token: Optional[str]
    expires_in: Optional[int]
    scope: Optional[str]
    token_type: str = "Bearer"
    
    @property
    def expires_at(self) -> Optional[int]:
        """Calculate expiration timestamp."""
        if self.expires_in:
            return int(time.time()) + self.expires_in
        return None
    
    def to_credential_payload(self, integration_id: str, revoke_url: Optional[str] = None) -> Dict[str, Any]:
        """Convert to credential payload format."""
        return {
            "integration_id": integration_id,
            "auth_type": "oauth2",
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "scope": self.scope,
            "token_type": self.token_type,
            "created_at": int(time.time()),
            "revocable": True,
            "revoke_url": revoke_url,
        }


class BaseAuthHandler(ABC):
    """Base class for authentication handlers."""
    
    def __init__(self, credential_store: Optional[CredentialStore] = None):
        self.credential_store = credential_store or get_credential_store()
    
    @abstractmethod
    async def authenticate(
        self,
        integration_id: str,
        config: IntegrationConfig,
        **kwargs
    ) -> bool:
        """
        Authenticate and store credentials.
        
        Returns True if authentication succeeded.
        """
        pass
    
    @abstractmethod
    async def refresh(self, integration_id: str, config: IntegrationConfig) -> bool:
        """Refresh expired credentials if possible."""
        pass
    
    async def revoke(self, integration_id: str, config: IntegrationConfig) -> bool:
        """Revoke credentials at the provider if supported."""
        try:
            credential = await self.credential_store.load(integration_id)
            revoke_url = credential.get("revoke_url")
            
            if revoke_url and credential.get("access_token"):
                # Attempt to revoke at provider
                await self._do_revoke(revoke_url, credential["access_token"])
            
            # Always wipe local credentials
            await self.credential_store.wipe(integration_id)
            return True
        except Exception as e:
            logger.error(f"Failed to revoke credentials for {integration_id}: {e}")
            return False
    
    async def _do_revoke(self, revoke_url: str, token: str) -> None:
        """Override to implement provider-specific revocation."""
        pass


class OAuth2Handler(BaseAuthHandler):
    """
    OAuth2 authentication handler with PKCE support.
    
    Handles the complete OAuth2 flow:
    1. Generate PKCE code verifier and challenge
    2. Open browser with authorization URL
    3. Wait for deep link callback
    4. Exchange code for tokens
    5. Store encrypted credentials
    """
    
    # Default timeouts
    AUTH_TIMEOUT = 300  # 5 minutes
    
    # OAuth2 endpoints by provider
    PROVIDER_ENDPOINTS = {
        "google": {
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "revoke_url": "https://oauth2.googleapis.com/revoke",
        },
        "microsoft": {
            "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
            "revoke_url": None,  # Microsoft doesn't have a simple revoke endpoint
        },
        "discord": {
            "auth_url": "https://discord.com/oauth2/authorize",
            "token_url": "https://discord.com/api/oauth2/token",
            "revoke_url": "https://discord.com/api/oauth2/token/revoke",
        },
    }
    
    def __init__(self, credential_store: Optional[CredentialStore] = None):
        super().__init__(credential_store)
        self._pending_states: Dict[str, asyncio.Future] = {}
        self._code_verifiers: Dict[str, str] = {}
    
    def _generate_pkce(self) -> Tuple[str, str]:
        """Generate PKCE code verifier and challenge."""
        # Code verifier: 43-128 characters
        verifier = secrets.token_urlsafe(64)
        # Code challenge: SHA256 hash of verifier, base64url encoded
        import hashlib
        import base64
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).decode().rstrip("=")
        return verifier, challenge
    
    def _get_oauth_config(self, config: IntegrationConfig) -> Dict[str, Any]:
        """Extract OAuth config from integration config."""
        oauth_config = getattr(config, 'oauth', None) or config.to_dict().get('oauth', {})
        return oauth_config
    
    def _get_endpoints(self, provider: str) -> Dict[str, Optional[str]]:
        """Get OAuth endpoints for a provider."""
        return self.PROVIDER_ENDPOINTS.get(provider, {
            "auth_url": None,
            "token_url": None,
            "revoke_url": None,
        })
    
    async def authenticate(
        self,
        integration_id: str,
        config: IntegrationConfig,
        client_id: str,
        client_secret: Optional[str] = None,
        additional_scopes: Optional[list] = None,
    ) -> bool:
        """
        Start OAuth2 authentication flow.
        
        Args:
            integration_id: The integration being authenticated
            config: Integration configuration
            client_id: OAuth client ID
            client_secret: OAuth client secret (optional for PKCE-only flows)
            additional_scopes: Additional scopes to request
        """
        oauth_config = self._get_oauth_config(config)
        provider = oauth_config.get("provider", "google")
        endpoints = self._get_endpoints(provider)
        
        if not endpoints.get("auth_url") or not endpoints.get("token_url"):
            raise AuthError(f"Unknown OAuth provider: {provider}")
        
        # Generate PKCE
        code_verifier, code_challenge = self._generate_pkce()
        
        # Generate state parameter for CSRF protection
        state = secrets.token_urlsafe(32)
        
        # Build authorization URL
        scopes = oauth_config.get("scopes", [])
        if additional_scopes:
            scopes = list(set(scopes + additional_scopes))
        
        redirect_uri = oauth_config.get("redirect_uri", f"iris://oauth/callback/{integration_id}")
        
        auth_params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",  # Request refresh token
            "prompt": "consent",  # Force consent to get refresh token
        }
        
        auth_url = f"{endpoints['auth_url']}?{urllib.parse.urlencode(auth_params)}"
        
        # Create future to wait for callback
        future = asyncio.get_event_loop().create_future()
        self._pending_states[state] = future
        self._code_verifiers[state] = code_verifier
        
        try:
            # Open browser
            logger.info(f"Opening browser for OAuth: {provider}")
            webbrowser.open(auth_url)
            
            # Wait for callback with timeout
            try:
                result = await asyncio.wait_for(future, timeout=self.AUTH_TIMEOUT)
            except asyncio.TimeoutError:
                raise AuthTimeoutError("Authentication timed out")
            
            if result.get("error"):
                raise AuthError(f"OAuth error: {result.get('error_description', result['error'])}")
            
            # Verify state matches
            returned_state = result.get("state")
            if returned_state != state:
                raise AuthError("State mismatch - possible CSRF attack")
            
            code = result.get("code")
            if not code:
                raise AuthError("No authorization code received")
            
            # Exchange code for tokens
            token_response = await self._exchange_code(
                token_url=endpoints["token_url"],
                code=code,
                code_verifier=code_verifier,
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
            )
            
            # Store credentials
            credential_payload = token_response.to_credential_payload(
                integration_id=integration_id,
                revoke_url=endpoints.get("revoke_url"),
            )
            await self.credential_store.save(integration_id, credential_payload)
            
            logger.info(f"OAuth authentication successful for {integration_id}")
            return True
            
        except Exception as e:
            logger.error(f"OAuth authentication failed for {integration_id}: {e}")
            raise
        finally:
            # Cleanup
            self._pending_states.pop(state, None)
            self._code_verifiers.pop(state, None)
    
    async def _exchange_code(
        self,
        token_url: str,
        code: str,
        code_verifier: str,
        client_id: str,
        client_secret: Optional[str],
        redirect_uri: str,
    ) -> OAuthTokenResponse:
        """Exchange authorization code for tokens."""
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": code_verifier,
        }
        
        if client_secret:
            payload["client_secret"] = client_secret
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                token_url,
                data=payload,
                headers=headers,
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    raise AuthError(f"Token exchange failed: {response.status} - {text}")
                
                data = await response.json()
                
                if "error" in data:
                    raise AuthError(f"Token error: {data.get('error_description', data['error'])}")
                
                return OAuthTokenResponse(
                    access_token=data["access_token"],
                    refresh_token=data.get("refresh_token"),
                    expires_in=data.get("expires_in"),
                    scope=data.get("scope"),
                    token_type=data.get("token_type", "Bearer"),
                )
    
    async def handle_callback(self, url: str) -> bool:
        """
        Handle OAuth deep link callback.
        
        Args:
            url: The full callback URL (e.g., "iris://oauth/callback/gmail?code=xxx&state=yyy")
        
        Returns True if a pending auth was handled.
        """
        try:
            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query)
            
            # Flatten single-value params
            result = {k: v[0] if len(v) == 1 else v for k, v in params.items()}
            
            state = result.get("state")
            if not state:
                logger.warning("OAuth callback missing state parameter")
                return False
            
            future = self._pending_states.get(state)
            if not future:
                logger.warning(f"No pending OAuth flow for state: {state}")
                return False
            
            # Complete the future
            if not future.done():
                future.set_result(result)
            
            return True
            
        except Exception as e:
            logger.error(f"Error handling OAuth callback: {e}")
            return False
    
    async def refresh(self, integration_id: str, config: IntegrationConfig) -> bool:
        """Refresh expired OAuth tokens."""
        try:
            credential = await self.credential_store.load(integration_id)
            refresh_token = credential.get("refresh_token")
            
            if not refresh_token:
                logger.warning(f"No refresh token available for {integration_id}")
                return False
            
            oauth_config = self._get_oauth_config(config)
            provider = oauth_config.get("provider", "google")
            endpoints = self._get_endpoints(provider)
            
            # Get client credentials from environment
            client_id = oauth_config.get("client_id_env", f"{provider.upper()}_CLIENT_ID")
            client_id_value = client_id if not client_id.endswith("_CLIENT_ID") else ""
            
            client_secret_env = oauth_config.get("client_secret_env", f"{provider.upper()}_CLIENT_SECRET")
            client_secret = None
            
            import os
            if client_id_value.startswith("$"):
                client_id_value = os.environ.get(client_id_env, "")
            if client_secret_env.startswith("$"):
                client_secret = os.environ.get(client_secret_env)
            
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id_value,
            }
            
            if client_secret:
                payload["client_secret"] = client_secret
            
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    endpoints["token_url"],
                    data=payload,
                    headers=headers,
                ) as response:
                    if response.status != 200:
                        text = await response.text()
                        logger.error(f"Token refresh failed: {text}")
                        return False
                    
                    data = await response.json()
                    
                    # Update credential with new tokens
                    credential["access_token"] = data["access_token"]
                    if data.get("refresh_token"):
                        credential["refresh_token"] = data["refresh_token"]
                    if data.get("expires_in"):
                        credential["expires_at"] = int(time.time()) + data["expires_in"]
                    
                    await self.credential_store.save(integration_id, credential)
                    logger.info(f"Token refreshed for {integration_id}")
                    return True
                    
        except Exception as e:
            logger.error(f"Failed to refresh token for {integration_id}: {e}")
            return False
    
    async def _do_revoke(self, revoke_url: str, token: str) -> None:
        """Revoke token at provider."""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                revoke_url,
                data={"token": token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as response:
                if response.status not in (200, 204):
                    logger.warning(f"Token revocation returned {response.status}")


class TelegramMTProtoHandler(BaseAuthHandler):
    """
    Telegram MTProto authentication handler.
    
    Uses Telethon library for MTProto protocol.
    """
    
    def __init__(self, credential_store: Optional[CredentialStore] = None):
        super().__init__(credential_store)
        self._sessions: Dict[str, Any] = {}
    
    async def authenticate(
        self,
        integration_id: str,
        config: IntegrationConfig,
        api_id: int,
        api_hash: str,
        phone_number: str,
        code_callback: Callable[[], asyncio.Future[str]],
        password_callback: Optional[Callable[[], asyncio.Future[str]]] = None,
    ) -> bool:
        """
        Authenticate with Telegram using MTProto.
        
        Args:
            integration_id: The integration ID
            config: Integration config
            api_id: Telegram API ID
            api_hash: Telegram API hash
            phone_number: User's phone number with country code
            code_callback: Async function that returns the SMS/code from user
            password_callback: Optional async function for 2FA password
        """
        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
            from telethon.errors import SessionPasswordNeededError
        except ImportError:
            raise AuthError("Telethon library not installed. Install with: pip install telethon")
        
        session = StringSession()
        client = TelegramClient(session, api_id, api_hash)
        
        try:
            await client.connect()
            
            if await client.is_user_authorized():
                logger.info("Already authorized with Telegram")
            else:
                # Send code request
                await client.send_code_request(phone_number)
                
                # Get code from user via callback
                code = await code_callback()
                
                try:
                    await client.sign_in(phone_number, code)
                except SessionPasswordNeededError:
                    if password_callback:
                        password = await password_callback()
                        await client.sign_in(password=password)
                    else:
                        raise AuthError("Two-factor authentication required but no password callback provided")
            
            # Get session string for storage
            session_string = client.session.save()
            
            # Get user info
            me = await client.get_me()
            username = me.username or me.first_name
            
            # Store credentials
            credential_payload = {
                "integration_id": integration_id,
                "auth_type": "telegram_mtproto",
                "session_string": session_string,
                "api_id": api_id,
                "phone_number": phone_number,
                "username": username,
                "created_at": int(time.time()),
                "revocable": False,  # MTProto sessions can't be remotely revoked easily
            }
            
            await self.credential_store.save(integration_id, credential_payload)
            logger.info(f"Telegram authentication successful for {integration_id}")
            return True
            
        except Exception as e:
            logger.error(f"Telegram authentication failed: {e}")
            raise AuthError(f"Telegram authentication failed: {e}")
        finally:
            await client.disconnect()
    
    async def refresh(self, integration_id: str, config: IntegrationConfig) -> bool:
        """MTProto sessions don't expire, no refresh needed."""
        return True


class CredentialsHandler(BaseAuthHandler):
    """
    Handler for direct credential-based authentication (IMAP/SMTP, API keys, etc.)
    """
    
    async def authenticate(
        self,
        integration_id: str,
        config: IntegrationConfig,
        credentials: Dict[str, str],
        test_connection: Optional[Callable[[Dict[str, str]], asyncio.Future[bool]]] = None,
    ) -> bool:
        """
        Store credentials after optional connection test.
        
        Args:
            integration_id: The integration ID
            config: Integration config
            credentials: Dict of credential fields (e.g., {"email": "...", "password": "..."})
            test_connection: Optional async function to test credentials before storing
        """
        # Validate required fields
        config_dict = config.to_dict()
        credentials_config = config_dict.get("credentials", {})
        required_fields = credentials_config.get("fields", [])
        
        for field in required_fields:
            key = field.get("key")
            if key and key not in credentials:
                if not field.get("optional", False):
                    raise AuthError(f"Required field missing: {key}")
        
        # Test connection if provided
        if test_connection:
            try:
                success = await test_connection(credentials)
                if not success:
                    raise AuthError("Connection test failed - please check your credentials")
            except Exception as e:
                raise AuthError(f"Connection test failed: {e}")
        
        # Store credentials
        credential_payload = {
            "integration_id": integration_id,
            "auth_type": "credentials",
            "credentials": credentials,
            "created_at": int(time.time()),
            "revocable": False,
        }
        
        await self.credential_store.save(integration_id, credential_payload)
        logger.info(f"Credentials stored for {integration_id}")
        return True
    
    async def refresh(self, integration_id: str, config: IntegrationConfig) -> bool:
        """Credentials don't expire, no refresh needed."""
        return True


# Handler factory
_auth_handlers: Dict[AuthType, type] = {
    AuthType.OAUTH2: OAuth2Handler,
    AuthType.TELEGRAM_MTPROTO: TelegramMTProtoHandler,
    AuthType.CREDENTIALS: CredentialsHandler,
}


def get_auth_handler(auth_type: AuthType) -> BaseAuthHandler:
    """Get the appropriate auth handler for an auth type."""
    handler_class = _auth_handlers.get(auth_type)
    if not handler_class:
        raise ValueError(f"No handler for auth type: {auth_type}")
    return handler_class()


def register_auth_handler(auth_type: AuthType, handler_class: type) -> None:
    """Register a custom auth handler."""
    _auth_handlers[auth_type] = handler_class
