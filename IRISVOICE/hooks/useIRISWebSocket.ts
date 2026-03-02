
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

// Field values by subnode ID (flat structure)
interface FieldValues {
  [subnodeId: string]: {
    [fieldId: string]: string | number | boolean
  }
}

// Confirmed node in orbit
interface ConfirmedNode {
  id: string
  label: string
  icon: string
  orbit_angle: number
  values: Record<string, string | number | boolean>
  category: string
}

// Full IRIS state from backend
interface IRISState {
  current_category: string | null
  current_subnode: string | null
  field_values: FieldValues
  active_theme: ColorTheme
  confirmed_nodes: ConfirmedNode[]
  subnodes: Record<string, Record<string, unknown>[]>
}

// Hook return type
type VoiceState = "idle" | "listening" | "processing_conversation" | "processing_tool" | "speaking" | "error"

// Text response message type
interface TextResponseMessage {
  text: string
  sender: "assistant"
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
  subnodes: Record<string, Record<string, unknown>[]>
  confirmedNodes: ConfirmedNode[]
  currentCategory: string | null
  currentSubnode: string | null
  voiceState: VoiceState
  audioLevel: number
  lastTextResponse: TextResponseMessage | null
  // Agent state
  agentStatus: Record<string, unknown> | null
  agentTools: Record<string, unknown> []
  agentSkills: Record<string, unknown> []
  selectCategory: (category: string) => void
  selectSubnode: (subnodeId: string | null) => void
  updateField: (subnodeId: string, fieldId: string, value: string | number | boolean) => void
  confirmMiniNode: (subnodeId: string, values: Record<string, string | number | boolean>) => void
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
  fieldErrors: Record<string, string> // Map of "subnodeId:fieldId" to error message
  clearFieldError: (subnodeId: string, fieldId: string) => void
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
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({}) // Map of "subnodeId:fieldId" to error message

  // IRIS state from backend
  const [theme, setTheme] = useState<ColorTheme>(DEFAULT_THEME)
  const [fieldValues, setFieldValues] = useState<FieldValues>({})
  const [subnodes, setSubnodes] = useState<Record<string, Record<string, unknown>[]>>({})
  const [confirmedNodes, setConfirmedNodes] = useState<ConfirmedNode[]>([])
  const [currentCategory, setCurrentCategory] = useState<string | null>(null)
  const [currentSubnode, setCurrentSubnode] = useState<string | null>(null)
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
  const pendingUpdatesRef = useRef<Map<string, { subnodeId: string; fieldId: string; previousValue: string | number | boolean }>>(new Map())
  
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

        // Request initial state
        ws.send(JSON.stringify({ type: "request_state", payload: {} }))
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
    const { type, ...payload } = message

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
        if (state && state.subnodes) setSubnodes(state.subnodes)
        if (state && state.confirmed_nodes) setConfirmedNodes(state.confirmed_nodes)
        if (state && state.current_category !== undefined) setCurrentCategory(state.current_category)
        if (state && state.current_subnode !== undefined) setCurrentSubnode(state.current_subnode)
        
        // BUG-02 FIX: Dispatch CustomEvent for SidePanel listeners
        if (typeof window !== 'undefined' && state) {
          window.dispatchEvent(new CustomEvent('iris:initial_state', {
            detail: { state }
          }))
        }
        break
      }

      case "category_changed": {
        if (payload.category && typeof payload.category === 'string') setCurrentCategory(payload.category)
        setCurrentSubnode(null)
        break
      }

      case "subnode_changed": {
        if (payload.subnode_id !== undefined) setCurrentSubnode(typeof payload.subnode_id === 'string' ? payload.subnode_id : null)
        break
      }

      case "field_updated": {
        // Optimistic update confirmed by server - remove from pending updates
        const { subnode_id, field_id, value, timestamp } = payload as { 
          subnode_id: string; 
          field_id: string; 
          value: string | number | boolean;
          timestamp?: number;
        }
        
        if (subnode_id && field_id !== undefined) {
          const updateKey = `${subnode_id}:${field_id}`
          
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
            [subnode_id]: {
              ...prev[subnode_id] || {},
              [field_id]: value,
            },
          }))
          
          // GAP-03 FIX: Dispatch CustomEvent for SidePanel and other listeners
          if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('iris:field_updated', {
              detail: { subnode_id, field_id, value, timestamp }
            }))
          }
        }
        break
      }

      case "validation_error": {
        // GAP-09 FIX: Handle flat payload structure from backend
        // Revert optimistic update on validation error
        const { field_id, subnode_id, error } = payload as { field_id?: string; subnode_id?: string; error: string }
        
        console.error("[IRIS WebSocket] Validation error:", error, field_id)
        setLastError(typeof error === 'string' ? error : null)
        
        // Store field-specific error message
        if (subnode_id && field_id) {
          const updateKey = `${subnode_id}:${field_id}`
          setFieldErrors((prev) => ({
            ...prev,
            [updateKey]: typeof error === 'string' ? error : 'Validation failed',
          }))
          
          const pendingUpdate = pendingUpdatesRef.current.get(updateKey)
          
          if (pendingUpdate) {
            // Revert to previous value
            setFieldValues((prev) => ({
              ...prev,
              [subnode_id]: {
                ...prev[subnode_id] || {},
                [field_id]: pendingUpdate.previousValue,
              },
            }))
            
            // Remove from pending updates
            pendingUpdatesRef.current.delete(updateKey)
            
            if (process.env.NODE_ENV !== 'production') {
              console.log(`[IRIS WebSocket] Reverted field ${subnode_id}.${field_id} to previous value:`, pendingUpdate.previousValue)
            }
          }
        }
        break
      }

      case "mini_node_confirmed": {
        // Server confirmed, state will be synced via state_sync
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
          
          // GAP-03 FIX: Dispatch CustomEvent for SidePanel and other listeners
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

      case "pong": {
        // Keep-alive response received, clear pong timeout
        if (pongTimeoutRef.current) {
          clearTimeout(pongTimeoutRef.current)
          pongTimeoutRef.current = null
        }
        break
      }

      case "voice_command_started": {
        // Voice command recording started
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Voice command started:", payload.message)
        }
        break
      }

      case "voice_command_ended": {
        // Voice command recording ended
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Voice command ended:", payload.message)
        }
        break
      }

      case "voice_command_result": {
        // Voice command processing result
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Voice command result:", payload)
        }
        break
      }

      case "native_audio_response": {
        // Native audio response from LFM2-Audio model
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Native audio response:", payload)
        }
        // Call the callback if provided
        if (onNativeAudioResponseRef.current) {
          onNativeAudioResponseRef.current(payload)
        }
        break
      }

      case "text_response": {
        // Text response from LFM2-8B-A1B model
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Text response:", payload)
        }
        if (payload.text && typeof payload.text === 'string' && payload.sender === "assistant") {
          setLastTextResponse({
            text: typeof payload.text === 'string' ? payload.text : '',
            sender: payload.sender
          })
        }
        break
      }

      case "agent_status": {
        // Agent kernel status response
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Agent status:", payload)
        }
        setAgentStatus(payload)
        break
      }

      case "agent_tools": {
        // Available tools list response
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Agent tools:", payload)
        }
        setAgentTools(Array.isArray(payload.tools) ? payload.tools as Record<string, unknown>[] : [])
        break
      }

      case "tool_result": {
        // Tool execution result
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Tool result:", payload)
        }
        if (payload.error) {
          setLastError(typeof payload.error === 'string' ? payload.error : null)
        }
        break
      }

      case "wake_words_list": {
        // Wake words list response
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Wake words:", payload)
        }
        const wakeWordsList = payload.wake_words as {filename: string; display_name: string; platform: string; version: string}[] || []
        setWakeWords(wakeWordsList)
        // Dispatch custom event for SidePanel listeners
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:wake_words_list', {
            detail: { wake_words: wakeWordsList }
          }))
        }
        break
      }

      case "audio_devices": {
        // Audio devices response
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Audio devices:", payload)
        }
        const inputDevices = payload.input_devices as {name: string; index: number; sample_rate: number}[] || []
        const outputDevices = payload.output_devices as {name: string; index: number; sample_rate: number}[] || []
        setAudioInputDevices(inputDevices)
        setAudioOutputDevices(outputDevices)
        // Dispatch custom event for SidePanel listeners
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:audio_devices', {
            detail: { input_devices: inputDevices, output_devices: outputDevices }
          }))
        }
        break
      }

      case "vision_status": {
        // Vision service status update
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Vision status:", payload)
        }
        setVisionStatus({
          status: (payload.status as "disabled" | "loading" | "enabled" | "error") || "disabled",
          vram_usage_mb: payload.vram_usage_mb as number | null,
          load_progress_percent: payload.load_progress_percent as number | null,
          error_message: payload.error_message as string | null,
          last_used: payload.last_used as string | null,
          model_name: (payload.model_name as string) || "minicpm-o4.5",
          quantization_enabled: (payload.quantization_enabled as boolean) ?? true,
          is_available: (payload.is_available as boolean) || false
        })
        // Dispatch custom event for UI listeners
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:vision_status', {
            detail: payload
          }))
        }
        break
      }

      case "enable_vision": {
        // Vision enabled confirmation
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Vision enabled:", payload)
        }
        if (payload.success) {
          setVisionStatus(prev => ({
            ...prev,
            status: "enabled",
            vram_usage_mb: payload.vram_usage_mb as number | null,
            quantization_enabled: (payload.quantization_enabled as boolean) ?? true
          }))
        } else {
          setVisionStatus(prev => ({
            ...prev,
            status: "error",
            error_message: (payload.error as string) || "Failed to enable vision"
          }))
          setLastError((payload.error as string) || "Failed to enable vision")
        }
        break
      }

      case "disable_vision": {
        // Vision disabled confirmation
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Vision disabled:", payload)
        }
        if (payload.success) {
          setVisionStatus(prev => ({
            ...prev,
            status: "disabled",
            vram_usage_mb: null,
            load_progress_percent: null,
            error_message: null
          }))
        } else {
          setVisionStatus(prev => ({
            ...prev,
            status: "error",
            error_message: (payload.error as string) || "Failed to disable vision"
          }))
          setLastError((payload.error as string) || "Failed to disable vision")
        }
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
        setAgentSkills(Array.isArray(payload.skills) ? payload.skills as Record<string, unknown>[] : [])
        break
      }

      case "skills_error": {
        // Skills reload error
        console.error("[IRIS WebSocket] Skills error:", payload)
        setLastError(typeof payload.error === 'string' ? payload.error : null)
        break
      }

      case "available_models": {
        // Available models list response
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Available models:", payload)
        }
        // Store available models in a way that can be accessed by components
        // We'll dispatch a custom event that WheelView can listen to
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:available_models', { 
            detail: { models: payload.models || [] }
          }))
        }
        break
      }

      case "voice_command_error": {
        // Voice command error
        console.error("[IRIS WebSocket] Voice command error:", payload.error)
        break
      }

      // GAP-08 FIX: Add error handler for backend error messages
      case "error": {
        const errorMessage = payload.message || payload.error || "Unknown error"
        console.error("[IRIS WebSocket] Backend error:", errorMessage)
        setLastError(typeof errorMessage === 'string' ? errorMessage : "Unknown error")
        break
      }

      // GAP-04 FIX: Add handlers for backend messages without frontend handlers
      case "subnodes": {
        // Handle subnodes response - updates available subnodes for current category
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Subnodes received:", payload.subnodes)
        }
        if (payload.subnodes && Array.isArray(payload.subnodes) && currentCategory) {
          setSubnodes((prev) => ({
            ...prev,
            [currentCategory]: payload.subnodes as Record<string, unknown>[]
          }))
        }
        break
      }

      case "model_selection_updated": {
        // Handle model selection update
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Model selection updated:", payload)
        }
        break
      }

      case "wake_word_selected": {
        // Handle wake word selection
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Wake word selected:", payload)
        }
        break
      }

      case "cleanup_report":
      case "cleanup_result": {
        // Handle cleanup operations
        if (process.env.NODE_ENV !== 'production') {
          console.log(`[IRIS WebSocket] ${type}:`, payload)
        }
        break
      }

      case "category_expanded": {
        // Handle category expansion confirmation
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Category expanded")
        }
        break
      }

      default:
        // GAP-04 FIX: Only log unknown message types in development mode
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Unknown message type:", type, payload)
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

  const selectSubnode = useCallback((subnodeId: string | null) => {
    if (subnodeId) {
      sendMessage("select_subnode", { subnode_id: subnodeId })
    } else {
      // Deselect - just update local state for now
      setCurrentSubnode(null)
    }
  }, [sendMessage])

  const updateField = useCallback((subnodeId: string, fieldId: string, value: string | number | boolean) => {
    // Store previous value for potential revert on validation error
    const updateKey = `${subnodeId}:${fieldId}`
    const previousValue = fieldValues[subnodeId]?.[fieldId]
    
    // Only track if we have a previous value (not first time setting)
    if (previousValue !== undefined) {
      pendingUpdatesRef.current.set(updateKey, {
        subnodeId,
        fieldId,
        previousValue,
      })
    }
    
    // Optimistic local update - update UI immediately
    setFieldValues((prev) => ({
      ...prev,
      [subnodeId]: {
        ...prev[subnodeId],
        [fieldId]: value,
      },
    }))

    // Send to server for validation and persistence
    sendMessage("field_update", { subnode_id: subnodeId, field_id: fieldId, value })
  }, [sendMessage, fieldValues])

  const confirmMiniNode = useCallback((subnodeId: string, values: Record<string, string | number | boolean>) => {
    sendMessage("confirm_mini_node", { subnode_id: subnodeId, values })
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
    sendMessage("voice_command_start", {})
  }, [sendMessage])

  const endVoiceCommand = useCallback(() => {
    sendMessage("voice_command_end", {})
  }, [sendMessage])

  // Clear field error
  const clearFieldError = useCallback((subnodeId: string, fieldId: string) => {
    const updateKey = `${subnodeId}:${fieldId}`
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
    subnodes,
    confirmedNodes,
    currentCategory,
    currentSubnode,
    voiceState,
    audioLevel,
    lastTextResponse,
    // Agent state
    agentStatus,
    agentTools,
    agentSkills,
    selectCategory,
    selectSubnode,
    updateField,
    confirmMiniNode,
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
