# Implementation Plan: Iris MCP Integration Layer

## Summary

- **20 task groups** organized by dependency
- **70+ individual tasks** covering backend, frontend, and testing
- All 42 acceptance criteria from requirements.md covered
- Estimated implementation sequence follows integration plan Section 12

**Current Status:**
- **Phase 1 (Foundation)**: ✅ Complete - CredentialStore, Registry Loader
- **Phase 2 (Backend Core)**: ✅ Complete - Lifecycle Manager, Auth Infrastructure
- **Phase 3 (Authentication)**: ✅ Complete - OAuth2, Telegram, Credentials handlers
- **Phase 4 (MCP Host)**: ✅ Complete - All MCP servers (Gmail, Outlook, Telegram, Discord, IMAP)
- **Phase 5 (WebSocket API)**: ✅ Complete - All handlers implemented, Tauri deep links
- **Phase 6 (Frontend UI)**: ✅ Complete - IntegrationsScreen, AuthFlowModal, Marketplace UI
- **Phase 7 (Dual-Interface)**: ✅ Complete - SidePanel integration, Dashboard tabs, Activity/Logs panels
- **Phase 8 (Memory System)**: ✅ Complete - Preference storage, recommendations, WebSocket handlers
- **Phase 9 (Testing)**: ✅ Complete - Unit tests, E2E tests, memory integration tests
- **Phase 10 (Documentation)**: ✅ Complete - MCP Integration README, WebSocket API docs

---

## Phase 1: Foundation

### 1.1 CredentialStore Core

- [x] 1.1.1 Create `CredentialPayload` dataclass
  - What to build: Define dataclass with all OAuth2, MTProto, and credentials fields
  - Files: `backend/integrations/models.py`
  - _Requirements: 2.2, 2.6_
  - <!-- done: CredentialPayload dataclass with all auth type fields -->

- [x] 1.1.2 Implement AES-256-GCM encryption utilities
  - What to build: `encrypt_data()` and `decrypt_data()` helper functions
  - Files: `backend/integrations/credential_store.py`
  - _Requirements: 2.2_
  - <!-- done: AES-256-GCM encryption with 12-byte IV and auth tag -->

- [x] 1.1.3 Implement `_getEncryptionKey()` with OS keychain
  - What to build: Key derivation using `keyring` library, generate new key if missing
  - Files: `backend/integrations/credential_store.py`
  - _Requirements: 2.3, 2.4_
  - <!-- done: _get_encryption_key() using keyring for cross-platform keychain -->

- [x] 1.1.4 Implement `CredentialStore.save()`
  - What to build: Encrypt payload and write to `~/.iris/credentials/{integrationId}.enc`
  - Files: `backend/integrations/credential_store.py`
  - _Requirements: 2.1, 2.2_
  - <!-- done: save() method with AES-256-GCM encryption -->

- [x] 1.1.5 Implement `CredentialStore.load()`
  - What to build: Read file, decrypt, return `CredentialPayload`
  - Files: `backend/integrations/credential_store.py`
  - _Requirements: 2.1, 2.2_
  - <!-- done: load() method with decryption and CredentialPayload parsing -->

- [x] 1.1.6 Implement `CredentialStore.wipe()`
  - What to build: Delete credential file and keychain entry, revoke OAuth token if applicable
  - Files: `backend/integrations/credential_store.py`
  - _Requirements: 2.1, 7.5_
  - <!-- done: wipe() method with file deletion and keychain cleanup -->

- [x] 1.1.7 Implement `CredentialStore.exists()`
  - What to build: Check if credential file exists
  - Files: `backend/integrations/credential_store.py`
  - _Requirements: 2.1_
  - <!-- done: exists() method checking file existence -->

- [x] 1.1.8 Write unit tests for CredentialStore
  - Test cases:
    - [x] Save and load roundtrip preserves data
    - [x] Wrong key fails decryption
    - [x] Wipe removes file and keychain entry
    - [x] Concurrent access is thread-safe
  - Run: `python -m pytest backend/integrations/tests/test_credential_store.py -v`
  - _Requirements: 2.1, 2.2, 2.6, 2.7_
  - <!-- done: test_credential_store.py with all test cases passing -->

### 1.2 Registry Loader

- [x] 1.2.1 Create `IntegrationConfig` dataclass
  - What to build: Define all fields from registry schema including OAuth, Telegram, Credentials configs
  - Files: `backend/integrations/models.py`
  - _Requirements: 1.2_
  - <!-- done: IntegrationConfig, OAuthConfig, TelegramConfig, MCPServerConfig dataclasses -->

- [x] 1.2.2 Create bundled registry.json
  - What to build: Registry with Gmail, Outlook, Telegram, Discord, IMAP configurations
  - Files: `integrations/registry.json`
  - _Requirements: 1.1, 1.2_
  - <!-- done: registry.json with all 5 built-in integrations -->

- [x] 1.2.3 Implement RegistryLoader
  - What to build: Load bundled registry + user registry, merge with override logic
  - Files: `backend/integrations/registry_loader.py`
  - _Requirements: 1.1_
  - <!-- done: RegistryLoader class with load_registries() method -->

- [x] 1.2.4 Implement user-registry.json creation
  - What to build: Create `~/.iris/user-registry.json` on first use if missing
  - Files: `backend/integrations/registry_loader.py`
  - _Requirements: 1.1, 8.7_
  - <!-- done: Automatic creation with ensure_user_registry() -->

- [x] 1.2.5 Write tests for RegistryLoader
  - Test cases:
    - [x] Loads bundled registry correctly
    - [x] Merges user registry entries
    - [x] User entries override bundled
    - [x] Handles missing files gracefully
  - _Requirements: 1.1, 1.2_
  - <!-- done: test_registry_loader.py with all test cases -->

---

## Phase 2: Backend Core

### 2.1 Integration State Management

- [x] 2.1.1 Create `IntegrationState` dataclass
  - What to build: Runtime state tracking (status, connected_account, error_message, etc.)
  - Files: `backend/integrations/models.py`
  - _Requirements: 3.7_
  - <!-- done: IntegrationState dataclass with status enum -->

- [x] 2.1.2 Create IntegrationStateManager
  - What to build: In-memory state tracking for all integrations
  - Files: `backend/integrations/lifecycle_manager.py` (state integrated)
  - _Requirements: 3.7_
  - <!-- done: State management integrated into LifecycleManager -->

### 2.2 Lifecycle Manager Core

- [x] 2.2.1 Implement process spawn logic
  - What to build: `asyncio.create_subprocess_exec()` with stdio pipes
  - Files: `backend/integrations/lifecycle_manager.py`
  - _Requirements: 3.2, 3.3_
  - <!-- done: _spawn_process() with stdio transport -->

- [x] 2.2.2 Implement credential environment variable injection
  - What to build: Pass `IRIS_CREDENTIAL` env var to spawned process
  - Files: `backend/integrations/lifecycle_manager.py`
  - _Requirements: 3.3, 10.2_
  - <!-- done: IRIS_CREDENTIAL and IRIS_INTEGRATION_ID env vars -->

- [x] 2.2.3 Implement process monitoring
  - What to build: Monitor stdout/stderr, detect process exit
  - Files: `backend/integrations/lifecycle_manager.py`
  - _Requirements: 3.6_
  - <!-- done: asyncio tasks for stdout/stderr reading -->

- [x] 2.2.4 Implement crash detection and restart logic
  - What to build: Track restart attempts, exponential backoff, set ERROR after 3 failures
  - Files: `backend/integrations/lifecycle_manager.py`
  - _Requirements: 3.6_
  - <!-- done: _handle_exit() with retry tracking and backoff -->

- [x] 2.2.5 Implement graceful shutdown
  - What to build: Send SIGTERM, wait for exit, force kill if needed
  - Files: `backend/integrations/lifecycle_manager.py`
  - _Requirements: 3.4, 3.7_
  - <!-- done: stop_process() with SIGTERM -> SIGKILL escalation -->

- [x] 2.2.6 Implement `enable()` flow
  - What to build: Check credentials exist → decrypt → spawn → register with MCP host
  - Files: `backend/integrations/lifecycle_manager.py`
  - _Requirements: 3.2, 3.8_
  - <!-- done: enable() method with full flow -->

- [x] 2.2.7 Implement `disable()` flow
  - What to build: Kill process → clear memory → optionally wipe credentials
  - Files: `backend/integrations/lifecycle_manager.py`
  - _Requirements: 3.4, 3.5_
  - <!-- done: disable() method with forget option -->

- [x] 2.2.8 Write tests for LifecycleManager
  - Test cases:
    - [x] Enable spawns process with correct env vars
    - [x] Disable kills process
    - [x] Crash triggers restart (up to 3 times)
    - [x] Forget credentials calls wipe
    - [x] Process cleanup on app shutdown
  - _Requirements: 3.2, 3.4, 3.5, 3.6, 3.7_
  - <!-- done: test_lifecycle_manager.py with mocked subprocess -->

### 2.3 Auth Flow Infrastructure

- [x] 2.3.1 Create auth handler base class
  - What to build: Abstract `AuthFlowHandler` with `start()`, `cancel()` methods
  - Files: `backend/integrations/auth_handlers.py`
  - _Requirements: 4.1, 5.1, 6.1_
  - <!-- done: AuthHandler base class with generate_id() helper -->

- [x] 2.3.2 Implement AuthFlowManager orchestrator
  - What to build: Route to appropriate handler based on auth_type, track flow state
  - Files: `backend/integrations/auth_handlers.py`
  - _Requirements: 4.1, 5.1, 6.1_
  - <!-- done: OAuth2Handler, TelegramHandler, CredentialsHandler implementations -->

---

## Phase 3: Authentication Flows

### 3.1 OAuth2 Handler

- [x] 3.1.1 Implement authorization URL generation
  - What to build: Build OAuth URL with scopes, client_id, redirect_uri, PKCE
  - Files: `backend/integrations/auth_handlers.py`
  - _Requirements: 4.2_
  - <!-- done: get_authorization_url() with PKCE code_challenge -->

- [x] 3.1.2 Implement token exchange
  - What to build: Exchange authorization code for access/refresh tokens
  - Files: `backend/integrations/auth_handlers.py`
  - _Requirements: 4.4_
  - <!-- done: exchange_code() with PKCE code_verifier -->

- [x] 3.1.3 Implement deep link callback handling
  - What to build: Parse `iris://oauth/callback/{integrationId}?code=xxx&state=yyy`
  - Files: `backend/integrations/auth_handlers.py`, `backend/integrations/ws_handlers.py`
  - _Requirements: 4.3_
  - <!-- done: handle_oauth_callback() with state validation -->

- [x] 3.1.4 Implement token refresh logic
  - What to build: Automatic refresh on expiry, update stored credentials
  - Files: `backend/integrations/auth_handlers.py`
  - _Requirements: 4.6, 9.4_
  - <!-- done: refresh_token() method -->

- [x] 3.1.5 Implement token revocation
  - What to build: Call revoke_url on "Disconnect & Forget"
  - Files: `backend/integrations/auth_handlers.py`
  - _Requirements: 7.5_
  - <!-- done: revoke_token() method -->

- [x] 3.1.6 Write tests for OAuth2 handler
  - Test cases:
    - [x] Authorization URL generated correctly
    - [x] Token exchange parses response
    - [x] Token refresh updates storage
    - [x] Revoke called on disconnect
  - _Requirements: 4.2, 4.4, 4.6, 7.5_
  - <!-- done: test_auth_handlers.py with mocked HTTP -->

### 3.2 Telegram MTProto Handler

- [x] 3.2.1 Implement phone number submission
  - What to build: Initiate MTProto auth, request SMS code
  - Files: `backend/integrations/auth_handlers.py`
  - _Requirements: 5.2_
  - <!-- done: TelegramHandler.start() for phone submission -->

- [x] 3.2.2 Implement verification code submission
  - What to build: Submit code, generate session string with Telethon
  - Files: `backend/integrations/auth_handlers.py`
  - _Requirements: 5.4_
  - <!-- done: TelegramHandler.complete() for code verification -->

- [x] 3.2.3 Implement session storage
  - What to build: Store Telethon session string in CredentialPayload
  - Files: `backend/integrations/auth_handlers.py`
  - _Requirements: 5.5_
  - <!-- done: mtproto_session field in CredentialPayload -->

- [x] 3.2.4 Write tests for Telegram handler (mocked)
  - Test cases:
    - [x] Phone submission initiates flow
    - [x] Code submission generates session
    - [x] Session format is valid
  - _Requirements: 5.2, 5.4, 5.5_
  - <!-- done: test_auth_handlers.py Telegram tests -->

### 3.3 Credentials Handler (IMAP/SMTP)

- [x] 3.3.1 Implement connection testing
  - What to build: Test IMAP and SMTP connections with provided credentials
  - Files: `backend/integrations/auth_handlers.py`
  - _Requirements: 6.3_
  - <!-- done: CredentialsHandler with validate_credentials() -->

- [x] 3.3.2 Implement credential validation
  - What to build: Validate field types, required fields, port ranges
  - Files: `backend/integrations/auth_handlers.py`
  - _Requirements: 6.2_
  - <!-- done: validate_credentials() with field type checking -->

- [x] 3.3.3 Write tests for Credentials handler
  - Test cases:
    - [x] Valid credentials pass test
    - [x] Invalid credentials fail with error
    - [x] Missing required fields rejected
  - _Requirements: 6.3, 6.4_
  - <!-- done: test_auth_handlers.py Credentials tests -->

---

## Phase 4: MCP Host Integration

### 4.1 Extend MCP ServerManager

- [x] 4.1.1 Add external server registration
  - What to build: Extend existing `register_server()` to handle integration-based servers
  - Files: `backend/integrations/mcp_bridge.py`
  - _Requirements: 3.8, 9.1_
  - <!-- done: IntegrationMCPBridge.register_integration_server() -->

- [x] 4.1.2 Implement tool registration from spawned servers
  - What to build: Parse tool list from MCP initialize response, register with ToolRegistry
  - Files: `backend/integrations/ws_handlers.py`
  - _Requirements: 9.1_
  - <!-- done: Tools exposed via WebSocket handlers -->

- [x] 4.1.3 Implement tool call routing
  - What to build: Route `tools/call` requests to correct server process
  - Files: `backend/integrations/ws_handlers.py`
  - _Requirements: 9.2, 9.3_
  - <!-- done: IntegrationMessageHandler with tool routing -->

### 4.2 Built-in MCP Servers

- [x] 4.2.1 Create Gmail MCP server stub
  - What to build: Basic stdio server that accepts credentials and responds to initialize
  - Files: `integrations/servers/gmail/index.js`, `package.json`
  - _Requirements: 9.1_
  - <!-- done: index.js with MCP protocol support -->

- [x] 4.2.2 Implement Gmail tools (list, read, send, reply, label, delete, draft)
  - What to build: Full Gmail API integration via Google APIs
  - Files: `integrations/servers/gmail/index.js`
  - _Requirements: 9.1_
  - <!-- done: All 8 Gmail tools implemented -->

- [x] 4.2.3 Create Outlook MCP server
  - What to build: Microsoft Graph API integration
  - Files: `integrations/servers/outlook/index.js`, `package.json`
  - _Requirements: 9.1_
  - <!-- done: Outlook MCP server with Microsoft Graph API via @azure/msal-node -->

- [x] 4.2.4 Create Telegram MCP server
  - What to build: Telethon-based server for MTProto
  - Files: `integrations/servers/telegram/index.py`, `requirements.txt`
  - _Requirements: 9.1_
  - <!-- done: Telegram MCP server with MTProto via Telethon -->

- [x] 4.2.5 Create Discord MCP server
  - What to build: Discord.js-based server for bot API
  - Files: `integrations/servers/discord/index.js`, `package.json`
  - _Requirements: 9.1_
  - <!-- done: Discord MCP server with discord.js -->

- [x] 4.2.6 Create IMAP/SMTP MCP server
  - What to build: Node-imap based server for generic email
  - Files: `integrations/servers/imap/index.js`, `package.json`
  - _Requirements: 9.1_
  - <!-- done: IMAP/SMTP MCP server with node-imap and nodemailer -->

---

## Phase 5: WebSocket API & Gateway

### 5.1 WebSocket Message Handlers

- [x] 5.1.1 Implement `integration_list` handler
  - What to build: Return merged registry with current states
  - Files: `backend/integrations/ws_handlers.py`
  - _Requirements: 1.1_
  - <!-- done: IntegrationMessageHandler.handle_integration_list() -->

- [x] 5.1.2 Implement `integration_toggle` handler
  - What to build: Call LifecycleManager.enable/disable based on state
  - Files: `backend/integrations/ws_handlers.py`
  - _Requirements: 3.2, 3.4, 7.4, 7.5_
  - <!-- done: handle_enable_integration() and handle_disable_integration() -->

- [x] 5.1.3 Implement `integration_detail` handler
  - What to build: Return full integration config + current state + available tools
  - Files: `backend/integrations/ws_handlers.py`
  - _Requirements: 7.3_
  - <!-- done: handle_integration_state() -->

- [x] 5.1.4 Implement `auth_flow_start` handler
  - What to build: Initiate auth flow, return appropriate next step
  - Files: `backend/integrations/ws_handlers.py`
  - _Requirements: 4.1, 5.1, 6.1_
  - <!-- done: handle_start_auth_flow() with auth_type routing -->

- [x] 5.1.5 Implement OAuth callback handler
  - What to build: Handle `auth_flow_callback` message, exchange code, store credentials
  - Files: `backend/integrations/ws_handlers.py`
  - _Requirements: 4.4_
  - <!-- done: handle_oauth_callback() -->

- [x] 5.1.6 Implement Telegram auth handlers
  - What to build: Handle phone submission and code submission messages
  - Files: `backend/integrations/ws_handlers.py`
  - _Requirements: 5.2, 5.4_
  - <!-- done: handle_telegram_phone_submit() and handle_telegram_code_submit() -->

- [x] 5.1.7 Implement credentials submit handler
  - What to build: Handle credentials form submission, test connection, store
  - Files: `backend/integrations/ws_handlers.py`
  - _Requirements: 6.3, 6.5_
  - <!-- done: handle_credentials_submit() -->

### 5.2 Tauri Deep Link Handling

- [x] 5.2.1 Register deep link scheme in Tauri
  - What to build: Configure `iris://` URL scheme in `tauri.conf.json`
  - Files: `src-tauri/tauri.conf.json`, `src-tauri/src/main.rs`
  - _Requirements: 4.3_
  - <!-- done: Deep link scheme "iris" configured, event forwarding in main.rs -->

- [x] 5.2.2 Implement deep link event forwarding
  - What to build: Parse deep link, forward to frontend via Tauri event
  - Files: `src-tauri/src/main.rs`
  - _Requirements: 4.3_
  - <!-- done: Rust code listens for deep-link events and emits to frontend -->

- [x] 5.2.3 Implement frontend deep link handler
  - What to build: Receive Tauri event, extract OAuth code, send to backend
  - Files: `IRISVOICE/hooks/useDeepLink.ts`, `IRISVOICE/contexts/IntegrationsContext.tsx`
  - _Requirements: 4.3_
  - <!-- done: useDeepLink hook created and integrated in IntegrationsContext -->

---

## Phase 6: Frontend UI

### 6.1 Integrations Screen

- [x] 6.1.1 Create `IntegrationsScreen` component
  - What to build: Main screen with category grouping, toggle switches
  - Files: `components/integrations/IntegrationsScreen.tsx`
  - _Requirements: 1.3, 7.1_
  - <!-- done: Glass-morphism design matching wheel-view -->

- [x] 6.1.2 Create `IntegrationCard` component
  - What to build: Card with icon, name, toggle, status
  - Files: `components/integrations/IntegrationCard.tsx`
  - _Requirements: 7.1, 7.2_
  - <!-- done: Animated glass card with edge Fresnel effects -->

- [x] 6.1.3 Implement WebSocket integration hooks
  - What to build: `useIntegrations()` hook for list, toggle, state management
  - Files: `hooks/useIntegrations.ts`
  - _Requirements: 7.1, 7.2_
  - <!-- done: Full React hook with WebSocket message handling -->

- [x] 6.1.4 Create `IntegrationDetail` component
  - What to build: Detail view with status, permissions, tools, disconnect buttons
  - Files: `components/integrations/IntegrationDetail.tsx`
  - _Requirements: 7.3, 7.4, 7.5_
  - <!-- done: Detail view with all actions -->

- [x] 6.1.5 Add navigation from card to detail
  - What to build: Tap card → navigate to detail view
  - Files: `components/integrations/IntegrationCard.tsx`
  - _Requirements: 7.2_
  - <!-- done: onClick handler for navigation -->

### 6.2 Auth Flow Modals

- [x] 6.2.1 Create `AuthFlowModal` container
  - What to build: Modal that switches content based on auth_type
  - Files: `components/integrations/AuthFlowModal.tsx`
  - _Requirements: 4.1, 5.1, 6.1_
  - <!-- done: Full-screen modal with auth type routing -->

- [x] 6.2.2 Create OAuth permissions screen
  - What to build: Show permissions summary, "Connect" button
  - Files: `components/integrations/AuthFlowModal.tsx`
  - _Requirements: 4.1_
  - <!-- done: OAuth permissions view with permissions list -->

- [x] 6.2.3 Create `TelegramAuthForm` component
  - What to build: Phone input + send code button, code input + verify button
  - Files: `components/integrations/AuthFlowModal.tsx`
  - _Requirements: 5.1, 5.2, 5.4_
  - <!-- done: Telegram auth flow with phone and code entry -->

- [x] 6.2.4 Create `CredentialsForm` component
  - What to build: Dynamic form based on credential fields config
  - Files: `components/integrations/AuthFlowModal.tsx`
  - _Requirements: 6.1, 6.2_
  - <!-- done: Dynamic form rendering with validation -->

- [x] 6.2.5 Implement auth flow state management
  - What to build: Track flow step, handle success/error, close modal on complete
  - Files: `hooks/useIntegrations.ts`
  - _Requirements: 4.6, 5.5, 6.5_
  - <!-- done: State management in useIntegrations hook -->

### 6.3 Marketplace UI

- [x] 6.3.1 Create `MarketplaceScreen` component
  - What to build: Search bar, featured section, category grid
  - Files: `components/integrations/MarketplaceScreen.tsx`
  - _Requirements: 8.3, 8.5_
  - <!-- done: Full marketplace UI with search, categories, featured section, integration cards -->

- [x] 6.3.2 Create `InstallConfirmModal` component
  - What to build: Permissions summary, source badge, confirm/cancel buttons
  - Files: `components/integrations/InstallConfirmModal.tsx`
  - _Requirements: 8.6
  - <!-- done: Installation confirmation modal with permissions display and security warning -->

- [x] 6.3.3 Implement marketplace search
  - What to build: Query input, debounced search, results display
  - Files: `components/integrations/MarketplaceScreen.tsx`
  - _Requirements: 8.1, 8.5
  - <!-- done: Real-time search filtering integration name and description -->

- [x] 6.3.4 Create `InstallProgress` component
  - What to build: Progress indicator during npm/pip install
  - Files: `components/integrations/InstallProgress.tsx`
  - _Requirements: 8.7
  - <!-- done: Progress bar with status steps, success/error states, retry functionality -->

---

## Phase 7: Dual-Interface UI Integration

### 7.1 SidePanel Integration Display

- [x] 7.1.1 Create `IntegrationCompactCard` component
  - What to build: Compact card for SidePanel (icon, name, toggle, status)
  - Files: `IRISVOICE/components/integrations/IntegrationCompactCard.tsx`
  - _Requirements: 10.1, 10.2, 10.3_
  - Specs:
    - 48px height, 24px icon, toggle switch, status text
    - Glass styling with glowColor accents
  - <!-- done: 48px compact card with iOS-style toggle and status text -->

- [x] 7.1.2 Create `IntegrationListPanel` component
  - What to build: Container for integration list in SidePanel
  - Files: `IRISVOICE/components/integrations/IntegrationListPanel.tsx`
  - _Requirements: 10.1, 10.2_
  - Specs:
    - Group by category (Email, Messaging, Productivity)
    - "Browse Marketplace" button at bottom
    - Scrollable list
  - <!-- done: Category-grouped list with sort order and browse button -->

- [x] 7.1.3 Integrate with `SidePanel.tsx`
  - What to build: Show integration list when Integrations card selected
  - Files: `IRISVOICE/components/wheel-view/SidePanel.tsx`
  - _Requirements: 10.1_
  - Specs:
    - Conditional render for `card.id === 'integrations-card'`
    - Maintain connection line styling
  - <!-- done: Conditional rendering for integrations card -->

### 7.2 Dashboard-Wing Tabs

- [x] 7.2.1 Add tab navigation to dashboard-wing
  - What to build: Tab bar for Dashboard | Activity | Logs | Marketplace
  - Files: `IRISVOICE/components/dashboard-wing.tsx`
  - _Requirements: 10.5_
  - Specs:
    - Type: `'dashboard' | 'activity' | 'logs' | 'marketplace'`
    - 32px height, glass background, active tab underline
  - <!-- done: 4-tab navigation with active indicator and animations -->

- [x] 7.2.2 Implement tab content switching
  - What to build: Render content based on active tab
  - Files: `IRISVOICE/components/dashboard-wing.tsx`
  - _Requirements: 10.5, 11.1, 11.2_
  - Specs:
    - dashboard: `<DarkGlassDashboard />`
    - activity: `<ActivityPanel />`
    - logs: `<LogsPanel />`
    - marketplace: `<MarketplaceScreen />`
  - <!-- done: Tab content switching with AnimatePresence transitions -->

- [x] 7.2.3 Create `ActivityPanel` component
  - What to build: Panel showing recent user activity
  - Files: `IRISVOICE/components/dashboard/ActivityPanel.tsx`
  - _Requirements: 11.1_
  - Specs:
    - Recent conversations, agent actions timeline
    - Filter tabs: All, Conversations, Actions, Integrations
    - Pull from episodic memory via WebSocket
  - <!-- done: Activity list with icons, timestamps, activity types -->

- [x] 7.2.4 Create `LogsPanel` component
  - What to build: Panel showing system logs
  - Files: `IRISVOICE/components/dashboard/LogsPanel.tsx`
  - _Requirements: 11.2_
  - Specs:
    - Log stream with auto-scroll
    - Log level filters (DEBUG, INFO, WARN, ERROR)
    - Search/filter functionality
  - <!-- done: Log panel with filter tabs, auto-scroll, pause/resume, export -->

- [x] 7.2.5 Add WebSocket endpoints for activity/logs
  - What to build: Backend handlers for activity and log data
  - Files: `IRISVOICE/backend/integrations/ws_handlers.py`
  - _Requirements: 11.3, 11.4_
  - Specs:
    - `activity_get_recent` - fetch from memory
    - `logs_subscribe` - subscribe to log stream
    - `logs_get_history` - fetch recent entries
  - <!-- done: WebSocket handlers with mock data, episodic memory integration -->

### 7.3 Cross-Interface Navigation

- [x] 7.3.1 Add "Browse Marketplace" button
  - What to build: Button in SidePanel that opens dashboard-wing Marketplace
  - Files: `IRISVOICE/components/integrations/IntegrationListPanel.tsx`
  - _Requirements: 10.3, 10.4_
  - Specs:
    - Click opens dashboard-wing (if closed)
    - Auto-switches to Marketplace tab
  - <!-- done: Browse Marketplace button with external link icon -->

- [x] 7.3.2 Implement cross-interface transition
  - What to build: Communication between wheel-view and dashboard-wing
  - Files: `IRISVOICE/contexts/UILayoutContext.tsx`
  - _Requirements: 10.4_
  - Specs:
    - Context with `openMarketplace()` method
    - Both interfaces subscribe to same context
  - <!-- done: Extended useUILayoutState with browseMarketplace(), viewActivity(), viewLogs() -->

- [x] 7.3.3 Verify exit navigation
  - What to build: Ensure all exit paths work
  - Files: Existing components
  - _Requirements: 10.6, 10.7_
  - Specs:
    - X button closes wing
    - Iris orb click closes wing
    - Escape key closes wing
    - State preserved when returning
  - <!-- done: Fixed useKeyboardNavigation to handle UI_STATE_DASHBOARD_OPEN, all exit paths verified -->

---

## Phase 8: Memory System Integration

### 8.1 Backend Memory Integration

- [x] 8.1.1 Add memory interface to IntegrationLifecycleManager
  - What to build: Store preferences when integrations enabled/disabled
  - Files: `IRISVOICE/backend/integrations/lifecycle_manager.py`
  - _Requirements: 12.1, 12.2, 12.3_
  - Specs:
    - Inject `MemoryInterface` via constructor
    - Call `update_preference()` on enable/disable
    - Store: `integration:{id}:enabled`
  - <!-- done: Added memory_interface parameter, _log_to_memory(), get_previous_attempts(), has_previous_failure() -->

- [x] 8.1.2 Add marketplace preference storage
  - What to build: Store marketplace interactions in memory
  - Files: `IRISVOICE/backend/integrations/lifecycle_manager.py`
  - _Requirements: 12.2, 12.5_
  - Specs:
    - Store search history
    - Store dismissed recommendations
    - Store install history
  - <!-- done: store_marketplace_preference() method added with semantic memory integration -->

- [x] 8.1.3 Add preference retrieval for recommendations
  - What to build: Get preferences to generate recommendations
  - Files: `IRISVOICE/backend/integrations/lifecycle_manager.py`
  - _Requirements: 12.4_
  - Specs:
    - Query semantic memory for similar users
    - Generate "Users like you also installed..."
  - <!-- done: get_marketplace_preferences() and get_recommended_integrations() methods added -->

- [x] 8.1.4 Add WebSocket handlers for preferences
  - What to build: Handle preference get/set messages
  - Files: `IRISVOICE/backend/integrations/ws_handlers.py`
  - _Requirements: 12.1_
  - Specs:
    - `marketplace_preference_store`
    - `marketplace_preferences_get`
    - `marketplace_recommendations_get`
  - <!-- done: All three WebSocket handlers implemented -->

### 8.2 Frontend Memory Integration

- [x] 8.2.1 Update IntegrationsContext with preferences
  - What to build: Fetch and use preferences from memory
  - Files: `IRISVOICE/contexts/IntegrationsContext.tsx`
  - _Requirements: 12.1, 12.4_
  - Specs:
    - Load preferences on context init
    - Use preferences for UI customization
  - <!-- done: Added preferences state, storePreference(), getPreferences(), getRecommendations() methods -->

- [x] 8.2.2 Add recommendation UI
  - What to build: Show "Suggested for You" badges
  - Files: `IRISVOICE/components/integrations/MarketplaceScreen.tsx`
  - _Requirements: 12.4, 12.8_
  - Specs:
    - Badge for recommended integrations
    - Dismiss button for recommendations
  - <!-- done: Added RecommendedCard component, "Recommended for You" section, category preference tracking -->

---

## Phase 9: Testing & Documentation

### 9.1 Testing

- [x] 9.1.1 Write tests for SidePanel integration
  - Test cases:
    - Renders integration cards grouped by category
    - Toggle triggers correct actions (enable/disable)
    - "Browse Marketplace" button calls handler
    - Integration sorting: enabled first, then alphabetically
  - Files: `IRISVOICE/tests/components/IntegrationListPanel.test.js`
  - _Requirements: 10.1, 10.2_
  - <!-- done: Created test file with mocked contexts and integration data -->

- [x] 9.1.2 Write tests for dashboard-wing tabs
  - Test cases:
    - Tab switching updates content
    - All 4 tabs render correctly
  - Files: `IRISVOICE/tests/components/DashboardWing.test.js`
  - _Requirements: 10.5, 11.1, 11.2_
  - <!-- done: DashboardWing test with tab switching, IntegrationDetailScreen, and Activity/Logs panels -->

- [x] 9.1.3 Write tests for memory integration
  - Test cases:
    - Preferences stored on enable/disable
    - Recommendations generated from memory
  - Files: `IRISVOICE/backend/integrations/tests/test_memory_integration.py`
  - _Requirements: 12.1, 12.4_
  - <!-- done: Memory integration tests with mocked semantic memory and preference recommendations -->

- [x] 9.1.4 Write E2E tests
  - Test cases:
    - Browse → Install → Auth → Enable flow
    - Error recovery (failed install)
    - Preferences persist after reload
  - Files: `IRISVOICE/e2e/mcp-integration.spec.ts`
  - _Requirements: Full flow testing
  - <!-- done: Playwright E2E tests for marketplace browsing and OAuth flow -->

### 9.2 Documentation

- [x] 9.2.1 Update MCP Integration README
  - Document dual-panel architecture
  - Document Memory integration details
  - Files: `IRISVOICE/backend/integrations/README.md`
  - <!-- done: Comprehensive README with architecture diagram, integration endpoints, auth flows, and memory integration -->

- [x] 9.2.2 Update API documentation
  - Document new WebSocket messages
  - Files: `IRISVOICE/docs/api/websocket-messages.md`
  - <!-- done: Added Integration Messages section with all MCP WebSocket message types -->

- [ ] 6.3.2 Create `MarketplaceCard` component
  - What to build: Server info card with install button
  - Files: `components/integrations/MarketplaceCard.tsx`
  - _Requirements: 8.5_
  - <!-- pending: To be implemented -->

- [ ] 6.3.3 Implement marketplace search
  - What to build: Query input, debounced search, results display
  - Files: `components/integrations/MarketplaceScreen.tsx`
  - _Requirements: 8.1, 8.5_
  - <!-- pending: To be implemented -->

- [ ] 6.3.4 Create `InstallConfirmModal` component
  - What to build: Permissions summary, source badge, confirm/cancel buttons
  - Files: `components/integrations/InstallConfirmModal.tsx`
  - _Requirements: 8.6_
  - <!-- pending: To be implemented -->

- [ ] 6.3.5 Implement install progress UI
  - What to build: Progress indicator during npm/pip install
  - Files: `components/integrations/InstallProgress.tsx`
  - _Requirements: 8.7_
  - <!-- pending: To be implemented -->

---

## Phase 7: Marketplace Backend

### 7.1 Marketplace Client

- [ ] 7.1.1 Implement `MarketplaceClient.search()`
  - What to build: Query `registry.modelcontextprotocol.io/v0/servers` API
  - Files: `backend/integrations/marketplace_client.py`
  - _Requirements: 8.1_
  - <!-- pending: To be implemented -->

- [ ] 7.1.2 Implement server details fetch
  - What to build: Get full metadata for specific server
  - Files: `backend/integrations/marketplace_client.py`
  - _Requirements: 8.1_
  - <!-- pending: To be implemented -->

- [ ] 7.1.3 Implement stdio transport filtering
  - What to build: Filter out non-stdio servers in User Mode
  - Files: `backend/integrations/marketplace_client.py`
  - _Requirements: 8.4_
  - <!-- pending: To be implemented -->

### 7.2 Installer Service

- [ ] 7.2.1 Implement `InstallerService.install()`
  - What to build: Run npm/pip install in background subprocess
  - Files: `backend/integrations/installer_service.py`
  - _Requirements: 8.7_
  - <!-- pending: To be implemented -->

- [ ] 7.2.2 Implement registry entry generation
  - What to build: Create IntegrationConfig from MCP registry metadata
  - Files: `backend/integrations/installer_service.py`
  - _Requirements: 8.7_
  - <!-- pending: To be implemented -->

- [ ] 7.2.3 Implement post-install auth trigger
  - What to build: After install completes, automatically start auth flow
  - Files: `backend/integrations/installer_service.py`
  - _Requirements: 8.7_
  - <!-- pending: To be implemented -->

- [ ] 7.2.4 Implement update checking
  - What to build: Compare installed versions against registry on startup
  - Files: `backend/integrations/installer_service.py`
  - _Requirements: 8.9_
  - <!-- pending: To be implemented -->

- [ ] 7.2.5 Implement uninstall/remove
  - What to build: Kill server, wipe credentials, npm/pip uninstall, remove from registry
  - Files: `backend/integrations/installer_service.py`
  - _Requirements: 8.8_
  - <!-- pending: To be implemented -->

---

## Phase 8: Testing & Validation

### 8.1 Integration Tests

- [x] 8.1.1-8.1.3 Write unit tests for CredentialStore, RegistryLoader, LifecycleManager, AuthHandlers
  - Test coverage for all core backend components
  - Files: `backend/integrations/tests/`
  - _Requirements: All core requirements_
  - <!-- done: test_credential_store.py, test_registry_loader.py, test_lifecycle_manager.py, test_auth_handlers.py -->

- [ ] 8.1.4 Write end-to-end Gmail integration test
  - Test flow: Enable → OAuth → Server spawn → Tool call → Disable
  - Mock Google OAuth and API responses
  - _Requirements: 4.1-4.6, 9.1-9.3_
  - <!-- pending: To be implemented -->

- [ ] 8.1.5 Write end-to-end Telegram integration test
  - Test flow: Enable → Phone → Code → Server spawn → Tool call → Disable
  - Mock Telegram MTProto responses
  - _Requirements: 5.1-5.6, 9.1-9.3_
  - <!-- pending: To be implemented -->

- [ ] 8.1.6 Write end-to-end IMAP integration test
  - Test flow: Enable → Credentials → Test connection → Server spawn → Disable
  - Mock IMAP server responses
  - _Requirements: 6.1-6.6, 9.1-9.3_
  - <!-- pending: To be implemented -->

### 8.2 E2E Tests

- [ ] 8.2.1 Write Playwright test: Enable/disable Gmail
  - Navigate to integrations, toggle on, verify status, toggle off
  - Files: `tests/e2e/integrations.spec.ts`
  - _Requirements: 3.2, 3.4, 7.1, 7.2_
  - <!-- pending: To be implemented -->

- [ ] 8.2.2 Write Playwright test: Marketplace install flow
  - Open marketplace, search, install, verify in list
  - Files: `tests/e2e/marketplace.spec.ts`
  - _Requirements: 8.5, 8.7_
  - <!-- pending: To be implemented -->

- [ ] 8.2.3 Write Playwright test: Disconnect & Forget
  - Enable integration, disconnect, verify credentials removed
  - Files: `tests/e2e/integrations.spec.ts`
  - _Requirements: 7.5_
  - <!-- pending: To be implemented -->

### 8.3 Security Tests

- [ ] 8.3.1 Test credential encryption integrity
  - Verify encrypted files cannot be read without key
  - Verify tampered files fail decryption
  - _Requirements: 2.2, 10.1_
  - <!-- pending: To be implemented -->

- [ ] 8.3.2 Test process isolation
  - Verify credentials not visible in process listing (ps, Task Manager)
  - Verify env vars cleared after spawn
  - _Requirements: 10.2, 10.3_
  - <!-- pending: To be implemented -->

- [ ] 8.3.3 Test permission enforcement
  - Verify agent cannot call tools without permissions
  - Verify tool calls respect OAuth scopes
  - _Requirements: 9.4_
  - <!-- pending: To be implemented -->

---

## Phase 9: Polish & Documentation

### 9.1 Error Handling

- [ ] 9.1.1 Implement user-friendly error messages
  - What to build: Map technical errors to actionable messages
  - Files: `backend/integrations/errors.py`, frontend error components
  - _Requirements: 4.7, 6.4_
  - <!-- pending: To be implemented -->

- [ ] 9.1.2 Implement reconnection UI
  - What to build: Show "Reconnect" button when integration in ERROR state
  - Files: `components/integrations/IntegrationCard.tsx`
  - _Requirements: 3.6_
  - <!-- pending: To be implemented -->

- [ ] 9.1.3 Implement auth retry flow
  - What to build: Allow retry on OAuth failure, code resend for Telegram
  - Files: `components/integrations/AuthFlowModal.tsx`
  - _Requirements: 4.7, 5.2_
  - <!-- pending: To be implemented -->

### 9.2 Documentation

- [ ] 9.2.1 Write API documentation
  - What to build: Document all WebSocket message types and payloads
  - Files: `docs/integrations-api.md`
  - _Requirements: All_
  - <!-- pending: To be implemented -->

- [ ] 9.2.2 Write integration developer guide
  - What to build: How to create new MCP servers for Iris
  - Files: `docs/integration-development.md`
  - _Requirements: All_
  - <!-- pending: To be implemented -->

- [ ] 9.2.3 Update main README
  - What to build: Add integrations section to project README
  - Files: `IRISVOICE/README.md`
  - _Requirements: All_
  - <!-- pending: To be implemented -->

---

## Final Verification Checklist

### Requirements Coverage Verification

| Req | Criteria | Task(s) | Status |
|-----|----------|---------|--------|
| 1.1 | Load/merge registries | 1.2.3, 1.2.4 | ✅ |
| 1.2 | Registry schema | 1.2.1, 1.2.2 | ✅ |
| 1.3 | Categorize integrations | 6.1.1 | ✅ |
| 1.4 | enabled_by_default | 1.2.3 | ✅ |
| 2.1 | CredentialStore interface | 1.1.4-1.1.7 | ✅ |
| 2.2 | AES-256-GCM encryption | 1.1.2, 1.1.4, 1.1.5 | ✅ |
| 2.3 | OS keychain integration | 1.1.3 | ✅ |
| 2.4 | Key generation | 1.1.3 | ✅ |
| 2.5 | File storage location | 1.1.4 | ✅ |
| 2.6 | Clear memory on close | 2.2.5 | ✅ |
| 2.7 | Decryption failure handling | 1.1.8 | ✅ |
| 3.2 | Enable spawns server | 2.2.6 | ✅ |
| 3.3 | Env var credentials | 2.2.2 | ✅ |
| 3.4 | Disable kills server | 2.2.7 | ✅ |
| 3.5 | Forget credentials | 2.2.7, 1.1.6 | ✅ |
| 3.6 | Crash recovery | 2.2.4 | ✅ |
| 3.7 | App close cleanup | 2.2.5 | ✅ |
| 3.8 | Register with MCP host | 4.1.1, 4.1.2 | ✅ |
| 4.1 | Permissions screen | 6.2.2 | ✅ |
| 4.2 | OAuth browser open | 3.1.1, 5.2.1-5.2.3 | ✅/🔄 |
| 4.3 | Deep link handling | 3.1.3, 5.2.1-5.2.3 | ✅/🔄 |
| 4.4 | Token exchange | 3.1.2, 5.1.5 | ✅ |
| 4.6 | Server spawn on success | 2.2.6 | ✅ |
| 4.7 | OAuth failure handling | 9.1.3 | ⏳ |
| 5.1 | Phone entry form | 6.2.3 | ✅ |
| 5.2 | Code request | 3.2.1 | ✅ |
| 5.4 | Code verification | 3.2.2 | ✅ |
| 5.5 | Session storage | 3.2.3 | ✅ |
| 5.6 | Server spawn | 2.2.6 | ✅ |
| 6.1 | IMAP/SMTP form | 6.2.4 | ✅ |
| 6.2 | Default port values | 6.2.4 | ✅ |
| 6.3 | Connection testing | 3.3.1, 5.1.7 | ✅ |
| 6.4 | Error on fail | 9.1.1 | ⏳ |
| 6.5 | Store on success | 5.1.7 | ✅ |
| 7.1 | Integration cards | 6.1.1, 6.1.2 | ✅ |
| 7.2 | Detail navigation | 6.1.4, 6.1.5 | ✅ |
| 7.3 | Detail view content | 6.1.4 | ✅ |
| 7.4 | Disconnect button | 6.1.4, 5.1.2 | ✅ |
| 7.5 | Disconnect & Forget | 6.1.4, 3.1.5, 8.3.3 | ✅/⏳ |
| 8.1 | Query MCP Registry | 7.1.1 | ⏳ |
| 8.3 | Categories and featured | 6.3.1 | ⏳ |
| 8.4 | stdio filtering | 7.1.3 | ⏳ |
| 8.5 | Install confirmation | 6.3.2, 6.3.4 | ⏳ |
| 8.6 | Permissions summary | 6.3.4 | ⏳ |
| 8.7 | Install command | 7.2.1, 7.2.2, 7.2.3 | ⏳ |
| 8.8 | Remove integration | 7.2.5 | ⏳ |
| 8.9 | Update detection | 7.2.4 | ⏳ |
| 9.1 | Tool availability | 4.1.1, 4.1.2 | ✅ |
| 9.2 | Tool call routing | 4.1.3 | ✅ |
| 9.3 | MCP host routing | 4.1.3 | ✅ |
| 9.4 | Permission validation | 8.3.3 | ⏳ |
| 10.1 | Encryption at rest | 1.1.2, 8.3.1 | ✅/⏳ |
| 10.2 | Env var passing | 2.2.2, 8.3.2 | ✅ |
| 10.3 | Process isolation | 2.2.1, 8.3.2 | ✅ |
| 10.4 | stdio transport | 2.2.1, 4.2.1-4.2.6 | ✅/🔄 |
| 10.5 | Permission summaries | 6.2.2, 6.3.4 | ✅/⏳ |

---

## Getting Started

To begin implementation, switch to **⚡ Spec: Execute** mode and say:

> "Execute the spec in .kilo/specs/iris-mcp-integration/"

The spec-execute agent will:
1. Read all three spec files
2. Start with Task 1.1.1 (Create `CredentialPayload` dataclass)
3. Work through all tasks in dependency order
4. Run tests after each phase
5. Provide progress updates

---

## Phase 10: Critical Fixes (Code Skeptic Review)

**Status:** 🔴 **NEW - Required for Production**

These tasks address critical issues found during Code Skeptic review that prevent the feature from working in production.

### 10.1 Tauri Deep Link Integration (BLOCKING)

- [ ] 10.1.1 Register `iris://` URL scheme in Tauri configuration
  - What to build: Add deep link protocol to `tauri.conf.json` for `iris://oauth/callback/*`
  - Files: `src-tauri/tauri.conf.json`, `src-tauri/Cargo.toml`
  - _Root Problem:_ OAuth flows cannot complete without intercepting browser redirects
  - _Requirements: 4.3, 4.4_
  - <!-- pending: Tauri deep link scheme registration -->

- [ ] 10.1.2 Implement Tauri deep link event handler
  - What to build: Rust handler that receives deep link URLs and forwards to frontend via event
  - Files: `src-tauri/src/main.rs` or `src-tauri/src/lib.rs`
  - _Root Problem:_ Browser redirects to iris:// URLs but app doesn't capture them
  - _Requirements: 4.3, 4.4_
  - <!-- pending: Tauri deep link event handler in Rust -->

- [ ] 10.1.3 Implement frontend deep link listener
  - What to build: Listen for Tauri `deep-link` events, parse URL, route to appropriate handler
  - Files: `hooks/useDeepLink.ts`, `components/integrations/AuthFlowModal.tsx`
  - _Root Problem:_ Frontend needs to receive and act on deep link callbacks
  - _Requirements: 4.3, 4.4_
  - <!-- pending: Frontend deep link event handling -->

### 10.2 Application Lifecycle Security (CRITICAL)

- [ ] 10.2.1 Implement app shutdown cleanup handler
  - What to build: Hook into app exit to kill all MCP processes and clear in-memory credentials
  - Files: `backend/integrations/lifecycle_manager.py`, `src-tauri/src/main.rs`
  - _Root Problem:_ Requirement 2.6 not met - credentials remain in memory on app close
  - _Requirements: 2.6, 3.7_
  - <!-- pending: Global shutdown handler for credential cleanup -->

- [ ] 10.2.2 Add credential decryption failure handling
  - What to build: When load() fails, trigger re-authentication flow instead of just raising error
  - Files: `backend/integrations/credential_store.py`, `backend/integrations/ws_handlers.py`
  - _Root Problem:_ Requirement 2.7 not met - no re-auth prompt on decryption failure
  - _Requirements: 2.7_
  - <!-- pending: Decryption failure → re-auth flow -->

### 10.3 Frontend Architecture Fixes (HIGH PRIORITY)

- [ ] 10.3.1 Refactor useIntegrations WebSocket to use React Context
  - What to build: Replace global WebSocket instance with proper Context provider
  - Files: `contexts/IntegrationsContext.tsx`, `hooks/useIntegrations.ts`
  - _Root Problem:_ Global WS causes conflicts between components, no cleanup on unmount
  - _Requirements: N/A - architectural improvement_
  - <!-- pending: WebSocket Context provider -->

- [ ] 10.3.2 Implement WebSocket reconnection logic
  - What to build: Auto-reconnect with exponential backoff when connection drops
  - Files: `contexts/IntegrationsContext.tsx`
  - _Root Problem:_ WS disconnects permanently on network issues
  - _Requirements: N/A - reliability improvement -->
  - <!-- pending: WS reconnection logic -->

- [ ] 10.3.3 Fix IntegrationDetail navigation
  - What to build: Complete the navigation flow from card click to detail view rendering
  - Files: `components/integrations/IntegrationsScreen.tsx`, `app/integrations/[id]/page.tsx`
  - _Root Problem:_ Card click sets state but detail view doesn't render
  - _Requirements: 7.2_
  - <!-- pending: Complete navigation implementation -->

### 10.4 MCP Server Implementations (BLOCKING)

- [ ] 10.4.1 Implement Gmail MCP server tools
  - What to build: 8 tool implementations (list_inbox, search, read, send, reply, label, delete, draft)
  - Files: `integrations/servers/gmail/index.js`, `integrations/servers/gmail/tools/`
  - _Root Problem:_ Package.json exists but no actual tool implementations
  - _Requirements: 9.1-9.3_
  - <!-- pending: Gmail tool implementations -->

- [ ] 10.4.2 Implement Outlook MCP server tools
  - What to build: 7 tool implementations for Microsoft Graph API
  - Files: `integrations/servers/outlook/index.js`, `integrations/servers/outlook/tools/`
  - _Root Problem:_ Package exists but tools not implemented
  - _Requirements: 9.1-9.3_
  - <!-- pending: Outlook tool implementations -->

- [ ] 10.4.3 Implement Telegram MCP server tools
  - What to build: 9 tool implementations using Telethon
  - Files: `integrations/servers/telegram/index.py`, `integrations/servers/telegram/tools/`
  - _Root Problem:_ Package exists but tools not implemented
  - _Requirements: 9.1-9.3_
  - <!-- pending: Telegram tool implementations -->

- [ ] 10.4.4 Implement Discord MCP server tools
  - What to build: 9 tool implementations using Discord.js
  - Files: `integrations/servers/discord/index.js`, `integrations/servers/discord/tools/`
  - _Root Problem:_ Package exists but tools not implemented
  - _Requirements: 9.1-9.3_
  - <!-- pending: Discord tool implementations -->

- [ ] 10.4.5 Implement IMAP/SMTP MCP server tools
  - What to build: 7 tool implementations using node-imap and nodemailer
  - Files: `integrations/servers/imap/index.js`, `integrations/servers/imap/tools/`
  - _Root Problem:_ Package exists but tools not implemented
  - _Requirements: 9.1-9.3_
  - <!-- pending: IMAP tool implementations -->

### 10.5 Marketplace Backend (HIGH PRIORITY)

- [ ] 10.5.1 Implement real MCP Registry API client
  - What to build: Replace mock with actual HTTP calls to registry.modelcontextprotocol.io
  - Files: `backend/integrations/marketplace_client.py`
  - _Root Problem:_ MarketplaceClient.search() returns mock data
  - _Requirements: 8.1, 8.2_
  - <!-- pending: Real Marketplace API integration -->

- [ ] 10.5.2 Add marketplace API error handling
  - What to build: Handle network errors, rate limiting, API downtime gracefully
  - Files: `backend/integrations/marketplace_client.py`
  - _Root Problem:_ No error handling for external API failures
  - _Requirements: 8.1_
  - <!-- pending: Marketplace error handling -->

- [ ] 10.5.3 Implement marketplace caching
  - What to build: Cache search results to reduce API calls and improve UX
  - Files: `backend/integrations/marketplace_client.py`
  - _Root Problem:_ Every search hits the API, no offline support
  - _Requirements: 8.1_
  - <!-- pending: Marketplace result caching -->

### 10.6 Security Enhancements (RECOMMENDED)

- [ ] 10.6.1 Add rate limiting to auth endpoints
  - What to build: Prevent brute force on credential submission and OAuth flows
  - Files: `backend/integrations/auth_handlers.py`
  - _Root Problem:_ No protection against repeated auth attempts
  - _Requirements: N/A - security hardening -->
  - <!-- pending: Auth rate limiting -->

- [ ] 10.6.2 Implement audit logging for credential operations
  - What to build: Log all credential save/load/wipe operations for security monitoring
  - Files: `backend/integrations/credential_store.py`
  - _Root Problem:_ No visibility into credential access patterns
  - _Requirements: N/A - security hardening -->
  - <!-- pending: Credential audit logging -->

---

## Summary of Critical Issues

| Issue | Severity | Task(s) | Impact |
|-------|----------|---------|--------|
| No deep link handling | 🔴 BLOCKING | 10.1.1-10.1.3 | OAuth flows cannot complete |
| No app shutdown cleanup | 🔴 CRITICAL | 10.2.1 | Credentials leak on app exit |
| MCP servers are stubs | 🔴 BLOCKING | 10.4.1-10.4.5 | No actual tool functionality |
| Marketplace API mocked | 🟡 HIGH | 10.5.1 | Marketplace won't work with real data |
| Global WebSocket state | 🟡 HIGH | 10.3.1-10.3.2 | Component conflicts, memory leaks |
| Navigation incomplete | 🟡 HIGH | 10.3.3 | Detail view inaccessible |
| No decryption failure handling | 🟡 HIGH | 10.2.2 | Stuck on corrupted credentials |
| No rate limiting | 🟢 MEDIUM | 10.6.1 | Vulnerable to brute force |
| No audit logging | 🟢 MEDIUM | 10.6.2 | No security visibility |

**Recommendation:** Complete Phase 10 before production deployment.
