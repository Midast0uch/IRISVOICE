"use client"

import { useEffect, useRef, useState } from "react"

/**
 * useClientMicCadence — browser-side spectral flux cadence detection.
 *
 * When `active` is true, requests microphone access and computes a
 * cadence envelope from the audio stream's spectral flux (speech-band
 * energy, 300 Hz – 3 kHz).  The value ranges 0..1 and represents
 * syllable-rate rhythm onsets — same algorithm as CadenceBreathDemo.
 *
 * Designed as a fallback for useCadenceDetection: if the backend isn't
 * sending audio_envelope messages (wrong input device, VAD not
 * engaged, etc.), this hook provides the cadence data that drives
 * OrbCanvas breathing.
 *
 * When `active` transitions to false (or on unmount), the microphone
 * stream and AudioContext are released immediately.
 */
export function useClientMicCadence(active: boolean): number {
  const [cadence, setCadence] = useState(0)

  // Refs so the RAF loop and async setup can read/write without
  // creating new closures every render.
  const activeRef = useRef(false)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const rafRef = useRef(0)
  const cadenceRef = useRef(0)

  // Cadence algorithm state
  const energyHistoryRef = useRef<number[]>(new Array(64).fill(0))
  const cooldownRef = useRef(0)
  const cadenceEnvRef = useRef(0)
  const lastStateUpdateRef = useRef(0)  // throttle state updates to ~5 Hz

  useEffect(() => {
    activeRef.current = active

    // ── Inline cleanup ──────────────────────────────────────────
    const doCleanup = () => {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = 0
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop())
        streamRef.current = null
      }
      if (audioCtxRef.current && audioCtxRef.current.state !== "closed") {
        audioCtxRef.current.close().catch(() => {})
        audioCtxRef.current = null
      }
      sourceRef.current = null
      analyserRef.current = null
      cadenceRef.current = 0
      cadenceEnvRef.current = 0
    }

    // ── Deactivate ──────────────────────────────────────────────
    if (!active) {
      doCleanup()
      setCadence(0)
      return
    }

    let cancelled = false

    async function start() {
      try {
        // 1. Request mic (user may have already granted via the app)
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
        if (cancelled || !activeRef.current) {
          stream.getTracks().forEach((t) => t.stop())
          return
        }
        streamRef.current = stream

        // 2. Create AudioContext (lazy — first access may be ~200 ms)
        const ctx = new AudioContext()
        if (cancelled || !activeRef.current) {
          ctx.close()
          return
        }
        audioCtxRef.current = ctx

        // 3. Wire source → analyser
        const source = ctx.createMediaStreamSource(stream)
        sourceRef.current = source

        const analyser = ctx.createAnalyser()
        analyser.fftSize = 1024
        analyser.smoothingTimeConstant = 0.3
        source.connect(analyser)
        analyserRef.current = analyser

        // 4. Reset algorithm state
        energyHistoryRef.current = new Array(64).fill(0)
        cooldownRef.current = 0
        cadenceEnvRef.current = 0
        lastStateUpdateRef.current = 0

        // 5. Start analysis loop
        const bufLen = analyser.frequencyBinCount
        const freqData = new Float32Array(bufLen)

        function analyse() {
          if (cancelled || !activeRef.current) return

          analyser.getFloatFrequencyData(freqData)

          // ── Spectral flux in speech band (300 Hz – 3 kHz) ──────
          const sampleRate = ctx.sampleRate
          const binHz = sampleRate / analyser.fftSize
          const speechStart = Math.floor(300 / binHz)
          const speechEnd = Math.min(bufLen, Math.floor(3000 / binHz))

          let speechEnergy = 0
          for (let i = speechStart; i < speechEnd; i++) {
            // Convert dBFS to linear
            speechEnergy += Math.pow(10, freqData[i] / 20)
          }
          speechEnergy /= speechEnd - speechStart

          // Adaptive threshold over rolling 64-frame history
          const hist = energyHistoryRef.current
          hist.push(speechEnergy)
          if (hist.length > 64) hist.shift()

          const avg = hist.reduce((a, b) => a + b, 0) / hist.length
          const threshold = avg * 1.2

          cooldownRef.current = Math.max(0, cooldownRef.current - 1)
          const isOnset =
            speechEnergy > threshold &&
            speechEnergy > 0.001 &&
            cooldownRef.current === 0

          if (isOnset) {
            cooldownRef.current = 8 // ~130 ms cooldown at 60 fps
            cadenceEnvRef.current = 1.0
          } else {
            // Exponential decay — the "exhale" of each syllable
            cadenceEnvRef.current *= 0.92
          }

          const val = cadenceEnvRef.current
          cadenceRef.current = val
          // Throttle React state updates to ~5 Hz (200ms) — ref is updated
          // every frame (60fps) for the canvas, but state only needs to be
          // fresh enough for the priority chain in useCadenceDetection.
          const now = performance.now()
          if (now - lastStateUpdateRef.current >= 200) {
            lastStateUpdateRef.current = now
            setCadence(val)
          }

          rafRef.current = requestAnimationFrame(analyse)
        }

        rafRef.current = requestAnimationFrame(analyse)
      } catch {
        // Permission denied, no mic, or error — stays at 0 silently.
        // The caller can detect this and fall through; there is no
        // separate error state because the hook is an optional bonus.
      }
    }

    start()

    return () => {
      cancelled = true
      doCleanup()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active])

  return cadence
}
