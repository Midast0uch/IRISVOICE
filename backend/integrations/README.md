# MCP Integration System

This directory contains the MCP (Model Context Protocol) integration system for IRIS, enabling seamless connection with external services through a unified interface.

## Architecture Overview

### Dual-Panel UI Architecture

The integration system uses a dual-panel architecture:

1. **Wheel-View SidePanel (155px)**
   - Compact integration cards with iOS-style toggles
   - Category-grouped list (Email, Messaging, Productivity, Other)
   - "Browse Marketplace" button for discovery
   - Located in: `IRISVOICE/components/integrations/IntegrationListPanel.tsx`

2. **Dashboard-Wing Panel (280-380px)**
   - Full-featured 4-tab interface:
     - **Dashboard**: Settings and configuration
     - **Activity**: Integration usage timeline
     - **Logs**: System logs and debugging
     - **Marketplace**: Browse and install new integrations
   - Located in: `IRISVOICE/components/dashboard-wing.tsx`

### Component Flow

```
User Action → IntegrationsContext → WebSocket → Backend Handler → IntegrationLifecycleManager
                                                                                ↓
                                                          Integration Enabled/Disabled
                                                                                ↓
                                                          Memory Interface (Preferences)
```

## Backend Components

### IntegrationLifecycleManager

Central manager for integration lifecycle operations:

- **File**: `lifecycle_manager.py`
- **Responsibilities**:
  - Spawn/monitor MCP server processes
  - Handle enable/disable operations
  - Automatic restart with exponential backoff
  - Episodic memory logging
  - Marketplace preference storage/retrieval

### Key Methods

```python
# Enable an integration
await lifecycle_manager.enable(integration_id: str) -> bool

# Disable an integration
await lifecycle_manager.disable(integration_id: str, forget_credentials: bool = False) -> bool

# Store marketplace preference
await lifecycle_manager.store_marketplace_preference(
    user_id: str,
    preference_type: str,  # 'category_viewed', 'integration_viewed'
    value: any,
    metadata: Optional[Dict]
) -> bool

# Get recommendations
await lifecycle_manager.get_recommended_integrations(user_id: str, limit: int = 5) -> List[Dict]
```

### WebSocket Handlers

Message handlers in `ws_handlers.py`:

| Message Type | Handler | Description |
|--------------|---------|-------------|
| `integration_list` | `_handle_list` | List all available integrations |
| `integration_enable` | `_handle_enable` | Enable an integration |
| `integration_disable` | `_handle_disable` | Disable an integration |
| `integration_oauth_callback` | `_handle_oauth_callback` | Handle OAuth callback |
| `integration_credentials_auth` | `_handle_credentials_auth` | Credentials-based auth |
| `integration_telegram_auth` | `_handle_telegram_auth` | Telegram MTProto auth |
| `marketplace_preference_store` | `_handle_marketplace_preference_store` | Store user preference |
| `marketplace_preferences_get` | `_handle_marketplace_preferences_get` | Get user preferences |
| `marketplace_recommendations_get` | `_handle_marketplace_recommendations_get` | Get recommendations |
| `activity_get_recent` | `_handle_activity_get_recent` | Get recent activity |
| `logs_subscribe` | `_handle_logs_subscribe` | Subscribe to logs |

## Memory Integration

### Semantic Memory Storage

User marketplace preferences are stored in semantic memory:

```python
# Example preference storage
{
    "type": "marketplace_preference",
    "user_id": "default_user",
    "preference_type": "category_viewed",
    "value": "email",
    "timestamp": "2024-01-15T10:30:00Z"
}
```

### Recommendation Algorithm

Recommendations are generated based on:

1. **Category Preferences**: Track which categories user browses most
2. **Integration View History**: Exclude already-viewed integrations
3. **Scoring**: Calculate relevance based on category match frequency

## Frontend Components

### IntegrationsContext

React Context providing integration state and methods:

```typescript
// Key properties
integrations: Integration[]           // List of all integrations
states: Record<string, IntegrationState>  // Current states
isLoading: boolean                    // Loading state
preferences: MarketplacePreference[]  // User preferences
recommendations: RecommendedIntegration[]  // Generated recommendations

// Key methods
enableIntegration(integrationId: string): Promise<void>
disableIntegration(integrationId: string): Promise<void>
storePreference(type: string, value: any): Promise<boolean>
getRecommendations(): Promise<RecommendedIntegration[]>
```

### Deep Link Handling (Tauri)

OAuth callbacks use Tauri deep links:

1. **Configuration**: `iris://oauth/callback` scheme registered in `tauri.conf.json`
2. **Rust Handler**: `src-tauri/src/main.rs` listens for deep-link events
3. **Frontend Hook**: `useDeepLink.ts` parses OAuth callback URLs
4. **Flow**: OAuth provider → iris://oauth/callback?code=xxx → Tauri → Frontend → WebSocket → Backend

## Testing

### Unit Tests

```bash
# Component tests
npm test -- IRISVOICE/tests/components/IntegrationListPanel.test.js
npm test -- IRISVOICE/tests/components/DashboardWing.test.js

# Backend tests
pytest IRISVOICE/backend/integrations/tests/test_memory_integration.py
```

### E2E Tests

```bash
# Playwright E2E tests
npx playwright test IRISVOICE/e2e/mcp-integration.spec.ts
```

## Configuration

### Adding a New Integration

1. Create config in `IRISVOICE/backend/integrations/registry/`:

```json
{
  "id": "my-integration",
  "name": "My Integration",
  "category": "productivity",
  "auth_type": "oauth2",
  "permissions_summary": "Access user data",
  "config": {
    "oauth2": {
      "client_id_env": "MY_INTEGRATION_CLIENT_ID",
      "scopes": ["read", "write"]
    }
  }
}
```

2. Add MCP server implementation in `IRISVOICE/backend/mcp/`

3. Register in `RegistryLoader`

## Security Considerations

- Credentials stored encrypted in `CredentialStore`
- OAuth tokens never exposed to frontend
- Deep link scheme `iris://` prevents URL hijacking
- All integration actions logged to episodic memory for audit

## Dependencies

- `@tauri-apps/api` - Deep link handling
- `framer-motion` - UI animations
- `lucide-react` - Icons
- `pytest` - Backend testing
- `@playwright/test` - E2E testing

## Related Documentation

- [WebSocket Messages](../docs/api/websocket-messages.md)
- [Auth Flows](./AUTH_FLOWS.md)
- [MCP Protocol](../mcp/README.md)
