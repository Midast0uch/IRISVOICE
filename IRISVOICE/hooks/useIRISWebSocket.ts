import { useState, useEffect, useRef, useCallback } from "react"

// WebSocket connection states
type ConnectionState = "connecting" | "connected" | "disconnected" | "error"

// Theme type matching backend
interface ColorTheme {
  primary: string
  glow: string
  font: string
  state_colors_enabled?: boolean
  idle_color?: string
  listening_color?: string
  processing_color?: string
  error_color?: string
}

// Field values by section ID (flat structure)
interface FieldValues {
  [sectionId: string]: {
    [fieldId: string]: string | number | boolean
  }
}

// Full IRIS state from backend
interface IRISState {
  current_category: string | null
  current_section: string | null
  field_values: FieldValues
  active_theme: ColorTheme
  sections: Record<string, Record<string, unknown>[]>
}

// Hook return type
type VoiceState = "idle" | "listening" | "processing_conversation" | "processing_tool" | "speaking" | "error"

// Text response message type
interface TextResponseMessage {
  text: string
  sender: "user" | "assistant"
}

interface VisionStatus {
  status: "disabled" | "loading" | "enabled" | "error"
  vram_usage_mb: number | null
  load_progress_percent: number | null
  error_message: string | null
  last_used: string | null
  model_name: string
  quantization_enabled: boolean
  is_available: boolean
}

interface UseIRISWebSocketReturn {
  isConnected: boolean
  connectionState: ConnectionState
  theme: ColorTheme
  fieldValues: FieldValues
  sections: Record<string, Record<string, unknown>[]>
  currentCategory: string | null
  currentSection: string | null
  voiceState: VoiceState
  audioLevel: number
  lastTextResponse: TextResponseMessage | null
  // Agent state
  agentStatus: Record<string, unknown> | null
  agentTools: Record<string, unknown> []
  agentSkills: Record<string, unknown> []
  selectCategory: (category: string) => void
  selectSection: (sectionId: string | null) => void
  updateField: (sectionId: string, fieldId: string, value: string | number | boolean) => void
  confirmCard: (sectionId: string, values: Record<string, string | number | boolean>) => void
  updateTheme: (glowColor?: string, fontColor?: string, stateColors?: { enabled?: boolean; idle?: string; listening?: string; processing?: string; error?: string }) => void
  requestState: () => void
  // Agent actions
  getAgentStatus: () => void
  getAgentTools: () => void
  executeTool: (toolName: string, params?: Record<string, unknown>) => void
  clearChat: () => void
  reloadSkills: () => void
  // Voice actions
  startVoiceCommand: () => void
  endVoiceCommand: () => void
  sendMessage: (type: string, payload?: Record<string, unknown>) => boolean
  // Device actions
  getWakeWords: () => void
  getAudioDevices: () => void
  lastError: string | null
  fieldErrors: Record<string, string> // Map of "sectionId:fieldId" to error message
  clearFieldError: (sectionId: string, fieldId: string) => void
  onWakeDetected?: () => void
  // Vision state and actions
  visionStatus: VisionStatus
  enableVision: () => void
  disableVision: () => void
}

// Default theme matching backend defaults
const DEFAULT_THEME: ColorTheme = {
  primary: "#00ff88",
  glow: "#00ff88",
  font: "#ffffff",
}

export function useIRISWebSocket(
  url: string = "ws://127.0.0.1:8000/ws/iris",
  autoConnect: boolean = true,
  onWakeDetected?: () => void,
  onNativeAudioResponse?: (payload: Record<string, unknown>) => void
): UseIRISWebSocketReturn {
  // Connection state
  const [connectionState, setConnectionState] = useState<ConnectionState>("disconnected")
  const [lastError, setLastError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({}) // Map of "sectionId:fieldId" to error message

  // IRIS state from backend
  const [theme, setTheme] = useState<ColorTheme>(DEFAULT_THEME)
  const [fieldValues, setFieldValues] = useState<FieldValues>({})
  const [sections, setSections] = useState<Record<string, Record<string, unknown>[]>>({})
  const [currentCategory, setCurrentCategory] = useState<string | null>(null)
  const [currentSection, setCurrentSection] = useState<string | null>(null)
  const [voiceState, setVoiceState] = useState<VoiceState>("idle")
  const [audioLevel, setAudioLevel] = useState<number>(0)
  const [lastTextResponse, setLastTextResponse] = useState<TextResponseMessage | null>(null)
  
  // Agent state
  const [agentStatus, setAgentStatus] = useState<Record<string, unknown> | null>(null)
  const [agentTools, setAgentTools] = useState<Record<string, unknown>[]>([])
  const [agentSkills, setAgentSkills] = useState<Record<string, unknown>[]>([])

  // Device state
  const [wakeWords, setWakeWords] = useState<{filename: string; display_name: string; platform: string; version: string}[]>([])
  const [audioInputDevices, setAudioInputDevices] = useState<{name: string; index: number; sample_rate: number}[]>([])
  const [audioOutputDevices, setAudioOutputDevices] = useState<{name: string; index: number; sample_rate: number}[]>([])

  // Vision service state
  const [visionStatus, setVisionStatus] = useState<{
    status: "disabled" | "loading" | "enabled" | "error"
    vram_usage_mb: number | null
    load_progress_percent: number | null
    error_message: string | null
    last_used: string | null
    model_name: string
    quantization_enabled: boolean
    is_available: boolean
  }>({
    status: "disabled",
    vram_usage_mb: null,
    load_progress_percent: null,
    error_message: null,
    last_used: null,
    model_name: "minicpm-o4.5",
    quantization_enabled: true,
    is_available: false
  })

  // WebSocket ref
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const pingTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const pongTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const onWakeDetectedRef = useRef(onWakeDetected)
  const onNativeAudioResponseRef = useRef(onNativeAudioResponse)
  
  // Optimistic update tracking: store previous values for revert on validation error
  const pendingUpdatesRef = useRef<Map<string, { sectionId: string; fieldId: string; previousValue: string | number | boolean }>>(new Map())
  
  // Timestamp tracking for out-of-order update handling
  const fieldTimestampsRef = useRef<Map<string, number>>(new Map())

  // Update ref when callback changes
  useEffect(() => {
    onWakeDetectedRef.current = onWakeDetected
    onNativeAudioResponseRef.current = onNativeAudioResponse
  }, [onWakeDetected, onNativeAudioResponse])

  const isConnected = connectionState === "connected"

  // Cleanup function
  const cleanup = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    if (pingTimeoutRef.current) {
      clearTimeout(pingTimeoutRef.current)
      pingTimeoutRef.current = null
    }
    if (pongTimeoutRef.current) {
      clearTimeout(pongTimeoutRef.current)
      pongTimeoutRef.current = null
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  // Connect to WebSocket
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return // Already connected
    }

    setConnectionState("connecting")
    setLastError(null)

    try {
      const ws = new WebSocket(url)

      ws.onopen = () => {
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Connected")
        }
        setConnectionState("connected")
        reconnectAttemptsRef.current = 0

        // Request initial state, audio devices, and wake words immediately on open.
        // These must be sent here (not in useEffect) because sendMessage() drops messages
        // silently if the socket is not yet OPEN — onopen guarantees it is.
        ws.send(JSON.stringify({ type: "request_state", payload: {} }))
        ws.send(JSON.stringify({ type: "get_audio_devices", payload: {} }))
        ws.send(JSON.stringify({ type: "get_wake_words", payload: {} }))
        ws.send(JSON.stringify({ type: "get_available_models", payload: {} }))
      }

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data)
          handleMessage(message)
        } catch (err) {
          console.error("[IRIS WebSocket] Failed to parse message:", err)
        }
      }

      ws.onerror = (error) => {
        // WebSocket errors don't contain detailed info - just log connection failed
        console.warn("[IRIS WebSocket] Connection failed - backend may be offline")
        setConnectionState("error")
        setLastError("Backend offline - running in standalone mode")
      }

      ws.onclose = (event) => {
        if (process.env.NODE_ENV !== 'production') {
          console.log(`[IRIS WebSocket] Closed (code: ${event.code})`)
        }
        setConnectionState("disconnected")
        wsRef.current = null

        // Clear ping/pong timers
        if (pingTimeoutRef.current) {
          clearTimeout(pingTimeoutRef.current)
          pingTimeoutRef.current = null
        }
        if (pongTimeoutRef.current) {
          clearTimeout(pongTimeoutRef.current)
          pongTimeoutRef.current = null
        }

        // Auto-reconnect with exponential backoff (1s, 2s, 4s) up to 3 attempts
        if (autoConnect && reconnectAttemptsRef.current < 3) {
          const delay = 1000 * Math.pow(2, reconnectAttemptsRef.current) // 1s, 2s, 4s
          reconnectAttemptsRef.current++

          if (process.env.NODE_ENV !== 'production') {
            console.log(`[IRIS WebSocket] Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current}/3)`)
          }

          reconnectTimeoutRef.current = setTimeout(() => {
            connect()
          }, delay)
        } else if (reconnectAttemptsRef.current >= 3) {
          setLastError("Backend offline - running in standalone mode")
        }
      }

      wsRef.current = ws
    } catch (err) {
      console.error("[IRIS WebSocket] Failed to create connection:", err)
      setConnectionState("error")
      setLastError("Failed to create connection")
    }
  }, [url, autoConnect])

  // Handle incoming messages
  const handleMessage = useCallback((message: Record<string, unknown>) => {
    const type = message.type
    // BUG-01 FIX: Extract payload correctly.
    // Backend sends EITHER { type, payload: {...} } (nested) OR { type, key1, key2 } (flat).
    // Old code `const { type, ...payload } = message` double-nested when backend used "payload" key,
    // producing { payload: { actual_data } } instead of { actual_data }.
    const payload: Record<string, unknown> = (message.payload && typeof message.payload === 'object')
      ? (message.payload as Record<string, unknown>)
      : (() => { const { type: _t, payload: _p, ...rest } = message; return rest; })()

    switch (type) {
      case "full_state": {
        // Legacy message type from old main.py - redirect to initial_state handler
        if (process.env.NODE_ENV !== 'production') {
          console.warn("[IRIS WebSocket] Received legacy 'full_state' message, treating as 'initial_state'")
        }
        // Fall through to initial_state handler
      }
      case "initial_state":
      case "state_sync": {
        const state: IRISState = payload.state as IRISState
        if (state && state.active_theme) setTheme(state.active_theme)
        if (state && state.field_values) setFieldValues(state.field_values)
        if (state && state.sections) setSections(state.sections)
        if (state && state.current_category !== undefined) setCurrentCategory(state.current_category)
        if (state && state.current_section !== undefined) setCurrentSection(state.current_section)
        
        // Dispatch CustomEvent for SidePanel listeners
        if (typeof window !== 'undefined' && state) {
          window.dispatchEvent(new CustomEvent('iris:initial_state', {
            detail: { state }
          }))
        }
        break
      }

      case "category_changed": {
        if (payload.category && typeof payload.category === 'string') setCurrentCategory(payload.category)
        setCurrentSection(null)
        break
      }

      case "section_changed": {
        if (payload.section_id !== undefined) setCurrentSection(typeof payload.section_id === 'string' ? payload.section_id : null)
        break
      }

      case "field_updated": {
        // Optimistic update confirmed by server - remove from pending updates
        const { section_id, field_id, value, timestamp } = payload as {
          section_id: string;
          field_id: string;
          value: string | number | boolean;
          timestamp?: number;
        }
        const sectionId = section_id
        
        if (sectionId && field_id !== undefined) {
          const updateKey = `${sectionId}:${field_id}`
          
          // Handle out-of-order updates using timestamps
          if (timestamp !== undefined) {
            // Initialize timestamp tracker if needed
            if (!fieldTimestampsRef.current) {
              fieldTimestampsRef.current = new Map<string, number>()
            }
            
            const existingTimestamp = fieldTimestampsRef.current.get(updateKey) || 0
            
            // Only apply update if timestamp is newer
            if (timestamp < existingTimestamp) {
              // This is an out-of-order update, ignore it
              if (process.env.NODE_ENV !== 'production') {
                console.log(`[IRIS WebSocket] Ignoring out-of-order update for ${updateKey}: ${timestamp} < ${existingTimestamp}`)
              }
              return
            }
            
            // Update timestamp tracker
            fieldTimestampsRef.current.set(updateKey, timestamp)
          }
          
          // Remove from pending updates (update confirmed)
          pendingUpdatesRef.current.delete(updateKey)
          
          // Clear any validation error for this field
          setFieldErrors((prev) => {
            const newErrors = { ...prev }
            delete newErrors[updateKey]
            return newErrors
          })
          
          // Apply the update to state
          setFieldValues((prev) => ({
            ...prev,
            [sectionId]: {
              ...prev[sectionId] || {},
              [field_id]: value,
            },
          }))
          
          // Dispatch CustomEvent for SidePanel and other listeners
          if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('iris:field_updated', {
              detail: { section_id: sectionId, field_id, value, timestamp }
            }))
          }
        }
        break
      }

      case "validation_error": {
        // Handle flat payload structure from backend
        // Revert optimistic update on validation error
        const { field_id, section_id, error } = payload as {
          field_id?: string;
          section_id?: string;
          error: string
        }
        const sectionId = section_id
        
        console.error("[IRIS WebSocket] Validation error:", error, field_id)
        setLastError(typeof error === 'string' ? error : null)
        
        // Store field-specific error message
        if (sectionId && field_id) {
          const updateKey = `${sectionId}:${field_id}`
          setFieldErrors((prev) => ({
            ...prev,
            [updateKey]: typeof error === 'string' ? error : 'Validation failed',
          }))
          
          const pendingUpdate = pendingUpdatesRef.current.get(updateKey)
          
          if (pendingUpdate) {
            // Revert to previous value
            setFieldValues((prev) => ({
              ...prev,
              [sectionId]: {
                ...prev[sectionId] || {},
                [field_id]: pendingUpdate.previousValue,
              },
            }))
            
            // Remove from pending updates
            pendingUpdatesRef.current.delete(updateKey)
            
            if (process.env.NODE_ENV !== 'production') {
              console.log(`[IRIS WebSocket] Reverted field ${sectionId}.${field_id} to previous value:`, pendingUpdate.previousValue)
            }
          }
        }
        break
      }

      case "card_confirmed": {
        // Server confirmed the section — dispatch event so UI can show feedback
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:card_confirmed', {
            detail: {
              section_id: payload.section_id,
              applied: payload.applied ?? true,
              error: payload.error ?? null
            }
          }))
        }
        break
      }

      case "theme_updated": {
        if (payload.glow || payload.font || payload.state_colors_enabled !== undefined) {
          setTheme((prev) => ({
            ...prev,
            ...(typeof payload.glow === 'string' && { glow: payload.glow, primary: payload.glow }),
            ...(typeof payload.font === 'string' && { font: payload.font }),
            ...(typeof payload.state_colors_enabled === 'boolean' && { state_colors_enabled: payload.state_colors_enabled }),
            ...(typeof payload.idle_color === 'string' && { idle_color: payload.idle_color }),
            ...(typeof payload.listening_color === 'string' && { listening_color: payload.listening_color }),
            ...(typeof payload.processing_color === 'string' && { processing_color: payload.processing_color }),
            ...(typeof payload.error_color === 'string' && { error_color: payload.error_color }),
          }))
        }
        break
      }

      case "wake_detected": {
        // Trigger wake word callback if provided
        if (onWakeDetectedRef.current) {
          onWakeDetectedRef.current()
        }
        break
      }

      case "listening_state": {
        if (payload.state) {
          const newState = payload.state as VoiceState
          setVoiceState(newState)
          
          // Dispatch CustomEvent for SidePanel and other listeners
          if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('iris:voice_state_change', {
              detail: { state: newState }
            }))
          }
          
          // Reset audio level when leaving listening state
          if (newState !== "listening") {
            setAudioLevel(0)
          }
        }
        break
      }

      case "audio_level": {
        // Audio level update during listening
        if (typeof payload.level === 'number') {
          setAudioLevel(payload.level)
        }
        break
      }

      case "text_response": {
        // Text response from LFM2-8B-A1B model
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Text response:", payload)
        }
        if (payload.text && typeof payload.text === 'string') {
          const sender = (payload.sender === "user" || payload.sender === "assistant")
            ? payload.sender
            : "assistant"
          setLastTextResponse({
            text: payload.text,
            sender
          })
          
          // Dispatch CustomEvent for SidePanel and other listeners
          if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('iris:text_response', {
              detail: { text: payload.text }
            }))
          }
        }
        break
      }

      case "agent_status": {
        // Agent kernel status response
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Agent status:", payload)
        }
        if (payload.status) {
          setAgentStatus(payload.status as Record<string, unknown>)
        }
        break
      }

      case "agent_tools": {
        // Available tools list response
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Agent tools:", payload)
        }
        if (payload.tools && Array.isArray(payload.tools)) {
          setAgentTools(payload.tools as Record<string, unknown>[])
        }
        break
      }

      case "tool_result": {
        // Tool execution result
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Tool result:", payload)
        }
        // Tool results are handled by the agent kernel
        break
      }

      case "wake_words": {
        // Wake words list response
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Wake words:", payload)
        }
        if (payload.wake_words && Array.isArray(payload.wake_words)) {
          setWakeWords(payload.wake_words as {filename: string; display_name: string; platform: string; version: string}[])
        }
        // Dispatch CustomEvent for SidePanel and other listeners
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:wake_words_list', {
            detail: {
              wake_words: payload.wake_words || [],
              count: payload.count || 0
            }
          }))
        }
        break
      }

      case "audio_devices": {
        // Audio devices response
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Audio devices:", payload)
        }
        if (payload.input_devices && Array.isArray(payload.input_devices)) {
          setAudioInputDevices(payload.input_devices as {name: string; index: number; sample_rate: number}[])
        }
        if (payload.output_devices && Array.isArray(payload.output_devices)) {
          setAudioOutputDevices(payload.output_devices as {name: string; index: number; sample_rate: number}[])
        }
        // Dispatch CustomEvent for SidePanel and other listeners
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:audio_devices', {
            detail: {
              input_devices: payload.input_devices || [],
              output_devices: payload.output_devices || []
            }
          }))
        }
        break
      }

      case "pong": {
        // Clear pong timeout on successful pong response
        if (pongTimeoutRef.current) {
          clearTimeout(pongTimeoutRef.current)
          pongTimeoutRef.current = null
        }
        break
      }

      case "vision_status": {
        // Vision service status update
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Vision status:", payload)
        }
        if (payload.status) {
          setVisionStatus((prev) => ({
            ...prev,
            status: payload.status as VisionStatus['status'],
            vram_usage_mb: typeof payload.vram_usage_mb === 'number' ? payload.vram_usage_mb : null,
            load_progress_percent: typeof payload.load_progress_percent === 'number' ? payload.load_progress_percent : null,
            error_message: typeof payload.error_message === 'string' ? payload.error_message : null,
            last_used: typeof payload.last_used === 'string' ? payload.last_used : null,
            is_available: payload.status === 'enabled'
          }))
        }
        break
      }

      case "vision_enabled": {
        // Vision enabled confirmation
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Vision enabled:", payload)
        }
        setVisionStatus((prev) => ({
          ...prev,
          status: 'enabled',
          is_available: true,
          load_progress_percent: 100,
          vram_usage_mb: typeof payload.vram_usage_mb === 'number' ? payload.vram_usage_mb : null,
        }))
        break
      }

      case "vision_disabled": {
        // Vision disabled confirmation
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Vision disabled:", payload)
        }
        setVisionStatus((prev) => ({
          ...prev,
          status: 'disabled',
          is_available: false,
          load_progress_percent: null,
          vram_usage_mb: null,
        }))
        break
      }

      case "chat_cleared": {
        // Chat history cleared
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Chat cleared")
        }
        setLastTextResponse(null)
        break
      }

      case "skills_reloaded": {
        // Skills reloaded successfully
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Skills reloaded:", payload)
        }
        // Skills are reloaded by the agent kernel
        break
      }

      case "available_models": {
        // Available models list response
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Available models:", payload)
        }
        // Dispatch CustomEvent for SidePanel and other listeners
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:available_models', {
            detail: { models: payload.models || [] }
          }))
        }
        break
      }

      case "wake_word_selected": {
        // Backend confirms a wake word was selected (e.g., from another client)
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:wake_word_selected', { detail: payload }))
        }
        break
      }

      case "model_selection_updated": {
        // Backend confirms model selection was applied
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:model_selection_updated', { detail: payload }))
        }
        break
      }

      case "skills_error": {
        // Backend reports a skill execution error
        if (process.env.NODE_ENV !== 'production') {
          console.warn("[IRIS WebSocket] Skills error:", payload)
        }
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:skills_error', { detail: payload }))
        }
        break
      }

      case "connection_test_result": {
        // VPS connection test result
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Connection test result:", payload)
        }
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:connection_test_result', { detail: payload }))
        }
        break
      }

      case "cleanup_report":
      case "cleanup_result": {
        // Session cleanup reports — no UI action needed
        break
      }

      default: {
        // Only log unknown message types in development mode
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Unknown message type:", type, payload)
        }
      }
    }
  }, [])

  // Send message helper
  const sendMessage = useCallback((type: string, payload: Record<string, unknown> = {}) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type, payload }))
      return true
    }
    console.warn("[IRIS WebSocket] Not connected, message dropped:", type)
    return false
  }, [])

  // Action methods
  const selectCategory = useCallback((category: string) => {
    sendMessage("select_category", { category })
  }, [sendMessage])

  const selectSection = useCallback((sectionId: string | null) => {
    if (sectionId) {
      sendMessage("select_section", { section_id: sectionId })
    } else {
      // Deselect - just update local state for now
      setCurrentSection(null)
    }
  }, [sendMessage])

  const updateField = useCallback((sectionId: string, fieldId: string, value: string | number | boolean) => {
    // Store previous value for potential revert on validation error
    const updateKey = `${sectionId}:${fieldId}`
    const previousValue = fieldValues[sectionId]?.[fieldId]
    
    // Only track if we have a previous value (not first time setting)
    if (previousValue !== undefined) {
      pendingUpdatesRef.current.set(updateKey, {
        sectionId,
        fieldId,
        previousValue,
      })
    }
    
    // Optimistic local update - update UI immediately
    setFieldValues((prev) => ({
      ...prev,
      [sectionId]: {
        ...prev[sectionId],
        [fieldId]: value,
      },
    }))

    // Send to server for validation and persistence
    sendMessage("field_update", { section_id: sectionId, field_id: fieldId, value })
  }, [sendMessage, fieldValues])

  const confirmCard = useCallback((sectionId: string, values: Record<string, string | number | boolean>) => {
    sendMessage("confirm_card", { section_id: sectionId, values })
  }, [sendMessage])

  const updateTheme = useCallback((glowColor?: string, fontColor?: string, stateColors?: { enabled?: boolean; idle?: string; listening?: string; processing?: string; error?: string }) => {
    // Optimistic local update
    setTheme((prev) => ({
      ...prev,
      ...(glowColor && { glow: glowColor, primary: glowColor }),
      ...(fontColor && { font: fontColor }),
      ...(stateColors?.enabled !== undefined && { state_colors_enabled: stateColors.enabled }),
      ...(stateColors?.idle && { idle_color: stateColors.idle }),
      ...(stateColors?.listening && { listening_color: stateColors.listening }),
      ...(stateColors?.processing && { processing_color: stateColors.processing }),
      ...(stateColors?.error && { error_color: stateColors.error }),
    }))

    // Send to server
    sendMessage("update_theme", { glow_color: glowColor, font_color: fontColor, state_colors: stateColors })
  }, [sendMessage])

  const requestState = useCallback(() => {
    sendMessage("request_state", {})
  }, [sendMessage])

  // Agent action methods
  const getAgentStatus = useCallback(() => {
    sendMessage("agent_status", {})
  }, [sendMessage])

  const getAgentTools = useCallback(() => {
    sendMessage("agent_tools", {})
  }, [sendMessage])

  const executeTool = useCallback((toolName: string, params: Record<string, unknown> = {}) => {
    sendMessage("execute_tool", { tool_name: toolName, parameters: params })
  }, [sendMessage])

  const clearChat = useCallback(() => {
    sendMessage("clear_chat", {})
  }, [sendMessage])

  const reloadSkills = useCallback(() => {
    sendMessage("reload_skills", {})
  }, [sendMessage])

  // Voice command methods
  const startVoiceCommand = useCallback(() => {
    // Optimistic update: show listening animation immediately without waiting for backend
    setVoiceState("listening")
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('iris:voice_state_change', {
        detail: { state: "listening" }
      }))
    }
    sendMessage("voice_command_start", {})
  }, [sendMessage])

  const endVoiceCommand = useCallback(() => {
    // Optimistic update: reset to idle immediately
    setVoiceState("idle")
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('iris:voice_state_change', {
        detail: { state: "idle" }
      }))
    }
    sendMessage("voice_command_end", {})
  }, [sendMessage])

  // Clear field error
  const clearFieldError = useCallback((sectionId: string, fieldId: string) => {
    const updateKey = `${sectionId}:${fieldId}`
    setFieldErrors((prev) => {
      const newErrors = { ...prev }
      delete newErrors[updateKey]
      return newErrors
    })
  }, [])

  // Device methods
  const getWakeWords = useCallback(() => {
    sendMessage("get_wake_words", {})
  }, [sendMessage])

  const getAudioDevices = useCallback(() => {
    sendMessage("get_audio_devices", {})
  }, [sendMessage])

  // Vision service methods
  const enableVision = useCallback(() => {
    sendMessage("enable_vision", {})
  }, [sendMessage])

  const disableVision = useCallback(() => {
    sendMessage("disable_vision", {})
  }, [sendMessage])

  // Initialize connection
  useEffect(() => {
    if (autoConnect) {
      connect()
    }

    return cleanup
  }, [autoConnect, connect, cleanup])

  // Keep-alive ping with pong timeout
  useEffect(() => {
    if (!isConnected) return

    const sendPing = () => {
      sendMessage("ping", {})
      
      // Set pong timeout (5 seconds)
      pongTimeoutRef.current = setTimeout(() => {
        if (process.env.NODE_ENV !== 'production') {
          console.warn("[IRIS WebSocket] Pong timeout - connection may be lost")
        }
        // Close connection to trigger reconnect
        if (wsRef.current) {
          wsRef.current.close()
        }
      }, 5000)
    }

    // Send initial ping
    sendPing()

    // Ping every 30 seconds
    const interval = setInterval(sendPing, 30000)

    return () => {
      clearInterval(interval)
      if (pongTimeoutRef.current) {
        clearTimeout(pongTimeoutRef.current)
        pongTimeoutRef.current = null
      }
    }
  }, [isConnected, sendMessage])

  return {
    isConnected,
    connectionState,
    theme,
    fieldValues,
    sections,
    currentCategory,
    currentSection,
    voiceState,
    audioLevel,
    lastTextResponse,
    // Agent state
    agentStatus,
    agentTools,
    agentSkills,
    selectCategory,
    selectSection,
    updateField,
    confirmCard,
    updateTheme,
    requestState,
    // Agent actions
    getAgentStatus,
    getAgentTools,
    executeTool,
    clearChat,
    reloadSkills,
    // Voice actions
    startVoiceCommand,
    endVoiceCommand,
    sendMessage,
    // Device actions
    getWakeWords,
    getAudioDevices,
    lastError,
    fieldErrors,
    clearFieldError,
    // Vision state and actions
    visionStatus,
    enableVision,
    disableVision,
  }
}

// Export type for components that receive sendMessage as prop
export type SendMessageFunction = (
  type: string,
  payload?: Record<string, unknown>
) => boolean;

// Export VisionStatus for components that need to display vision state
export type { VisionStatus };
