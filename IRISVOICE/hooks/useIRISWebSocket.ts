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
  thinking?: string  // chain-of-thought from the model, shown in collapsible block
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
  cancelVoiceCommand: () => void
  sendMessage: (type: string, payload?: Record<string, unknown>) => boolean
  // Device actions
  getWakeWords: () => void
  getAudioDevices: () => void
  isChatTyping: boolean
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

// WebSocket resilience constants (module-level — stable references across renders)
const NON_QUEUEABLE_TYPES = new Set(['ping', 'pong'])
const RECONNECT_MAX_DELAY = 30_000   // 30 s ceiling
const STABILITY_THRESHOLD = 10_000  // reset backoff counter after 10 s of uptime

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
  // True while a text_message is being processed — drives ChatView typing indicator
  // independently of voiceState so the IrisOrb never animates for typed messages.
  const [isChatTyping, setIsChatTyping] = useState<boolean>(false)
  
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
  const onWakeDetectedRef = useRef(onWakeDetected)
  const onNativeAudioResponseRef = useRef(onNativeAudioResponse)

  // Resilience: sequence counter, send queue, connection-stability tracking
  const seqRef = useRef(0)
  const messageQueueRef = useRef<Array<{ type: string; payload: Record<string, unknown> }>>([])
  const connectedAtRef = useRef<number | null>(null)

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
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  // ─── scheduleReconnect ───────────────────────────────────────────────────
  // Shared helper used by both the readiness check and ws.onclose.
  // Unlimited retries with exponential backoff capped at RECONNECT_MAX_DELAY.
  const scheduleReconnect = useCallback(() => {
    if (!autoConnect) return
    const base = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current), RECONNECT_MAX_DELAY)
    const jitter = base * 0.2 * (Math.random() - 0.5)  // ±10 %
    const delay = Math.round(base + jitter)
    reconnectAttemptsRef.current++
    if (process.env.NODE_ENV !== 'production') {
      console.log(`[IRIS WebSocket] Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current})`)
    }
    reconnectTimeoutRef.current = setTimeout(() => connect(), delay)
  // connect is added to deps below after its declaration
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoConnect])

  // ─── connect ─────────────────────────────────────────────────────────────
  const connect = useCallback(async () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return // Already connected
    }

    setConnectionState("connecting")
    setLastError(null)

    // Fix 1 — Readiness check: probe the HTTP health endpoint before opening
    // the WebSocket socket. This prevents noisy ECONNREFUSED WebSocket errors
    // when the backend is still starting or temporarily down.
    const httpUrl = url.replace(/^ws(s?):\/\//, 'http$1://').replace(/\/ws.*$/, '/')
    try {
      await fetch(httpUrl, { signal: AbortSignal.timeout(2000) })
    } catch {
      // Backend not reachable — skip WebSocket, schedule a backoff retry
      if (process.env.NODE_ENV !== 'production') {
        console.log("[IRIS WebSocket] Backend not reachable, will retry...")
      }
      setConnectionState("disconnected")
      scheduleReconnect()
      return
    }

    try {
      const ws = new WebSocket(url)

      ws.onopen = () => {
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Connected")
        }
        setConnectionState("connected")
        reconnectAttemptsRef.current = 0     // reset backoff counter on success
        connectedAtRef.current = Date.now()  // Fix 2 — record connection time

        // Fix 4 — reset sequence counter on each fresh connection
        seqRef.current = 0

        // Burst messages on open (seq-tagged)
        ws.send(JSON.stringify({ type: "request_state",     payload: {}, seq: seqRef.current++ }))
        ws.send(JSON.stringify({ type: "get_audio_devices", payload: {}, seq: seqRef.current++ }))
        ws.send(JSON.stringify({ type: "get_wake_words",    payload: {}, seq: seqRef.current++ }))
        ws.send(JSON.stringify({ type: "get_available_models", payload: {}, seq: seqRef.current++ }))

        // Fix 3 — flush the send queue accumulated while disconnected
        const queued = messageQueueRef.current.splice(0)
        for (const msg of queued) {
          ws.send(JSON.stringify({ type: msg.type, payload: msg.payload, seq: seqRef.current++ }))
        }
        if (process.env.NODE_ENV !== 'production' && queued.length > 0) {
          console.log(`[IRIS WebSocket] Flushed ${queued.length} queued message(s)`)
        }
      }

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data)
          handleMessage(message)
        } catch (err) {
          console.error("[IRIS WebSocket] Failed to parse message:", err)
        }
      }

      ws.onerror = () => {
        // WebSocket errors don't expose useful detail — just set status
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

        // Fix 2 — if the connection was stable (≥ STABILITY_THRESHOLD ms), reset
        // the backoff counter so the next attempt is fast rather than at 30 s.
        const wasStable =
          connectedAtRef.current !== null &&
          Date.now() - connectedAtRef.current >= STABILITY_THRESHOLD
        if (wasStable) {
          reconnectAttemptsRef.current = 0
        }
        connectedAtRef.current = null

        // Fix 2 — no hard cap: always retry while autoConnect is true
        setLastError("Backend offline - running in standalone mode")
        scheduleReconnect()
      }

      wsRef.current = ws
    } catch (err) {
      console.error("[IRIS WebSocket] Failed to create connection:", err)
      setConnectionState("error")
      setLastError("Failed to create connection")
      scheduleReconnect()
    }
  }, [url, autoConnect, scheduleReconnect])

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

      case "chat_typing": {
        // Typing indicator for text_message flow — does NOT affect voiceState/IrisOrb
        setIsChatTyping(payload.active === true)
        break
      }

      case "chat_message": {
        // Final assistant response from text_message flow (streamed then complete)
        const content = typeof payload.content === 'string' ? payload.content : null
        if (content) {
          setLastTextResponse({
            text: content,
            sender: "assistant",
            ...(payload.thinking && typeof payload.thinking === 'string'
              ? { thinking: payload.thinking }
              : {}),
          })
        }
        break
      }

      case "chat_chunk": {
        // Streaming chunk — dispatch for progressive rendering
        if (typeof window !== 'undefined' && typeof payload.chunk === 'string') {
          window.dispatchEvent(new CustomEvent('iris:chat_chunk', {
            detail: { chunk: payload.chunk }
          }))
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
            sender,
            ...(payload.thinking && typeof payload.thinking === 'string'
              ? { thinking: payload.thinking }
              : {}),
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

      case "ping": {
        // Backend-initiated heartbeat ping — respond immediately to keep connection alive.
        // The backend's _heartbeat_loop in ws_manager.py sends a ping every 30s and
        // disconnects the client if no pong arrives within 30s (PONG_TIMEOUT).
        // Without this handler the connection is forcibly closed every ~60s.
        sendMessage("pong", {})
        break
      }

      case "pong": {
        // Backend responded to a pong — no action needed on the frontend.
        // The frontend no longer sends its own pings; the backend drives the
        // heartbeat.  This case is kept so the message doesn't fall through to
        // the "unknown type" warning branch.
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

      case "skills_list": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:skills_list', { detail: { payload } }))
        }
        break
      }

      case "skill_toggled": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:skill_toggled', { detail: { payload } }))
        }
        break
      }

      case "skill_deleted": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:skill_deleted', { detail: { payload } }))
        }
        break
      }

      case "skill_created": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:skill_created', { detail: { payload } }))
        }
        break
      }

      case "skills_reloaded": {
        // Skills reloaded by agent kernel — re-fetch the skills list
        if (process.env.NODE_ENV !== 'production') {
          console.log("[IRIS WebSocket] Skills reloaded:", payload)
        }
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:skills_reloaded', { detail: { payload } }))
        }
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

  // Send message helper — Fix 3 (queue) + Fix 4 (sequence numbers)
  const sendMessage = useCallback((type: string, payload: Record<string, unknown> = {}) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type, payload, seq: seqRef.current++ }))
      return true
    }
    // Not connected: queue non-ephemeral messages for delivery on next reconnect
    if (!NON_QUEUEABLE_TYPES.has(type)) {
      if (messageQueueRef.current.length >= 50) {
        messageQueueRef.current.shift()  // drop oldest to prevent unbounded growth
      }
      messageQueueRef.current.push({ type, payload })
      if (process.env.NODE_ENV !== 'production') {
        console.log(`[IRIS WebSocket] Queued message (not connected): ${type}`)
      }
    }
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
    // Optimistic update: show processing immediately (backend will transcribe + respond)
    // Avoids flicker: listening → idle (wrong) → processing_conversation (backend)
    setVoiceState("processing_conversation")
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('iris:voice_state_change', {
        detail: { state: "processing_conversation" }
      }))
    }
    sendMessage("voice_command_end", {})
  }, [sendMessage])

  const cancelVoiceCommand = useCallback(() => {
    // Immediate cancel — resets to idle without waiting for transcription/agent
    setVoiceState("idle")
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('iris:voice_state_change', {
        detail: { state: "idle" }
      }))
    }
    sendMessage("voice_command_cancel", {})
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

  // No frontend-initiated heartbeat.
  // The backend drives the ping/pong cycle (PING_INTERVAL=30s, PONG_TIMEOUT=30s).
  // The frontend responds to backend pings with pong (see case "ping" in handleMessage).
  // Having a competing frontend heartbeat that closes the socket on pong-timeout
  // caused spurious disconnects whenever the backend asyncio event loop was briefly
  // busy (TTS synthesis, model loading, subprocess calls) and the pong reply arrived
  // a few seconds late.  Removing it eliminates that class of disconnect entirely.

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
    cancelVoiceCommand,
    sendMessage,
    // Device actions
    getWakeWords,
    getAudioDevices,
    lastError,
    fieldErrors,
    clearFieldError,
    isChatTyping,
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
