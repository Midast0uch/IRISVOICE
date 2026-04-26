"""
IRIS MCP Integration Layer

Manages external service integrations (Gmail, Outlook, Telegram, Discord, IMAP/SMTP)
with secure credential storage and lifecycle management.
"""

from .models import (
    AuthType,
    IntegrationStatus,
    OAuthConfig,
    TelegramConfig,
    CredentialField,
    CredentialsConfig,
    MCPServerConfig,
    IntegrationConfig,
    CredentialPayload,
    IntegrationState,
)

from .credential_store import (
    CredentialStore,
    get_credential_store,
    CredentialStoreError,
    CredentialDecryptionError,
)

from .registry_loader import RegistryLoader, get_registry_loader

from .lifecycle_manager import (
    IntegrationLifecycleManager,
    ProcessInfo,
    ProcessError,
    CredentialError,
    get_lifecycle_manager,
    reset_lifecycle_manager,
)

from .auth_handlers import (
    OAuth2Handler,
    TelegramMTProtoHandler,
    CredentialsHandler,
    OAuthTokenResponse,
    AuthError,
    AuthTimeoutError,
    AuthCancelledError,
    BaseAuthHandler,
    get_auth_handler,
    register_auth_handler,
)

from .ws_handlers import (
    IntegrationMessageHandler,
    get_integration_handler,
    reset_integration_handler,
    handle_integration_message,
)

from .mcp_bridge import (
    IntegrationMCPBridge,
    get_mcp_bridge,
    reset_mcp_bridge,
)

__all__ = [
    # Enums
    "AuthType",
    "IntegrationStatus",
    # Config classes
    "OAuthConfig",
    "TelegramConfig",
    "CredentialField",
    "CredentialsConfig",
    "MCPServerConfig",
    "IntegrationConfig",
    "CredentialPayload",
    "IntegrationState",
    # Main classes
    "CredentialStore",
    "CredentialStoreError",
    "RegistryLoader",
    "IntegrationLifecycleManager",
    "ProcessInfo",
    # Auth handlers
    "OAuth2Handler",
    "TelegramMTProtoHandler",
    "CredentialsHandler",
    "OAuthTokenResponse",
    "BaseAuthHandler",
    # Exceptions
    "ProcessError",
    "CredentialError",
    "AuthError",
    "AuthTimeoutError",
    "AuthCancelledError",
    # WebSocket handlers
    "IntegrationMessageHandler",
    "get_integration_handler",
    "reset_integration_handler",
    "handle_integration_message",
    # MCP Bridge
    "IntegrationMCPBridge",
    "get_mcp_bridge",
    "reset_mcp_bridge",
    # Factory functions
    "get_credential_store",
    "get_registry_loader",
    "get_lifecycle_manager",
    "reset_lifecycle_manager",
    "get_auth_handler",
    "register_auth_handler",
]
