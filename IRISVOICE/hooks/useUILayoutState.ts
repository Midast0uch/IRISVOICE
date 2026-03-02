"use client"

import { useState, useCallback, useEffect, useRef } from "react"
import { useNavigation } from "@/contexts/NavigationContext"

/**
 * UI Layout State enum
 * Defines the three-state UI layout system for the IRIS widget
 * These states operate as a sub-layer only accessible when NavigationContext is at Level 1
 */
export enum UILayoutState {
  UI_STATE_IDLE = 'idle',           // Orb only, chat activation text visible (NavigationContext Level 1)
  UI_STATE_CHAT_OPEN = 'chat_open', // Chat wing left, Orb retreated (only at NavigationContext Level 1)
  UI_STATE_BOTH_OPEN = 'both_open'  // Chat left + Dashboard right, Orb retreated (only at NavigationContext Level 1)
}

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

    // UI_STATE_CHAT_OPEN and UI_STATE_BOTH_OPEN are only accessible at NavigationContext Level 1
    if (
      (targetState === UILayoutState.UI_STATE_CHAT_OPEN || 
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
      transitionTo(UILayoutState.UI_STATE_CHAT_OPEN, 'forward')
    }
  }, [uiState, transitionTo])

  /**
   * Opens the dashboard wing
   * Transitions from UI_STATE_CHAT_OPEN to UI_STATE_BOTH_OPEN
   * Only allowed when NavigationContext level is 1
   */
  const openDashboard = useCallback(() => {
    if (uiState === UILayoutState.UI_STATE_CHAT_OPEN) {
      transitionTo(UILayoutState.UI_STATE_BOTH_OPEN, 'forward')
    }
  }, [uiState, transitionTo])

  /**
   * Closes all wings and returns to idle state
   * Can be called from any state
   */
  const closeAll = useCallback(() => {
    if (uiState !== UILayoutState.UI_STATE_IDLE) {
      transitionTo(UILayoutState.UI_STATE_IDLE, 'backward')
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

  return {
    // Current state
    state: uiState,
    isTransitioning,
    transitionDirection,
    navigationLevel: navState.level,
    
    // Transition functions
    openChat,
    openDashboard,
    closeAll,
    
    // State checks (convenience helpers)
    isIdle: uiState === UILayoutState.UI_STATE_IDLE,
    isChatOpen: uiState === UILayoutState.UI_STATE_CHAT_OPEN,
    isBothOpen: uiState === UILayoutState.UI_STATE_BOTH_OPEN,
    canOpenWings: navState.level === 1, // Wings can only be opened at Level 1
  }
}
