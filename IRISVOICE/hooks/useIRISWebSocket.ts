
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
  sendMessage: (type: string, payload?: Record<string, unknown>) => boolean
  lastError: string | null
  onWakeDetected?: () => void
}

// Default theme matching backend defaults
const DEFAULT_THEME: ColorTheme = {
  primary: "#00ff88",
  glow: "#00ff88",
  font: "#ffffff",
}

export function useIRISWebSocket(
  url: string = "ws://localhost:8000/ws/iris", // Reverted to port 8000
  autoConnect: boolean = true,
  onWakeDetected?: () => void,
  onNativeAudioResponse?: (payload: Record<string, unknown>) => void
): UseIRISWebSocketReturn {
  // Connection state
  const [connectionState, setConnectionState] = useState<ConnectionState>("disconnected")
  const [lastError, setLastError] = useState<string | null>(null)

  // IRIS state from backend
  const [theme, setTheme] = useState<ColorTheme>(DEFAULT_THEME)
  const [fieldValues, setFieldValues] = useState<FieldValues>({})
  const [subnodes, setSubnodes] = useState<Record<string, Record<string, unknown>[]>>({})
  const [confirmedNodes, setConfirmedNodes] = useState<ConfirmedNode[]>([])
  const [currentCategory, setCurrentCategory] = useState<string | null>(null)
  const [currentSubnode, setCurrentSubnode] = useState<string | null>(null)
  const [voiceState, setVoiceState] = useState<VoiceState>("idle")
  const [lastTextResponse, setLastTextResponse] = useState<TextResponseMessage | null>(null)
  
  // Agent state
  const [agentStatus, setAgentStatus] = useState<Record<string, unknown> | null>(null)
  const [agentTools, setAgentTools] = useState<Record<string, unknown>[]>([])
  const [agentSkills, setAgentSkills] = useState<Record<string, unknown>[]>([])

  // WebSocket ref
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const onWakeDetectedRef = useRef(onWakeDetected)
  const onNativeAudioResponseRef = useRef(onNativeAudioResponse)

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

        // Auto-reconnect with exponential backoff - longer initial delay for browser mode
        if (autoConnect && reconnectAttemptsRef.current < 3) {
          const delay = Math.min(5000 * Math.pow(2, reconnectAttemptsRef.current), 30000)
          reconnectAttemptsRef.current++

          if (process.env.NODE_ENV !== 'production') {
            console.log(`[IRIS WebSocket] Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current}/3)`)
          }

          reconnectTimeoutRef.current = setTimeout(() => {
            connect()
          }, delay)
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
      case "initial_state":
      case "state_sync": {
        const state: IRISState = payload.state as IRISState
        if (state.active_theme) setTheme(state.active_theme)
        if (state.field_values) setFieldValues(state.field_values)
        if (state.subnodes) setSubnodes(state.subnodes)
        if (state.confirmed_nodes) setConfirmedNodes(state.confirmed_nodes)
        if (state.current_category !== undefined) setCurrentCategory(state.current_category)
        if (state.current_subnode !== undefined) setCurrentSubnode(state.current_subnode)
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
        // Optimistic update confirmed by server
        const { subnode_id, field_id, value } = payload as { subnode_id: string; field_id: string; value: string | number | boolean }
        if (subnode_id && field_id !== undefined) {
          setFieldValues((prev) => ({
            ...prev,
            [subnode_id]: {
              ...prev[subnode_id] || {},
              [field_id]: value,
            },
          }))
        }
        break
      }

      case "validation_error": {
        console.error("[IRIS WebSocket] Validation error:", payload.error, payload.field_id)
        setLastError(typeof payload.error === 'string' ? payload.error : null)
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
          setVoiceState(payload.state as VoiceState)
        }
        break
      }

      case "pong": {
        // Keep-alive response, no action needed
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

      case "voice_command_error": {
        // Voice command error
        console.error("[IRIS WebSocket] Voice command error:", payload.error)
        break
      }

      default:
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
    // Optimistic local update
    setFieldValues((prev) => ({
      ...prev,
      [subnodeId]: {
        ...prev[subnodeId],
        [fieldId]: value,
      },
    }))

    // Send to server
    sendMessage("field_update", { subnode_id: subnodeId, field_id: fieldId, value })
  }, [sendMessage])

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

  // Initialize connection
  useEffect(() => {
    if (autoConnect) {
      connect()
    }

    return cleanup
  }, [autoConnect, connect, cleanup])

  // Keep-alive ping
  useEffect(() => {
    if (!isConnected) return

    const interval = setInterval(() => {
      sendMessage("ping", {})
    }, 30000) // Ping every 30 seconds

    return () => clearInterval(interval)
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
    sendMessage,
    lastError,
  }
}
