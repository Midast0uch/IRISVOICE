# Design: Iris MCP Integration Layer

## Overview

The Iris MCP Integration Layer extends the existing MCP infrastructure to support external service integrations (Gmail, Outlook, Telegram, Discord, IMAP/SMTP) with secure credential management, multiple authentication flows, and a unified marketplace for discovering and installing new MCP servers.

**Key Architectural Decisions:**
- Extend existing `backend/mcp/` module rather than replace it
- Use AES-256-GCM encryption with OS keychain-derived keys (Phase 1)
- All MCP servers communicate via stdio transport (no network exposure)
- Credentials passed to servers via environment variables only
- Modular auth flow system supporting OAuth2, MTProto, and direct credentials
- Future-proof design for Torus Dilithium identity layer upgrade

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           IRIS APPLICATION                                   │
│                                                                              │
│  ┌─────────────────────┐    ┌─────────────────────────────────────────┐     │
│  │   Integrations UI   │    │         Integration Manager            │     │
│  │  - IntegrationsScreen │◄──►│  - RegistryLoader                      │     │
│  │  - IntegrationDetail  │    │  - LifecycleManager                    │     │
│  │  - AuthFlowModal      │    │  - AuthFlowManager                     │     │
│  │  - MarketplaceScreen  │    │  - CredentialStore                     │     │
│  └─────────────────────┘    └─────────────────────────────────────────┘     │
│            │                              │                                  │
│            │ WebSocket                    │                                  │
│            ▼                              ▼                                  │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │                         Backend (Python)                         │        │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────┐ │        │
│  │  │MCP Host/Router│  │  Registry   │  │  Auth Flows │  │ Marketplace│ │        │
│  │  │(existing)    │◄─┤   Loader    │◄─┤  - OAuth2   │◄─┤  Client    │ │        │
│  │  └──────┬──────┘  └─────────────┘  │  - MTProto  │  └──────────┘ │        │
│  │         │                           │  - Credentials            │        │
│  │         │ stdio                     └─────────────┘             │        │
│  │         ▼                                                      │        │
│  │  ┌─────────────────────────────────────────────────────────────┐│        │
│  │  │              MCP Server Processes (Child)                    ││        │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       ││        │
│  │  │  │  Gmail   │ │  Outlook │ │ Telegram │ │  IMAP/   │       ││        │
│  │  │  │  Server  │ │  Server  │ │  Server  │ │  SMTP    │       ││        │
│  │  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘       ││        │
│  │  │       │            │            │            │              ││        │
│  │  └───────┼────────────┼────────────┼────────────┼──────────────┘│        │
│  │          │            │            │            │               │        │
│  └──────────┼────────────┼────────────┼────────────┼───────────────┘        │
│             │            │            │            │                        │
│             ▼            ▼            ▼            ▼                        │
│       Google API    Microsoft    Telegram     Mail Server                  │
│                     Graph API    MTProto      (IMAP/SMTP)                  │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                      CredentialStore                                   │  │
│  │  - OS Keychain (Phase 1) / Torus Identity (Future)                    │  │
│  │  - AES-256-GCM encryption                                             │  │
│  │  - ~/.iris/credentials/*.enc                                          │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### State Machine Per Integration

```
                    ┌─────────────┐
    ┌───────────────┤  DISABLED   │◄─────────────────────────────┐
    │               └──────┬──────┘                              │
    │                      │ User toggles ON                     │
    │               ┌──────▼──────┐                              │
    │               │ AUTH_PENDING │                             │
    │               └──────┬──────┘                              │
    │                      │ Auth flow completes                 │
    │    ┌─────────────────▼─────────────────┐                   │
    │    │           RUNNING                 │                   │
    │    │  (MCP server spawned, tools       │                   │
    │    │   available to agent)             │                   │
    │    └─────────────────┬─────────────────┘                   │
    │                      │                                     │
    │    ┌─────────────────┼─────────────────┐                   │
    │    │                 │                 │                   │
    │    ▼                 ▼                 ▼                   │
    │ Credential      User toggles      Crash detected           │
    │ expires          OFF               (>3 restarts)           │
    │    │                 │                 │                     │
    │    ▼                 │                 ▼                     │
    │ ┌──────────┐         │           ┌─────────┐                │
    │ │REAUTH_   │◄────────┘           │  ERROR  │──► Reconnect  │
    │ │PENDING   │                       └─────────┘    prompt    │
    │ └──────────┘                                                 │
    │                                                              │
    │                     ┌──────────┐                            │
    └────────────────────►│  WIPED   │◄───────────────────────────┘
      Disconnect & Forget └──────────┘
      (credentials deleted)
```

## Data Models

### Integration Registry Schema

```python
# backend/integrations/models.py

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime


class AuthType(str, Enum):
    OAUTH2 = "oauth2"
    TELEGRAM_MTPROTO = "telegram_mtproto"
    CREDENTIALS = "credentials"


class IntegrationStatus(str, Enum):
    DISABLED = "disabled"
    AUTH_PENDING = "auth_pending"
    RUNNING = "running"
    ERROR = "error"
    REAUTH_PENDING = "reauth_pending"


@dataclass
class OAuthConfig:
    provider: str  # "google", "microsoft", "discord"
    scopes: List[str]
    client_id_env: str  # Environment variable name for client ID
    redirect_uri: str  # e.g., "iris://oauth/callback/gmail"
    authorization_url: Optional[str] = None
    token_url: Optional[str] = None


@dataclass
class TelegramConfig:
    api_id_env: str
    api_hash_env: str
    session_storage: str = "encrypted_local"


@dataclass
class CredentialField:
    key: str
    label: str
    type: str  # "text", "number", "email", "password"
    default: Optional[Any] = None
    required: bool = True


@dataclass
class CredentialsConfig:
    fields: List[CredentialField]


@dataclass
class MCPServerConfig:
    module: Optional[str] = None  # Path to server module
    binary: str  # Binary name to spawn
    runtime: str = "node"  # "node", "python"
    transport: str = "stdio"
    tools: List[str] = field(default_factory=list)
    install_command: Optional[str] = None


@dataclass
class IntegrationConfig:
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
```

### Credential Payload Schema

```python
# backend/integrations/credential_store.py

from dataclasses import dataclass
from typing import Optional
from datetime import datetime


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
```

### Encrypted File Format

```python
# Stored at ~/.iris/credentials/{integration_id}.enc

{
    "iv": "<hex-encoded 12-byte initialization vector>",
    "tag": "<hex-encoded 16-byte authentication tag>",
    "data": "<hex-encoded encrypted ciphertext>",
    "version": 1  # For future migration support
}
```

## API / Interface Changes

### WebSocket Messages (Frontend ↔ Backend)

```typescript
// New message types for integration management

type IntegrationMessageType =
  | "integration_list"
  | "integration_toggle"
  | "integration_status"
  | "integration_detail"
  | "auth_flow_start"
  | "auth_flow_callback"
  | "auth_flow_complete"
  | "marketplace_search"
  | "marketplace_install"
  | "integration_disconnect";

// Request: Get list of all integrations
interface IntegrationListRequest {
  type: "integration_list";
}

// Response: List of integrations with current state
interface IntegrationListResponse {
  type: "integration_list";
  integrations: IntegrationListItem[];
}

interface IntegrationListItem {
  id: string;
  name: string;
  category: string;
  icon: string;
  status: "disabled" | "auth_pending" | "running" | "error" | "reauth_pending";
  connectedAccount?: string;
  permissionsSummary: string;
  enabledByDefault: boolean;
  hasCredentials: boolean;
}

// Request: Toggle integration on/off
interface IntegrationToggleRequest {
  type: "integration_toggle";
  integrationId: string;
  enabled: boolean;
  forgetCredentials?: boolean;  // For "Disconnect & Forget"
}

// Request: Start auth flow
interface AuthFlowStartRequest {
  type: "auth_flow_start";
  integrationId: string;
  authType: "oauth2" | "telegram_mtproto" | "credentials";
}

// Response: Auth flow initiated (e.g., OAuth URL for browser)
interface AuthFlowStartResponse {
  type: "auth_flow_start";
  integrationId: string;
  authType: string;
  // OAuth2
  authorizationUrl?: string;
  // MTProto
  phoneRequired?: boolean;
  // Credentials
  fields?: CredentialField[];
}

// Request: Submit auth callback (OAuth deep link)
interface AuthFlowCallbackRequest {
  type: "auth_flow_callback";
  integrationId: string;
  code: string;  // OAuth authorization code
  state?: string;
}

// Request: Submit phone number (Telegram)
interface TelegramPhoneRequest {
  type: "auth_flow_telegram_phone";
  integrationId: string;
  phoneNumber: string;
}

// Request: Submit verification code (Telegram)
interface TelegramCodeRequest {
  type: "auth_flow_telegram_code";
  integrationId: string;
  code: string;
}

// Request: Submit credentials (IMAP/SMTP)
interface CredentialsSubmitRequest {
  type: "auth_flow_credentials_submit";
  integrationId: string;
  credentials: {
    imap_host?: string;
    imap_port?: number;
    smtp_host?: string;
    smtp_port?: number;
    email?: string;
    password?: string;
    [key: string]: any;
  };
}

// Marketplace
interface MarketplaceSearchRequest {
  type: "marketplace_search";
  query?: string;
  category?: string;
  limit?: number;
}

interface MarketplaceSearchResponse {
  type: "marketplace_search";
  servers: MarketplaceServer[];
  hasMore: boolean;
}

interface MarketplaceServer {
  id: string;
  name: string;
  description: string;
  category: string;
  version: string;
  source: "official" | "community";
  installCommand: string;
  packageManager: "npm" | "pip";
  permissionsSummary: string;
  sizeEstimate?: string;
}

interface MarketplaceInstallRequest {
  type: "marketplace_install";
  serverId: string;
}
```

### Python Class Interfaces

```python
# backend/integrations/credential_store.py

class CredentialStore:
    """
    Secure credential storage with AES-256-GCM encryption.
    Interface is stable across Phase 1 (OS Keychain) and Phase 2 (Torus Identity).
    """
    
    async def save(self, integration_id: str, credential: CredentialPayload) -> None:
        """Encrypt and store credential"""
        pass
    
    async def load(self, integration_id: str) -> Optional[CredentialPayload]:
        """Retrieve and decrypt credential"""
        pass
    
    async def wipe(self, integration_id: str) -> None:
        """Delete stored credential and revoke if applicable"""
        pass
    
    async def exists(self, integration_id: str) -> bool:
        """Check if credential exists"""
        pass
    
    async def _get_encryption_key(self, integration_id: str) -> bytes:
        """
        Get or derive encryption key for this integration.
        THIS IS THE ONLY METHOD THAT CHANGES IN FUTURE UPGRADES.
        Phase 1: OS keychain via keyring
        Phase 2: HKDF from Dilithium private key
        """
        pass


# backend/integrations/lifecycle_manager.py

class IntegrationLifecycleManager:
    """
    Manages MCP server process lifecycle.
    Spawns/kills servers based on user toggle state.
    """
    
    def __init__(
        self,
        credential_store: CredentialStore,
        mcp_host: MCPHost,
        registry: IntegrationRegistry
    ):
        self._processes: Dict[str, asyncio.subprocess.Process] = {}
        self._states: Dict[str, IntegrationState] = {}
    
    async def enable(self, integration_id: str) -> bool:
        """
        Enable integration: load credentials, spawn MCP server.
        Returns True if successfully started.
        """
        pass
    
    async def disable(self, integration_id: str, forget_credentials: bool = False) -> None:
        """
        Disable integration: kill process, clear memory.
        If forget_credentials=True, also wipe stored credentials.
        """
        pass
    
    async def handle_crash(self, integration_id: str) -> None:
        """Handle server crash with retry logic"""
        pass
    
    def get_state(self, integration_id: str) -> IntegrationState:
        """Get current runtime state"""
        pass


# backend/integrations/auth_flow_manager.py

class AuthFlowManager:
    """
    Manages authentication flows for different auth types.
    """
    
    async def start_oauth_flow(
        self,
        integration_id: str,
        config: OAuthConfig
    ) -> str:
        """Start OAuth2 flow, return authorization URL"""
        pass
    
    async def handle_oauth_callback(
        self,
        integration_id: str,
        code: str,
        state: str
    ) -> CredentialPayload:
        """Exchange code for tokens, return credential payload"""
        pass
    
    async def start_telegram_flow(
        self,
        integration_id: str,
        config: TelegramConfig
    ) -> None:
        """Initiate Telegram MTProto flow"""
        pass
    
    async def submit_telegram_phone(
        self,
        integration_id: str,
        phone_number: str
    ) -> bool:
        """Submit phone number, request code"""
        pass
    
    async def submit_telegram_code(
        self,
        integration_id: str,
        code: str
    ) -> CredentialPayload:
        """Submit verification code, return session"""
        pass
    
    async def test_and_save_credentials(
        self,
        integration_id: str,
        credentials: dict
    ) -> CredentialPayload:
        """Test IMAP/SMTP credentials, return payload if valid"""
        pass


# backend/integrations/marketplace_client.py

class MarketplaceClient:
    """
    Client for querying MCP Registry and managing installations.
    """
    
    REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0"
    
    async def search(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 20
    ) -> List[MarketplaceServer]:
        """Search MCP Registry for servers"""
        pass
    
    async def get_server_details(self, server_name: str) -> MarketplaceServer:
        """Get full details for a specific server"""
        pass
    
    async def install(self, server: MarketplaceServer) -> IntegrationConfig:
        """
        Install server via npm/pip, create registry entry.
        Returns new IntegrationConfig.
        """
        pass
    
    async def check_updates(self) -> List[UpdateInfo]:
        """Check installed community servers for updates"""
        pass
```

## Sequence Diagrams

### OAuth2 Authentication Flow (Gmail Example)

```
┌─────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐  ┌────────┐  ┌──────────┐
│User │  │Integrations│  │Lifecycle │  │AuthFlowManager│  │Browser │  │Google   │
│     │  │  Screen   │  │ Manager  │  │              │  │        │  │OAuth    │
└──┬──┘  └─────┬────┘  └─────┬────┘  └──────┬───────┘  └───┬────┘  └────┬─────┘
   │           │             │              │              │            │
   │ Toggle ON │             │              │              │            │
   │──────────>│             │              │              │            │
   │           │             │              │              │            │
   │           │ enable("gmail")            │              │            │
   │           │────────────>│              │              │            │
   │           │             │              │              │            │
   │           │             │ Check for credentials      │            │
   │           │             │──────────────┼─────────────>│            │
   │           │             │              │              │            │
   │           │             │ No credentials found       │            │
   │           │             │<─────────────┼──────────────│            │
   │           │             │              │              │            │
   │           │ Status: AUTH_PENDING       │              │            │
   │           │<────────────│              │              │            │
   │           │             │              │              │            │
   │ Show permissions summary               │              │            │
   │<──────────│             │              │              │            │
   │           │             │              │              │            │
   │ Confirm   │             │              │              │            │
   │──────────>│             │              │              │            │
   │           │             │              │              │            │
   │           │ start_oauth_flow()        │              │            │
   │           │──────────────────────────>│              │            │
   │           │             │              │              │            │
   │           │             │              │ Build auth URL            │
   │           │             │              │              │            │
   │           │ Authorization URL         │              │            │
   │           │<──────────────────────────│              │            │
   │           │             │              │              │            │
   │ Open browser with URL                  │              │            │
   │<──────────│             │              │              │            │
   │           │             │              │              │            │
   │           │             │              │              │───────────>│
   │           │             │              │              │  User logs │
   │           │             │              │              │  in and    │
   │           │             │              │              │  approves  │
   │           │             │              │              │<───────────│
   │           │             │              │              │            │
   │           │             │              │              │ Redirect   │
   │           │             │              │              │ iris://oauth│
   │           │             │              │              │            │
   │ Deep link intercepted                  │              │            │
   │<──────────├─────────────┼─────────────┼──────────────┤            │
   │           │             │              │              │            │
   │ auth_flow_callback(code)              │              │            │
   │──────────>│             │              │              │            │
   │           │             │              │              │            │
   │           │ handle_oauth_callback()   │              │            │
   │           │──────────────────────────>│              │            │
   │           │             │              │              │            │
   │           │             │              │ Exchange code for tokens  │
   │           │             │              │─────────────────────────>│
   │           │             │              │              │            │
   │           │             │              │ Tokens received           │
   │           │             │              │<─────────────────────────│
   │           │             │              │              │            │
   │           │             │              │ Encrypt and store         │
   │           │             │              │──────────────┼───────────>│
   │           │             │              │              │            │
   │           │             │ enable("gmail")  (retry with credentials)
   │           │             │<─────────────┼──────────────┤            │
   │           │             │              │              │            │
   │           │             │ Spawn MCP server with env credential    │
   │           │             │─────────────┼──────────────┼───────────>│
   │           │             │              │              │            │
   │           │ Status: RUNNING           │              │            │
   │           │<────────────│              │              │            │
   │           │             │              │              │            │
   │ Update UI │             │              │              │            │
   │<──────────│             │              │              │            │
```

### Tool Call Routing

```
┌─────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐
│Agent│  │ MCP Host │  │Lifecycle │  │Gmail MCP │  │ Google API │
│     │  │ (Router) │  │ Manager  │  │  Server  │  │            │
└──┬──┘  └─────┬────┘  └─────┬────┘  └─────┬────┘  └─────┬──────┘
   │           │             │             │             │
   │ Call tool:gmail_send    │             │             │
   │──────────>│             │             │             │
   │           │             │             │             │
   │           │ Route to "gmail" server   │             │
   │           │────────────>│             │             │
   │           │             │             │             │
   │           │             │ Forward via stdio         │
   │           │             │────────────>│             │
   │           │             │             │             │
   │           │             │             │ Make API call
   │           │             │             │────────────>│
   │           │             │             │             │
   │           │             │             │ API Response│
   │           │             │             │<────────────│
   │           │             │             │             │
   │           │             │             │ Return result
   │           │             │<────────────│             │
   │           │             │             │             │
   │           │ Return result             │             │
   │<──────────│             │             │             │
```

## Key Design Decisions

### 1. Credential Storage Architecture
**Choice:** AES-256-GCM with OS keychain-derived keys (Phase 1), pluggable for Torus identity

**Rationale:**
- AES-256-GCM provides authenticated encryption (confidentiality + integrity)
- OS keychain is widely supported (macOS Keychain, Windows DPAPI, Linux libsecret)
- Single method `_getEncryptionKey()` abstraction allows future upgrade to Dilithium
- No dependencies on external key management services in Phase 1

**Alternatives considered:**
- Fernet (from cryptography library): Good but lacks authentication tag flexibility
- Plain OS keychain storage: Limits credential size, less portable
- File-based encrypted SQLite: Adds complexity, no key derivation

### 2. Process Isolation Model
**Choice:** Each MCP server runs as separate child process via stdio

**Rationale:**
- Process isolation prevents credential leakage between integrations
- stdio transport is simplest and most secure (no network ports)
- Environment variable passing avoids temp files
- Aligns with MCP specification best practices

**Alternatives considered:**
- In-process Python modules: Sacrifices isolation, harder to support Node.js servers
- WebSocket/HTTP servers: Requires port management, network exposure
- Docker containers: Too heavy for desktop app, adds complexity

### 3. Auth Flow Abstraction
**Choice:** Unified auth flow manager with type-specific handlers

**Rationale:**
- Single interface for UI to interact with (start, submit, cancel)
- Easy to add new auth types (e.g., SAML, OIDC) without UI changes
- Handles flow state internally (phone submitted → waiting for code)
- Clear separation between flow orchestration and protocol details

**Implementation approach:**
```python
# Pseudocode
class AuthFlowManager:
    _flows: Dict[str, AuthFlowHandler] = {
        "oauth2": OAuth2Handler(),
        "telegram_mtproto": TelegramHandler(),
        "credentials": CredentialsHandler()
    }
    
    async def start(self, integration_id: str, auth_type: str):
        return await self._flows[auth_type].start(integration_id)
```

### 4. Registry Loading Strategy
**Choice:** Load and merge bundled + user registries at startup

**Rationale:**
- Bundled registry is read-only, version-controlled with app
- User registry is writable, stores marketplace installations
- Merged view provides unified interface
- IDs must be unique across both sources

**Conflict resolution:**
- User registry entries override bundled entries with same ID
- Prevents bundled updates from breaking user customizations

## Error Handling & Edge Cases

### Authentication Failures

| Scenario | Handling |
|----------|----------|
| OAuth authorization denied | Return to AUTH_PENDING, show error message |
| Invalid OAuth code (expired) | Prompt to retry, restart flow |
| Telegram code timeout | Allow resend, maintain phone number state |
| IMAP connection test fails | Show error, don't store credentials |
| Token refresh fails | Set REAUTH_PENDING, notify user |

### Server Process Failures

| Scenario | Handling |
|----------|----------|
| Spawn fails (binary not found) | Set ERROR status, show install prompt |
| Process crashes | Retry up to 3 times with exponential backoff |
| All retries exhausted | Set ERROR status, show reconnect button |
| Credential env var missing | Log security error, refuse to start |

### Security Edge Cases

| Scenario | Handling |
|----------|----------|
| Credential decryption fails | Raise security exception, prompt re-auth |
| Keychain unavailable | Fallback to passphrase entry, warn user |
| OS suspends/resumes | Re-validate connections, re-auth if needed |
| Concurrent toggle on/off | Queue operations, apply in order |

## Testing Strategy

### Unit Tests

```python
# backend/integrations/tests/test_credential_store.py

class TestCredentialStore:
    async def test_save_and_load_roundtrip(self):
        """Verify encryption/decryption preserves data"""
        
    async def test_wipe_removes_file_and_key(self):
        """Verify wipe deletes both credential file and keychain entry"""
        
    async def test_wrong_key_fails_decryption(self):
        """Verify decryption fails with tampered key"""
        
    async def test_concurrent_access_safe(self):
        """Verify thread-safe concurrent read/write"""

# backend/integrations/tests/test_lifecycle_manager.py

class TestLifecycleManager:
    async def test_enable_spawns_process(self):
        """Verify enable creates subprocess with correct env"""
        
    async def test_disable_kills_process(self):
        """Verify disable sends SIGTERM and cleans up"""
        
    async def test_crash_restart_logic(self):
        """Verify 3 restart attempts then ERROR state"""
        
    async def test_forget_credentials_wipes_storage(self):
        """Verify disable(forget=True) calls wipe"""
```

### Integration Tests

```python
# backend/integrations/tests/test_oauth_flow.py

class TestOAuthFlow:
    async def test_full_oauth_flow_mocked(self):
        """
        Mock Google OAuth endpoints.
        Verify: URL generation → callback handling → token exchange → storage
        """
        
    async def test_oauth_token_refresh(self):
        """Verify automatic token refresh on expiry"""

# backend/integrations/tests/test_end_to_end.py

class TestEndToEnd:
    async def test_gmail_integration_full(self):
        """
        1. Enable Gmail
        2. Complete OAuth flow (mocked)
        3. Verify server spawned
        4. Call gmail_list_inbox tool
        5. Verify response
        6. Disable integration
        7. Verify process killed
        """
```

### E2E Tests (Playwright)

```typescript
// tests/e2e/integrations.spec.ts

test("user can enable and disable Gmail integration", async ({ page }) => {
  // Navigate to integrations screen
  // Toggle Gmail ON
  // Complete OAuth flow (mocked)
  // Verify "Connected" status
  // Toggle OFF
  // Verify "Disabled" status
});

test("marketplace install flow", async ({ page }) => {
  // Open marketplace
  // Search for Slack
  // Click Install
  // Verify confirmation modal
  // Confirm install
  // Verify new integration in list
});
```

### Test Commands

```bash
# Run all integration tests
cd IRISVOICE/backend && python -m pytest integrations/tests/ -v

# Run with coverage
python -m pytest integrations/tests/ --cov=integrations --cov-report=html

# E2E tests
npm run test:e2e
```

## Security & Performance Considerations

### Security

1. **Encryption at Rest**
   - AES-256-GCM with 12-byte IV, 16-byte authentication tag
   - Keys derived from OS keychain (never stored in app)
   - Credentials file unreadable without keychain access

2. **Memory Protection**
   - Credentials passed via env vars, not command line
   - Env vars cleared from memory after server spawn
   - In-memory credentials cleared on app close

3. **Process Isolation**
   - Each integration runs in separate process
   - No shared memory between MCP servers
   - Agent never sees raw credentials

4. **Transport Security**
   - stdio only — no network ports exposed
   - No risk of external network access to MCP servers

5. **OAuth Security**
   - PKCE support for OAuth2 flows
   - State parameter validation
   - Token revocation on disconnect & forget

### Performance

1. **Startup Time**
   - Registry loading: <100ms for 50 integrations
   - Parallel credential existence checks
   - Lazy server spawning (only when enabled)

2. **Runtime Overhead**
   - Each MCP server: ~20-50MB RAM
   - stdio transport: minimal CPU overhead
   - Tool call latency: <10ms routing overhead

3. **Scalability**
   - Supports 20+ concurrent integrations
   - Process pool limits for marketplace installs
   - Background installation with progress updates

4. **Storage**
   - Encrypted credentials: <1KB per integration
   - Registry files: <100KB total
   - Log rotation for MCP server output

### Monitoring

```python
# Key metrics to track
INTEGRATION_METRICS = {
    "integration.start.duration": Histogram,
    "integration.crashes": Counter,
    "integration.auth_failures": Counter,
    "tool.calls.total": Counter,
    "tool.calls.errors": Counter,
    "credential.operations": Counter,
}
```

## UI Consistency Guidelines

The integrations UI must match the existing Iris design language used in [`wheel-view/`](IRISVOICE/components/wheel-view/), [`dashboard-wing.tsx`](IRISVOICE/components/dashboard-wing.tsx), and [`dark-glass-dashboard.tsx`](IRISVOICE/components/dark-glass-dashboard.tsx).

### Visual Design Patterns

#### 1. Glass-Morphism Card Style
All integration cards and panels must use the same glass-morphism treatment:

```tsx
// Background
backgroundColor: "rgba(10, 10, 20, 0.95)"  // or 0.45 for lighter panels
backdropFilter: "blur(16px)"

// Border
border: `1px solid ${glowColor}20`  // 12.5% opacity glow color
borderRadius: "12px"  // or "1.5rem" for larger panels

// Shadow
boxShadow: `
  inset 0 1px 1px rgba(255,255,255,0.05),
  inset 0 -1px 1px rgba(0,0,0,0.5),
  0 0 0 1px rgba(0,0,0,0.8),
  -20px 0 60px rgba(0,0,0,0.5)
`
```

#### 2. HUD Effects Overlay
All panels must include the HUD scanline overlay:

```tsx
<div 
  className="absolute inset-0 pointer-events-none z-10"
  style={{
    background: `
      linear-gradient(180deg, transparent 0%, rgba(255,255,255,0.02) 50%, transparent 100%),
      repeating-linear-gradient(
        0deg,
        transparent,
        transparent 2px,
        rgba(0,0,0,0.03) 2px,
        rgba(0,0,0,0.03) 4px
      )
    `,
    backgroundSize: '100% 100%, 100% 4px',
  }}
/>
```

#### 3. Edge Fresnel Effect
All panels must include the edge glow:

```tsx
<div 
  className="absolute inset-0 pointer-events-none z-20"
  style={{
    background: `
      linear-gradient(90deg, ${glowColor}08 0%, transparent 15%, transparent 85%, ${glowColor}08 100%),
      linear-gradient(0deg, ${glowColor}05 0%, transparent 20%, transparent 80%, ${glowColor}05 100%)
    `,
    borderRadius: '12px',
  }}
/>
```

#### 4. Typography Scale
Use consistent text sizing:

| Element | Size | Weight | Letter Spacing |
|---------|------|--------|----------------|
| Card title | `text-[11px]` | `font-medium` | `tracking-wider` |
| Section header | `text-[9px]` | `font-black` | `tracking-[0.2em]` |
| Button text | `text-[10px]` | `font-bold` | `uppercase tracking-wider` |
| Body text | `text-[10px]` | `font-medium` | - |
| Status text | `text-[8px]` | `font-medium` | `tabular-nums` |

#### 5. Toggle Styling
Toggles must match the dashboard-wing style:

```tsx
<button
  onClick={() => setValue(!value)}
  className="relative w-7 h-3.5 rounded-full transition-colors"
  style={{ backgroundColor: value ? glowColor : 'rgba(255,255,255,0.15)' }}
>
  <motion.span
    className="absolute top-0.5 w-2.5 h-2.5 rounded-full bg-white"
    animate={{ left: value ? '14px' : '2px' }}
    transition={{ type: 'spring', stiffness: 500, damping: 30 }}
  />
</button>
```

#### 6. Button Styling
Primary action buttons use glow color accents:

```tsx
<button
  className="w-full py-1.5 rounded text-[9px] font-medium tracking-wider transition-all"
  style={{
    background: `${glowColor}20`,
    color: glowColor,
    border: `1px solid ${glowColor}40`,
  }}
  onMouseEnter={(e) => {
    e.currentTarget.style.background = `${glowColor}30`;
    e.currentTarget.style.borderColor = `${glowColor}60`;
  }}
  onMouseLeave={(e) => {
    e.currentTarget.style.background = `${glowColor}20`;
    e.currentTarget.style.borderColor = `${glowColor}40`;
  }}
>
  Connect
</button>
```

### Animation Patterns

Use consistent Framer Motion configurations:

```tsx
// Panel entrance
<motion.div
  initial={{ x: 120, opacity: 0, scale: 0.95 }}
  animate={{ x: 0, opacity: 1, scale: 1 }}
  exit={{ x: 120, opacity: 0, scale: 0.95 }}
  transition={{ type: "spring", stiffness: 280, damping: 25, mass: 0.8 }}
/>

// Card hover
<motion.div
  whileHover={{ scale: 1.02 }}
  whileTap={{ scale: 0.98 }}
  transition={{ type: "spring", stiffness: 400, damping: 25 }}
/>

// Content crossfade
<AnimatePresence mode="wait">
  <motion.div
    key={activeTab}
    initial={{ opacity: 0, y: -8 }}
    animate={{ opacity: 1, y: 0 }}
    exit={{ opacity: 0, y: -8 }}
    transition={{ duration: 0.2 }}
  />
</AnimatePresence>
```

### Theme Integration

All components must use the theme system:

```tsx
const { activeTheme } = useNavigation();
const glowColor = activeTheme?.glow || "#00d4ff";
const fontColor = activeTheme?.font || "#ffffff";
```

### Layout Guidelines

1. **Integrations Screen**: Use similar layout to dashboard-wing - fixed position, right side, HUD glass panel
2. **Integration Cards**: Use card style consistent with dark-glass-dashboard field rows
3. **Detail View**: Use side panel pattern like wheel-view's SidePanel
4. **Modals**: Use centered modal with glass-morphism backdrop
5. **Marketplace Grid**: Use responsive grid with consistent card sizing

### Example: Integration Card Component

```tsx
export const IntegrationCard: React.FC<IntegrationCardProps> = ({
  integration,
  isEnabled,
  onToggle,
  glowColor
}) => {
  return (
    <motion.div
      className="relative rounded-xl overflow-hidden"
      style={{
        backgroundColor: "rgba(0, 0, 0, 0.45)",
        backdropFilter: "blur(16px)",
        border: `1px solid ${glowColor}20`,
      }}
      whileHover={{ scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
    >
      {/* HUD overlay */}
      <div className="absolute inset-0 pointer-events-none z-10"
        style={{
          background: `linear-gradient(180deg, transparent 0%, rgba(255,255,255,0.02) 50%, transparent 100%)`,
        }}
      />
      
      {/* Edge glow */}
      <div className="absolute inset-0 pointer-events-none z-20"
        style={{
          background: `linear-gradient(90deg, ${glowColor}08 0%, transparent 15%, transparent 85%, ${glowColor}08 100%)`,
          borderRadius: '12px',
        }}
      />
      
      {/* Content */}
      <div className="relative z-30 p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <IntegrationIcon icon={integration.icon} glowColor={glowColor} />
          <div>
            <span className="text-[11px] font-medium tracking-wider text-white/90">
              {integration.name}
            </span>
            <p className="text-[8px] text-white/50 mt-0.5">
              {integration.status}
            </p>
          </div>
        </div>
        
        <Toggle 
          value={isEnabled} 
          onChange={onToggle} 
          glowColor={glowColor} 
        />
      </div>
    </motion.div>
  );
};
```

## File Structure

```
IRISVOICE/
├── backend/
│   ├── mcp/                          # Existing MCP module
│   │   ├── __init__.py
│   │   ├── server_manager.py         # Extended for external servers
│   │   └── ...
│   │
│   └── integrations/                 # NEW MODULE
│       ├── __init__.py
│       ├── models.py                 # Data classes
│       ├── registry_loader.py        # Load/merge registries
│       ├── credential_store.py       # Encryption/decryption
│       ├── lifecycle_manager.py      # Process spawn/kill
│       ├── auth_flow_manager.py      # Auth orchestration
│       ├── auth/
│       │   ├── oauth2_handler.py     # OAuth2 flow
│       │   ├── telegram_handler.py   # MTProto flow
│       │   └── credentials_handler.py # IMAP/SMTP flow
│       ├── marketplace_client.py     # MCP Registry API
│       ├── installer_service.py      # npm/pip install
│       └── tests/
│           ├── test_credential_store.py
│           ├── test_lifecycle_manager.py
│           └── test_auth_flows.py
│
├── IRISVOICE/frontend/
│   ├── components/
│   │   └── integrations/             # NEW COMPONENTS
│   │       ├── IntegrationsScreen.tsx
│   │       ├── IntegrationCard.tsx
│   │       ├── IntegrationDetail.tsx
│   │       ├── AuthFlowModal.tsx
│   │       ├── OAuthCallbackHandler.tsx
│   │       ├── TelegramAuthForm.tsx
│   │       ├── CredentialsForm.tsx
│   │       ├── MarketplaceScreen.tsx
│   │       ├── MarketplaceCard.tsx
│   │       └── InstallConfirmModal.tsx
│   │
│   └── hooks/
│       └── useIntegrations.ts        # WebSocket integration hooks
│
├── integrations/                     # BUNDLED MCP SERVERS
│   ├── registry.json                 # Bundled integrations
│   └── servers/
│       ├── gmail/
│       │   ├── index.js
│       │   └── package.json
│       ├── outlook/
│       │   ├── index.js
│       │   └── package.json
│       ├── telegram/
│       │   ├── index.py
│       │   └── requirements.txt
│       ├── discord/
│       │   ├── index.js
│       │   └── package.json
│       └── imap/
│           ├── index.js
│           └── package.json
│
└── src-tauri/
    └── src/
        └── main.rs                   # Deep link handling
```

## Implementation Dependencies

### Python Backend
```
# Existing
keyring>=24.0.0          # OS keychain access (already used in biometric.py)
cryptography>=41.0.0     # AES-256-GCM (already used)
httpx>=0.24.0            # HTTP client (already used)
websockets>=11.0         # WebSocket support (already used)

# New for Telegram
Telethon>=1.29.0         # MTProto client (optional, for Telegram only)
```

### Node.js Frontend
```
# Existing
@tauri-apps/api          # Tauri bridge (already installed)
```

### System Requirements
- OS keychain access permissions
- Node.js runtime (for JS MCP servers)
- Python 3.10+ (for Python MCP servers)

## Migration & Future Upgrade Path

### Phase 1 → Phase 2 (Torus Identity)

**What changes:**
```python
# backend/integrations/credential_store.py

# BEFORE (Phase 1)
async def _get_encryption_key(self, integration_id: str) -> bytes:
    SERVICE = 'iris'
    ACCOUNT = f'credential-key-{integration_id}'
    key_hex = await keyring.get_password(SERVICE, ACCOUNT)
    if not key_hex:
        key = os.urandom(32)
        await keyring.set_password(SERVICE, ACCOUNT, key.hex())
    return bytes.fromhex(key_hex)

# AFTER (Phase 2)
async def _get_encryption_key(self, integration_id: str) -> bytes:
    from torus_identity import get_private_key
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    
    dilithium_private_key = await get_private_key()
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=f"iris/credentials/{integration_id}".encode()
    ).derive(dilithium_private_key)
```

**What stays the same:**
- `CredentialStore` public interface
- Credential payload format
- `.enc` file structure
- All MCP servers
- All auth flows
- All UI components

**Migration process:**
1. On first launch with Phase 2, detect existing Phase 1 credentials
2. For each credential:
   - Decrypt with old key (from keyring)
   - Re-encrypt with new key (Dilithium-derived)
   - Store in new format
3. Delete old keyring entries
4. User sees nothing, no re-authentication required

---

## Dual-Interface UI Architecture

### Overview

The MCP Integration Layer uses IRIS's dual-interface architecture:
- **wheel-view Interface**: Orb + SidePanel (155px) for quick integration toggles
- **dashboard-wing Interface**: Panel (280-380px) with Dashboard | Activity | Logs | Marketplace tabs

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           IRIS UI LAYER                                      │
│                                                                              │
│  ┌─────────────────────────┐    ┌─────────────────────────────────────────┐ │
│  │       SidePanel         │    │         dashboard-wing                  │ │
│  │   (155px, right of orb) │    │    (280-380px, right side)              │ │
│  │                         │    │  ┌─────────────────────────────────────┐│ │
│  │  ┌───────────────────┐  │    │  │  [Dashboard] [Activity] [Logs] [Mkt]││ │
│  │  │ IntegrationCard   │  │    │  ├─────────────────────────────────────┤│ │
│  │  │ - Icon + Name     │  │    │  │                                     ││ │
│  │  │ - Toggle Switch   │  │◄───┤  │  Tab Content: Dashboard/Activity/   ││ │
│  │  │ - Status Indicator│  │    │  │  Logs/Marketplace                   ││ │
│  │  └───────────────────┘  │    │  │                                     ││ │
│  │                         │    │  └─────────────────────────────────────┘│ │
│  │  [Browse Marketplace]   │───►│                                         │ │
│  │       (Button)          │    │                                         │ │
│  └─────────────────────────┘    │                                         │ │
│                                 │                                         │ │
│  ┌─────────────────────────┐    │                                         │ │
│  │     AuthFlowModal       │    │                                         │ │
│  │   (Overlay, centered)   │    │                                         │ │
│  │  (OAuth/Phone/Creds)    │    │                                         │ │
│  └─────────────────────────┘    │                                         │ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Interface Navigation Flow

**Entry from wheel-view:**
1. User clicks "Integrations" card → SidePanel shows integration list
2. User clicks "Browse Marketplace" → Opens dashboard-wing → Auto-switches to Marketplace tab
3. wheel-view stays visible (dimmed 60%, scaled 0.85x, blurred 2px)

**Exit from dashboard-wing:**
1. Click X button → Closes wing → Returns to wheel-view
2. Click Iris orb → Closes wing → Returns to wheel-view
3. Press Escape → Closes wing → Returns to wheel-view

### Tab Structure (4 Tabs)

**Tab Type:** `'dashboard' | 'activity' | 'logs' | 'marketplace'`

- **Dashboard**: Existing DarkGlassDashboard (settings/config cards)
- **Activity**: Recent conversations, agent actions, integrations timeline
- **Logs**: System log stream with filtering (DEBUG, INFO, WARN, ERROR)
- **Marketplace**: MCP server discovery and installation

### Activity Panel

**Location:** `IRISVOICE/components/dashboard/ActivityPanel.tsx`

**Content:**
- Recent conversations list (last 10) from episodic memory
- Agent actions timeline (tool usage, integrations enabled/disabled)
- Filter tabs: All, Conversations, Actions, Integrations

```typescript
interface ActivityItem {
  id: string;
  type: 'conversation' | 'action' | 'integration';
  title: string;
  description: string;
  timestamp: Date;
  metadata?: Record<string, any>;
}
```

### Logs Panel

**Location:** `IRISVOICE/components/dashboard/LogsPanel.tsx`

**Content:**
- System log stream (tail -f style)
- Log level filtering (DEBUG, INFO, WARN, ERROR)
- Search/filter logs
- Clear/export buttons
- Error highlighting

```typescript
interface LogEntry {
  id: string;
  timestamp: Date;
  level: 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';
  source: string;
  message: string;
}
```

### Memory System Integration

The MCP Integration Layer integrates with the Memory Foundation:

#### Semantic Memory Storage

```python
# User integration preferences stored via MemoryInterface
memory.update_preference(
    key="integration:gmail:enabled",
    value=True,
    source="user",
    confidence=1.0
)

# Marketplace search patterns
memory.update_preference(
    key="marketplace:search_history",
    value=["email", "calendar", "slack"],
    source="implicit",
    confidence=0.7
)

# Dismissed recommendations
memory.forget_preference("marketplace:recommendation:discord")
```
