/**
 * useIntegrations Hook
 * 
 * React hook for managing integrations via WebSocket.
 * DEPRECATED: This hook uses global singleton WebSocket which can cause conflicts.
 * Use `useIntegrationsContext` from `contexts/IntegrationsContext.tsx` instead.
 * 
 * This hook is kept for backward compatibility but wraps the new Context-based
 * implementation to avoid conflicts.
 */

import { useIntegrationsContext } from '../contexts/IntegrationsContext';

// Re-export types from context
export type {
  AuthType,
  IntegrationStatus,
  Integration,
  IntegrationState,
  AuthField,
  AuthConfig,
} from '../contexts/IntegrationsContext';

// Hook now wraps the Context-based implementation
export function useIntegrations() {
  const context = useIntegrationsContext();
  
  // Return same interface as before for backward compatibility
  return {
    integrations: context.integrations,
    states: context.states,
    isLoading: context.isLoading,
    error: context.error,
    refreshIntegrations: context.refreshIntegrations,
    enableIntegration: context.enableIntegration,
    disableIntegration: context.disableIntegration,
    restartIntegration: context.restartIntegration,
    forgetIntegration: context.forgetIntegration,
    getIntegrationState: context.getIntegrationState,
    startOAuthFlow: context.startOAuthFlow,
    submitCredentials: context.submitCredentials,
    submitTelegramCode: context.submitTelegramCode,
    pendingAuth: context.pendingAuth,
    clearPendingAuth: context.clearPendingAuth,
  };
}

// Also export the Context components for proper setup
export { IntegrationsProvider, useIntegrationsContext } from '../contexts/IntegrationsContext';
