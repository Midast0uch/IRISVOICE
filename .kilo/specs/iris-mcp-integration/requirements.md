# Requirements: Iris MCP Integration Layer

## Introduction

This spec covers the implementation of a local MCP (Model Context Protocol) integration layer for Iris. The system manages locally-running MCP servers as child processes, providing users with a unified interface to connect external services (Gmail, Outlook, Telegram, Discord, IMAP/SMTP) through simple toggle interactions. No manual configuration, JSON editing, or port management is required — users see a clean list of services and the infrastructure remains invisible.

## Requirements

### Requirement 1: Integration Registry

**User Story:** As an Iris user, I want to see all available service integrations in a unified list, so that I can easily discover and manage which external services my AI agent can access.

#### Acceptance Criteria

1. WHEN the application starts THE SYSTEM SHALL load and merge `registry.json` (bundled official integrations) and `~/.iris/user-registry.json` (user-installed integrations) into a unified registry
2. THE SYSTEM SHALL support integration entries with the following fields: `id`, `name`, `category`, `icon`, `auth_type`, `permissions_summary`, `enabled_by_default`, `oauth` configuration, `telegram` configuration, `credentials` configuration, and `mcp_server` configuration
3. THE SYSTEM SHALL categorize integrations into groups (e.g., "EMAIL", "MESSAGING", "PRODUCTIVITY") based on the `category` field
4. IF an integration has `enabled_by_default: true` THEN THE SYSTEM SHALL mark it as enabled in the initial state
5. THE SYSTEM SHALL treat bundled and user-installed integrations identically after loading

### Requirement 2: Credential Storage

**User Story:** As an Iris user, I want my service credentials to be securely encrypted, so that my sensitive data is protected even if my device is compromised.

#### Acceptance Criteria

1. THE SYSTEM SHALL provide a `CredentialStore` interface with methods: `save(integrationId, credentialPayload)`, `load(integrationId)`, `wipe(integrationId)`, and `exists(integrationId)`
2. WHEN `CredentialStore.save()` is called THE SYSTEM SHALL encrypt the credential payload using AES-256-GCM before writing to disk
3. THE SYSTEM SHALL derive encryption keys using the OS-native keychain service (macOS Keychain, Windows DPAPI/Credential Store, Linux libsecret/GNOME Keyring) via the `keyring` library
4. IF no key exists for an integration THEN THE SYSTEM SHALL generate a cryptographically random 256-bit key and store it in the OS keychain
5. THE SYSTEM SHALL store encrypted credentials at `~/.iris/credentials/{integrationId}.enc`
6. WHEN the application closes THE SYSTEM SHALL clear all in-memory credentials immediately
7. IF credential decryption fails THE SYSTEM SHALL raise a security exception and prompt for re-authentication

### Requirement 3: MCP Server Lifecycle Management

**User Story:** As an Iris user, I want MCP servers to start automatically when I enable a service and stop when I disable it, so that resources are used efficiently and I don't need to manage processes manually.

#### Acceptance Criteria

1. THE SYSTEM SHALL implement an `IntegrationLifecycleManager` that manages MCP server processes
2. WHEN a user toggles an integration ON AND valid credentials exist THEN THE SYSTEM SHALL spawn the MCP server as a child process with `stdio` transport
3. THE SYSTEM SHALL pass decrypted credentials to the server process via the `IRIS_CREDENTIAL` environment variable at spawn time
4. WHEN a user toggles an integration OFF THEN THE SYSTEM SHALL send `SIGTERM` to the server process and clear in-memory credentials
5. IF `forgetCredentials: true` is specified on toggle-off THEN THE SYSTEM SHALL also call `CredentialStore.wipe()` to delete stored credentials
6. THE SYSTEM SHALL implement crash recovery with up to 3 restart attempts before setting the integration status to `ERROR`
7. WHEN the application closes THE SYSTEM SHALL kill all running MCP server processes
8. THE SYSTEM SHALL register connected servers with the MCP host so tools are available to the agent

### Requirement 4: OAuth2 Authentication Flow

**User Story:** As an Iris user, I want to connect OAuth2-based services (Gmail, Outlook, Discord) through a standard browser-based flow, so that I can securely authorize Iris without sharing my password.

#### Acceptance Criteria

1. WHEN a user toggles ON an OAuth2 integration without stored credentials THEN THE SYSTEM SHALL display a permissions summary screen showing what the integration will be able to do
2. WHEN the user confirms THEN THE SYSTEM SHALL open the system browser to the provider's OAuth authorization URL with configured scopes and redirect URI
3. THE SYSTEM SHALL support deep link handling for `iris://oauth/callback/{integrationId}` URLs
4. WHEN the OAuth callback is received THEN THE SYSTEM SHALL exchange the authorization code for access and refresh tokens
5. THE SYSTEM SHALL store the complete credential payload including `access_token`, `refresh_token`, `expires_at`, `scope`, `revocable`, and `revoke_url`
6. WHEN token exchange succeeds THEN THE SYSTEM SHALL spawn the MCP server and set integration status to `RUNNING`
7. IF the OAuth flow is cancelled or fails THEN THE SYSTEM SHALL return the integration to `DISABLED` state with an error message

### Requirement 5: Telegram MTProto Authentication Flow

**User Story:** As an Iris user, I want to connect Telegram using my phone number and verification code, so that I don't need to use a browser for authentication.

#### Acceptance Criteria

1. WHEN a user toggles ON the Telegram integration without stored credentials THEN THE SYSTEM SHALL display an inline phone number entry form
2. WHEN the user submits their phone number THEN THE SYSTEM SHALL initiate MTProto authentication and request an SMS/in-app code from Telegram
3. THE SYSTEM SHALL display a code entry form for the user to input the verification code
4. WHEN the correct code is submitted THEN THE SYSTEM SHALL generate a session string using Telethon
5. THE SYSTEM SHALL encrypt and store the session string as the credential payload
6. WHEN authentication completes THEN THE SYSTEM SHALL spawn the Telegram MCP server and set status to `RUNNING`

### Requirement 6: Credentials-based Authentication Flow

**User Story:** As an Iris user, I want to connect generic IMAP/SMTP email accounts by directly entering server details and credentials, so that I can use Iris with any email provider.

#### Acceptance Criteria

1. WHEN a user toggles ON the IMAP/SMTP integration without stored credentials THEN THE SYSTEM SHALL display an inline form with fields: IMAP Host, IMAP Port, SMTP Host, SMTP Port, Email Address, and Password
2. THE SYSTEM SHALL support default values for common ports (IMAP: 993, SMTP: 587)
3. WHEN the user submits the form THEN THE SYSTEM SHALL test the connection before storing credentials
4. IF the connection test fails THEN THE SYSTEM SHALL display an error message without storing credentials
5. IF the connection test succeeds THEN THE SYSTEM SHALL encrypt and store the credentials
6. THE SYSTEM SHALL spawn the IMAP MCP server and set status to `RUNNING`

### Requirement 7: Integration Status and Detail View

**User Story:** As an Iris user, I want to see the status of my connected services and manage them individually, so that I can understand what my agent can access and disconnect services when needed.

#### Acceptance Criteria

1. THE SYSTEM SHALL display integration cards showing: name, icon, current status (ON/OFF), and connection details (e.g., "Connected as user@gmail.com")
2. WHEN a user taps an integration card THEN THE SYSTEM SHALL navigate to a detail view
3. THE DETAIL VIEW SHALL display: current status, connected account information, connection date, list of permissions, list of available tools, and OAuth scopes (if applicable)
4. THE SYSTEM SHALL provide a "Disconnect" button that stops the server and clears memory while preserving encrypted credentials
5. THE SYSTEM SHALL provide a "Disconnect & Forget" button that stops the server, clears memory, AND deletes stored credentials
6. WHEN credentials are deleted THEN THE SYSTEM SHALL also revoke OAuth tokens via the `revoke_url` if `revocable: true`

### Requirement 8: MCP Marketplace

**User Story:** As an Iris user, I want to discover and install new MCP servers from a marketplace, so that I can extend my agent's capabilities without manual setup.

#### Acceptance Criteria

1. THE SYSTEM SHALL query the Official MCP Registry at `registry.modelcontextprotocol.io/v0/servers` for available servers
2. THE SYSTEM SHALL merge the Official MCP Registry with the Iris Curated List (bundled with the app)
3. THE MARKETPLACE SHALL display servers in categories with featured integrations highlighted
4. THE SYSTEM SHALL filter servers by transport type, showing only `stdio` servers in User Mode
5. WHEN a user selects a server for installation THEN THE SYSTEM SHALL display an installation confirmation modal with: source, package name and version, size estimate, and permissions summary
6. THE SYSTEM SHALL support installation via npm (`npm install -g {package}`) or pip (`pip install {package}`)
7. WHEN installation completes THEN THE SYSTEM SHALL automatically generate a registry entry in `~/.iris/user-registry.json` and launch the appropriate auth flow
8. THE SYSTEM SHALL check for available updates on startup and display an "Update Available" badge on installed community servers

### Requirement 9: Agent Tool Access

**User Story:** As an Iris user, I want my AI agent to automatically access tools from connected integrations, so that it can perform tasks on my behalf without manual configuration.

#### Acceptance Criteria

1. WHEN an MCP server is running THEN THE SYSTEM SHALL expose its tools to the agent through the MCP host
2. THE AGENT SHALL call tools by name (e.g., `gmail_send`) with arguments, without handling raw credentials
3. THE MCP HOST SHALL route tool calls to the appropriate server process and return responses
4. THE SYSTEM SHALL validate tool calls against the permissions granted during authentication
5. IF a tool call fails due to authentication THEN THE SYSTEM SHALL set the integration status to `REAUTH_PENDING` and notify the user

### Requirement 10: Dual-Interface UI Integration

**User Story:** As an Iris user, I want to manage my integrations from both the wheel-view SidePanel and the dashboard-wing marketplace, with seamless navigation between the two interfaces.

#### Acceptance Criteria

1. THE SYSTEM SHALL display active integrations in the wheel-view SidePanel when the user selects the "Integrations" card
2. THE SYSTEM SHALL show integration toggles as compact cards (icon, name, status toggle) in wheel-view SidePanel
3. THE SYSTEM SHALL display a "Browse Marketplace" button at the bottom of the integration list
4. WHEN the user clicks "Browse Marketplace" in wheel-view THE SYSTEM SHALL:
   - OPEN dashboard-wing (if closed)
   - SWITCH dashboard-wing to Marketplace tab
   - Keep wheel-view visible (dimmed/scaled in background)
5. THE SYSTEM SHALL support tab switching within dashboard-wing (Dashboard | Activity | Logs | Marketplace)
6. THE SYSTEM SHALL provide an X (Close) button in dashboard-wing header to close the wing and return to wheel-view
7. WHEN the user clicks the Iris orb while dashboard-wing is open THE SYSTEM SHALL close dashboard-wing and return to wheel-view
8. THE SYSTEM SHALL synchronize integration state between wheel-view and dashboard-wing in real-time via WebSocket

### Requirement 11: Activity and Logs Panels

**User Story:** As an Iris user, I want to view my recent activity and system logs in the dashboard-wing, so I can monitor what my agent has been doing.

#### Acceptance Criteria

1. THE SYSTEM SHALL provide an "Activity" tab in dashboard-wing showing:
   - Recent conversations list (last 10)
   - Agent actions timeline (tool usage, integrations enabled/disabled)
   - Filter by: All, Conversations, Actions, Integrations
2. THE SYSTEM SHALL provide a "Logs" tab in dashboard-wing showing:
   - System log stream (tail -f style)
   - Log level filtering (DEBUG, INFO, WARN, ERROR)
   - Search/filter functionality
   - Clear and export buttons
3. THE SYSTEM SHALL pull Activity data from episodic memory via WebSocket
4. THE SYSTEM SHALL stream Logs from the backend logging system via WebSocket

### Requirement 12: Memory System Integration

**User Story:** As an Iris user, I want my integration preferences to be remembered and learned from, so that my agent understands which services I prefer.

#### Acceptance Criteria

1. THE SYSTEM SHALL store user integration preferences in semantic memory via `MemoryInterface.update_preference()`
2. THE SYSTEM SHALL store: frequently used integrations, preferred auth methods, marketplace search history
3. WHEN the user enables an integration THE SYSTEM SHALL record it as a preference with source="user"
4. THE SYSTEM SHALL use semantic memory to suggest relevant integrations in marketplace ("Users like you also installed...")
5. THE SYSTEM SHALL remember dismissed marketplace recommendations via `forget_preference()`
6. THE SYSTEM SHALL NOT store credentials in memory - only preference metadata

### Requirement 13: Security Model

**User Story:** As a security-conscious user, I want multiple layers of protection for my credentials and data, so that even if one layer is compromised, my sensitive information remains secure.

#### Acceptance Criteria

1. THE SYSTEM SHALL encrypt all credentials at rest using AES-256-GCM with OS keychain-derived keys
2. THE SYSTEM SHALL pass decrypted credentials to MCP servers only via environment variables, never via files or command-line arguments
3. THE AGENT SHALL NEVER have direct access to raw credentials — only to tool call interfaces
4. THE SYSTEM SHALL isolate MCP server processes — each server runs as a separate child process
5. ALL MCP SERVERS SHALL communicate over stdio transport — no network ports exposed
6. THE SYSTEM SHALL display clear permission summaries before any authentication flow
7. THE SYSTEM SHALL support future upgrade to Torus Dilithium-based encryption without changing interfaces (see Future Upgrade section)

## Future Upgrade: Torus Identity Layer (Phase 2)

**Note:** This section documents a planned future enhancement, not Phase 1 requirements.

1. THE SYSTEM SHALL be architected such that only the `_getEncryptionKey()` method in `CredentialStore` changes when upgrading to Torus Dilithium-based encryption
2. ALL OTHER COMPONENTS SHALL remain unchanged: `CredentialStore` interface, credential payload format, `.enc` file structure, `LifecycleManager`, MCP servers, auth flows, and UI components
3. WHEN the Torus identity layer is integrated THEN THE SYSTEM SHALL derive AES encryption keys using HKDF-SHA256 from the Dilithium private key
4. THE SYSTEM SHALL support automatic migration of existing credentials from OS keychain keys to Dilithium-derived keys on first launch after upgrade
