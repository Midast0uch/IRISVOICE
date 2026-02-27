"use client"

import React, { createContext, useContext, useReducer, useEffect, useCallback, useMemo, useState, type ReactNode } from "react"
import { useIRISWebSocket } from "@/hooks/useIRISWebSocket"
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
import { MAIN_CATEGORY_IDS, SUB_NODE_IDS } from "@/data/navigation-ids"
import { getMiniNodesForSubnode } from "@/data/mini-nodes"

const CONFIRMED_NODES_KEY = 'irisvoice_confirmed_nodes'

// Mapping from main category to sub-node IDs
const CATEGORY_TO_SUBNODES: Record<string, string[]> = {
  [MAIN_CATEGORY_IDS.VOICE]: [
    SUB_NODE_IDS.VOICE_INPUT,
    SUB_NODE_IDS.VOICE_OUTPUT,
    SUB_NODE_IDS.VOICE_PROCESSING,
    SUB_NODE_IDS.VOICE_MODEL,
  ],
  [MAIN_CATEGORY_IDS.AGENT]: [
    SUB_NODE_IDS.AGENT_IDENTITY,
    SUB_NODE_IDS.AGENT_WAKE,
    SUB_NODE_IDS.AGENT_SPEECH,
    SUB_NODE_IDS.AGENT_MEMORY,
  ],
  [MAIN_CATEGORY_IDS.AUTOMATE]: [
    SUB_NODE_IDS.AUTOMATE_TOOLS,
    SUB_NODE_IDS.AUTOMATE_VISION,
    SUB_NODE_IDS.AUTOMATE_WORKFLOWS,
    SUB_NODE_IDS.AUTOMATE_SHORTCUTS,
    SUB_NODE_IDS.AUTOMATE_GUI,
  ],
  [MAIN_CATEGORY_IDS.SYSTEM]: [
    SUB_NODE_IDS.SYSTEM_POWER,
    SUB_NODE_IDS.SYSTEM_DISPLAY,
    SUB_NODE_IDS.SYSTEM_STORAGE,
    SUB_NODE_IDS.SYSTEM_NETWORK,
  ],
  [MAIN_CATEGORY_IDS.CUSTOMIZE]: [
    SUB_NODE_IDS.CUSTOMIZE_THEME,
    SUB_NODE_IDS.CUSTOMIZE_STARTUP,
    SUB_NODE_IDS.CUSTOMIZE_BEHAVIOR,
    SUB_NODE_IDS.CUSTOMIZE_NOTIFICATIONS,
  ],
  [MAIN_CATEGORY_IDS.MONITOR]: [
    SUB_NODE_IDS.MONITOR_ANALYTICS,
    SUB_NODE_IDS.MONITOR_LOGS,
    SUB_NODE_IDS.MONITOR_DIAGNOSTICS,
    SUB_NODE_IDS.MONITOR_UPDATES,
  ],
}

const initialState: NavState = {
  level: 1,
  history: [],
  mainView: 'navigation',
  selectedMain: null,
  selectedSub: null,
  isTransitioning: false,
  transitionDirection: null,
  // Mini node stack state (Level 3)
  miniNodeStack: [],
  activeMiniNodeIndex: 0,
  confirmedMiniNodes: [],
  miniNodeValues: {},
  view: null,
}

/**
 * Validates navigation state consistency
 * 
 * CRITICAL RULES:
 * - Level 2: No requirements (showing main categories)
 * - Level 3: MUST have selectedMain (showing subnodes for a category)
 * 
 * @param state - Current navigation state
 * @returns true if state is valid, false otherwise
 */
function validateNavState(state: NavState): boolean {
  // Level 3 must have selectedMain
  if (state.level === 3 && !state.selectedMain) {
    if (process.env.NODE_ENV === 'development') {
      console.error('❌ Navigation State Error: Level 3 requires selectedMain to be set')
      console.error('Current state:', { level: state.level, selectedMain: state.selectedMain })
    }
    return false
  }
  
  return true
}

/**
 * Normalizes navigation level to valid range [1, 3]
 * Converts any level 4 values to level 3 for WheelView integration
 * Handles edge cases like NaN, null, undefined, Infinity
 * 
 * @param level - Level value to normalize
 * @returns Normalized level in range [1, 3]
 */
function normalizeLevel(level: number): NavigationLevel {
  // Handle NaN, null, undefined, Infinity
  if (!Number.isFinite(level)) return 1
  if (level > 3) return 3
  if (level < 1) return 1
  return level as NavigationLevel
}

/**
 * Logs navigation state changes in development mode
 * Helps debug navigation issues by showing state transitions
 * 
 * @param action - The action being dispatched
 * @param prevState - State before action
 * @param nextState - State after action
 */
function logNavStateChange(action: NavAction, prevState: NavState, nextState: NavState): void {
  if (process.env.NODE_ENV !== 'development') return
  
  // Only log if level or selections changed
  const levelChanged = prevState.level !== nextState.level
  const mainChanged = prevState.selectedMain !== nextState.selectedMain
  const subChanged = prevState.selectedSub !== nextState.selectedSub
  
  if (levelChanged || mainChanged || subChanged) {
    console.log('🔄 Navigation State Change:', {
      action: action.type,
      transition: `Level ${prevState.level} → Level ${nextState.level}`,
      selectedMain: nextState.selectedMain,
      selectedSub: nextState.selectedSub,
      direction: nextState.transitionDirection
    })
    
    // Validate the new state
    if (!validateNavState(nextState)) {
      console.warn('⚠️ Invalid state detected after action:', action.type)
    }
  }
}

function navReducer(state: NavState, action: NavAction): NavState {
  let nextState: NavState
  
  switch (action.type) {
    case 'EXPAND_TO_MAIN': {
      if (state.level !== 1) {
        nextState = state
        break
      }
      nextState = {
        ...state,
        level: 2,
        history: [...state.history, { level: 1, nodeId: null }],
        transitionDirection: 'forward',
      }
      break
    }

    case 'SELECT_MAIN': {
      // Allow transition even if level changed due to React batching
      // Extract miniNodes from payload (default to empty array if not provided)
      const miniNodes = action.payload.miniNodes || []
      nextState = {
        ...state,
        level: 3,
        selectedMain: action.payload.nodeId,
        miniNodeStack: miniNodes,
        activeMiniNodeIndex: miniNodes.length > 0 ? 0 : state.activeMiniNodeIndex,
        history: [...state.history, { level: 2, nodeId: null }],
        transitionDirection: 'forward',
      }
      break
    }

    case 'SELECT_SUB': {
      // Allow transition even if level is transitioning (level 3 or 4)
      // Updated to set level to 3 (not 4) for WheelView integration
      nextState = {
        ...state,
        level: 3,
        selectedSub: action.payload.subnodeId,
        miniNodeStack: action.payload.miniNodes,
        activeMiniNodeIndex: 0,
        history: [...state.history, { level: 3, nodeId: state.selectedMain }],
        transitionDirection: 'forward',
      }
      break
    }

    case 'GO_BACK': {
      if (state.level === 1) {
        nextState = state
        break
      }
      
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
        // Keep selectedMain so the main node remains highlighted at level 2
        newSelectedSub = null
        newMiniNodeStack = []
        newActiveMiniNodeIndex = 0
        newConfirmedMiniNodes = []
      }
      // Level 3 state is preserved (miniNodeStack and activeMiniNodeIndex remain)

      nextState = {
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
      break
    }

    case 'COLLAPSE_TO_IDLE': {
      nextState = {
        ...initialState,
        miniNodeValues: state.miniNodeValues, // Persist values across sessions
        transitionDirection: 'backward',
      }
      break
    }

    case 'SET_VIEW': {
      nextState = {
        ...state,
        view: action.payload.view,
      }
      break
    }

    case 'SET_MAIN_VIEW': {
      nextState = {
        ...state,
        mainView: action.payload.view,
      }
      break
    }

    case 'SET_TRANSITIONING': {
      nextState = {
        ...state,
        isTransitioning: action.payload,
        transitionDirection: action.payload ? state.transitionDirection : null,
      }
      break
    }

    case 'RESTORE_STATE': {
      // Validate and normalize restored state to prevent level 4 from old storage
      const restoredLevel = action.payload.level
      const validLevel = normalizeLevel(restoredLevel)
      
      nextState = {
        ...action.payload,
        level: validLevel,
        isTransitioning: false,
        transitionDirection: null,
      }
      break
    }

    // Mini node stack actions
    case 'ROTATE_STACK_FORWARD': {
      if (state.level !== 3 || state.miniNodeStack.length === 0) {
        nextState = state
        break
      }
      const newIndex = (state.activeMiniNodeIndex + 1) % state.miniNodeStack.length
      nextState = {
        ...state,
        activeMiniNodeIndex: newIndex,
      }
      break
    }

    case 'ROTATE_STACK_BACKWARD': {
      if (state.level !== 3 || state.miniNodeStack.length === 0) {
        nextState = state
        break
      }
      const newIndex = state.activeMiniNodeIndex === 0 
        ? state.miniNodeStack.length - 1 
        : state.activeMiniNodeIndex - 1
      nextState = {
        ...state,
        activeMiniNodeIndex: newIndex,
      }
      break
    }

    case 'JUMP_TO_MINI_NODE': {
      if (state.level !== 3) {
        nextState = state
        break
      }
      const index = action.payload.index
      if (index < 0 || index >= state.miniNodeStack.length) {
        nextState = state
        break
      }
      nextState = {
        ...state,
        activeMiniNodeIndex: index,
      }
      break
    }

    case 'CONFIRM_MINI_NODE': {
      if (state.level !== 3) {
        nextState = state
        break
      }
      const { id, values } = action.payload
      const miniNode = state.miniNodeStack.find(n => n.id === id)
      if (!miniNode) {
        nextState = state
        break
      }
      
      // Check if already confirmed
      if (state.confirmedMiniNodes.some(n => n.id === id)) {
        nextState = state
        break
      }
      
      // Limit to 8 confirmed nodes
      if (state.confirmedMiniNodes.length >= 8) {
        nextState = state
        break
      }
      
      const confirmedNode: import("@/types/navigation").ConfirmedNode = {
        id,
        label: miniNode.label,
        icon: miniNode.icon,
        values,
        orbitAngle: ((state.confirmedMiniNodes.length * 45) - 90) % 360, // Start from top (-90°), spread 45° apart
        timestamp: Date.now(),
      }
      
      nextState = {
        ...state,
        confirmedMiniNodes: [...state.confirmedMiniNodes, confirmedNode],
        miniNodeValues: {
          ...state.miniNodeValues,
          [id]: values,
        },
      }
      break
    }

    case 'RECALL_CONFIRMED_NODE': {
      if (state.level !== 3) {
        nextState = state
        break
      }
      const nodeId = action.payload.id
      const nodeIndex = state.miniNodeStack.findIndex(n => n.id === nodeId)
      if (nodeIndex === -1) {
        nextState = state
        break
      }
      
      nextState = {
        ...state,
        activeMiniNodeIndex: nodeIndex,
      }
      break
    }

    case 'UPDATE_MINI_NODE_VALUE': {
      const { nodeId, fieldId, value } = action.payload
      nextState = {
        ...state,
        miniNodeValues: {
          ...state.miniNodeValues,
          [nodeId]: {
            ...state.miniNodeValues[nodeId],
            [fieldId]: value,
          },
        },
      }
      break
    }

    case 'CLEAR_MINI_NODE_STATE': {
      nextState = {
        ...state,
        miniNodeStack: [],
        activeMiniNodeIndex: 0,
        confirmedMiniNodes: [],
      }
      break
    }

    default:
      nextState = state
  }
  
  // Log state changes and validate in development
  logNavStateChange(action, state, nextState)
  
  return nextState
}

function getIrisOrbState(state: NavState, mainNodeLabels: Record<string, string>, subNodeLabels: Record<string, string>): IrisOrbState {
  switch (state.level) {
    case 1:
      return { label: 'IRIS', icon: 'home', showBackIndicator: false }
    case 2:
      return { label: 'IRIS', icon: 'close', showBackIndicator: true }
    case 3:
      // Level 3 now shows WheelView with both sub-nodes and mini-nodes
      if (state.selectedSub) {
        return { 
          label: subNodeLabels[state.selectedSub] || state.selectedSub.toUpperCase(),
          icon: 'back',
          showBackIndicator: true 
        }
      }
      return { 
        label: state.selectedMain ? (mainNodeLabels[state.selectedMain] || state.selectedMain.toUpperCase()) : 'IRIS',
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
  subnodes: Record<string, any[]> // Add subnodes to the context

  // Functions that dispatch actions AND send WebSocket messages
  handleExpandToMain: () => void
  handleSelectMain: (nodeId: string) => void
  handleSelectSub: (subnodeId: string, miniNodes: import("@/types/navigation").MiniNode[]) => void
  handleGoBack: () => void
  handleCollapseToIdle: () => void
  handleIrisClick: () => void

  // Original dispatching functions (for internal use if needed)
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
  setMainView: (view: 'navigation' | 'chat') => void
  setView: (view: string | null) => void

  // WebSocket state and functions
  wsConfirmedNodes: any[]
  currentCategory: string | null
  currentSubnode: string | null
  voiceState: "idle" | "listening" | "processing_conversation" | "processing_tool" | "speaking" | "error"
  audioLevel: number
  fieldValues: Record<string, any>
  fieldErrors: Record<string, string> // Map of "subnodeId:fieldId" to error message
  lastTextResponse: { text: string; sender: "assistant" } | null
  activeTheme: { primary: string; glow: string; font: string } // Add activeTheme from WebSocket
  selectCategory: (category: string) => void
  selectSubnode: (subnodeId: string) => void
  sendMessage: (type: string, payload?: any) => boolean
  clearFieldError: (subnodeId: string, fieldId: string) => void
  
  // Voice actions
  startVoiceCommand: () => void
  endVoiceCommand: () => void
  
  // Chat actions
  clearChat: () => void
  
  // Agent actions
  getAgentStatus: () => void
  getAgentTools: () => void
}

const NavigationContext = createContext<NavigationContextValue | undefined>(undefined)

export function NavigationProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(navReducer, initialState)
  const [config, setConfig] = useState<NavigationConfig>(DEFAULT_NAV_CONFIG)
  const [mainNodeLabels, setMainNodeLabels] = useState<Record<string, string>>({})
  const [subNodeLabels, setSubNodeLabels] = useState<Record<string, string>>({})

  // WebSocket integration
  const {
    confirmedNodes: wsConfirmedNodes,
    currentCategory,
    currentSubnode,
    voiceState,
    audioLevel,
    fieldValues,
    fieldErrors,
    lastTextResponse,
    theme: activeTheme, // Expose theme from WebSocket as activeTheme
    selectCategory,
    selectSubnode,
    sendMessage,
    clearFieldError,
    subnodes, // This is the subnodes from WebSocket
    startVoiceCommand,
    endVoiceCommand,
    clearChat: wsClearChat,
    getAgentStatus,
    getAgentTools,
  } = useIRISWebSocket()

  // Initialize from localStorage with migration support
  useEffect(() => {
    // Restore navigation state with migration
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      if (saved) {
        const parsed = JSON.parse(saved)
        let migrated = false
        
        // Normalize level 4 to level 3
        if (parsed.level === 4 || parsed.level > 3) {
          parsed.level = 3
          migrated = true
        }
        
        // Remove obsolete level4ViewMode property
        if ('level4ViewMode' in parsed) {
          delete parsed.level4ViewMode
          migrated = true
        }
        
        // Preserve Mini_Node_Stack and miniNodeValues during migration
        // These are already in the parsed object, just ensure they're not lost
        const restoredState = {
          ...parsed,
          level: normalizeLevel(parsed.level),
          miniNodeStack: parsed.miniNodeStack || [],
          miniNodeValues: parsed.miniNodeValues || {},
        }
        
        dispatch({ type: 'RESTORE_STATE', payload: restoredState })
        
        // Save migrated state back to localStorage
        if (migrated) {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(restoredState))
          if (process.env.NODE_ENV === 'development') {
            console.log('[Migration] Navigation state migrated to 3-level system')
          }
        }
      }
    } catch (e) {
      // Handle corrupted localStorage data
      if (process.env.NODE_ENV === 'development') {
        console.error('[NavigationContext] Failed to restore state from localStorage:', e)
      }
      // Clear corrupted data and start fresh
      localStorage.removeItem(STORAGE_KEY)
      dispatch({ type: 'RESTORE_STATE', payload: initialState })
    }

    // Restore config
    try {
      const savedConfig = localStorage.getItem(CONFIG_STORAGE_KEY)
      if (savedConfig) {
        const parsed = JSON.parse(savedConfig)
        setConfig({ ...DEFAULT_NAV_CONFIG, ...parsed })
      }
    } catch (e) {
      if (process.env.NODE_ENV === 'development') {
        console.error('[NavigationContext] Failed to restore config from localStorage:', e)
      }
      localStorage.removeItem(CONFIG_STORAGE_KEY)
    }

    // Restore mini node values
    try {
      const savedValues = localStorage.getItem(MINI_NODE_VALUES_KEY)
      if (savedValues) {
        const parsed = JSON.parse(savedValues)
        // Restore all mini node values at once
        dispatch({ 
          type: 'RESTORE_STATE', 
          payload: { 
            ...state, 
            miniNodeValues: parsed 
          } 
        })
      }
    } catch (e) {
      if (process.env.NODE_ENV === 'development') {
        console.error('[NavigationContext] Failed to restore mini node values from localStorage:', e)
      }
      localStorage.removeItem(MINI_NODE_VALUES_KEY)
    }
  }, [])

  // Persist state to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
    } catch (e) {
      // Ignore storage errors
    }
  }, [state])

  // Persist config to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify(config))
    } catch (e) {
      // Ignore storage errors
    }
  }, [config])

  // Persist mini node values to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(MINI_NODE_VALUES_KEY, JSON.stringify(state.miniNodeValues))
    } catch (e) {
      // Ignore storage errors
    }
  }, [state.miniNodeValues])

  // Persist confirmed nodes to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(CONFIRMED_NODES_KEY, JSON.stringify(state.confirmedMiniNodes))
    } catch (e) {
      // Ignore storage errors
    }
  }, [state.confirmedMiniNodes])

  const orbState = useMemo(() => getIrisOrbState(state, mainNodeLabels, subNodeLabels), [state, mainNodeLabels, subNodeLabels])

  // Wrapper functions that dispatch actions AND send WebSocket messages
  const handleExpandToMain = useCallback(() => {
    dispatch({ type: 'EXPAND_TO_MAIN' })
    sendMessage('expand_to_main')
  }, [sendMessage])

  const handleSelectMain = useCallback((nodeId: string) => {
    // Aggregate all mini-nodes from all sub-nodes under this main category
    const allMiniNodes: import("@/types/navigation").MiniNode[] = []
    
    // First, try to get mini-nodes from WebSocket subnodes if they have the miniNodes property
    const categorySubnodes = subnodes[nodeId] || []
    
    if (categorySubnodes.length > 0) {
      for (const subnode of categorySubnodes) {
        // Check if subnode has miniNodes property (from WebSocket)
        if (subnode.miniNodes && Array.isArray(subnode.miniNodes)) {
          allMiniNodes.push(...(subnode.miniNodes as import("@/types/navigation").MiniNode[]))
        }
      }
    }
    
    // If no mini-nodes found from WebSocket, use local SUB_NODES_WITH_MINI data
    if (allMiniNodes.length === 0) {
      const subnodeIds = CATEGORY_TO_SUBNODES[nodeId] || []
      for (const subnodeId of subnodeIds) {
        const miniNodes = getMiniNodesForSubnode(subnodeId)
        if (miniNodes.length > 0) {
          allMiniNodes.push(...miniNodes)
        }
      }
    }
    
    // Dispatch with aggregated mini-nodes
    dispatch({ 
      type: 'SELECT_MAIN', 
      payload: { nodeId, miniNodes: allMiniNodes } 
    })
    sendMessage('select_category', { category: nodeId })
  }, [subnodes, sendMessage])

  const handleSelectSub = useCallback((subnodeId: string, miniNodes: import("@/types/navigation").MiniNode[]) => {
    dispatch({ type: 'SELECT_SUB', payload: { subnodeId, miniNodes } })
    sendMessage('select_subnode', { subnode_id: subnodeId })
  }, [sendMessage])

  const handleGoBack = useCallback(() => {
    dispatch({ type: 'GO_BACK' })
    sendMessage('go_back')
  }, [sendMessage])

  const handleCollapseToIdle = useCallback(() => {
    dispatch({ type: 'COLLAPSE_TO_IDLE' })
    sendMessage('collapse_to_idle')
  }, [sendMessage])

  // Original dispatching functions (for internal use if needed)
  const goBack = useCallback(() => dispatch({ type: 'GO_BACK' }), [])
  const expandToMain = useCallback(() => dispatch({ type: 'EXPAND_TO_MAIN' }), [])
  const selectMain = useCallback((nodeId: string) => dispatch({ type: 'SELECT_MAIN', payload: { nodeId } }), [])
  const selectSub = useCallback((subnodeId: string, miniNodes: import("@/types/navigation").MiniNode[]) => dispatch({ type: 'SELECT_SUB', payload: { subnodeId, miniNodes } }), [])
  const collapseToIdle = useCallback(() => dispatch({ type: 'COLLAPSE_TO_IDLE' }), [])
  const setTransitioning = useCallback((value: boolean) => dispatch({ type: 'SET_TRANSITIONING', payload: value }), [])
  const updateConfig = useCallback((newConfig: Partial<NavigationConfig>) => setConfig(prev => ({ ...prev, ...newConfig })), [])
  const setNodeLabels = useCallback((main: Record<string, string>, sub: Record<string, string>) => {
    setMainNodeLabels(main)
    setSubNodeLabels(sub)
  }, [])

  // Mini node stack helpers
  const rotateStackForward = useCallback(() => dispatch({ type: 'ROTATE_STACK_FORWARD' }), [])
  const rotateStackBackward = useCallback(() => dispatch({ type: 'ROTATE_STACK_BACKWARD' }), [])
  const jumpToMiniNode = useCallback((index: number) => dispatch({ type: 'JUMP_TO_MINI_NODE', payload: { index } }), [])
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

  const setMainView = useCallback((view: 'navigation' | 'chat') => {
    dispatch({ type: 'SET_MAIN_VIEW', payload: { view } })
  }, [])
  const setView = useCallback((view: string | null) => {
    dispatch({ type: 'SET_VIEW', payload: { view } })
  }, [])

  const handleIrisClick = useCallback(() => {
    if (state.level > 1) {
      handleGoBack()
    } else {
      handleExpandToMain()
    }
  }, [state.level, handleGoBack, handleExpandToMain])

  const value = useMemo<NavigationContextValue>(() => ({
    state,
    config,
    orbState,
    dispatch,
    subnodes,

    // Functions that dispatch actions AND send WebSocket messages
    handleExpandToMain,
    handleSelectMain,
    handleSelectSub,
    handleGoBack,
    handleCollapseToIdle,
    handleIrisClick,

    // Original dispatching functions (for internal use if needed)
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
    setMainView,
    setView,

    // WebSocket state and functions
    wsConfirmedNodes,
    currentCategory,
    currentSubnode,
    voiceState,
    audioLevel,
    fieldValues,
    fieldErrors,
    lastTextResponse,
    activeTheme, // Add activeTheme from WebSocket
    selectCategory,
    selectSubnode,
    sendMessage,
    clearFieldError,
    
    // Voice actions
    startVoiceCommand,
    endVoiceCommand,
    
    // Chat actions
    clearChat: wsClearChat,
    
    // Agent actions
    getAgentStatus,
    getAgentTools,
  }), [
    state,
    config,
    orbState,
    dispatch,
    subnodes,

    // Functions that dispatch actions AND send WebSocket messages
    handleExpandToMain,
    handleSelectMain,
    handleSelectSub,
    handleGoBack,
    handleCollapseToIdle,

    // Original dispatching functions (for internal use if needed)
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
    setMainView,
    setView,

    // WebSocket state and functions
    wsConfirmedNodes,
    currentCategory,
    currentSubnode,
    voiceState,
    audioLevel,
    fieldValues,
    fieldErrors,
    lastTextResponse,
    activeTheme, // Add activeTheme to dependencies
    selectCategory,
    selectSubnode,
    sendMessage,
    clearFieldError,
    
    // Voice actions
    startVoiceCommand,
    endVoiceCommand,
    
    // Chat actions
    wsClearChat,
    
    // Agent actions
    getAgentStatus,
    getAgentTools,
  ])

  return (
    <NavigationContext.Provider value={value}>
      {children}
    </NavigationContext.Provider>
  )
}

export function useNavigation() {
  const context = useContext(NavigationContext)
  if (context === undefined) {
    throw new Error('useNavigation must be used within a NavigationProvider')
  }
  return context
}