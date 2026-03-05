"use client"

import React, { createContext, useContext, useReducer, useEffect, useCallback, useMemo, useState, type ReactNode } from "react"
import { useIRISWebSocket } from "@/hooks/useIRISWebSocket"
import type { 
  NavState, 
  NavAction, 
  NavigationLevel, 
  NavigationConfig, 
  IrisOrbState,
  HistoryEntry,
  Card
} from "@/types/navigation"
import { 
  DEFAULT_NAV_CONFIG, 
  STORAGE_KEY, 
  CONFIG_STORAGE_KEY,
  CARD_VALUES_KEY
} from "@/types/navigation"
import { MAIN_CATEGORY_IDS, SECTION_IDS } from "@/data/navigation-ids"
import { getCardsForSection } from "@/data/cards"

// Mapping from main category to section IDs
const CATEGORY_TO_SECTIONS: Record<string, string[]> = {
  [MAIN_CATEGORY_IDS.VOICE]: [
    SECTION_IDS.VOICE_INPUT,
    SECTION_IDS.VOICE_OUTPUT,
    SECTION_IDS.VOICE_WAKE,
    SECTION_IDS.VOICE_SPEECH,
  ],
  [MAIN_CATEGORY_IDS.AGENT]: [
    SECTION_IDS.AGENT_MODEL_SELECTION,
    SECTION_IDS.AGENT_INFERENCE_MODE,
    SECTION_IDS.AGENT_IDENTITY,
    SECTION_IDS.AGENT_MEMORY,
  ],
  [MAIN_CATEGORY_IDS.AUTOMATE]: [
    SECTION_IDS.AUTOMATE_TOOLS,
    SECTION_IDS.AUTOMATE_VISION,
    SECTION_IDS.AUTOMATE_DESKTOP_CONTROL,
    SECTION_IDS.AUTOMATE_SKILLS,
    SECTION_IDS.AUTOMATE_PROFILE,
  ],
  [MAIN_CATEGORY_IDS.SYSTEM]: [
    SECTION_IDS.SYSTEM_POWER,
    SECTION_IDS.SYSTEM_DISPLAY,
    SECTION_IDS.SYSTEM_STORAGE,
    SECTION_IDS.SYSTEM_NETWORK,
  ],
  [MAIN_CATEGORY_IDS.CUSTOMIZE]: [
    SECTION_IDS.CUSTOMIZE_THEME,
    SECTION_IDS.CUSTOMIZE_STARTUP,
    SECTION_IDS.CUSTOMIZE_BEHAVIOR,
    SECTION_IDS.CUSTOMIZE_NOTIFICATIONS,
  ],
  [MAIN_CATEGORY_IDS.MONITOR]: [
    SECTION_IDS.MONITOR_ANALYTICS,
    SECTION_IDS.MONITOR_LOGS,
    SECTION_IDS.MONITOR_DIAGNOSTICS,
    SECTION_IDS.MONITOR_UPDATES,
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
  // Card stack state (Level 3)
  cardStack: [],
  activeCardIndex: 0,
  cardValues: {},
  view: null,
}

/**
 * Validates navigation state consistency
 * 
 * CRITICAL RULES:
 * - Level 2: No requirements (showing main categories)
 * - Level 3: MUST have selectedMain (showing sections for a category)
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
        history: [...state.history, { level: 1, categoryId: null }],
        transitionDirection: 'forward',
      }
      break
    }

    case 'SELECT_MAIN': {
      // Allow transition even if level changed due to React batching
      // Extract cards from payload (default to empty array if not provided)
      const cards = action.payload.cards || []
      nextState = {
        ...state,
        level: 3,
        selectedMain: action.payload.categoryId,
        cardStack: cards,
        activeCardIndex: cards.length > 0 ? 0 : state.activeCardIndex,
        history: [...state.history, { level: 2, categoryId: null }],
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
        selectedSub: action.payload.sectionId,
        cardStack: action.payload.cards,
        activeCardIndex: 0,
        history: [...state.history, { level: 3, categoryId: state.selectedMain }],
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
      let newCardStack = state.cardStack
      let newActiveCardIndex = state.activeCardIndex

      if (newLevel === 1) {
        newSelectedMain = null
        newSelectedSub = null
        newCardStack = []
        newActiveCardIndex = 0
      } else if (newLevel === 2) {
        // Keep selectedMain so the main category remains highlighted at level 2
        newSelectedSub = null
        newCardStack = []
        newActiveCardIndex = 0
      }
      // Level 3 state is preserved (cardStack and activeCardIndex remain)

      nextState = {
        ...state,
        level: newLevel,
        history: newHistory,
        selectedMain: newSelectedMain,
        selectedSub: newSelectedSub,
        cardStack: newCardStack,
        activeCardIndex: newActiveCardIndex,
        transitionDirection: 'backward',
      }
      break
    }

    case 'COLLAPSE_TO_IDLE': {
      nextState = {
        ...initialState,
        cardValues: state.cardValues, // Persist values across sessions
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

    // Card stack actions
    case 'ROTATE_STACK_FORWARD': {
      if (state.level !== 3 || state.cardStack.length === 0) {
        nextState = state
        break
      }
      const newIndex = (state.activeCardIndex + 1) % state.cardStack.length
      nextState = {
        ...state,
        activeCardIndex: newIndex,
      }
      break
    }

    case 'ROTATE_STACK_BACKWARD': {
      if (state.level !== 3 || state.cardStack.length === 0) {
        nextState = state
        break
      }
      const newIndex = state.activeCardIndex === 0 
        ? state.cardStack.length - 1 
        : state.activeCardIndex - 1
      nextState = {
        ...state,
        activeCardIndex: newIndex,
      }
      break
    }

    case 'JUMP_TO_CARD': {
      if (state.level !== 3) {
        nextState = state
        break
      }
      const index = action.payload.index
      if (index < 0 || index >= state.cardStack.length) {
        nextState = state
        break
      }
      nextState = {
        ...state,
        activeCardIndex: index,
      }
      break
    }

    case 'CONFIRM_CARD': {
      if (state.level !== 3) {
        nextState = state
        break
      }
      const { id, values } = action.payload
      
      nextState = {
        ...state,
        cardValues: {
          ...state.cardValues,
          [id]: values,
        },
      }
      break
    }

    case 'UPDATE_CARD_VALUE': {
      const { cardId, fieldId, value } = action.payload
      nextState = {
        ...state,
        cardValues: {
          ...state.cardValues,
          [cardId]: {
            ...state.cardValues[cardId],
            [fieldId]: value,
          },
        },
      }
      break
    }

    case 'CLEAR_CARD_STATE': {
      nextState = {
        ...state,
        cardStack: [],
        activeCardIndex: 0,
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

function getIrisOrbState(state: NavState, mainCategoryLabels: Record<string, string>, sectionLabels: Record<string, string>): IrisOrbState {
  switch (state.level) {
    case 1:
      return { label: 'IRIS', icon: 'home', showBackIndicator: false }
    case 2:
      return { label: 'IRIS', icon: 'close', showBackIndicator: true }
    case 3:
      // Level 3 now shows WheelView with both sections and cards
      if (state.selectedSub) {
        return { 
          label: sectionLabels[state.selectedSub] || state.selectedSub.toUpperCase(),
          icon: 'back',
          showBackIndicator: true 
        }
      }
      return { 
        label: state.selectedMain ? (mainCategoryLabels[state.selectedMain] || state.selectedMain.toUpperCase()) : 'IRIS',
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
  sections: Record<string, any[]> // Add sections to the context

  // Functions that dispatch actions AND send WebSocket messages
  handleExpandToMain: () => void
  handleSelectMain: (categoryId: string) => void
  handleSelectSection: (sectionId: string, cards: Card[]) => void
  handleGoBack: () => void
  handleCollapseToIdle: () => void
  handleIrisClick: () => void

  // Original dispatching functions (for internal use if needed)
  goBack: () => void
  expandToMain: () => void
  selectMain: (categoryId: string) => void
  selectSection: (sectionId: string, cards: Card[]) => void
  collapseToIdle: () => void
  setTransitioning: (value: boolean) => void
  updateConfig: (newConfig: Partial<NavigationConfig>) => void
  setCategoryLabels: (main: Record<string, string>, sub: Record<string, string>) => void
  // Card stack helpers
  rotateStackForward: () => void
  rotateStackBackward: () => void
  jumpToCard: (index: number) => void
  confirmCard: (id: string, values: Record<string, any>) => void
  updateCardValue: (cardId: string, fieldId: string, value: any) => void
  setMainView: (view: 'navigation' | 'chat') => void
  setView: (view: string | null) => void

  // WebSocket state and functions
  currentCategory: string | null
  currentSection: string | null
  voiceState: "idle" | "listening" | "processing_conversation" | "processing_tool" | "speaking" | "error"
  audioLevel: number
  fieldValues: Record<string, any>
  fieldErrors: Record<string, string> // Map of "sectionId:fieldId" to error message
  lastTextResponse: { text: string; sender: "assistant" } | null
  activeTheme: { primary: string; glow: string; font: string } // Add activeTheme from WebSocket
  selectCategory: (category: string) => void
  selectSectionWs: (sectionId: string) => void
  sendMessage: (type: string, payload?: any) => boolean
  clearFieldError: (sectionId: string, fieldId: string) => void
  
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
  const [mainCategoryLabels, setMainCategoryLabels] = useState<Record<string, string>>({})
  const [sectionLabels, setSectionLabels] = useState<Record<string, string>>({})

  // WebSocket integration
  const {
    currentCategory,
    currentSection,
    voiceState,
    audioLevel,
    fieldValues,
    fieldErrors,
    lastTextResponse,
    theme: activeTheme, // Expose theme from WebSocket as activeTheme
    selectCategory,
    selectSection: selectSectionWs,
    sendMessage,
    clearFieldError,
    sections, // This is the sections from WebSocket
    startVoiceCommand,
    endVoiceCommand,
    clearChat: wsClearChat,
    getAgentStatus,
    getAgentTools,
    getWakeWords,
    getAudioDevices,
  } = useIRISWebSocket()

  // Initialize from localStorage with migration support
  useEffect(() => {
    let restoredState = { ...initialState }
    let migrated = false

    // Step 1: Restore navigation state with migration
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      if (saved) {
        const parsed = JSON.parse(saved)
        
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
        
        // Migrate old property names to new ones
        if (parsed.miniNodeStack) {
          parsed.cardStack = parsed.miniNodeStack
          delete parsed.miniNodeStack
          migrated = true
        }
        if (parsed.activeMiniNodeIndex !== undefined) {
          parsed.activeCardIndex = parsed.activeMiniNodeIndex
          delete parsed.activeMiniNodeIndex
          migrated = true
        }
        if (parsed.miniNodeValues) {
          parsed.cardValues = parsed.miniNodeValues
          delete parsed.miniNodeValues
          migrated = true
        }
        // Remove confirmedMiniNodes (feature removed)
        if (parsed.confirmedMiniNodes) {
          delete parsed.confirmedMiniNodes
          migrated = true
        }
        
        restoredState = {
          ...parsed,
          level: normalizeLevel(parsed.level),
          cardStack: parsed.cardStack || [],
          cardValues: parsed.cardValues || {},
        }
        
        // Save migrated state back to localStorage
        if (migrated) {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(restoredState))
          if (process.env.NODE_ENV === 'development') {
            console.log('[Migration] Navigation state migrated to new terminology')
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
      restoredState = { ...initialState }
    }

    // Step 2: Restore card values (merge into existing restoredState)
    try {
      const savedValues = localStorage.getItem(CARD_VALUES_KEY)
      if (savedValues) {
        const parsed = JSON.parse(savedValues)
        // Merge with existing restoredState.cardValues (from main state or empty)
        restoredState.cardValues = {
          ...restoredState.cardValues,
          ...parsed
        }
      }
    } catch (e) {
      if (process.env.NODE_ENV === 'development') {
        console.error('[NavigationContext] Failed to restore card values from localStorage:', e)
      }
      localStorage.removeItem(CARD_VALUES_KEY)
    }

    // Step 3: Single RESTORE_STATE dispatch with complete state
    dispatch({ type: 'RESTORE_STATE', payload: restoredState })

    // Step 4: Restore config separately (separate state, not part of NavState)
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
  }, [])

  // Persist state with debounce and exclude animation transitions
  useEffect(() => {
    // Skip persistence during animation transitions
    if (state.isTransitioning) return

    const timer = setTimeout(() => {
      try {
        // Only persist meaningful navigation state (exclude transition-related fields)
        const stateToPersist = {
          level: state.level,
          history: state.history,
          mainView: state.mainView,
          selectedMain: state.selectedMain,
          selectedSub: state.selectedSub,
          cardStack: state.cardStack,
          activeCardIndex: state.activeCardIndex,
          cardValues: state.cardValues,
          view: state.view,
          // Note: isTransitioning and transitionDirection are intentionally omitted
        }
        localStorage.setItem(STORAGE_KEY, JSON.stringify(stateToPersist))
      } catch (e) {
        // Ignore storage errors
      }
    }, 100) // 100ms debounce

    return () => clearTimeout(timer)
  }, [
    state.level,
    state.history,
    state.mainView,
    state.selectedMain,
    state.selectedSub,
    state.cardStack,
    state.activeCardIndex,
    state.cardValues,
    state.view,
    state.isTransitioning, // Included to re-run when transition ends
  ])

  // Persist config to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify(config))
    } catch (e) {
      // Ignore storage errors
    }
  }, [config])

  // Persist card values to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(CARD_VALUES_KEY, JSON.stringify(state.cardValues))
    } catch (e) {
      // Ignore storage errors
    }
  }, [state.cardValues])

  const orbState = useMemo(() => getIrisOrbState(state, mainCategoryLabels, sectionLabels), [state, mainCategoryLabels, sectionLabels])

  // Wrapper functions that dispatch actions AND send WebSocket messages
  const handleExpandToMain = useCallback(() => {
    dispatch({ type: 'EXPAND_TO_MAIN' })
    sendMessage('expand_to_main')
  }, [sendMessage])

  const handleSelectMain = useCallback((categoryId: string) => {
    // Aggregate all cards from all sections under this main category
    const allCards: Card[] = []
    
    // First, try to get cards from WebSocket sections if they have the cards property
    const categorySections = sections[categoryId] || []
    
    if (categorySections.length > 0) {
      for (const section of categorySections) {
        // Check if section has cards property (from WebSocket)
        if (section.cards && Array.isArray(section.cards)) {
          allCards.push(...(section.cards as Card[]))
        }
      }
    }
    
    // If no cards found from WebSocket, use local data
    if (allCards.length === 0) {
      const sectionIds = CATEGORY_TO_SECTIONS[categoryId] || []
      console.log(`[NavigationContext] Loading cards for category: ${categoryId}, sections:`, sectionIds)
      for (const sectionId of sectionIds) {
        const cards = getCardsForSection(sectionId)
        console.log(`[NavigationContext] Section ${sectionId}: ${cards.length} cards`, cards.map(c => c.id))
        if (cards.length > 0) {
          allCards.push(...cards)
        }
      }
    }
    
    console.log(`[NavigationContext] Total cards for ${categoryId}:`, allCards.length, allCards.map(c => c.id))
    
    // Dispatch with aggregated cards
    dispatch({ 
      type: 'SELECT_MAIN', 
      payload: { categoryId, cards: allCards } 
    })
    sendMessage('select_category', { category: categoryId })
  }, [sections, sendMessage])

  const handleSelectSection = useCallback((sectionId: string, cards: Card[]) => {
    dispatch({ type: 'SELECT_SUB', payload: { sectionId, cards } })
    sendMessage('select_section', { section_id: sectionId })
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
  const selectMain = useCallback((categoryId: string) => dispatch({ type: 'SELECT_MAIN', payload: { categoryId } }), [])
  const selectSection = useCallback((sectionId: string, cards: Card[]) => dispatch({ type: 'SELECT_SUB', payload: { sectionId, cards } }), [])
  const collapseToIdle = useCallback(() => dispatch({ type: 'COLLAPSE_TO_IDLE' }), [])
  const setTransitioning = useCallback((value: boolean) => dispatch({ type: 'SET_TRANSITIONING', payload: value }), [])
  const updateConfig = useCallback((newConfig: Partial<NavigationConfig>) => setConfig(prev => ({ ...prev, ...newConfig })), [])
  const setCategoryLabels = useCallback((main: Record<string, string>, sub: Record<string, string>) => {
    setMainCategoryLabels(main)
    setSectionLabels(sub)
  }, [])

  // Card stack helpers
  const rotateStackForward = useCallback(() => dispatch({ type: 'ROTATE_STACK_FORWARD' }), [])
  const rotateStackBackward = useCallback(() => dispatch({ type: 'ROTATE_STACK_BACKWARD' }), [])
  const jumpToCard = useCallback((index: number) => dispatch({ type: 'JUMP_TO_CARD', payload: { index } }), [])
  const confirmCard = useCallback((id: string, values: Record<string, any>) => {
    if (state.isTransitioning) return
    dispatch({ type: 'CONFIRM_CARD', payload: { id, values } })
  }, [state.isTransitioning])
  const updateCardValue = useCallback((cardId: string, fieldId: string, value: any) => {
    dispatch({ type: 'UPDATE_CARD_VALUE', payload: { cardId, fieldId, value } })
  }, [])

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
    sections,

    // Functions that dispatch actions AND send WebSocket messages
    handleExpandToMain,
    handleSelectMain,
    handleSelectSection,
    handleGoBack,
    handleCollapseToIdle,
    handleIrisClick,

    // Original dispatching functions (for internal use if needed)
    goBack,
    expandToMain,
    selectMain,
    selectSection,
    collapseToIdle,
    setTransitioning,
    updateConfig,
    setCategoryLabels,

    // Card stack helpers
    rotateStackForward,
    rotateStackBackward,
    jumpToCard,
    confirmCard,
    updateCardValue,
    setMainView,
    setView,

    // WebSocket state and functions
    currentCategory,
    currentSection,
    voiceState,
    audioLevel,
    fieldValues,
    fieldErrors,
    lastTextResponse,
    activeTheme, // Add activeTheme from WebSocket
    selectCategory,
    selectSectionWs,
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
    getWakeWords,
    getAudioDevices,
  }), [
    state,
    config,
    orbState,
    dispatch,
    sections,

    // Functions that dispatch actions AND send WebSocket messages
    handleExpandToMain,
    handleSelectMain,
    handleSelectSection,
    handleGoBack,
    handleCollapseToIdle,

    // Original dispatching functions (for internal use if needed)
    goBack,
    expandToMain,
    selectMain,
    selectSection,
    collapseToIdle,
    setTransitioning,
    updateConfig,
    setCategoryLabels,

    // Card stack helpers
    rotateStackForward,
    rotateStackBackward,
    jumpToCard,
    confirmCard,
    updateCardValue,
    setMainView,
    setView,

    // WebSocket state and functions
    currentCategory,
    currentSection,
    voiceState,
    audioLevel,
    fieldValues,
    fieldErrors,
    lastTextResponse,
    activeTheme, // Add activeTheme to dependencies
    selectCategory,
    selectSectionWs,
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
    getWakeWords,
    getAudioDevices,
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
