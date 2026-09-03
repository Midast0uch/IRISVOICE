"use client"

import { useEffect } from "react"
import { UILayoutState, SpotlightState } from "@/hooks/useUILayoutState"

/**
 * Props for useKeyboardNavigation hook
 */
interface UseKeyboardNavigationProps {
  closeAll: () => void
  uiState: UILayoutState
  spotlightState?: SpotlightState
  restoreBalanced?: () => void
}

/**
 * Custom hook for keyboard navigation
 *
 * Features:
 * - Listens for Escape key press globally
 * - Triggers UI_STATE_IDLE transition on Escape at UI_STATE_CHAT_OPEN
 * - Triggers UI_STATE_IDLE transition on Escape at UI_STATE_DASHBOARD_OPEN
 * - Triggers UI_STATE_IDLE transition on Escape at UI_STATE_BOTH_OPEN
 * - Uses same animations as orb click for consistency (handled by closeAll function)
 * - Preserves voice command functionality (doesn't interfere with voice state)
 *
 * Requirements:
 * - 8.1: Escape at UI_STATE_CHAT_OPEN returns to UI_STATE_IDLE
 * - 8.2: Escape at UI_STATE_DASHBOARD_OPEN returns to UI_STATE_IDLE
 * - 8.3: Escape at UI_STATE_BOTH_OPEN returns to UI_STATE_IDLE
 * - 8.4: Escape closes all open wings simultaneously
 * - 8.5: Wings close via Escape use same animations as clicking the Orb
 * - 8.6: Voice command functionality is preserved
 *
 * @param closeAll - Callback function to close all wings and return to idle state
 * @param uiState - Current UI layout state to determine if Escape should trigger
 */
export function useKeyboardNavigation({ 
  closeAll, 
  uiState, 
  spotlightState,
  restoreBalanced 
}: UseKeyboardNavigationProps): void {
  useEffect(() => {
    /**
     * Handles keydown events for keyboard navigation
     * 
     * @param event - Keyboard event
     */
    const handleKeyDown = (event: KeyboardEvent) => {
      // Check if Escape key was pressed
      if (event.key === 'Escape') {
        // Only trigger closeAll when wings are open
        if (
          uiState === UILayoutState.UI_STATE_CHAT_OPEN ||
          uiState === UILayoutState.UI_STATE_DASHBOARD_OPEN ||
          uiState === UILayoutState.UI_STATE_BOTH_OPEN
        ) {
          // If in spotlight mode (not balanced), restore balanced first
          if (
            spotlightState && 
            restoreBalanced &&
            spotlightState !== SpotlightState.BALANCED
          ) {
            if (process.env.NODE_ENV === 'development') {
              console.log(`[useKeyboardNavigation] Escape pressed at ${uiState} with spotlight ${spotlightState}, restoring balanced view`)
            }
            restoreBalanced()
            return
          }

          if (process.env.NODE_ENV === 'development') {
            console.log(`[useKeyboardNavigation] Escape pressed at ${uiState}, closing all wings`)
          }
          
          closeAll()
        }
        // No action needed when uiState is UI_STATE_IDLE
      }
    }

    // Add global keydown event listener
    window.addEventListener('keydown', handleKeyDown)

    // Cleanup: remove event listener on unmount
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [closeAll, uiState, spotlightState, restoreBalanced])
}
