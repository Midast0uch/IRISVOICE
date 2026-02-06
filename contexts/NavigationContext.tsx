"use client"

import React, { createContext, useContext, useReducer, useEffect, useCallback, useMemo, type ReactNode } from "react"
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
  CONFIG_STORAGE_KEY,
  MINI_NODE_VALUES_KEY
} from "@/types/navigation"

const CONFIRMED_NODES_KEY = 'irisvoice_confirmed_nodes'

const initialState: NavState = {
  level: 1,
  history: [],
  selectedMain: null,
  selectedSub: null,
  isTransitioning: false,
  transitionDirection: null,
  // Mini node stack state (Level 4)
  miniNodeStack: [],
  activeMiniNodeIndex: 0,
  confirmedMiniNodes: [],
  miniNodeValues: {},
}

function navReducer(state: NavState, action: NavAction): NavState {
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
      // Allow transition even if level is transitioning (level 3 or 4)
      return {
        ...state,
        level: 4,
        selectedSub: action.payload.subnodeId,
        miniNodeStack: action.payload.miniNodes,
        activeMiniNodeIndex: 0,
        history: [...state.history, { level: 3, nodeId: state.selectedMain }],
        transitionDirection: 'forward',
      }
    }

    case 'GO_BACK': {
      if (state.level === 1) return state
      
      const newLevel = (state.level - 1) as NavigationLevel
      const newHistory = state.history.slice(0, -1)
      
      let newSelectedMain = state.selectedMain
      let newSelectedSub = state.selectedSub
      let newMiniNodeStack = state.miniNodeStack
      let newActiveMiniNodeIndex = state.activeMiniNodeIndex
      let newConfirmedMiniNodes = state.confirmedMiniNodes

      if (newLevel === 1) {
        newSelectedMain = null
        newSelectedSub = null
        newMiniNodeStack = []
        newActiveMiniNodeIndex = 0
        newConfirmedMiniNodes = []
      } else if (newLevel === 2) {
        newSelectedMain = null
        newSelectedSub = null
        newMiniNodeStack = []
        newActiveMiniNodeIndex = 0
        newConfirmedMiniNodes = []
      } else if (newLevel === 3) {
        newSelectedSub = null
        newMiniNodeStack = []
        newActiveMiniNodeIndex = 0
      }

      return {
        ...state,
        level: newLevel,
        history: newHistory,
        selectedMain: newSelectedMain,
        selectedSub: newSelectedSub,
        miniNodeStack: newMiniNodeStack,
        activeMiniNodeIndex: newActiveMiniNodeIndex,
        confirmedMiniNodes: newConfirmedMiniNodes,
        transitionDirection: 'backward',
      }
    }

    case 'COLLAPSE_TO_IDLE': {
      return {
        ...initialState,
        miniNodeValues: state.miniNodeValues, // Persist values across sessions
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
      const validLevel = (restoredLevel >= 1 && restoredLevel <= 4) ? restoredLevel : 1
      return {
        ...action.payload,
        level: validLevel as NavigationLevel,
        isTransitioning: false,
        transitionDirection: null,
      }
    }

    // Mini node stack actions
    case 'ROTATE_STACK_FORWARD': {
      if (state.level !== 4 || state.miniNodeStack.length === 0) return state
      const newIndex = (state.activeMiniNodeIndex + 1) % state.miniNodeStack.length
      return {
        ...state,
        activeMiniNodeIndex: newIndex,
      }
    }

    case 'ROTATE_STACK_BACKWARD': {
      if (state.level !== 4 || state.miniNodeStack.length === 0) return state
      const newIndex = state.activeMiniNodeIndex === 0 
        ? state.miniNodeStack.length - 1 
        : state.activeMiniNodeIndex - 1
      return {
        ...state,
        activeMiniNodeIndex: newIndex,
      }
    }

    case 'JUMP_TO_MINI_NODE': {
      if (state.level !== 4) return state
      const index = action.payload.index
      if (index < 0 || index >= state.miniNodeStack.length) return state
      return {
        ...state,
        activeMiniNodeIndex: index,
      }
    }

    case 'CONFIRM_MINI_NODE': {
      if (state.level !== 4) return state
      const { id, values } = action.payload
      const miniNode = state.miniNodeStack.find(n => n.id === id)
      if (!miniNode) return state
      
      // Check if already confirmed
      if (state.confirmedMiniNodes.some(n => n.id === id)) return state
      
      // Limit to 8 confirmed nodes
      if (state.confirmedMiniNodes.length >= 8) return state
      
      const confirmedNode: import("@/types/navigation").ConfirmedNode = {
        id,
        label: miniNode.label,
        icon: miniNode.icon,
        values,
        orbitAngle: ((state.confirmedMiniNodes.length * 45) - 90) % 360, // Start from top (-90°), spread 45° apart
        timestamp: Date.now(),
      }
      
      return {
        ...state,
        confirmedMiniNodes: [...state.confirmedMiniNodes, confirmedNode],
        miniNodeValues: {
          ...state.miniNodeValues,
          [id]: values,
        },
      }
    }

    case 'RECALL_CONFIRMED_NODE': {
      if (state.level !== 4) return state
      const nodeId = action.payload.id
      const nodeIndex = state.miniNodeStack.findIndex(n => n.id === nodeId)
      if (nodeIndex === -1) return state
      
      return {
        ...state,
        activeMiniNodeIndex: nodeIndex,
      }
    }

    case 'UPDATE_MINI_NODE_VALUE': {
      const { nodeId, fieldId, value } = action.payload
      return {
        ...state,
        miniNodeValues: {
          ...state.miniNodeValues,
          [nodeId]: {
            ...state.miniNodeValues[nodeId],
            [fieldId]: value,
          },
        },
      }
    }

    case 'CLEAR_MINI_NODE_STATE': {
      return {
        ...state,
        miniNodeStack: [],
        activeMiniNodeIndex: 0,
        confirmedMiniNodes: [],
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
  selectSub: (subnodeId: string, miniNodes: import("@/types/navigation").MiniNode[]) => void
  collapseToIdle: () => void
  setTransitioning: (value: boolean) => void
  updateConfig: (newConfig: Partial<NavigationConfig>) => void
  setNodeLabels: (main: Record<string, string>, sub: Record<string, string>) => void
  // Mini node stack helpers
  rotateStackForward: () => void
  rotateStackBackward: () => void
  jumpToMiniNode: (index: number) => void
  confirmMiniNode: (id: string, values: Record<string, any>) => void
  updateMiniNodeValue: (nodeId: string, fieldId: string, value: any) => void
  recallConfirmedNode: (id: string) => void
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

    // Load mini node values from localStorage
    try {
      const savedMiniValues = localStorage.getItem(MINI_NODE_VALUES_KEY)
      if (savedMiniValues) {
        const parsed = JSON.parse(savedMiniValues)
        // Restore into initialState through a special action
        dispatch({ 
          type: 'RESTORE_STATE', 
          payload: { 
            ...initialState, 
            miniNodeValues: parsed 
          } as NavState 
        })
      }
    } catch (e) {
      console.warn('[NavigationContext] Failed to restore mini node values:', e)
    }

    // Load confirmed nodes from localStorage
    try {
      const savedConfirmedNodes = localStorage.getItem(CONFIRMED_NODES_KEY)
      if (savedConfirmedNodes) {
        const parsed = JSON.parse(savedConfirmedNodes)
        dispatch({ 
          type: 'RESTORE_STATE', 
          payload: { 
            ...initialState, 
            confirmedMiniNodes: parsed 
          } as NavState 
        })
      }
    } catch (e) {
      console.warn('[NavigationContext] Failed to restore confirmed nodes:', e)
    }
  }, [])

  // Navigation state is NOT persisted - always start fresh at level 1
  // Only configuration settings and mini node values are saved

  // Persist mini node values to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(MINI_NODE_VALUES_KEY, JSON.stringify(state.miniNodeValues))
    } catch (e) {
      console.warn('[NavigationContext] Failed to save mini node values:', e)
    }
  }, [state.miniNodeValues])

  // Persist confirmed nodes to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(CONFIRMED_NODES_KEY, JSON.stringify(state.confirmedMiniNodes))
    } catch (e) {
      console.warn('[NavigationContext] Failed to save confirmed nodes:', e)
    }
  }, [state.confirmedMiniNodes])

  const goBack = useCallback(() => {
    if (state.isTransitioning) return
    dispatch({ type: 'GO_BACK' })
  }, [state.isTransitioning])

  const expandToMain = useCallback(() => {
    if (state.isTransitioning) return
    dispatch({ type: 'EXPAND_TO_MAIN' })
  }, [state.isTransitioning])

  const selectMain = useCallback((nodeId: string) => {
    dispatch({ type: 'SELECT_MAIN', payload: { nodeId } })
  }, [])

  const selectSub = useCallback((subnodeId: string, miniNodes: import("@/types/navigation").MiniNode[]) => {
    if (state.isTransitioning) return
    dispatch({ type: 'SELECT_SUB', payload: { subnodeId, miniNodes } })
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

  // Mini node stack helper functions
  const rotateStackForward = useCallback(() => {
    if (state.isTransitioning) return
    dispatch({ type: 'ROTATE_STACK_FORWARD' })
  }, [state.isTransitioning])

  const rotateStackBackward = useCallback(() => {
    if (state.isTransitioning) return
    dispatch({ type: 'ROTATE_STACK_BACKWARD' })
  }, [state.isTransitioning])

  const jumpToMiniNode = useCallback((index: number) => {
    if (state.isTransitioning) return
    dispatch({ type: 'JUMP_TO_MINI_NODE', payload: { index } })
  }, [state.isTransitioning])

  const confirmMiniNode = useCallback((id: string, values: Record<string, any>) => {
    if (state.isTransitioning) return
    dispatch({ type: 'CONFIRM_MINI_NODE', payload: { id, values } })
  }, [state.isTransitioning])

  const updateMiniNodeValue = useCallback((nodeId: string, fieldId: string, value: any) => {
    dispatch({ type: 'UPDATE_MINI_NODE_VALUE', payload: { nodeId, fieldId, value } })
  }, [])

  const recallConfirmedNode = useCallback((id: string) => {
    if (state.isTransitioning) return
    dispatch({ type: 'RECALL_CONFIRMED_NODE', payload: { id } })
  }, [state.isTransitioning])

  const orbState = getIrisOrbState(state, mainNodeLabels, subNodeLabels)

  const value = useMemo<NavigationContextValue>(() => ({
    state,
    config,
    orbState,
    dispatch,
    goBack,
    expandToMain,
    selectMain,
    selectSub,
    collapseToIdle,
    setTransitioning,
    updateConfig,
    setNodeLabels,
    // Mini node stack helpers
    rotateStackForward,
    rotateStackBackward,
    jumpToMiniNode,
    confirmMiniNode,
    updateMiniNodeValue,
    recallConfirmedNode,
  }), [
    state,
    config,
    orbState,
    goBack,
    expandToMain,
    selectMain,
    selectSub,
    collapseToIdle,
    setTransitioning,
    updateConfig,
    setNodeLabels,
    rotateStackForward,
    rotateStackBackward,
    jumpToMiniNode,
    confirmMiniNode,
    updateMiniNodeValue,
    recallConfirmedNode,
  ])

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
