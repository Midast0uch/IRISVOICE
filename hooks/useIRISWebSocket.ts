import { useState, useEffect, useRef, useCallback } from "react"

// WebSocket connection states
type ConnectionState = "connecting" | "connected" | "disconnected" | "error"

// Theme type matching backend
interface ColorTheme {
  primary: string
  glow: string
  font: string
}

// Field values by category
interface FieldValues {
  [category: string]: {
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
}

// Hook return type
interface UseIRISWebSocketReturn {
  isConnected: boolean
  connectionState: ConnectionState
  theme: ColorTheme
  fieldValues: FieldValues
  confirmedNodes: ConfirmedNode[]
  currentCategory: string | null
  currentSubnode: string | null
  selectCategory: (category: string) => void
  selectSubnode: (subnodeId: string | null) => void
  updateField: (category: string, fieldId: string, value: string | number | boolean) => void
  confirmMiniNode: (category: string, subnodeId: string, values: Record<string, string | number | boolean>) => void
  updateTheme: (glowColor?: string, fontColor?: string) => void
  requestState: () => void
  lastError: string | null
}

// Default theme matching backend defaults
const DEFAULT_THEME: ColorTheme = {
  primary: "#00ff88",
  glow: "#00ff88",
  font: "#ffffff",
}

export function useIRISWebSocket(
  url: string = "ws://localhost:8000/ws/iris",
  autoConnect: boolean = true
): UseIRISWebSocketReturn {
  // Connection state
  const [connectionState, setConnectionState] = useState<ConnectionState>("disconnected")
  const [lastError, setLastError] = useState<string | null>(null)

  // IRIS state from backend
  const [theme, setTheme] = useState<ColorTheme>(DEFAULT_THEME)
  const [fieldValues, setFieldValues] = useState<FieldValues>({})
  const [confirmedNodes, setConfirmedNodes] = useState<ConfirmedNode[]>([])
  const [currentCategory, setCurrentCategory] = useState<string | null>(null)
  const [currentSubnode, setCurrentSubnode] = useState<string | null>(null)

  // WebSocket ref
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const reconnectAttemptsRef = useRef(0)

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
        console.log("[IRIS WebSocket] Connected")
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
        console.error("[IRIS WebSocket] Error:", error)
        setConnectionState("error")
        setLastError("Connection error")
      }

      ws.onclose = (event) => {
        console.log(`[IRIS WebSocket] Closed (code: ${event.code})`)
        setConnectionState("disconnected")
        wsRef.current = null

        // Auto-reconnect with exponential backoff
        if (autoConnect && reconnectAttemptsRef.current < 10) {
          const delay = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current), 30000)
          reconnectAttemptsRef.current++

          console.log(`[IRIS WebSocket] Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current})`)

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
  const handleMessage = useCallback((message: any) => {
    const { type, ...payload } = message

    switch (type) {
      case "initial_state":
      case "state_sync": {
        const state: IRISState = payload.state
        if (state.active_theme) setTheme(state.active_theme)
        if (state.field_values) setFieldValues(state.field_values)
        if (state.confirmed_nodes) setConfirmedNodes(state.confirmed_nodes)
        if (state.current_category !== undefined) setCurrentCategory(state.current_category)
        if (state.current_subnode !== undefined) setCurrentSubnode(state.current_subnode)
        break
      }

      case "category_changed": {
        if (payload.category) setCurrentCategory(payload.category)
        setCurrentSubnode(null)
        break
      }

      case "subnode_changed": {
        if (payload.subnode_id !== undefined) setCurrentSubnode(payload.subnode_id)
        break
      }

      case "field_updated": {
        // Optimistic update confirmed by server
        const { category, field_id, value } = payload
        if (category && field_id !== undefined) {
          setFieldValues((prev) => ({
            ...prev,
            [category]: {
              ...prev[category],
              [field_id]: value,
            },
          }))
        }
        break
      }

      case "validation_error": {
        console.error("[IRIS WebSocket] Validation error:", payload.error, payload.field_id)
        setLastError(payload.error)
        break
      }

      case "mini_node_confirmed": {
        // Server confirmed, state will be synced via state_sync
        break
      }

      case "theme_updated": {
        if (payload.glow || payload.font) {
          setTheme((prev) => ({
            ...prev,
            ...(payload.glow && { glow: payload.glow, primary: payload.glow }),
            ...(payload.font && { font: payload.font }),
          }))
        }
        break
      }

      case "pong": {
        // Keep-alive response, no action needed
        break
      }

      default:
        console.log("[IRIS WebSocket] Unknown message type:", type, payload)
    }
  }, [])

  // Send message helper
  const sendMessage = useCallback((type: string, payload: any = {}) => {
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

  const updateField = useCallback((category: string, fieldId: string, value: string | number | boolean) => {
    // Optimistic local update
    setFieldValues((prev) => ({
      ...prev,
      [category]: {
        ...prev[category],
        [fieldId]: value,
      },
    }))

    // Send to server
    sendMessage("field_update", { category, field_id: fieldId, value })
  }, [sendMessage])

  const confirmMiniNode = useCallback((category: string, subnodeId: string, values: Record<string, string | number | boolean>) => {
    sendMessage("confirm_mini_node", { category, subnode_id: subnodeId, values })
  }, [sendMessage])

  const updateTheme = useCallback((glowColor?: string, fontColor?: string) => {
    // Optimistic local update
    setTheme((prev) => ({
      ...prev,
      ...(glowColor && { glow: glowColor, primary: glowColor }),
      ...(fontColor && { font: fontColor }),
    }))

    // Send to server
    sendMessage("update_theme", { glow_color: glowColor, font_color: fontColor })
  }, [sendMessage])

  const requestState = useCallback(() => {
    sendMessage("request_state", {})
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
    confirmedNodes,
    currentCategory,
    currentSubnode,
    selectCategory,
    selectSubnode,
    updateField,
    confirmMiniNode,
    updateTheme,
    requestState,
    lastError,
  }
}
