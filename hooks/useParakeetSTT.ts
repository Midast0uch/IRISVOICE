/**
 * useParakeetSTT — React hook for web-browser ASR via the backend Parakeet
 * service (NVIDIA Parakeet TDT 0.6B v3, local RTX 3070).
 *
 * == DEPRECATED ==
 *   The primary voice command flow now uses VoiceCommandHandler with
 *   in-process ParakeetTranscriber (no separate HTTP service needed).
 *   This hook is retained for potential direct browser→parakeet streaming
 *   in the future, but is NOT used in the current voice command pipeline.
 *
 * == Modes ==
 *   web   – getUserMedia → AudioContext → ScriptProcessorNode → 16 kHz Int16
 *           PCM → WebSocket to the Parakeet service (ws://localhost:8765/ws/stream).
 *   tauri – (stub) delegates to the Tauri backend audio engine via the IRIS
 *           gateway; the backend owns the mic and streams to Parakeet directly.
 *
 * == Usage ==
 *   ```tsx
 *   const { isListening, startListening, stopListening, interimText, error } = useParakeetSTT({
 *     onResult: (text) => console.log("Final:", text),
 *     parakeetServiceUrl: "ws://localhost:8765/ws/stream",
 *   })
 *   ```
 *
 * == Protocol (web mode) ==
 *   1. Opens a WebSocket to the Parakeet service.
 *   2. Receives {"type":"ready","sample_rate":16000}.
 *   3. Streams binary Int16 PCM chunks (16000 Hz, mono).
 *   4. The server may reply with {"type":"partial","text":"...","confidence":N}.
 *   5. To stop: sends {"type":"stop"} as a JSON text frame.
 *   6. Server flushes the TDT buffer and replies {"type":"final","text":"...","confidence":N}.
 *   7. Hook closes the WS and cleans up audio resources.
 *
 * == Error handling ==
 *   - Media permission denied → error state
 *   - WebSocket connection failure → error state
 *   - WebSocket reconnection not supported (stateless: user clicks stop, no reconnect)
 *   - All async failures caught and surfaced through `error` state
 *
 * @module useParakeetSTT
 */

import { useCallback, useEffect, useRef, useState } from "react"

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_WS_URL = "ws://localhost:8765/ws/stream"
const TARGET_SAMPLE_RATE = 16000
const SCRIPT_PROCESSOR_BUFFER = 4096
// Grace period after receiving final before forceful teardown (ms).
const FINAL_TIMEOUT_MS = 5000
// No-op fallback for environments without AudioContext.
const AudioCtx: typeof AudioContext =
  typeof window !== "undefined"
    ? (window.AudioContext ?? (window as any).webkitAudioContext)
    : null!

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface UseParakeetSTTOptions {
  /** WebSocket URL of the backend Parakeet ASR service. */
  parakeetServiceUrl?: string
  /** Runtime mode.  "auto" (default) detects Tauri via window.__TAURI__. */
  mode?: "auto" | "tauri" | "web"
  /** Fires on every partial (interim) transcription from the server. */
  onInterim?: (text: string) => void
  /** Fires on the final transcription (speech segment ended). */
  onResult?: (text: string, confidence?: number) => void
  /** Fires on any unrecoverable error. */
  onError?: (err: string) => void
}

export interface UseParakeetSTTReturn {
  /** True while the mic is live and audio is being streamed. */
  isListening: boolean
  /** True if the current environment supports this mode. */
  isSupported: boolean
  /** Start capturing audio and streaming to the Parakeet service. */
  startListening: () => Promise<void>
  /** Stop capturing, flush the Parakeet buffer, and return the final text. */
  stopListening: () => Promise<string | null>
  /** Latest partial (interim) transcription while listening. */
  interimText: string
  /** Final transcription from the most recent listening session. */
  finalText: string
  /** Human-readable error message, or null when healthy. */
  error: string | null
  /** Reset error state. */
  clearError: () => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Downsample a Float32 buffer from `srcRate` to `TARGET_SAMPLE_RATE` using
 * linear interpolation, then convert to Int16 PCM bytes.
 */
function downsampleAndConvert(
  buffer: Float32Array,
  srcRate: number,
): ArrayBuffer {
  const ratio = srcRate / TARGET_SAMPLE_RATE
  const outLen = Math.max(1, Math.floor(buffer.length / ratio))
  const out = new Int16Array(outLen)

  for (let i = 0; i < outLen; i++) {
    const srcIdx = i * ratio
    const lo = Math.floor(srcIdx)
    const hi = Math.min(lo + 1, buffer.length - 1)
    const frac = srcIdx - lo
    const sample =
      buffer[lo] * (1 - frac) + buffer[hi] * frac
    // Clamp to [-1, 1] then scale to Int16 range
    const clamped = Math.max(-1, Math.min(1, sample))
    out[i] = clamped * 0x7fff
  }

  return out.buffer
}

/**
 * Check whether the browser supports Web Audio API microphone access.
 */
function checkMicSupport(): boolean {
  if (typeof window === "undefined") return false
  if (!navigator.mediaDevices?.getUserMedia) return false
  if (!AudioCtx) return false
  return true
}

/**
 * Check if running inside a Tauri webview.
 */
function isTauri(): boolean {
  return typeof window !== "undefined" && (window as any).__TAURI__ !== undefined
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useParakeetSTT(options: UseParakeetSTTOptions = {}): UseParakeetSTTReturn {
  const {
    parakeetServiceUrl = DEFAULT_WS_URL,
    mode: modeOpt = "auto",
    onInterim,
    onResult,
    onError,
  } = options

  const mode = modeOpt === "auto" ? (isTauri() ? "tauri" : "web") : modeOpt

  // ---- State ---------------------------------------------------------------
  const [isListening, setIsListening] = useState(false)
  const [interimText, setInterimText] = useState("")
  const [finalText, setFinalText] = useState("")
  const [error, setError] = useState<string | null>(null)

  // ---- Refs (stable across renders) ----------------------------------------
  const wsRef = useRef<WebSocket | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const finalTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const finalResolver = useRef<((text: string | null) => void) | null>(null)
  // Flag so we don't process audio frames after stop has been signalled.
  const stoppedRef = useRef(false)

  const isSupported = mode === "web" ? checkMicSupport() : mode === "tauri"

  // ---- Cleanup helper ------------------------------------------------------
  const cleanup = useCallback(() => {
    // Stop processor
    if (processorRef.current) {
      processorRef.current.disconnect()
      processorRef.current = null
    }
    if (sourceRef.current) {
      sourceRef.current.disconnect()
      sourceRef.current = null
    }
    if (audioCtxRef.current && audioCtxRef.current.state !== "closed") {
      audioCtxRef.current.close().catch(() => {})
      audioCtxRef.current = null
    }
    // Stop all tracks
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
    // Close WS
    if (wsRef.current) {
      wsRef.current.onclose = null
      wsRef.current.onerror = null
      wsRef.current.onmessage = null
      if (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING) {
        wsRef.current.close()
      }
      wsRef.current = null
    }
    if (finalTimeoutRef.current) {
      clearTimeout(finalTimeoutRef.current)
      finalTimeoutRef.current = null
    }
  }, [])

  // ---- Cleanup on unmount --------------------------------------------------
  useEffect(() => cleanup, [cleanup])

  // ---- startListening ------------------------------------------------------
  const startListening = useCallback(async () => {
    if (isListening) return
    stoppedRef.current = false
    setError(null)
    setInterimText("")
    setFinalText("")

    if (mode === "tauri") {
      // Tauri mode: the backend owns the mic.  Use Tauri invoke API to start
      // the backend's Parakeet streaming pipeline, or fall back to IRIS WS
      // voice_result messages (already wired in useIRISWebSocket.ts).
      //
      // TODO(@parakeet): wire Tauri invoke command here once the Rust backend
      // exposes `parakeet_start_streaming` / `parakeet_stop_streaming`.
      // For now, report that Tauri mic capture is mediated by the backend.
      setError("Tauri mic capture is managed by the backend audio engine.")
      return
    }

    // ---- Web mode ----------------------------------------------------------
    if (!checkMicSupport()) {
      setError("Your browser does not support microphone access.")
      onError?.("getUserMedia not available")
      return
    }

    try {
      // 1. Get user mic
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: { ideal: TARGET_SAMPLE_RATE },
          channelCount: { ideal: 1 },
          echoCancellation: true,
          noiseSuppression: true,
        },
      })
      streamRef.current = stream

      // 2. Create AudioContext
      const ctx = new AudioCtx()
      audioCtxRef.current = ctx
      const source = ctx.createMediaStreamSource(stream)
      sourceRef.current = source

      // 3. ScriptProcessorNode for raw PCM access
      const processor = ctx.createScriptProcessor(
        SCRIPT_PROCESSOR_BUFFER,
        1, /* input channels */
        1, /* output channels */
      )
      processorRef.current = processor

      // 4. Connect WebSocket
      const ws = new WebSocket(parakeetServiceUrl)
      wsRef.current = ws
      ws.binaryType = "arraybuffer"

      // Await WS open and "ready" message
      await new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error("WebSocket connection timeout")), 5000)

        ws.onopen = () => {
          // Wait for the server's "ready" message
        }

        ws.onmessage = (evt) => {
          try {
            const msg = JSON.parse(evt.data as string)
            if (msg.type === "ready") {
              clearTimeout(timeout)
              resolve()
            } else if (msg.type === "error") {
              clearTimeout(timeout)
              reject(new Error(msg.error ?? "Parakeet service error"))
            }
          } catch {
            // Not JSON — ignore non-JSON frames during handshake
          }
        }

        ws.onerror = () => {
          clearTimeout(timeout)
          reject(new Error("WebSocket connection failed"))
        }
      })

      // 5. Wire up audio processor → WS streaming
      processor.onaudioprocess = (evt: AudioProcessingEvent) => {
        if (stoppedRef.current) return
        if (ws.readyState !== WebSocket.OPEN) return

        const input = evt.inputBuffer.getChannelData(0)
        const pcm = downsampleAndConvert(input, ctx.sampleRate)
        ws.send(pcm)
      }

      source.connect(processor)
      processor.connect(ctx.destination) // required by spec (output goes nowhere)

      // 6. Wire up WS incoming → partial/final results
      ws.onmessage = (evt: MessageEvent) => {
        try {
          const msg = JSON.parse(evt.data as string)
          if (msg.type === "partial") {
            const t: string = msg.text ?? ""
            setInterimText(t)
            onInterim?.(t)
          } else if (msg.type === "final") {
            const t: string = msg.text ?? ""
            const c: number | undefined = msg.confidence ?? undefined
            setFinalText(t)
            setInterimText("")
            onResult?.(t, c)
            resolveFinal(t)
          } else if (msg.type === "error") {
            setError(msg.error ?? "Parakeet error")
            onError?.(msg.error ?? "Parakeet error")
            resolveFinal(null)
          }
        } catch {
          // Non-JSON frame — ignore
        }
      }

      ws.onerror = () => {
        if (!stoppedRef.current) {
          setError("WebSocket error during streaming")
          onError?.("WebSocket error")
        }
      }

      ws.onclose = () => {
        if (!stoppedRef.current) {
          // Unexpected close — the server's finally may have sent final
          // before closing.  We don't have it because onmessage fires
          // before onclose in compliant browsers.
        }
      }

      setIsListening(true)
    } catch (err: any) {
      const msg = err?.message ?? "Unknown error starting Parakeet STT"
      setError(msg)
      onError?.(msg)
      cleanup()
    }
  }, [isListening, mode, parakeetServiceUrl, onInterim, onResult, onError, cleanup])

  // Internal: resolve the stop promise (stored in finalResolver).
  function resolveFinal(text: string | null) {
    finalResolver.current?.(text)
    finalResolver.current = null
    if (finalTimeoutRef.current) {
      clearTimeout(finalTimeoutRef.current)
      finalTimeoutRef.current = null
    }
  }

  // ---- stopListening -------------------------------------------------------
  const stopListening = useCallback(async (): Promise<string | null> => {
    if (!isListening) return finalText

    stoppedRef.current = true

    if (mode === "tauri") {
      // Tauri mode: no-op for now (backend manages streaming).
      setIsListening(false)
      return null
    }

    return new Promise<string | null>((resolve) => {
      finalResolver.current = resolve

      // Safety timeout — force resolve if server doesn't respond.
      finalTimeoutRef.current = setTimeout(() => {
        resolveFinal(null)
      }, FINAL_TIMEOUT_MS)

      // Send stop signal to the Parakeet service so it flushes the TDT buffer
      // and returns the final transcription while the WS is still open.
      try {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: "stop" }))
        }
      } catch {
        // WS already closed — resolve immediately.
        resolveFinal(null)
      }

      setIsListening(false)
    }).finally(() => {
      // Full cleanup after final received or timeout.
      cleanup()
    })
  }, [isListening, mode, finalText, cleanup])

  // ---- clearError ----------------------------------------------------------
  const clearError = useCallback(() => setError(null), [])

  // ---- Teardown on error ---------------------------------------------------
  useEffect(() => {
    if (error) {
      cleanup()
      setIsListening(false)
    }
  }, [error, cleanup])

  return {
    isListening,
    isSupported,
    startListening,
    stopListening,
    interimText,
    finalText,
    error,
    clearError,
  }
}
