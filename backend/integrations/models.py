"""
Integration Models - Data classes for MCP Integration Layer
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime


class AuthType(str, Enum):
    """Authentication types supported"""
    OAUTH2 = "oauth2"
    TELEGRAM_MTPROTO = "telegram_mtproto"
    CREDENTIALS = "credentials"


class IntegrationStatus(str, Enum):
    """Integration runtime statuses"""
    DISABLED = "disabled"
    AUTH_PENDING = "auth_pending"
    RUNNING = "running"
    ERROR = "error"
    REAUTH_PENDING = "reauth_pending"


@dataclass
class OAuthConfig:
    """OAuth2 configuration for an integration"""
    provider: str  # "google", "microsoft", "discord"
    scopes: List[str]
    client_id_env: str  # Environment variable name for client ID
    redirect_uri: str  # e.g., "iris://oauth/callback/gmail"
    authorization_url: Optional[str] = None
    token_url: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            k: v for k, v in self.__dict__.items()
            if v is not None
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'OAuthConfig':
        """Create from dictionary"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class TelegramConfig:
    """Telegram MTProto configuration"""
    api_id_env: str
    api_hash_env: str
    session_storage: str = "encrypted_local"

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            k: v for k, v in self.__dict__.items()
            if v is not None
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'TelegramConfig':
        """Create from dictionary"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CredentialField:
    """Field definition for credentials form"""
    key: str
    label: str
    type: str  # "text", "number", "email", "password"
    default: Optional[Any] = None
    required: bool = True

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            k: v for k, v in self.__dict__.items()
            if v is not None
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'CredentialField':
        """Create from dictionary"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CredentialsConfig:
    """Credentials-based auth configuration (IMAP/SMTP)"""
    fields: List[CredentialField] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "fields": [f.to_dict() for f in self.fields]
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'CredentialsConfig':
        """Create from dictionary"""
        fields = [CredentialField.from_dict(f) for f in data.get("fields", [])]
        return cls(fields=fields)


@dataclass
class MCPServerConfig:
    """MCP server configuration"""
    module: Optional[str] = None  # Path to server module
    binary: str = ""  # Binary name to spawn
    runtime: str = "node"  # "node", "python"
    transport: str = "stdio"
    tools: List[str] = field(default_factory=list)
    install_command: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            k: v for k, v in self.__dict__.items()
            if v is not None
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'MCPServerConfig':
        """Create from dictionary"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class IntegrationConfig:
    """Configuration for an integration (from registry)"""
    id: str
    name: str
    category: str  # "email", "messaging", "productivity"
    icon: str
    auth_type: AuthType
    permissions_summary: str
    enabled_by_default: bool = False

    # Auth configurations (one will be populated based on auth_type)
    oauth: Optional[OAuthConfig] = None
    telegram: Optional[TelegramConfig] = None
    credentials: Optional[CredentialsConfig] = None

    # MCP server configuration
    mcp_server: MCPServerConfig = field(default_factory=MCPServerConfig)

    # Metadata for user-installed integrations
    source: str = "bundled"  # "bundled", "mcp-registry", "github", "local"
    version: Optional[str] = None
    installed_at: Optional[datetime] = None
    registry_name: Optional[str] = None  # For MCP registry sources

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        result = {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "icon": self.icon,
            "auth_type": self.auth_type.value,
            "permissions_summary": self.permissions_summary,
            "enabled_by_default": self.enabled_by_default,
            "mcp_server": self.mcp_server.to_dict(),
            "source": self.source,
        }

        if self.oauth:
            result["oauth"] = self.oauth.to_dict()
        if self.telegram:
            result["telegram"] = self.telegram.to_dict()
        if self.credentials:
            result["credentials"] = self.credentials.to_dict()
        if self.version:
            result["version"] = self.version
        if self.installed_at:
            result["installed_at"] = self.installed_at.isoformat()
        if self.registry_name:
            result["registry_name"] = self.registry_name

        return result

    @classmethod
    def from_dict(cls, data: dict) -> 'IntegrationConfig':
        """Create from dictionary"""
        # Parse auth type
        auth_type = AuthType(data.get("auth_type", "oauth2"))

        # Parse nested configs
        oauth = OAuthConfig.from_dict(data["oauth"]) if "oauth" in data else None
        telegram = TelegramConfig.from_dict(data["telegram"]) if "telegram" in data else None
        credentials = CredentialsConfig.from_dict(data["credentials"]) if "credentials" in data else None
        mcp_server = MCPServerConfig.from_dict(data.get("mcp_server", {}))

        # Parse datetime
        installed_at = None
        if "installed_at" in data and data["installed_at"]:
            if isinstance(data["installed_at"], str):
                installed_at = datetime.fromisoformat(data["installed_at"])
            else:
                installed_at = data["installed_at"]

        return cls(
            id=data["id"],
            name=data["name"],
            category=data["category"],
            icon=data["icon"],
            auth_type=auth_type,
            permissions_summary=data["permissions_summary"],
            enabled_by_default=data.get("enabled_by_default", False),
            oauth=oauth,
            telegram=telegram,
            credentials=credentials,
            mcp_server=mcp_server,
            source=data.get("source", "bundled"),
            version=data.get("version"),
            installed_at=installed_at,
            registry_name=data.get("registry_name"),
        )


@dataclass
class CredentialPayload:
    """
    Unified credential payload structure.
    Same structure regardless of auth type or encryption backend.
    """
    integration_id: str
    auth_type: str  # "oauth2", "telegram_mtproto", "credentials"

    # OAuth2 fields
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_at: Optional[int] = None  # Unix timestamp
    scope: Optional[str] = None

    # Telegram MTProto
    session_string: Optional[str] = None

    # Credentials (IMAP/SMTP)
    imap_host: Optional[str] = None
    imap_port: Optional[int] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    email: Optional[str] = None
    password: Optional[str] = None

    # Common metadata
    created_at: int = field(default_factory=lambda: int(datetime.now().timestamp()))
    revocable: bool = False
    revoke_url: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            k: v for k, v in self.__dict__.items()
            if v is not None
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'CredentialPayload':
        """Create from dictionary"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class IntegrationState:
    """Runtime state for an integration (not persisted)"""
    integration_id: str
    status: IntegrationStatus
    connected_account: Optional[str] = None  # e.g., "user@gmail.com"
    connected_at: Optional[datetime] = None
    error_message: Optional[str] = None
    restart_attempts: int = 0
    last_restart: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        result = {
            "integration_id": self.integration_id,
            "status": self.status.value,
            "restart_attempts": self.restart_attempts,
        }

        if self.connected_account:
            result["connected_account"] = self.connected_account
        if self.connected_at:
            result["connected_at"] = self.connected_at.isoformat()
        if self.error_message:
            result["error_message"] = self.error_message
        if self.last_restart:
            result["last_restart"] = self.last_restart.isoformat()

        return result

    @classmethod
    def from_dict(cls, data: dict) -> 'IntegrationState':
        """Create from dictionary"""
        status = IntegrationStatus(data.get("status", "disabled"))

        connected_at = None
        if "connected_at" in data and data["connected_at"]:
            connected_at = datetime.fromisoformat(data["connected_at"])

        last_restart = None
        if "last_restart" in data and data["last_restart"]:
            last_restart = datetime.fromisoformat(data["last_restart"])

        return cls(
            integration_id=data["integration_id"],
            status=status,
            connected_account=data.get("connected_account"),
            connected_at=connected_at,
            error_message=data.get("error_message"),
            restart_attempts=data.get("restart_attempts", 0),
            last_restart=last_restart,
        )
