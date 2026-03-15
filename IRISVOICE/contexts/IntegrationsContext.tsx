"use client"

/**
 * IntegrationsContext
 *
 * React Context for managing integrations WebSocket connection.
 * Provides a single WebSocket connection per component tree with proper
 * lifecycle management and automatic reconnection.
 */

import React, { createContext, useContext, useState, useCallback, useEffect, useRef, ReactNode } from 'react';
import { useDeepLink, isTauri } from '@/hooks/useDeepLink';

// Types matching backend models
export type AuthType = 'oauth2' | 'telegram_mtproto' | 'credentials';

export type IntegrationStatus = 
  | 'disabled' 
  | 'auth_pending' 
  | 'running' 
  | 'error' 
  | 'reauth_pending' 
  | 'wiped';

export interface Integration {
  id: string;
  name: string;
  category: 'email' | 'messaging' | 'other';
  icon: string;
  auth_type: AuthType;
  permissions_summary: string;
  enabled_by_default: boolean;
  status: IntegrationStatus;
  credential_exists: boolean;
  is_running: boolean;
  tools?: string[];
}

export interface IntegrationState {
  integration_id: string;
  status: IntegrationStatus;
  connected_since?: string;
  error_message?: string;
  last_error_at?: string;
  retry_count: number;
}

export interface AuthField {
  key: string;
  label: string;
  type: 'text' | 'number' | 'email' | 'password';
  default?: string | number;
  optional?: boolean;
}

export interface AuthConfig {
  provider?: string;
  scopes?: string[];
  client_id_env?: string;
  redirect_uri?: string;
  api_id_env?: string;
  api_hash_env?: string;
  fields?: AuthField[];
}

// WebSocket message types
interface WebSocketMessage {
  type: string;
  payload: any;
}

// Preference types
export interface MarketplacePreference {
  preference_type: string;
  value: any;
  timestamp?: string;
  metadata?: Record<string, any>;
}

export interface RecommendedIntegration {
  integration_id: string;
  name: string;
  description: string;
  category: string;
  score: number;
  reason: string;
}

// Context state interface
interface IntegrationsContextState {
  // Data
  integrations: Integration[];
  states: Record<string, IntegrationState>;
  isLoading: boolean;
  error: string | null;
  isConnected: boolean;
  
  // Preferences
  preferences: MarketplacePreference[];
  recommendations: RecommendedIntegration[];
  preferencesLoading: boolean;
  
  // Actions
  refreshIntegrations: () => void;
  enableIntegration: (integrationId: string) => Promise<void>;
  disableIntegration: (integrationId: string, forgetCredentials?: boolean) => Promise<void>;
  restartIntegration: (integrationId: string) => Promise<void>;
  forgetIntegration: (integrationId: string) => Promise<void>;
  getIntegrationState: (integrationId: string) => Promise<IntegrationState | null>;
  
  // Auth flows
  startOAuthFlow: (integrationId: string) => Promise<void>;
  submitCredentials: (integrationId: string, credentials: Record<string, string>) => Promise<void>;
  submitTelegramCode: (integrationId: string, code: string) => Promise<void>;
  
  // Auth state
  pendingAuth: { integrationId: string; authType: AuthType; authConfig: AuthConfig } | null;
  clearPendingAuth: () => void;
  
  // Preferences
  storePreference: (preferenceType: string, value: any, metadata?: Record<string, any>) => Promise<boolean>;
  getPreferences: (preferenceType?: string) => Promise<MarketplacePreference[]>;
  getRecommendations: () => Promise<RecommendedIntegration[]>;
  
  // Reconnection
  reconnect: () => void;
  reconnectAttempts: number;
}

// Create context with default values
const IntegrationsContext = createContext<IntegrationsContextState | null>(null);

// Provider props
interface IntegrationsProviderProps {
  children: ReactNode;
  wsUrl?: string;
  maxReconnectAttempts?: number;
  reconnectInterval?: number;
}

export function IntegrationsProvider({ 
  children, 
  wsUrl: customWsUrl,
  maxReconnectAttempts = 5,
  reconnectInterval = 3000,
}: IntegrationsProviderProps) {
  // State
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [states, setStates] = useState<Record<string, IntegrationState>>({});
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [pendingAuth, setPendingAuth] = useState<{ integrationId: string; authType: AuthType; authConfig: AuthConfig } | null>(null);
  
  // Preferences state
  const [preferences, setPreferences] = useState<MarketplacePreference[]>([]);
  const [recommendations, setRecommendations] = useState<RecommendedIntegration[]>([]);
  const [preferencesLoading, setPreferencesLoading] = useState(false);
  const [reconnectAttempts, setReconnectAttempts] = useState(0);
  
  // WebSocket ref
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const messageListenersRef = useRef<((msg: WebSocketMessage) => void)[]>([]);
  const pendingRequestsRef = useRef<Map<string, { resolve: (value: any) => void; reject: (error: any) => void }>>(new Map());
  
  // Get WebSocket URL.
  // Must include a client_id path segment — the backend only registers
  // @app.websocket("/ws/{client_id}") so bare "/ws" always gets a 403.
  // Use a dedicated "iris_integration" slot to avoid conflicting with the
  // primary "iris" connection opened by useIRISWebSocket.
  const wsUrl = customWsUrl || process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws/iris_integration';
  
  // Deep link handling for OAuth callbacks
  useDeepLink({
    debug: process.env.NODE_ENV === 'development',
    onOAuthCallback: (params) => {
      console.log('[IntegrationsContext] OAuth callback received:', params);
      
      if (params.error) {
        setError(`OAuth error: ${params.error_description || params.error}`);
        setPendingAuth(null);
        return;
      }
      
      if (params.code && pendingAuth) {
        // Send OAuth code to backend
        sendMessage({
          type: 'integration_oauth_callback',
          payload: {
            integration_id: pendingAuth.integrationId,
            code: params.code,
            state: params.state,
          }
        });
      }
    },
  });
  
  // Connect WebSocket
  const connect = useCallback(() => {
    if (typeof window === 'undefined') return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    
    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      
      ws.onopen = () => {
        console.log('[IntegrationsContext] WebSocket connected');
        setIsConnected(true);
        setReconnectAttempts(0);
        setError(null);
        
        // Request integration list on connect
        sendMessage({ type: 'integration_list', payload: {} });
      };
      
      ws.onclose = () => {
        console.log('[IntegrationsContext] WebSocket disconnected');
        setIsConnected(false);
        wsRef.current = null;
        
        // Attempt reconnection if not at max attempts
        if (reconnectAttempts < maxReconnectAttempts) {
          const nextAttempt = reconnectAttempts + 1;
          const delay = Math.min(reconnectInterval * Math.pow(2, nextAttempt - 1), 30000);
          
          console.log(`[IntegrationsContext] Reconnecting in ${delay}ms (attempt ${nextAttempt}/${maxReconnectAttempts})`);
          
          reconnectTimeoutRef.current = setTimeout(() => {
            setReconnectAttempts(nextAttempt);
            connect();
          }, delay);
        } else {
          setError('Failed to connect to integration server after multiple attempts');
        }
      };
      
      ws.onerror = () => {
        // Browser WebSocket onerror events carry no useful detail (always an empty Event).
        // Downgrade to warn — this fires every time the backend is offline, which is normal
        // during development. The onclose handler will manage reconnection.
        console.warn('[IntegrationsContext] WebSocket connection failed (backend may be offline)');
        setError('WebSocket connection error');
      };
      
      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);

          // Respond to backend-initiated heartbeat pings immediately.
          // The backend's _heartbeat_loop sends {"type":"ping"} every 30s and
          // disconnects if no pong arrives within 5s.  Without this, the
          // iris_integration connection is killed every ~35s.
          if (message.type === 'ping') {
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: 'pong', payload: {} }));
            }
            return; // pings are internal — don't forward to listeners
          }

          // Notify all registered listeners
          messageListenersRef.current.forEach(listener => listener(message));
        } catch (e) {
          console.error('[IntegrationsContext] Failed to parse message:', e);
        }
      };
    } catch (e) {
      console.error('[IntegrationsContext] Failed to create WebSocket:', e);
      setError('Failed to create WebSocket connection');
    }
  }, [wsUrl, reconnectAttempts, maxReconnectAttempts, reconnectInterval]);
  
  // Send message through WebSocket
  const sendMessage = useCallback((message: WebSocketMessage): void => {
    const socket = wsRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(message));
    } else {
      console.warn('[IntegrationsContext] WebSocket not connected, message queued');
      // Could implement message queue here if needed
    }
  }, []);
  
  // Disconnect WebSocket
  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);
  
  // Manual reconnect
  const reconnect = useCallback(() => {
    disconnect();
    setReconnectAttempts(0);
    setError(null);
    connect();
  }, [disconnect, connect]);
  
  // Connect on mount
  useEffect(() => {
    connect();
    
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);
  
  // Message handler
  useEffect(() => {
    const handleMessage = (message: WebSocketMessage) => {
      const { type, payload } = message;
      
      switch (type) {
        case 'integration_list':
          setIntegrations(payload.integrations || []);
          setIsLoading(false);
          break;
          
        case 'integration_list_error':
          setError(payload.error || 'Failed to load integrations');
          setIsLoading(false);
          break;
          
        case 'integration_state':
          if (payload.states) {
            setStates(payload.states);
          } else if (payload.integration_id) {
            setStates(prev => ({
              ...prev,
              [payload.integration_id]: {
                integration_id: payload.integration_id,
                status: payload.status,
                connected_since: payload.connected_since,
                error_message: payload.error_message,
                last_error_at: payload.last_error_at,
                retry_count: payload.retry_count || 0,
              }
            }));
          }
          break;
          
        case 'integration_state_changed':
          if (payload.integration_id && payload.state) {
            setStates(prev => ({
              ...prev,
              [payload.integration_id]: payload.state
            }));
            // Also update in integrations list
            setIntegrations(prev => prev.map(int => 
              int.id === payload.integration_id 
                ? { ...int, status: payload.state.status, is_running: payload.state.status === 'running' }
                : int
            ));
          }
          break;
          
        case 'integration_enable':
          if (payload.status === 'auth_required') {
            setPendingAuth({
              integrationId: payload.integration_id,
              authType: payload.auth_type,
              authConfig: payload.auth_config,
            });
          }
          // Resolve pending promise
          const enableResolver = pendingRequestsRef.current.get(`enable_${payload.integration_id}`);
          if (enableResolver) {
            enableResolver.resolve(payload);
            pendingRequestsRef.current.delete(`enable_${payload.integration_id}`);
          }
          break;
          
        case 'integration_enable_error':
          const enableRejecter = pendingRequestsRef.current.get(`enable_${payload.integration_id}`);
          if (enableRejecter) {
            enableRejecter.reject(new Error(payload.error));
            pendingRequestsRef.current.delete(`enable_${payload.integration_id}`);
          }
          setError(payload.error);
          break;
          
        case 'integration_disable':
          const disableResolver = pendingRequestsRef.current.get(`disable_${payload.integration_id}`);
          if (disableResolver) {
            disableResolver.resolve(payload);
            pendingRequestsRef.current.delete(`disable_${payload.integration_id}`);
          }
          break;
          
        case 'integration_disable_error':
          const disableRejecter = pendingRequestsRef.current.get(`disable_${payload.integration_id}`);
          if (disableRejecter) {
            disableRejecter.reject(new Error(payload.error));
            pendingRequestsRef.current.delete(`disable_${payload.integration_id}`);
          }
          break;
          
        case 'integration_oauth_callback':
          setPendingAuth(null);
          break;
          
        case 'integration_oauth_callback_error':
          setError(payload.error);
          break;
          
        case 'integration_credentials_auth':
          setPendingAuth(null);
          break;
          
        case 'integration_credentials_auth_error':
          setError(payload.error);
          break;
      }
    };
    
    messageListenersRef.current.push(handleMessage);
    return () => {
      messageListenersRef.current = messageListenersRef.current.filter(l => l !== handleMessage);
    };
  }, []);
  
  // Request integration list
  const refreshIntegrations = useCallback(() => {
    setIsLoading(true);
    setError(null);
    sendMessage({ type: 'integration_list', payload: {} });
  }, [sendMessage]);
  
  // Enable integration
  const enableIntegration = useCallback(async (integrationId: string): Promise<void> => {
    return new Promise((resolve, reject) => {
      pendingRequestsRef.current.set(`enable_${integrationId}`, { resolve, reject });
      sendMessage({
        type: 'integration_enable',
        payload: { integration_id: integrationId }
      });
    });
  }, [sendMessage]);
  
  // Disable integration
  const disableIntegration = useCallback(async (integrationId: string, forgetCredentials: boolean = false): Promise<void> => {
    return new Promise((resolve, reject) => {
      pendingRequestsRef.current.set(`disable_${integrationId}`, { resolve, reject });
      sendMessage({
        type: 'integration_disable',
        payload: { integration_id: integrationId, forget_credentials: forgetCredentials }
      });
    });
  }, [sendMessage]);
  
  // Restart integration
  const restartIntegration = useCallback(async (integrationId: string): Promise<void> => {
    return new Promise((resolve, reject) => {
      pendingRequestsRef.current.set(`restart_${integrationId}`, { resolve, reject });
      sendMessage({
        type: 'integration_restart',
        payload: { integration_id: integrationId }
      });
    });
  }, [sendMessage]);
  
  // Forget integration credentials
  const forgetIntegration = useCallback(async (integrationId: string): Promise<void> => {
    return new Promise((resolve, reject) => {
      pendingRequestsRef.current.set(`forget_${integrationId}`, { resolve, reject });
      sendMessage({
        type: 'integration_forget',
        payload: { integration_id: integrationId }
      });
    });
  }, [sendMessage]);
  
  // Get integration state
  const getIntegrationState = useCallback(async (integrationId: string): Promise<IntegrationState | null> => {
    return new Promise((resolve) => {
      const handler = (message: WebSocketMessage) => {
        if (message.type === 'integration_state' && message.payload.integration_id === integrationId) {
          resolve(message.payload);
          messageListenersRef.current = messageListenersRef.current.filter(l => l !== handler);
        }
      };
      messageListenersRef.current.push(handler);
      sendMessage({
        type: 'integration_state',
        payload: { integration_id: integrationId }
      });
    });
  }, [sendMessage]);
  
  // Start OAuth flow
  const startOAuthFlow = useCallback(async (integrationId: string): Promise<void> => {
    sendMessage({
      type: 'integration_oauth_callback',
      payload: { integration_id: integrationId }
    });
  }, [sendMessage]);
  
  // Submit credentials
  const submitCredentials = useCallback(async (integrationId: string, credentials: Record<string, string>): Promise<void> => {
    sendMessage({
      type: 'integration_credentials_auth',
      payload: { integration_id: integrationId, credentials }
    });
  }, [sendMessage]);
  
  // Submit Telegram verification code
  const submitTelegramCode = useCallback(async (integrationId: string, code: string): Promise<void> => {
    sendMessage({
      type: 'integration_telegram_auth',
      payload: { integration_id: integrationId, code }
    });
  }, [sendMessage]);
  
  // Clear pending auth
  const clearPendingAuth = useCallback(() => {
    setPendingAuth(null);
  }, []);
  
  // Store marketplace preference
  const storePreference = useCallback(async (
    preferenceType: string,
    value: any,
    metadata?: Record<string, any>
  ): Promise<boolean> => {
    return new Promise((resolve) => {
      const handler = (message: WebSocketMessage) => {
        if (message.type === 'marketplace_preference_stored') {
          resolve(message.payload?.success ?? false);
          messageListenersRef.current = messageListenersRef.current.filter(l => l !== handler);
        }
      };
      messageListenersRef.current.push(handler);
      sendMessage({
        type: 'marketplace_preference_store',
        payload: {
          user_id: 'default_user',
          preference_type: preferenceType,
          value,
          metadata,
        }
      });
      // Timeout after 5 seconds
      setTimeout(() => {
        messageListenersRef.current = messageListenersRef.current.filter(l => l !== handler);
        resolve(false);
      }, 5000);
    });
  }, [sendMessage]);
  
  // Get marketplace preferences
  const getPreferences = useCallback(async (
    preferenceType?: string
  ): Promise<MarketplacePreference[]> => {
    return new Promise((resolve) => {
      setPreferencesLoading(true);
      const handler = (message: WebSocketMessage) => {
        if (message.type === 'marketplace_preferences') {
          const prefs = message.payload?.preferences || [];
          setPreferences(prefs);
          setPreferencesLoading(false);
          resolve(prefs);
          messageListenersRef.current = messageListenersRef.current.filter(l => l !== handler);
        }
      };
      messageListenersRef.current.push(handler);
      sendMessage({
        type: 'marketplace_preferences_get',
        payload: {
          user_id: 'default_user',
          preference_type: preferenceType,
        }
      });
      // Timeout after 5 seconds
      setTimeout(() => {
        messageListenersRef.current = messageListenersRef.current.filter(l => l !== handler);
        setPreferencesLoading(false);
        resolve([]);
      }, 5000);
    });
  }, [sendMessage]);
  
  // Get recommendations
  const getRecommendations = useCallback(async (): Promise<RecommendedIntegration[]> => {
    return new Promise((resolve) => {
      setPreferencesLoading(true);
      const handler = (message: WebSocketMessage) => {
        if (message.type === 'marketplace_recommendations') {
          const recs = message.payload?.recommendations || [];
          setRecommendations(recs);
          setPreferencesLoading(false);
          resolve(recs);
          messageListenersRef.current = messageListenersRef.current.filter(l => l !== handler);
        }
      };
      messageListenersRef.current.push(handler);
      sendMessage({
        type: 'marketplace_recommendations_get',
        payload: {
          user_id: 'default_user',
        }
      });
      // Timeout after 5 seconds
      setTimeout(() => {
        messageListenersRef.current = messageListenersRef.current.filter(l => l !== handler);
        setPreferencesLoading(false);
        resolve([]);
      }, 5000);
    });
  }, [sendMessage]);
  
  // Context value
  const value: IntegrationsContextState = {
    integrations,
    states,
    isLoading,
    error,
    isConnected,
    refreshIntegrations,
    enableIntegration,
    disableIntegration,
    restartIntegration,
    forgetIntegration,
    getIntegrationState,
    startOAuthFlow,
    submitCredentials,
    submitTelegramCode,
    pendingAuth,
    clearPendingAuth,
    // Preferences
    preferences,
    recommendations,
    preferencesLoading,
    storePreference,
    getPreferences,
    getRecommendations,
    reconnect,
    reconnectAttempts,
  };
  
  return (
    <IntegrationsContext.Provider value={value}>
      {children}
    </IntegrationsContext.Provider>
  );
}

// Custom hook to use the context
export function useIntegrationsContext(): IntegrationsContextState {
  const context = useContext(IntegrationsContext);
  if (!context) {
    throw new Error('useIntegrationsContext must be used within an IntegrationsProvider');
  }
  return context;
}

// Export the raw context for advanced use cases
export { IntegrationsContext };
