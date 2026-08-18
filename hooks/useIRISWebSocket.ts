import { useState, useEffect, useRef, useCallback, useSyncExternalStore } from "react"
import type { OpenTabMsg, CloseTabMsg, CrawlerStartedMsg, CrawlerPageMsg, CrawlerErrorMsg, CrawlerCompleteMsg, CrawlerProgressMsg, CrawlerPhaseMsg, CrawlerVisionActionMsg, CrawlerSourceParkedMsg, CrawlerSourcesAddedMsg } from "@/types/iris"

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

// ── Shared voiceState singleton ──────────────────────────────────────────────
// useIRISWebSocket is instantiated by multiple components (NavigationContext,
// orbit-node, useInferenceState). Each instance opens its OWN WebSocket as
// client="iris", and the backend keeps only the LAST-connected socket
// (ws_manager.py replaces the prior connection). So a `wake_detected` broadcast
// reaches only ONE instance — usually not the NavigationContext instance that
// drives the orb / text area / ContextPill. That made the wake word fail to
// update the UI on most triggers (and especially after a thread switch, which
// remounts/reconnects the sockets).
//
// Fix: voiceState is a SINGLE source of truth at module scope, shared by every
// useIRISWebSocket instance via useSyncExternalStore. Any instance that receives
// `wake_detected` (or calls startVoiceCommand) updates the shared store, and ALL
// instances — including NavigationContext — re-render. This makes the wake word
// drive the UI reliably on every trigger and every conversation thread.
let _voiceState: VoiceState = "idle"
const _voiceStateSubs = new Set<() => void>()

function _emitVoiceState(next: VoiceState) {
  if (_voiceState === next) return
  _voiceState = next
  _voiceStateSubs.forEach((cb) => {
    try { cb() } catch { /* subscriber error must not break the emit */ }
  })
}

function _subscribeVoiceState(cb: () => void): () => void {
  _voiceStateSubs.add(cb)
  return () => { _voiceStateSubs.delete(cb) }
}

function _getVoiceState(): VoiceState {
  return _voiceState
}

// ── Shared active-conversation singleton ────────────────────────────────────
// Same problem as voiceState, different blast radius. Every useIRISWebSocket
// instance kept its OWN currentConversationId, each seeded from localStorage at
// ITS mount and each sending `sync_state {conversation_id}` on (re)connect. The
// instances also fight over client="iris", so every connect evicts the previous
// socket and re-sends sync_state — a steady churn of rebinds.
//
// So "New Conversation" could not work: chat-view cleared the NavigationContext
// instance's copy, while the orbit-node / useInferenceState instances still held
// the OLD thread and re-bound the backend to it on their next connect. Observed
// live as the log pair `client_replace cancelled in-flight thread conv-4` +
// `sync_state attached conversation conv-4` right after starting a new
// conversation — the fresh thread snapping back to the previous one.
//
// One id, module scope, one localStorage writer. Clearing it clears it for every
// instance, so no socket can resurrect a thread the user has left.
const ACTIVE_ID_KEY = "iris_active_conversation_id_v1"

let _activeConvId: string | undefined = (() => {
  if (typeof window === "undefined") return undefined
  try {
    return localStorage.getItem(ACTIVE_ID_KEY) || undefined
  } catch {
    return undefined
  }
})()
const _activeConvSubs = new Set<() => void>()

function _emitActiveConvId(next: string | undefined) {
  if (_activeConvId === next) return
  _activeConvId = next
  try {
    if (next) localStorage.setItem(ACTIVE_ID_KEY, next)
    else localStorage.removeItem(ACTIVE_ID_KEY)
  } catch {
    // localStorage unavailable — non-fatal, the in-memory value still rules
  }
  _activeConvSubs.forEach((cb) => {
    try { cb() } catch { /* subscriber error must not break the emit */ }
  })
}

function _subscribeActiveConvId(cb: () => void): () => void {
  _activeConvSubs.add(cb)
  return () => { _activeConvSubs.delete(cb) }
}

function _getActiveConvId(): string | undefined {
  return _activeConvId
}

function _getActiveConvIdServer(): string | undefined {
  return undefined
}

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
  // Cadence (spectral flux) during listening — from backend audio_envelope WS
  cadenceLevel: number
  // TTS audio level (RMS) during speaking — from backend audio_envelope WS
  ttsAudioLevel: number
  // Audio phase: "listening" | "speaking" | "idle"
  audioPhase: "listening" | "speaking" | "idle"
  // Per-thread context keying (Phase 1)
  currentConversationId: string | undefined
  setCurrentConversationId: (id: string | undefined) => void
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
  selectAudioDevice: (deviceType: "input" | "output", deviceIndex: number, deviceName: string) => void
  isChatTyping: boolean
  lastError: string | null
  fieldErrors: Record<string, string> // Map of "sectionId:fieldId" to error message
  clearFieldError: (sectionId: string, fieldId: string) => void
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
// Transient navigation messages must NOT replay on reconnect —
// the backend rejects them if they refer to stale state (e.g. an old
// "marketplace" category that is no longer valid after a reconnect).
const NON_QUEUEABLE_TYPES = new Set([
  'ping', 'pong',
  'select_category', 'select_section', 'go_back',
  'expand_to_main', 'collapse_to_idle',
])
const RECONNECT_MAX_DELAY = 30_000   // 30 s ceiling
const STABILITY_THRESHOLD = 10_000  // reset backoff counter after 10 s of uptime

export function useIRISWebSocket(
  url?: string,
  autoConnect: boolean = true,
  onNativeAudioResponse?: (payload: Record<string, unknown>) => void
): UseIRISWebSocketReturn {
  // Compute WebSocket URL based on page hostname (works on localhost AND Tailscale)
  const resolvedUrl = url ?? (typeof window !== 'undefined'
    ? (process.env.NEXT_PUBLIC_WS_URL || `ws://${window.location.hostname}:${process.env.NEXT_PUBLIC_BACKEND_PORT || 8090}/ws/iris`)
    : (process.env.NEXT_PUBLIC_WS_URL || `ws://127.0.0.1:${process.env.NEXT_PUBLIC_BACKEND_PORT || 8090}/ws/iris`))
  const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window

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
  // voiceState is a SHARED singleton (see module-level store above) so every
  // useIRISWebSocket instance — including NavigationContext — sees the same
  // value. This is what makes the wake word reliably drive the UI.
  const voiceState = useSyncExternalStore(_subscribeVoiceState, _getVoiceState, _getVoiceState)
  const setVoiceState = useCallback((next: VoiceState) => {
    _emitVoiceState(next)
  }, [])
  const [audioLevel, setAudioLevel] = useState<number>(0)
  // Cadence (spectral flux) during listening — from backend audio_envelope WS
  const [cadenceLevel, setCadenceLevel] = useState<number>(0)
  // TTS audio level (RMS) during speaking — from backend audio_envelope WS
  const [ttsAudioLevel, setTtsAudioLevel] = useState<number>(0)
  // Audio phase: "listening" | "speaking" | "idle"
  const [audioPhase, setAudioPhase] = useState<"listening" | "speaking" | "idle">("idle")
  const [lastTextResponse, setLastTextResponse] = useState<TextResponseMessage | null>(null)
  // True while a text_message is being processed — drives ChatView typing indicator
  // independently of voiceState so the IrisOrb never animates for typed messages.
  const [isChatTyping, setIsChatTyping] = useState<boolean>(false)
  // Bumped on every inbound WS frame. Feeds the typing-indicator watchdog below
  // so it measures SILENCE from the backend rather than elapsed turn time.
  const [typingActivityTick, setTypingActivityTick] = useState(0)
  // Single source of truth for the ACTIVE conversation thread.  Initialized
  // from localStorage so thread identity survives component unmounts, widget
  // drags, Tauri window reopens, and WS reconnects — the active thread must
  // NOT reset to undefined on any of those (it would let the backend fall
  // back to a stale/old conversation).  chat-view also keeps its own copy,
  // but the WS hook is authoritative: every switch/new writes here AND back
  // to the same localStorage key chat-view uses, keeping them in lockstep.
  // Backed by the module-level singleton above, so every instance of this hook
  // sees — and writes — the SAME thread id.
  const currentConversationId = useSyncExternalStore(
    _subscribeActiveConvId,
    _getActiveConvId,
    _getActiveConvIdServer,
  )
  const setCurrentConversationId = useCallback((id: string | undefined) => {
    _emitActiveConvId(id)
  }, [])
  
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
    model_name: "lfm2.5-vl",
    quantization_enabled: true,
    is_available: false
  })

  // WebSocket ref
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const onNativeAudioResponseRef = useRef(onNativeAudioResponse)

  // Resilience: sequence counter, send queue, connection-stability tracking
  const seqRef = useRef(0)
  const messageQueueRef = useRef<Array<{ type: string; payload: Record<string, unknown> }>>([])
  const connectedAtRef = useRef<number | null>(null)

  // Optimistic update tracking: store previous values for revert on validation error
  const pendingUpdatesRef = useRef<Map<string, { sectionId: string; fieldId: string; previousValue: string | number | boolean }>>(new Map())
  
  // Timestamp tracking for out-of-order update handling
  const fieldTimestampsRef = useRef<Map<string, number>>(new Map())

  // Deduplicate buffered chat_message replays by turn_id
  const seenTurnIdsRef = useRef<Set<string>>(new Set())

  // Update ref when callback changes
  useEffect(() => {
    onNativeAudioResponseRef.current = onNativeAudioResponse
  }, [onNativeAudioResponse])

  // The active thread id is read straight from the module singleton at every
  // use site (connect(), sendMessage()). It replaced a per-instance ref that a
  // per-instance effect kept in sync — which is precisely how instances came to
  // disagree about which thread was live. There is nothing left to synchronise:
  // the store IS the value, and it owns the localStorage write.

  // Safety timeout: reset the typing indicator if the backend goes SILENT.
  // Covers a backend crash mid-response or a lost chat_typing:false event,
  // which would otherwise leave "thinking…" stuck forever.
  //
  // SILENCE WATCHDOG, NOT A FIXED CAP (2026-08-17). This was a flat 30 s from
  // the moment typing began, so it fired on every healthy multi-step turn —
  // measured live: typing went true at t=26 s and false at t=56 s, exactly 30 s
  // later, while step 4 of 4 was still running. The indicator then stayed off
  // until the answer arrived, leaving the UI completely blank for the rest of
  // the turn (16 s on a 45 s turn; 62 s on a slower one). A DER turn legitimately
  // runs far past 30 s, so the cap was guaranteed to misfire.
  //
  // `typingActivityTick` bumps on every inbound WS frame, so the timer restarts
  // whenever the backend is demonstrably alive. It now only fires after a real
  // stretch of silence — which is the condition it was written for.
  useEffect(() => {
    if (!isChatTyping) return;
    const timer = setTimeout(() => {
      setIsChatTyping(false);
      console.log(
        "[IRIS WebSocket] Typing indicator reset — no backend activity for 90s",
      );
    }, 90_000);
    return () => clearTimeout(timer);
  }, [isChatTyping, typingActivityTick])

  const isConnected = connectionState === "connected"

  // HMR-safe cleanup — defers WS close for 2 s so that Fast Refresh /
  // Turbopack remounts don't kill in-flight API responses.  The browser
  // closes all WS on actual page unload, so the deferred close is safe.
  const _closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cleanup = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    // ── Tauri path: disconnect Rust-side WS client ───────────────────
    if (isTauri) {
      import('@tauri-apps/api/core').then(({ invoke }) => {
        invoke('ws_disconnect');
      }).catch(() => {});
    }
    // Close after 2 s delay — cancel if the component remounts before then
    // (the new mount's effect calls _cancelDeferredClose).
    if (wsRef.current) {
      _closeTimerRef.current = setTimeout(() => {
        if (wsRef.current) {
          wsRef.current.close()
          wsRef.current = null
        }
        _closeTimerRef.current = null
      }, 2000)
    }
  }, [])
  // Called from the auto-connect effect to cancel a pending deferred close.
  // Must be declared before the effect that uses it (hoisting in the
  // function body is fine).
  function _cancelDeferredClose() {
    if (_closeTimerRef.current) {
      clearTimeout(_closeTimerRef.current)
      _closeTimerRef.current = null
    }
  }

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

    // ── Tauri path: delegate to Rust-side WS client ──────────────────
    if (isTauri) {
      setConnectionState("connecting");
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        await invoke('start_ws_client', { url: resolvedUrl });
      } catch (e) {
        console.error("[IRIS WebSocket] Tauri start_ws_client failed:", e);
        setConnectionState("disconnected");
      }
      return;
    }

    setConnectionState("connecting")
    setLastError(null)

    // The WebSocket handles connection failures via onerror/onclose + reconnect.
    // Skip the blocking readiness check — it delays connection by up to 16s
    // and can silently fail due to CORS on the internal fetch.

    try {
      const ws = new WebSocket(resolvedUrl)

       ws.onopen = () => {
         if (process.env.NODE_ENV !== 'production') {
           console.log("[IRIS WebSocket] Connected")
         }
         setConnectionState("connected")
         reconnectAttemptsRef.current = 0     // reset backoff counter on success
         connectedAtRef.current = Date.now()  // Fix 2 — record connection time
         setIsChatTyping(false)               // Fix: reset typing state on reconnect
                                              // prevents stuck "thinking..." after disconnect

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

        // Phase 4.3: re-attach the active conversation's kernel after a
        // (re)connect so the resumed thread keeps its own history instead of
        // the session default.  The backend binds the WS kernel to this id
        // and restores its persisted context.
        const _convId = _getActiveConvId()
        if (_convId) {
          ws.send(JSON.stringify({
            type: "sync_state",
            payload: { conversation_id: _convId },
            seq: seqRef.current++,
          }))
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
        // onclose should follow onerror per the WS spec, but some browsers
        // can skip it (chromium edge case). Close explicitly to guarantee
        // onclose fires, which owns the reconnect scheduling.
        try { ws.close() } catch { /* already closing */ }
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
  }, [resolvedUrl, autoConnect, scheduleReconnect])

  // Handle incoming messages
  const handleMessage = useCallback((message: Record<string, unknown>) => {
    const type = message.type
    // Proof of life for the typing watchdog: any frame from the backend means
    // it is still working, so the "stuck indicator" timer restarts. Cheap —
    // a counter bump, and the watchdog is the only reader.
    setTypingActivityTick((n) => n + 1)
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

        // Adopt the backend's authoritative active conversation id.  The backend
        // owns _active_conversation_id per session (set on new_conversation /
        // switch_conversation), so on (re)connect this is the tiebreaker that
        // keeps the frontend and backend in lockstep — preventing a wake-word
        // response from landing in a stale/old thread after a drag, remount, or
        // backend restart.  Only override when the backend actually has an id,
        // so we never clobber a legitimate in-flight frontend-led switch.
        const backendCid = (payload as Record<string, unknown>)?.current_conversation_id as string | undefined
        if (backendCid && backendCid !== _getActiveConvId()) {
          setCurrentConversationId(backendCid)
        }

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
        // Wake word detected — same visual feedback as double-click.
        // Backend already started recording via _handle_voice, so no need
        // to send voice_command_start (that would be a duplicate).
        console.log('[IRIS WebSocket] wake_detected — activating listening state')
        setVoiceState("listening")
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:voice_state_change', {
            detail: { state: "listening" }
          }))
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

      case "tts_started": {
        // Backend signals first TTS audio chunk has been pushed to the player.
        // Frontend uses this to sync word highlighting with actual audio.
        // Pass turn_id and total_words so chat-view can set currentTtsMessageId
        // immediately — BEFORE text_response arrives — preventing the re-run
        // race that drops tts_word events between cleanup/setup cycles.
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:tts_started', {
            detail: {
              turn_id: typeof payload.turn_id === 'string' ? payload.turn_id : undefined,
              total_words: typeof payload.total_words === 'number' ? payload.total_words : undefined,
            }
          }))
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
        // Also reset typing indicator — chat_message always means processing is done
        setIsChatTyping(false)
        const _turnId = typeof payload.turn_id === 'string' ? payload.turn_id : null
        if (_turnId && seenTurnIdsRef.current.has(_turnId)) {
          if (process.env.NODE_ENV !== 'production') {
            console.log(`[IRIS WebSocket] Deduplicating replayed chat_message turn=${_turnId}`)
          }
          break
        }
        if (_turnId) {
          seenTurnIdsRef.current.add(_turnId)
        }
        const content = typeof payload.content === 'string' ? payload.content : null
        if (content) {
          const thinking = typeof payload.thinking === 'string' ? payload.thinking : undefined
          // `spoken` is the line TTS actually says — a short briefing when the
          // answer is long (iris_gateway builds it alongside `content`). ChatView
          // needs it because the backend's tts_word indices count words of THIS
          // string, not of the body.
          const spoken = typeof payload.spoken === 'string' ? payload.spoken : undefined
          setLastTextResponse({
            text: content,
            sender: "assistant",
            ...(thinking ? { thinking } : {}),
          })
          // Also dispatch CustomEvent so chat-view synchronous listener catches it
          if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('iris:text_response', {
              detail: { text: content, sender: 'assistant', thinking, spoken }
            }))
          }
        }
        break
      }

       case "chat_chunk": {
          // Streaming chunk — dispatch for progressive rendering
          if (typeof window !== 'undefined' && typeof payload.chunk === 'string') {
            window.dispatchEvent(new CustomEvent('iris:chat_chunk', {
              detail: { chunk: payload.chunk, turn_id: payload.turn_id }
            }))
          }
          break
        }

       case "chat_reasoning": {
         // Reasoning/thinking tokens from chain-of-thought models
         if (typeof window !== 'undefined') {
           window.dispatchEvent(new CustomEvent('iris:chat_reasoning', {
             detail: { chunk: payload.chunk ?? "" }
           }))
         }
         break
       }

        case "audio_level": {
         // Audio level update during listening (legacy — old IrisOrb.tsx)
         if (typeof payload.level === 'number') {
           setAudioLevel(payload.level)
         }
         break
       }

       case "audio_envelope": {
         // Consolidated audio envelope: { rms, cadence, phase }
         // Used by XurOrb for cadence-driven breathing at all levels.
         const rms = typeof payload.rms === 'number' ? payload.rms : 0
         const cadence = typeof payload.cadence === 'number' ? payload.cadence : 0
         const phase = typeof payload.phase === 'string' ? payload.phase : "idle"
         setAudioPhase(phase as "listening" | "speaking" | "idle")
         if (phase === "listening") {
           setAudioLevel(rms)
           setCadenceLevel(cadence)
           setTtsAudioLevel(0)
         } else if (phase === "speaking") {
           setTtsAudioLevel(rms)
           setCadenceLevel(rms)  // TTS cadence = RMS (no spectral flux for playback)
           setAudioLevel(0)
         } else {
           setAudioLevel(0)
           setCadenceLevel(0)
           setTtsAudioLevel(0)
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
          
          // Dispatch CustomEvent for SidePanel and other listeners.
          // turn_id lives at the top level of the WS message (not inside payload)
          // and is used by chat-view to match tts_started's currentTtsMessageId
          // so word highlighting renders against the correct message.
          const turnId = typeof message.turn_id === 'string' ? message.turn_id : undefined
          if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('iris:text_response', {
              detail: {
                text: payload.text,
                sender,
                thinking: typeof payload.thinking === 'string' ? payload.thinking : undefined,
                turn_id: turnId,
              }
            }))
          }
        }
        break
      }

      // ── TTS word-highlight event ─────────────────────────────────────────
      // Backend Pocket-TTS emits word-level indices during playback.
      // chat-view.tsx listens for iris:tts_word to sync highlight with real
      // TTS speed instead of the 200ms fallback interval.
      case "tts_word": {
        if (typeof window !== 'undefined' && typeof payload.word_index === 'number') {
          window.dispatchEvent(new CustomEvent('iris:tts_word', {
            detail: {
              word_index: payload.word_index,
              total_words: typeof payload.total_words === 'number' ? payload.total_words : undefined,
              message_id: typeof payload.message_id === 'string' ? payload.message_id : undefined,
              is_final: payload.word_index === Number(payload.total_words ?? 0) - 1 || payload.is_final === true,
            }
          }))
        }
        break
      }

      // ── Parakeet ASR voice result ─────────────────────────────────────────
      // Backend broadcasts the final ASR transcript (from Parakeet service)
      // to all clients in the session.  chat-view.tsx listens for
      // iris:voice_final to show the user's spoken text as a message.
      case "voice_result": {
        if (typeof window !== 'undefined' && typeof payload.text === 'string') {
          window.dispatchEvent(new CustomEvent('iris:voice_final', {
            detail: {
              text: payload.text,
              confidence: typeof payload.confidence === 'number' ? payload.confidence : undefined,
              turn_id: typeof payload.turn_id === 'string' ? payload.turn_id : undefined,
            }
          }))
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

      case "audio_devices_changed": {
        // A device was plugged or unplugged — re-fetch the full list
        if (process.env.NODE_ENV !== "production") {
          console.log(
            "[IRIS WebSocket] Devices changed:",
            payload.input_count,
            "inputs,",
            payload.output_count,
            "outputs"
          )
        }
        sendMessage("get_audio_devices", {})
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

      case "provider_added": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:provider_added', { detail: payload }))
        }
        break
      }
      case "role_bindings_updated": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:role_bindings_updated', { detail: payload }))
        }
        break
      }
      case "role_binding_error": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:role_binding_error', { detail: payload }))
        }
        break
      }
      case "role_binding_updated": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:role_binding_updated', { detail: payload }))
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

      case "inference_event":
      case "model_load_event":
      // ── Local model / hardware events ── forwarded to iris:ws_message so
      // ModelsScreen and InferenceConsolePanel receive them without prop-drilling.
      case "local_models_list":
      case "hardware_info":
      case "local_model_status": {
        // Drive the dashboard "MODEL STATUS" badge (field local_model_status
        // under the 'local_model' section). The backend sends an object
        // {status, loaded, model_path, ...}; the badge expects a string status
        // (loaded/unloaded/loading/error). Without this, the badge stays
        // "unloaded" forever after a successful load (pin_9e97e21340e7).
        const p = payload || {}
        let status: string
        if (typeof p === 'string') {
          status = p
        } else if (typeof p.status === 'string') {
          status = p.status
        } else if (p.loaded === true) {
          status = 'loaded'
        } else if (p.loaded === false && (p.status === 'error' || p.error)) {
          status = 'error'
        } else {
          status = 'unloaded'
        }
        // The badge field is declared in data/cards.ts under section id
        // 'local-model-card' (hyphens), and dark-glass-dashboard resolves a
        // field's value by that SECTION id. Writing only to `local_model`
        // dropped every update into a bucket nothing renders, which is why a
        // load could succeed, wire the kernel and register the provider while
        // MODEL STATUS still read UNLOADED. Write both: the hyphenated section
        // the card actually uses, and the legacy key other panels read.
        setFieldValues((prev) => ({
          ...prev,
          'local-model-card': {
            ...((prev as any)['local-model-card'] || {}),
            local_model_status: status,
          },
          local_model: { ...(prev.local_model || {}), local_model_status: status },
        }))
        // Forward to any panel that listens on iris:ws_message
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:ws_message', {
            detail: { type, payload }
          }))
        }
        break
      }
      case "local_model_loading":
      case "gguf_download_progress":
      case "model_pin_updated":
      case "hf_models_list":
      // ── Monitor analytics ─────────────────────────────────────────────────
      case "monitor_analytics_data":
      // ── Field updates for side panel cards ─────────────────────────────────
      case "update_field": {
        // Forward to any panel that listens on iris:ws_message
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:ws_message', {
            detail: { type, payload }
          }))
        }
        break
      }

      // ── Tab system ────────────────────────────────────────────────────────
      // open_tab / close_tab are forwarded as CustomEvents so DashboardWing
      // can receive them without threading state through NavigationContext.
      case "open_tab": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:open_tab', {
            detail: message as unknown as OpenTabMsg
          }))
        }
        break
      }

      case "close_tab": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:close_tab', {
            detail: message as unknown as CloseTabMsg
          }))
        }
        break
      }

      // ── Crawler status ─────────────────────────────────────────────────────
      case "crawler_started": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:crawler_started', {
            detail: message as unknown as CrawlerStartedMsg
          }))
        }
        break
      }

      case "crawler_page_fetched": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:crawler_page_fetched', {
            detail: message as unknown as CrawlerPageMsg
          }))
        }
        break
      }

      case "crawler_error": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:crawler_error', {
            detail: message as unknown as CrawlerErrorMsg
          }))
        }
        break
      }

      // Terminal event (REQ-29/30): crawl finished. Reset the orb phase to
      // idle/thinking and surface the summary + citations. Dispatched so the
      // useCrawl hook (and SSE fallback) can finalize crawl state.
      case "crawler_complete": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:crawler_complete', {
            detail: message as unknown as CrawlerCompleteMsg
          }))
        }
        break
      }

      // ── Crawler live detail (REQ-11/12, T17/T19) ─────────────────────────
      // In-flight stage message + structured phase. The SSE fallback emits the
      // SAME CustomEvent names (useCrawlSSE re-dispatches `iris:${type}`), so
      // the two transports stay on one event contract (REQ-31 AC4). The WS
      // handlers today do NOT send these types (phases arrive as `task:progress`
      // via WSEventBridge); the cases are wired so a future ux_map-routed WS
      // message lands in the same place — and the SSE path already delivers.
      case "crawler_progress": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:crawler_progress', {
            detail: message as unknown as CrawlerProgressMsg
          }))
        }
        break
      }

      case "crawler_phase": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:crawler_phase', {
            detail: message as unknown as CrawlerPhaseMsg
          }))
        }
        break
      }

      // ux_map.py maps CRAWLER_PHASE -> msg_type "task:event" (the SSE contract).
      // Forward the same name over WS so useCrawl's phase listener fires
      // regardless of transport.
      case "task:event": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:task:event', {
            detail: message as unknown as CrawlerPhaseMsg
          }))
        }
        break
      }

      case "crawler_vision_action": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:crawler_vision_action', {
            detail: message as unknown as CrawlerVisionActionMsg
          }))
        }
        break
      }

      case "crawler_source_parked": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:crawler_source_parked', {
            detail: message as unknown as CrawlerSourceParkedMsg
          }))
        }
        break
      }

      // Sources added mid-run (broadened re-plan / vision search discovery). The
      // plan card appends them — the set announced at crawler_started is not
      // final, so without this the card keeps showing sources the agent has
      // already moved on from.
      case "crawler_sources_added": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:crawler_sources_added', {
            detail: message as unknown as CrawlerSourcesAddedMsg
          }))
        }
        break
      }

      case "crawler_sync_required": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:crawler_sync_required', {
            detail: message as unknown as { session_id: string }
          }))
        }
        break
      }

      // ── Mode change ────────────────────────────────────────────────────────
      // Broadcast from /api/mode POST — iris-launcher set a new mode.
      // Forwarded so useLauncherMode can react without polling.
      case "mode_changed": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:mode_changed', {
            detail: { mode: (message as Record<string, unknown>).mode as string }
          }))
        }
        break
      }

      // ── Conversation switch ───────────────────────────────────────────────
      // Acknowledgment from backend after switch_conversation message.
      case "conversation_switched": {
        if (process.env.NODE_ENV !== 'production') {
          console.debug(
            "[IRIS WebSocket] Conversation switched to",
            (payload as Record<string, unknown>)?.conversation_id
          )
        }
        // The backend's switch ack was logged and dropped. Anything holding
        // per-thread UI state (useTaskProgress' plan card) had no way to learn
        // the thread changed, so it kept rendering the previous conversation's
        // run inside the new one.
        if (typeof window !== 'undefined') {
          window.dispatchEvent(
            new CustomEvent('iris:conversation_switched', { detail: payload })
          )
        }
        break
      }

      // ── Permission events ──────────────────────────────────────────────────
      // Forwarded from ToolPermissionSystem to frontend PermissionCard.
      case "permission:request":
      case "permission:granted":
      case "permission:denied": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent(
            `iris:${(message as Record<string, unknown>).type}`,
            { detail: payload }
          ))
        }
        break
      }

      // ── Agent question events ──────────────────────────────────────────────
      // Forwarded from AskUserTool to frontend QuestionCard.
      case "question:ask":
      case "question:answered":
      case "question:timeout": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent(
            `iris:${(message as Record<string, unknown>).type}`,
            { detail: payload }
          ))
        }
        break
      }

      // ── Task progress events ───────────────────────────────────────────────
      // Forwarded from WSEventBridge to frontend TaskListCard + OrbBadge.
      // Collapsed into a single iris:task_update CustomEvent (detail carries
      // the original event type) so useTaskProgress can reduce them.
      case "task:start":
      case "task:progress":
      case "task:milestone":
      case "task:done":
      case "task:fail":
      case "task:learning":
      case "tool:call":
      case "tool:result":
      case "tool:error": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:task_update', {
            detail: {
              type: (message as Record<string, unknown>).type,
              ...(payload as Record<string, unknown>),
            },
          }))
        }
        break
      }

      // ── Context usage events ───────────────────────────────────────────────
      // Forwarded from WSEventBridge to frontend ContextPill.
      case "context:usage": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:context_usage', { detail: payload }))
        }
        break
      }

      // ── Document render (plan Issue D.3) ───────────────────────────────
      // Agent pushed a rich document (format + content + alternatives).
      // Forwarded to iris:document_render so chat-view renders it inline.
      case "document:render": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:document_render', { detail: payload }))
        }
        break
      }

      // Reformat failure — surfaced as an inline error on the document card.
      case "reformat_document_error": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:reformat_document_error', { detail: payload }))
        }
        break
      }

      // ── Document re-hydration (document-rehydration spec, REQ-1/2) ───────
      // Response to a `get_documents` request. Forwarded to iris:documents so
      // chat-view can merge prior rendered documents back into the panel on
      // resume/switch (single convergence point: hydrateDocuments -> reducer).
      case "documents": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:documents', { detail: payload }))
        }
        break
      }

      // ── Execution-hardening plan events (Phase 4.1) ─────────────────────
      // VALIDATION_FAILED / RECOVERY_START / TOPOLOGY_RECOVERY / BUDGET_EXHAUSTED
      // from the agent kernel, bridged via WSEventBridge. Forwarded to
      // iris:plan_event so chat-view renders them as system messages.
      case "plan:budget_exhausted":
      case "plan:validation_failed":
      case "plan:recovery_start":
      case "plan:topology_recovery": {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:plan_event', {
            detail: { type, ...(payload as Record<string, unknown>) }
          }))
        }
        break
      }

      case 'cli_output': {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:cli_output', { detail: payload }))
        }
        break
      }

      case 'cli_started': {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:cli_started', { detail: payload }))
        }
        break
      }

      case 'cli_activity': {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:cli_activity', { detail: payload }))
        }
        break
      }

      case 'file_activity': {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:file_activity', { detail: payload }))
        }
        break
      }

      case 'dcp_pruned': {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:dcp_pruned', { detail: payload }))
        }
        break
      }

      case 'session_end': {
        // Backend is shutting down or session ending — signal Launcher
        // to open DiffReviewPage.  Also write to localStorage so other
        // windows (Tauri launcher window) can detect it.
        if (typeof window !== 'undefined') {
          try {
            localStorage.setItem('iris:session_ended', JSON.stringify({
              timestamp: Date.now(),
              pending_writes: (payload as any)?.pending_writes ?? 0,
              branch: (payload as any)?.branch ?? '',
            }));
          } catch { /* ignore quota errors */ }
          window.dispatchEvent(new CustomEvent('iris:session_end', { detail: payload }))
        }
        break
      }

      case 'system_status': {
        // Broadcast system snapshot — replaces FE polling in iris-launcher
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:system_status', { detail: payload }))
        }
        break
      }

      case 'error': {
        // Backend error notification (parakeet_service, iris_gateway, crawler).
        // Shapes vary: { error: "..." } or { payload: { message: "..." } }.
        // Surface it as a CustomEvent so UI components can react, and log it
        // properly instead of falling through to "Unknown message type".
        const msg =
          (payload as any)?.error ??
          (payload as any)?.payload?.message ??
          (payload as any)?.message ??
          'Unknown backend error'
        if (process.env.NODE_ENV !== 'production') {
          console.warn('[IRIS WebSocket] backend error:', msg)
        }
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:error', { detail: { message: msg, raw: payload } }))
        }
        break
      }

      case 'sync_state_ack': {
        // Backend acknowledgment that a session bind/attach succeeded.
        // Forwarded to iris:sync_state_ack (carries conversation_id) so chat-view
        // can re-hydrate that conversation's rendered documents (REQ-1).
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('iris:sync_state_ack', { detail: payload }))
        }
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
  // Message types that belong to a conversation thread. Anything here MUST
  // carry a conversation_id or the backend falls back to session_id
  // (iris_gateway :4454 `payload.get("conversation_id") or session_id`).
  const CONVERSATION_SCOPED = new Set([
    'text_message',
    'voice_command_start',
    'get_documents',
    'sync_state',
    // LEARN from thread changes too, so the stored id tracks the active
    // thread instead of going stale (a stale id is what caused the merge).
    'new_conversation',
    'switch_conversation',
  ])
  // Only these may have an id INJECTED when absent — see the note in
  // sendMessage. Everything else must carry its own or surface the gap.
  const SUPPLY_IF_MISSING = new Set(['voice_command_start', 'sync_state'])

  const sendMessage = useCallback((type: string, payload: Record<string, unknown> = {}) => {
    // ── CONVERSATION IDENTITY IS OWNED BY THE SOCKET, NOT BY A COMPONENT ──
    // chat-view.tsx keeps its own activeConversationId in component state and
    // sends that on text_message. This app is a HANDS-FREE WIDGET: ChatView is
    // usually CLOSED and the user is speaking, so that state does not exist for
    // most turns — the id was omitted and the backend fell back to session_id.
    //
    // Kernels are cached BY conversation_id (agent_kernel get_agent_kernel), so
    // a drifting id does not just fragment memory, it CONSTRUCTS A NEW KERNEL
    // mid-turn and orphans the previous one's in-turn state. Measured live in a
    // single turn: session_iris -> conv_1786308248687_l669rs2kj -> conv-1 ->
    // conv_1786321564292_haw9swbjx, four full kernels for one question.
    //
    // Fix, same principle as the web-mode resync: the socket owns the identity.
    // It is localStorage-backed (ACTIVE_ID_KEY), restored on mount, re-synced on
    // reconnect, and survives every component unmount — which is exactly what a
    // widget needs. Two directions:
    //   LEARN  — a caller that DOES supply an id becomes the new current one.
    //   SUPPLY — a caller that omits one gets the durable id injected.
    if (CONVERSATION_SCOPED.has(type)) {
      const supplied = payload.conversation_id
      if (typeof supplied === 'string' && supplied) {
        // LEARN — always safe: the caller knows which thread it is in, so the
        // socket just mirrors it for the paths that cannot know.
        // One writer: the singleton emits and persists.
        _emitActiveConvId(supplied)
      } else if (
        _getActiveConvId() &&
        SUPPLY_IF_MISSING.has(type)
      ) {
        // SUPPLY — NARROWED. An earlier revision injected the stored id into
        // ANY conversation-scoped message that omitted one. That was wrong and
        // caused real damage: when ChatView had no active thread yet, a
        // text_message was silently filed into whatever stale thread was last
        // in localStorage, MERGING separate conversations. Observed live as a
        // spurious `conv-1` kernel appearing between two freshly created
        // threads, and as prompts aggregating into one thread after a refresh.
        //
        // A wrong-but-plausible id is worse than a missing one: a missing id
        // is a visible fallback, a wrong one silently corrupts thread history.
        // So only supply where the caller GENUINELY cannot know the thread —
        // voice turns (ChatView unmounted, which is the normal state for this
        // hands-free widget) and reconnect re-binding. text_message and
        // get_documents always come from a mounted ChatView that knows its own
        // thread; if they arrive without an id that is a bug to surface, not to
        // paper over.
        payload = { ...payload, conversation_id: _getActiveConvId() }
      }
    }

    const seq = seqRef.current++;
    const message = JSON.stringify({ type, payload, seq });

    // ── Tauri path: send via Rust-side WS client ────────────────────────
    if (isTauri) {
      import('@tauri-apps/api/core').then(({ invoke }) => {
        invoke('ws_send', { message }).then((sent) => {
          if (!sent) {
            // Queue if disconnected (Rust side will send on reconnect)
            messageQueueRef.current.push({ type, payload });
          }
        });
      }).catch(() => {
        messageQueueRef.current.push({ type, payload });
      });
      return true;
    }

    // ── Browser path: send via raw WebSocket ─────────────────────────────
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(message)
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

  // ── Capability re-declaration on every (re)connect ───────────────────────
  // The backend's internet-access flag is PROCESS state: it defaults to OFF and
  // a backend restart silently resets it. Nothing on the client changes when
  // that happens, so no new set_web_mode is ever generated — the send queue
  // cannot help either, because it only replays messages produced WHILE
  // disconnected. Observed directly: the toggle read aria-pressed="true" /
  // "Web mode ON" while the backend refused every search as disabled.
  //
  // This lives on the SOCKET, not in the component that owns the toggle. The
  // app is a widget whose panels mount and unmount constantly, so a resync in
  // chat-view only runs when chat happens to be mounted — exactly the fragility
  // that produced the desync. Connection lifecycle is the one trigger that is
  // always present, and localStorage is the one piece of state that survives an
  // unmount. Idempotent: re-declaring the same value is harmless, so this can
  // fire on every reconnect without coordination.
  //
  // Keyed on connectionState rather than the raw socket so any transport that
  // reports "connected" (browser WS today, the Tauri client path) is covered.
  useEffect(() => {
    if (!isConnected) return
    let webMode = false
    try {
      webMode = localStorage.getItem('iris-web-mode') === 'true'
    } catch {
      // Storage unavailable — fall through with false, which matches BOTH the
      // UI default and the backend default, so the two still agree.
    }
    sendMessage('set_web_mode', { enabled: webMode })
  }, [isConnected, sendMessage])

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
  const startVoiceCommand = useCallback((conversationId?: string) => {
    // Optimistic update: show listening animation immediately without waiting for backend
    setVoiceState("listening")
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('iris:voice_state_change', {
        detail: { state: "listening" }
      }))
    }
    const payload: Record<string, unknown> = {}
    const cid = conversationId || currentConversationId
    if (cid) {
      payload.conversation_id = cid
    }
    sendMessage("voice_command_start", payload)
  }, [sendMessage, currentConversationId])

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

  const selectAudioDevice = useCallback(
    (deviceType: "input" | "output", deviceIndex: number, deviceName: string) => {
      sendMessage("select_audio_device", {
        device_type: deviceType,
        device_index: deviceIndex,
        device_name: deviceName,
      })
    },
    [sendMessage]
  )

  // Vision service methods
  const enableVision = useCallback(() => {
    sendMessage("enable_vision", {})
  }, [sendMessage])

  const disableVision = useCallback(() => {
    sendMessage("disable_vision", {})
  }, [sendMessage])

  // Initialize connection
  useEffect(() => {
    _cancelDeferredClose()          // cancel pending delayed-close from a prior HMR
    if (autoConnect) {
      connect()
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
    return cleanup
  }, [autoConnect, connect, cleanup])

  // No frontend-initiated heartbeat.
  // The backend drives the ping/pong cycle (PING_INTERVAL=30s, PONG_TIMEOUT=30s).
  // The frontend responds to backend pings with pong (see case "ping" in handleMessage).
  // Having a competing frontend heartbeat that closes the socket on pong-timeout
  // caused spurious disconnects whenever the backend asyncio event loop was briefly
  // busy (TTS synthesis, model loading, subprocess calls) and the pong reply arrived
  // a few seconds late.  Removing it eliminates that class of disconnect entirely.

  // ── Tauri event listeners ────────────────────────────────────────────
  // When running inside Tauri, the WebSocket connection lives in the Rust
  // process.  We listen for events from the Rust-side WS client.
  useEffect(() => {
    if (!isTauri) return;

    let unlistConnected: (() => void) | null = null;
    let unlistDisconnected: (() => void) | null = null;
    let unlistMessage: (() => void) | null = null;

    (async () => {
      const { listen } = await import('@tauri-apps/api/event');

      unlistConnected = await listen<string>('ws:connected', () => {
        setConnectionState('connected');
        reconnectAttemptsRef.current = 0;
        connectedAtRef.current = Date.now();
        setIsChatTyping(false);
        seqRef.current = 0;

        // Send burst messages on connect (same as browser path)
        sendMessage('request_state', {});
        sendMessage('get_audio_devices', {});
        sendMessage('get_wake_words', {});
        sendMessage('get_available_models', {});

        // Flush the send queue accumulated while disconnected
        const queued = messageQueueRef.current.splice(0);
        for (const msg of queued) {
          sendMessage(msg.type, msg.payload);
        }
        if (process.env.NODE_ENV !== 'production' && queued.length > 0) {
          console.log(`[IRIS WebSocket] Flushed ${queued.length} queued message(s)`);
        }
      });

      unlistDisconnected = await listen<string>('ws:disconnected', () => {
        setConnectionState('disconnected');
        if (process.env.NODE_ENV !== 'production') {
          console.log('[IRIS WebSocket] Rust-side WS disconnected');
        }
      });

      unlistMessage = await listen<string>('ws:message', (event) => {
        try {
          const message = JSON.parse(event.payload);
          handleMessage(message);
        } catch (err) {
          console.error('[IRIS WebSocket] Failed to parse Tauri WS message:', err);
        }
      });
    })();

    return () => {
      unlistConnected?.();
      unlistDisconnected?.();
      unlistMessage?.();
    };
  }, [isTauri, sendMessage]);

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
    cadenceLevel,
    ttsAudioLevel,
    audioPhase,
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
    selectAudioDevice,
    lastError,
    fieldErrors,
    clearFieldError,
    currentConversationId,
    setCurrentConversationId,
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
