/**
 * useDeepLink Hook
 * 
 * Handles Tauri deep link events for OAuth callbacks and other URI schemes.
 * Listens for 'deep-link' events from the Tauri backend and parses the URL.
 * 
 * Usage:
 * ```tsx
 * useDeepLink({
 *   onOAuthCallback: (params) => {
 *     // Handle OAuth callback
 *   }
 * });
 * ```
 */

import { useEffect, useCallback, useRef } from 'react';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';

export interface DeepLinkParams {
  url: string;
  scheme: string;
  path: string;
  queryParams: Record<string, string>;
}

export interface UseDeepLinkOptions {
  /** Callback when any deep link is received */
  onDeepLink?: (params: DeepLinkParams) => void;
  /** Callback specifically for OAuth callbacks (iris://oauth/callback) */
  onOAuthCallback?: (params: {
    code?: string;
    state?: string;
    error?: string;
    error_description?: string;
  }) => void;
  /** Enable debug logging */
  debug?: boolean;
}

/**
 * Parse a deep link URL into its components
 */
function parseDeepLink(url: string): DeepLinkParams | null {
  try {
    const urlObj = new URL(url);
    const queryParams: Record<string, string> = {};
    
    // Parse query parameters
    urlObj.searchParams.forEach((value, key) => {
      queryParams[key] = value;
    });
    
    return {
      url,
      scheme: urlObj.protocol.replace(':', ''),
      path: urlObj.pathname,
      queryParams,
    };
  } catch (error) {
    console.error('[useDeepLink] Failed to parse URL:', url, error);
    return null;
  }
}

/**
 * Hook for handling Tauri deep link events
 */
export function useDeepLink(options: UseDeepLinkOptions = {}): void {
  const { onDeepLink, onOAuthCallback, debug = false } = options;
  const unlistenRef = useRef<UnlistenFn | null>(null);

  const handleDeepLink = useCallback((url: string) => {
    if (debug) {
      console.log('[useDeepLink] Received deep link:', url);
    }

    const parsed = parseDeepLink(url);
    if (!parsed) return;

    // Call general deep link handler
    onDeepLink?.(parsed);

    // Handle OAuth callbacks specifically
    if (parsed.scheme === 'iris' && parsed.path === '/oauth/callback') {
      if (debug) {
        console.log('[useDeepLink] OAuth callback detected:', parsed.queryParams);
      }

      const { code, state, error, error_description } = parsed.queryParams;
      
      onOAuthCallback?.({
        code,
        state,
        error,
        error_description,
      });
    }
  }, [onDeepLink, onOAuthCallback, debug]);

  useEffect(() => {
    let isMounted = true;

    // Listen for deep link events from Tauri
    const setupListener = async () => {
      try {
        const unlisten = await listen<string>('deep-link', (event) => {
          if (isMounted && event.payload) {
            handleDeepLink(event.payload);
          }
        });

        if (isMounted) {
          unlistenRef.current = unlisten;
        } else {
          unlisten();
        }
      } catch (error) {
        console.error('[useDeepLink] Failed to set up listener:', error);
      }
    };

    setupListener();

    // Cleanup
    return () => {
      isMounted = false;
      if (unlistenRef.current) {
        unlistenRef.current();
        unlistenRef.current = null;
      }
    };
  }, [handleDeepLink]);
}

/**
 * Standalone function to check if running in Tauri environment
 */
export function isTauri(): boolean {
  return typeof window !== 'undefined' && 
         typeof (window as any).__TAURI__ !== 'undefined';
}

/**
 * Parse OAuth callback URL manually (for non-Tauri environments or testing)
 */
export function parseOAuthCallback(url: string): {
  code?: string;
  state?: string;
  error?: string;
  error_description?: string;
} | null {
  try {
    const urlObj = new URL(url);
    const params: Record<string, string> = {};
    
    urlObj.searchParams.forEach((value, key) => {
      params[key] = value;
    });
    
    return {
      code: params.code,
      state: params.state,
      error: params.error,
      error_description: params.error_description,
    };
  } catch (error) {
    console.error('[useDeepLink] Failed to parse OAuth callback:', error);
    return null;
  }
}

export default useDeepLink;
