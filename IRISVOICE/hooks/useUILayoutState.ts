"use client"

import { useState, useCallback, useEffect, useRef } from "react"
import { useNavigation } from "@/contexts/NavigationContext"
import type { DashboardTab } from "@/components/dashboard-wing"

// Re-export DashboardTab for convenience
export type { DashboardTab }

/**
 * UI Layout State enum
 * Defines the three-state UI layout system for the IRIS widget
 * These states operate as a sub-layer only accessible when NavigationContext is at Level 1
 */
export enum UILayoutState {
  UI_STATE_IDLE = 'idle',                // Orb only, chat activation text visible (NavigationContext Level 1)
  UI_STATE_CHAT_OPEN = 'chat_open',      // Chat wing left, Orb retreated (only at NavigationContext Level 1)
  UI_STATE_DASHBOARD_OPEN = 'dashboard_open', // Dashboard wing right, Orb retreated (solo view)
  UI_STATE_BOTH_OPEN = 'both_open'       // Chat left + Dashboard right, Orb retreated (only at NavigationContext Level 1)
}

/**
 * Spotlight State enum
 * Defines the three spotlight configurations when both wings are open (UI_STATE_BOTH_OPEN)
 */
export enum SpotlightState {
  BALANCED = 'balanced',                    // Both wings equal (default)
  CHAT_SPOTLIGHT = 'chatSpotlight',         // ChatWing expanded, DashboardWing minimized
  DASHBOARD_SPOTLIGHT = 'dashboardSpotlight' // DashboardWing expanded, ChatWing minimized
}

export type SpotlightStateType = SpotlightState;

/**
 * Transition direction for animations
 */
export type TransitionDirection = 'forward' | 'backward' | null

/**
 * UI Layout State Manager interface
 */
export interface UILayoutStateManager {
  state: UILayoutState
  isTransitioning: boolean
  transitionDirection: TransitionDirection
  navigationLevel: number
}

/**
 * Custom hook for managing UI layout state machine
 * 
 * Features:
 * - Three-state system: idle, chat_open, both_open
 * - Transition validation to prevent concurrent transitions
 * - Integration with NavigationContext to read current level
 * - Automatic wing closure when NavigationContext changes to Level 2 or 3
 * - Prevents transitions to chat_open or both_open when NavigationContext level is not 1
 * 
 * @returns UI layout state manager with transition functions
 */
export function useUILayoutState() {
  const { state: navState } = useNavigation()
  const [uiState, setUIState] = useState<UILayoutState>(UILayoutState.UI_STATE_IDLE)
  const [isTransitioning, setIsTransitioning] = useState(false)
  const [transitionDirection, setTransitionDirection] = useState<TransitionDirection>(null)
  
  // Spotlight state (works in both UI_STATE_CHAT_OPEN and UI_STATE_BOTH_OPEN)
  const [spotlightState, setSpotlightState] = useState<SpotlightState>(SpotlightState.BALANCED)
  
  // Dashboard tab state for cross-interface navigation
  const [activeDashboardTab, setActiveDashboardTab] = useState<DashboardTab>('dashboard')
  
  // Track if we were in chat spotlight before opening dashboard (for bidirectional transitions)
  const wasChatSpotlightRef = useRef(false)
  
  // Track which wing was active when both were open (for single-wing close transitions)
  const lastActiveWingRef = useRef<'chat' | 'dashboard' | null>(null)
  
  // Track previous navigation level to detect changes
  const prevNavigationLevel = useRef(navState.level)

  /**
   * Validates if a transition to the target state is allowed
   * 
   * @param targetState - The desired UI layout state
   * @returns true if transition is allowed, false otherwise
   */
  const canTransition = useCallback((targetState: UILayoutState): boolean => {
    // Prevent concurrent transitions
    if (isTransitioning) {
      if (process.env.NODE_ENV === 'development') {
        console.warn('[useUILayoutState] Transition blocked: Another transition is in progress')
      }
      return false
    }

    // UI_STATE_CHAT_OPEN, UI_STATE_DASHBOARD_OPEN, and UI_STATE_BOTH_OPEN are only accessible at NavigationContext Level 1
    if (
      (targetState === UILayoutState.UI_STATE_CHAT_OPEN || 
       targetState === UILayoutState.UI_STATE_DASHBOARD_OPEN ||
       targetState === UILayoutState.UI_STATE_BOTH_OPEN) &&
      navState.level !== 1
    ) {
      if (process.env.NODE_ENV === 'development') {
        console.warn(
          `[useUILayoutState] Transition to ${targetState} blocked: NavigationContext level is ${navState.level}, must be 1`
        )
      }
      return false
    }

    return true
  }, [isTransitioning, navState.level])

  /**
   * Transitions to a new UI layout state with validation
   * 
   * @param targetState - The desired UI layout state
   * @param direction - The transition direction for animations
   */
  const transitionTo = useCallback((
    targetState: UILayoutState,
    direction: 'forward' | 'backward'
  ) => {
    if (!canTransition(targetState)) {
      return
    }

    // Start transition
    setIsTransitioning(true)
    setTransitionDirection(direction)
    setUIState(targetState)

    if (process.env.NODE_ENV === 'development') {
      console.log(`[useUILayoutState] Transitioning to ${targetState} (${direction})`)
    }

    // End transition after animation completes (300ms for orb retreat + 250ms for wing animation)
    setTimeout(() => {
      setIsTransitioning(false)
      setTransitionDirection(null)
    }, 550)
  }, [canTransition])

  /**
   * Opens the chat wing
   * Transitions from UI_STATE_IDLE to UI_STATE_CHAT_OPEN
   * Only allowed when NavigationContext level is 1
   */
  const openChat = useCallback(() => {
    if (uiState === UILayoutState.UI_STATE_IDLE) {
      lastActiveWingRef.current = 'chat'
      transitionTo(UILayoutState.UI_STATE_CHAT_OPEN, 'forward')
    }
  }, [uiState, transitionTo])

  /**
   * Opens chat from dashboard solo mode
   * Transitions from UI_STATE_DASHBOARD_OPEN to UI_STATE_BOTH_OPEN
   * Preserves dashboard spotlight state
   */
  const openChatFromDashboard = useCallback(() => {
    if (uiState === UILayoutState.UI_STATE_DASHBOARD_OPEN) {
      lastActiveWingRef.current = null // Both will be active
      // If dashboard was in spotlight, keep it; otherwise use balanced
      if (spotlightState !== SpotlightState.DASHBOARD_SPOTLIGHT) {
        setSpotlightState(SpotlightState.BALANCED)
      }
      transitionTo(UILayoutState.UI_STATE_BOTH_OPEN, 'forward')
    }
  }, [uiState, spotlightState, transitionTo])

  /**
   * Opens the dashboard wing in solo mode
   * Transitions from UI_STATE_IDLE to UI_STATE_DASHBOARD_OPEN
   * Mirrors the ChatWing solo view but for dashboard
   * Only allowed when NavigationContext level is 1
   */
  const openDashboardSolo = useCallback(() => {
    if (uiState === UILayoutState.UI_STATE_IDLE) {
      lastActiveWingRef.current = 'dashboard'
      // Set spotlight to dashboard mode for solo view
      setSpotlightState(SpotlightState.DASHBOARD_SPOTLIGHT)
      transitionTo(UILayoutState.UI_STATE_DASHBOARD_OPEN, 'forward')
    }
  }, [uiState, transitionTo])

  /**
   * Opens the dashboard wing
   * Transitions from UI_STATE_CHAT_OPEN to UI_STATE_BOTH_OPEN
   * Preserves chat spotlight state when transitioning
   * Only allowed when NavigationContext level is 1
   */
  const openDashboard = useCallback(() => {
    if (uiState === UILayoutState.UI_STATE_CHAT_OPEN) {
      // Track that both wings will be active
      lastActiveWingRef.current = null // Both are active
      // Remember if we were in chat spotlight mode
      wasChatSpotlightRef.current = spotlightState === SpotlightState.CHAT_SPOTLIGHT
      // Set appropriate spotlight state for both-open mode
      if (spotlightState === SpotlightState.CHAT_SPOTLIGHT) {
        // Keep chat spotlight active when opening dashboard
        setSpotlightState(SpotlightState.CHAT_SPOTLIGHT)
      } else {
        // Default to balanced when opening dashboard from non-spotlight state
        setSpotlightState(SpotlightState.BALANCED)
      }
      transitionTo(UILayoutState.UI_STATE_BOTH_OPEN, 'forward')
    }
  }, [uiState, spotlightState, transitionTo])

  /**
   * Closes all wings and returns to idle state
   * Can be called from any state
   */
  const closeAll = useCallback(() => {
    if (uiState !== UILayoutState.UI_STATE_IDLE) {
      wasChatSpotlightRef.current = false
      transitionTo(UILayoutState.UI_STATE_IDLE, 'backward')
    }
  }, [uiState, transitionTo])

  /**
   * Closes the chat wing, transitioning to dashboard-only or idle
   * From UI_STATE_BOTH_OPEN: transitions to UI_STATE_DASHBOARD_OPEN (dashboard solo view)
   * From UI_STATE_CHAT_OPEN: transitions to UI_STATE_IDLE
   */
  const closeChat = useCallback(() => {
    if (uiState === UILayoutState.UI_STATE_BOTH_OPEN) {
      // In both-open mode, closing chat transitions to dashboard-only solo view
      lastActiveWingRef.current = 'dashboard'
      wasChatSpotlightRef.current = false
      // Keep dashboard spotlight for the solo view
      setSpotlightState(SpotlightState.DASHBOARD_SPOTLIGHT)
      transitionTo(UILayoutState.UI_STATE_DASHBOARD_OPEN, 'backward')
    } else if (uiState === UILayoutState.UI_STATE_CHAT_OPEN) {
      // In chat-only mode, closing chat returns to idle
      lastActiveWingRef.current = null
      wasChatSpotlightRef.current = false
      transitionTo(UILayoutState.UI_STATE_IDLE, 'backward')
    }
  }, [uiState, transitionTo])

  /**
   * Closes the dashboard wing, transitioning to chat-only or idle
   * From UI_STATE_BOTH_OPEN: transitions to UI_STATE_CHAT_OPEN (chat solo view)
   * From UI_STATE_DASHBOARD_OPEN: transitions to UI_STATE_IDLE
   */
  const closeDashboard = useCallback(() => {
    if (uiState === UILayoutState.UI_STATE_BOTH_OPEN) {
      // In both-open mode, closing dashboard transitions to chat-only solo view
      lastActiveWingRef.current = 'chat'
      // Restore chat spotlight if it was active before, otherwise balanced
      if (wasChatSpotlightRef.current) {
        setSpotlightState(SpotlightState.CHAT_SPOTLIGHT)
      } else {
        setSpotlightState(SpotlightState.BALANCED)
      }
      transitionTo(UILayoutState.UI_STATE_CHAT_OPEN, 'backward')
    } else if (uiState === UILayoutState.UI_STATE_DASHBOARD_OPEN) {
      // In dashboard-only mode, closing dashboard returns to idle
      lastActiveWingRef.current = null
      transitionTo(UILayoutState.UI_STATE_IDLE, 'backward')
    }
  }, [uiState, transitionTo])

  /**
   * Toggles chat spotlight state
   * Works in both UI_STATE_CHAT_OPEN and UI_STATE_BOTH_OPEN
   * Toggles between CHAT_SPOTLIGHT and BALANCED
   */
  const toggleChatSpotlight = useCallback(() => {
    // Allow spotlight toggle in both chat-open and both-open states
    if (uiState !== UILayoutState.UI_STATE_CHAT_OPEN && uiState !== UILayoutState.UI_STATE_BOTH_OPEN) return
    setSpotlightState(prev => 
      prev === SpotlightState.CHAT_SPOTLIGHT 
        ? SpotlightState.BALANCED 
        : SpotlightState.CHAT_SPOTLIGHT
    )
  }, [uiState])

  /**
   * Toggles dashboard spotlight state
   * Works in both UI_STATE_BOTH_OPEN and UI_STATE_DASHBOARD_OPEN
   * Toggles between DASHBOARD_SPOTLIGHT and BALANCED
   */
  const toggleDashboardSpotlight = useCallback(() => {
    // Allow spotlight toggle in both dashboard-open states (solo and both-open)
    if (uiState !== UILayoutState.UI_STATE_BOTH_OPEN && uiState !== UILayoutState.UI_STATE_DASHBOARD_OPEN) return
    setSpotlightState(prev => 
      prev === SpotlightState.DASHBOARD_SPOTLIGHT 
        ? SpotlightState.BALANCED 
        : SpotlightState.DASHBOARD_SPOTLIGHT
    )
  }, [uiState])

  /**
   * Restores balanced spotlight state
   * Can be called from any spotlight state
   */
  const restoreBalanced = useCallback(() => {
    setSpotlightState(SpotlightState.BALANCED)
  }, [])

  /**
   * Cross-interface navigation: Browse Marketplace
   * Opens dashboard and switches to marketplace tab
   */
  const browseMarketplace = useCallback(() => {
    setActiveDashboardTab('marketplace')
    // Open dashboard if not already open
    if (uiState === UILayoutState.UI_STATE_IDLE) {
      transitionTo(UILayoutState.UI_STATE_DASHBOARD_OPEN, 'forward')
    } else if (uiState === UILayoutState.UI_STATE_CHAT_OPEN) {
      // If only chat is open, open both
      transitionTo(UILayoutState.UI_STATE_BOTH_OPEN, 'forward')
    }
    // If dashboard is already open (solo or both), just switch tab
  }, [uiState, transitionTo])

  /**
   * Cross-interface navigation: View Activity
   * Opens dashboard and switches to activity tab
   */
  const viewActivity = useCallback(() => {
    setActiveDashboardTab('activity')
    if (uiState === UILayoutState.UI_STATE_IDLE) {
      transitionTo(UILayoutState.UI_STATE_DASHBOARD_OPEN, 'forward')
    } else if (uiState === UILayoutState.UI_STATE_CHAT_OPEN) {
      transitionTo(UILayoutState.UI_STATE_BOTH_OPEN, 'forward')
    }
  }, [uiState, transitionTo])

  /**
   * Cross-interface navigation: View Logs
   * Opens dashboard and switches to logs tab
   */
  const viewLogs = useCallback(() => {
    setActiveDashboardTab('logs')
    if (uiState === UILayoutState.UI_STATE_IDLE) {
      transitionTo(UILayoutState.UI_STATE_DASHBOARD_OPEN, 'forward')
    } else if (uiState === UILayoutState.UI_STATE_CHAT_OPEN) {
      transitionTo(UILayoutState.UI_STATE_BOTH_OPEN, 'forward')
    }
  }, [uiState, transitionTo])

  /**
   * Automatic wing closure when NavigationContext changes to Level 2 or 3
   * This effect monitors NavigationContext level changes and closes wings automatically
   */
  useEffect(() => {
    const currentLevel = navState.level
    const previousLevel = prevNavigationLevel.current

    // Detect transition from Level 1 to Level 2 or 3
    if (previousLevel === 1 && (currentLevel === 2 || currentLevel === 3)) {
      // Automatically close all wings
      if (uiState !== UILayoutState.UI_STATE_IDLE) {
        if (process.env.NODE_ENV === 'development') {
          console.log(
            `[useUILayoutState] Auto-closing wings: NavigationContext changed from Level ${previousLevel} to Level ${currentLevel}`
          )
        }
        
        // Force immediate transition to idle without validation
        setIsTransitioning(true)
        setTransitionDirection('backward')
        setUIState(UILayoutState.UI_STATE_IDLE)
        
        setTimeout(() => {
          setIsTransitioning(false)
          setTransitionDirection(null)
        }, 550)
      }
    }

    // Update previous level reference
    prevNavigationLevel.current = currentLevel
  }, [navState.level, uiState])

  /**
   * Reset spotlight to balanced only when entering IDLE state
   * This preserves spotlight state during chat-only and both-open transitions
   * while ensuring clean state when returning to idle
   */
  useEffect(() => {
    if (uiState === UILayoutState.UI_STATE_IDLE) {
      setSpotlightState(SpotlightState.BALANCED)
      wasChatSpotlightRef.current = false
    }
  }, [uiState])

  return {
    // Current state
    state: uiState,
    isTransitioning,
    transitionDirection,
    navigationLevel: navState.level,
    
    // Transition functions
    openChat,
    openDashboard,
    openDashboardSolo,
    openChatFromDashboard,
    closeAll,
    closeChat,
    closeDashboard,
    
    // State checks (convenience helpers)
    isIdle: uiState === UILayoutState.UI_STATE_IDLE,
    isChatOpen: uiState === UILayoutState.UI_STATE_CHAT_OPEN,
    isDashboardOpen: uiState === UILayoutState.UI_STATE_DASHBOARD_OPEN,
    isBothOpen: uiState === UILayoutState.UI_STATE_BOTH_OPEN,
    canOpenWings: navState.level === 1, // Wings can only be opened at Level 1
    lastActiveWing: lastActiveWingRef.current,
    
    // Spotlight state (NEW)
    spotlightState,
    isBalanced: spotlightState === SpotlightState.BALANCED,
    isChatSpotlight: spotlightState === SpotlightState.CHAT_SPOTLIGHT,
    isDashboardSpotlight: spotlightState === SpotlightState.DASHBOARD_SPOTLIGHT,
    
    // Spotlight methods (NEW)
    setSpotlightState,
    toggleChatSpotlight,
    toggleDashboardSpotlight,
    restoreBalanced,
    
    // Dashboard tab state (NEW)
    activeDashboardTab,
    setActiveDashboardTab,
    
    // Cross-interface navigation (NEW)
    browseMarketplace,
    viewActivity,
    viewLogs,
  }
}
