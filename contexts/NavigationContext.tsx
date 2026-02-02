"use client"

import React, { createContext, useContext, useReducer, useEffect, useCallback, type ReactNode } from "react"
import type { 
  NavState, 
  NavAction, 
  NavigationLevel, 
  NavigationConfig, 
  IrisOrbState,
  HistoryEntry 
} from "@/types/navigation"
import { 
  DEFAULT_NAV_CONFIG, 
  STORAGE_KEY, 
  CONFIG_STORAGE_KEY 
} from "@/types/navigation"

const initialState: NavState = {
  level: 1,
  history: [],
  selectedMain: null,
  selectedSub: null,
  selectedMini: null,
  isTransitioning: false,
  transitionDirection: null,
}

function navReducer(state: NavState, action: NavAction): NavState {
  console.log('[DEBUG] navReducer ENTRY:', { 
    actionType: action.type, 
    currentLevel: state.level, 
    isTransitioning: state.isTransitioning,
    selectedMain: state.selectedMain 
  })
  
  switch (action.type) {
    case 'EXPAND_TO_MAIN': {
      if (state.level !== 1) return state
      return {
        ...state,
        level: 2,
        history: [...state.history, { level: 1, nodeId: null }],
        transitionDirection: 'forward',
      }
    }

    case 'SELECT_MAIN': {
      console.log('[DEBUG] Reducer SELECT_MAIN:', { currentLevel: state.level, nodeId: action.payload.nodeId, isTransitioning: state.isTransitioning })
      // Allow transition even if level changed due to React batching
      return {
        ...state,
        level: 3,
        selectedMain: action.payload.nodeId,
        history: [...state.history, { level: 2, nodeId: null }],
        transitionDirection: 'forward',
      }
    }

    case 'SELECT_SUB': {
      if (state.level !== 3) return state
      return {
        ...state,
        level: 4,
        selectedSub: action.payload.nodeId,
        history: [...state.history, { level: 3, nodeId: state.selectedMain }],
        transitionDirection: 'forward',
      }
    }

    case 'CONFIRM_MINI': {
      if (state.level !== 4) return state
      return {
        ...state,
        level: 5,
        selectedMini: action.payload.nodeId,
        history: [...state.history, { level: 4, nodeId: state.selectedSub }],
        transitionDirection: 'forward',
      }
    }

    case 'GO_BACK': {
      if (state.level === 1) return state
      
      const newLevel = (state.level - 1) as NavigationLevel
      const newHistory = state.history.slice(0, -1)
      
      let newSelectedMain = state.selectedMain
      let newSelectedSub = state.selectedSub
      let newSelectedMini = state.selectedMini

      if (newLevel === 1) {
        newSelectedMain = null
        newSelectedSub = null
        newSelectedMini = null
      } else if (newLevel === 2) {
        newSelectedMain = null
        newSelectedSub = null
        newSelectedMini = null
      } else if (newLevel === 3) {
        newSelectedSub = null
        newSelectedMini = null
      } else if (newLevel === 4) {
        newSelectedMini = null
      }

      return {
        ...state,
        level: newLevel,
        history: newHistory,
        selectedMain: newSelectedMain,
        selectedSub: newSelectedSub,
        selectedMini: newSelectedMini,
        transitionDirection: 'backward',
      }
    }

    case 'COLLAPSE_TO_IDLE': {
      return {
        ...initialState,
        transitionDirection: 'backward',
      }
    }

    case 'SET_TRANSITIONING': {
      return {
        ...state,
        isTransitioning: action.payload,
        transitionDirection: action.payload ? state.transitionDirection : null,
      }
    }

    case 'RESTORE_STATE': {
      // Validate and normalize restored state to prevent level 0 from old storage
      const restoredLevel = action.payload.level
      const validLevel = (restoredLevel >= 1 && restoredLevel <= 5) ? restoredLevel : 1
      return {
        ...action.payload,
        level: validLevel as NavigationLevel,
        isTransitioning: false,
        transitionDirection: null,
      }
    }

    default:
      return state
  }
}

function getIrisOrbState(state: NavState, mainNodeLabels: Record<string, string>, subNodeLabels: Record<string, string>): IrisOrbState {
  switch (state.level) {
    case 1:
      return { label: 'IRIS', icon: 'home', showBackIndicator: false }
    case 2:
      return { label: 'CLOSE', icon: 'close', showBackIndicator: true }
    case 3:
      return { 
        label: state.selectedMain ? (mainNodeLabels[state.selectedMain] || state.selectedMain.toUpperCase()) : 'BACK',
        icon: 'back',
        showBackIndicator: true 
      }
    case 4:
      return { 
        label: state.selectedSub ? (subNodeLabels[state.selectedSub] || state.selectedSub.toUpperCase()) : 'BACK',
        icon: 'back',
        showBackIndicator: true 
      }
    case 5:
      return { 
        label: state.selectedMini ? state.selectedMini.toUpperCase() : 'DONE',
        icon: 'back',
        showBackIndicator: true 
      }
    default:
      return { label: 'IRIS', icon: 'home', showBackIndicator: false }
  }
}

interface NavigationContextValue {
  state: NavState
  config: NavigationConfig
  orbState: IrisOrbState
  dispatch: React.Dispatch<NavAction>
  goBack: () => void
  expandToMain: () => void
  selectMain: (nodeId: string) => void
  selectSub: (nodeId: string) => void
  confirmMini: (nodeId: string) => void
  collapseToIdle: () => void
  setTransitioning: (value: boolean) => void
  updateConfig: (newConfig: Partial<NavigationConfig>) => void
  setNodeLabels: (main: Record<string, string>, sub: Record<string, string>) => void
}

const NavigationContext = createContext<NavigationContextValue | null>(null)

interface NavigationProviderProps {
  children: ReactNode
}

export function NavigationProvider({ children }: NavigationProviderProps) {
  const [state, dispatch] = useReducer(navReducer, initialState)
  const [config, setConfig] = React.useState<NavigationConfig>(DEFAULT_NAV_CONFIG)
  const [mainNodeLabels, setMainNodeLabels] = React.useState<Record<string, string>>({})
  const [subNodeLabels, setSubNodeLabels] = React.useState<Record<string, string>>({})

  useEffect(() => {
    // Clear any saved navigation state on startup - start fresh at level 1
    // Only restore configuration, not navigation position
    try {
      localStorage.removeItem(STORAGE_KEY)
    } catch (e) {
      // Ignore
    }

    try {
      const savedConfig = localStorage.getItem(CONFIG_STORAGE_KEY)
      if (savedConfig) {
        setConfig({ ...DEFAULT_NAV_CONFIG, ...JSON.parse(savedConfig) })
      }
    } catch (e) {
      console.warn('[NavigationContext] Failed to restore config:', e)
    }
  }, [])

  // Navigation state is NOT persisted - always start fresh at level 1
  // Only configuration settings are saved

  const goBack = useCallback(() => {
    if (state.isTransitioning) return
    dispatch({ type: 'GO_BACK' })
  }, [state.isTransitioning])

  const expandToMain = useCallback(() => {
    if (state.isTransitioning) return
    dispatch({ type: 'EXPAND_TO_MAIN' })
  }, [state.isTransitioning])

  const selectMain = useCallback((nodeId: string) => {
    console.log('[DEBUG] selectMain called:', { nodeId, level: state.level })
    dispatch({ type: 'SELECT_MAIN', payload: { nodeId } })
  }, [state.level])

  const selectSub = useCallback((nodeId: string) => {
    if (state.isTransitioning) return
    dispatch({ type: 'SELECT_SUB', payload: { nodeId } })
  }, [state.isTransitioning, state.level])

  const confirmMini = useCallback((nodeId: string) => {
    if (state.isTransitioning) return
    dispatch({ type: 'CONFIRM_MINI', payload: { nodeId } })
  }, [state.isTransitioning])

  const collapseToIdle = useCallback(() => {
    if (state.isTransitioning) return
    dispatch({ type: 'COLLAPSE_TO_IDLE' })
  }, [state.isTransitioning])

  const setTransitioning = useCallback((value: boolean) => {
    dispatch({ type: 'SET_TRANSITIONING', payload: value })
  }, [])

  const updateConfig = useCallback((newConfig: Partial<NavigationConfig>) => {
    setConfig(prev => {
      const updated = { ...prev, ...newConfig }
      try {
        localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify(updated))
      } catch (e) {
        console.warn('[NavigationContext] Failed to save config:', e)
      }
      return updated
    })
  }, [])

  const setNodeLabels = useCallback((main: Record<string, string>, sub: Record<string, string>) => {
    setMainNodeLabels(main)
    setSubNodeLabels(sub)
  }, [])

  const orbState = getIrisOrbState(state, mainNodeLabels, subNodeLabels)

  const value: NavigationContextValue = {
    state,
    config,
    orbState,
    dispatch,
    goBack,
    expandToMain,
    selectMain,
    selectSub,
    confirmMini,
    collapseToIdle,
    setTransitioning,
    updateConfig,
    setNodeLabels,
  }

  return (
    <NavigationContext.Provider value={value}>
      {children}
    </NavigationContext.Provider>
  )
}

export function useNavigation() {
  const context = useContext(NavigationContext)
  if (!context) {
    throw new Error('useNavigation must be used within a NavigationProvider')
  }
  return context
}

export function useNavigationLevel(): NavigationLevel {
  const { state } = useNavigation()
  return state.level
}

export function useIsTransitioning(): boolean {
  const { state } = useNavigation()
  return state.isTransitioning
}

export function useTransitionDirection(): 'forward' | 'backward' | null {
  const { state } = useNavigation()
  return state.transitionDirection
}
