'use client'

import React, { useRef, useState, useCallback, useEffect } from 'react'
import { PrototypeOrbBreathing } from './PrototypeOrbBreathing'

interface CadenceBreathDemoProps {
  glowColor?: string
}

/**
 * Cadence-based breath demo — reads the microphone via Web Audio API,
 * detects speech onsets (syllable boundaries), builds a smooth cadence
 * envelope, and feeds it to the D-model breathing orb.
 *
 * The key difference from volume-based: this follows RHYTHM not loudness.
 * A whispered word still produces a cadence beat. A long hum does not.
 */
export function CadenceBreathDemo({ glowColor = '#00d4ff' }: CadenceBreathDemoProps) {
  const [isListening, setIsListening] = useState(false)
  const [cadenceLevel, setCadenceLevel] = useState(0)
  const [rmsLevel, setRmsLevel] = useState(0)
  const [onsetCount, setOnsetCount] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [hasPermission, setHasPermission] = useState(false)

  const audioCtxRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const rafRef = useRef<number>(0)
  const streamRef = useRef<MediaStream | null>(null)

  // Cadence state (refs so the rAF loop doesn't restart)
  const energyHistoryRef = useRef<number[]>(new Array(64).fill(0))
  const peakThresholdRef = useRef(1.2) // adaptive: multiplier over running avg
  const cooldownRef = useRef(0)       // frames since last onset
  const cadenceEnvRef = useRef(0)     // smoothed envelope output 0..1
  const onsetCountRef = useRef(0)

  // Visualization state
  const [onsetFlash, setOnsetFlash] = useState(0)
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const stopListening = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current)
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop())
      streamRef.current = null
    }
    if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
      audioCtxRef.current.close().catch(() => {})
      audioCtxRef.current = null
    }
    analyserRef.current = null
    setIsListening(false)
    setCadenceLevel(0)
    setRmsLevel(0)
    energyHistoryRef.current.fill(0)
    cadenceEnvRef.current = 0
    cooldownRef.current = 0
  }, [])

  const startListening = useCallback(async () => {
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      setHasPermission(true)

      const ctx = new AudioContext()
      audioCtxRef.current = ctx

      const source = ctx.createMediaStreamSource(stream)
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 1024
      analyser.smoothingTimeConstant = 0.3
      source.connect(analyser)
      analyserRef.current = analyser

      setIsListening(true)
      onsetCountRef.current = 0
      setOnsetCount(0)

      const bufLen = analyser.frequencyBinCount
      const timeData = new Float32Array(bufLen)
      const freqData = new Float32Array(bufLen)

      function analyse() {
        analyser.getFloatTimeDomainData(timeData)
        analyser.getFloatFrequencyData(freqData)

        // ── RMS (raw volume for comparison) ────────────────────────
        let sumSq = 0
        for (let i = 0; i < bufLen; i++) sumSq += timeData[i] * timeData[i]
        const rms = Math.sqrt(sumSq / bufLen)
        const normalizedRms = Math.min(1, rms * 4) // scale up since mic is quiet

        // ── Onset detection (cadence) ──────────────────────────────
        // Method: spectral flux — measure how much the spectrum changes
        // frame-to-frame. Large changes = onset = syllable boundary.

        // 1. Compute spectral energy in speech band (300Hz–3kHz)
        const sampleRate = ctx.sampleRate
        const binHz = sampleRate / (analyser.fftSize)
        const speechBandStart = Math.floor(300 / binHz)
        const speechBandEnd = Math.min(bufLen, Math.floor(3000 / binHz))

        let speechEnergy = 0
        for (let i = speechBandStart; i < speechBandEnd; i++) {
          // Convert dB to linear
          speechEnergy += Math.pow(10, freqData[i] / 20)
        }
        speechEnergy /= (speechBandEnd - speechBandStart)

        // 2. Track energy history for adaptive threshold
        const hist = energyHistoryRef.current
        hist.push(speechEnergy)
        if (hist.length > 64) hist.shift()

        const avgEnergy = hist.reduce((a, b) => a + b, 0) / hist.length
        const threshold = avgEnergy * peakThresholdRef.current

        // 3. Detect onset (energy crosses threshold + cooldown)
        cooldownRef.current = Math.max(0, cooldownRef.current - 1)
        const isOnset = speechEnergy > threshold && speechEnergy > 0.001 && cooldownRef.current === 0

        if (isOnset) {
          onsetCountRef.current += 1
          setOnsetCount(onsetCountRef.current)
          cooldownRef.current = 8 // ~130ms at 60fps cooldown between onsets

          // Flash the onset indicator
          setOnsetFlash(1)
          if (flashTimerRef.current) clearTimeout(flashTimerRef.current)
          flashTimerRef.current = setTimeout(() => setOnsetFlash(0), 150)
        }

        // 4. Build cadence envelope
        //    Attack fast on onset, decay slowly — mimics natural breath
        const targetEnv = isOnset ? 1.0 : 0
        if (isOnset) {
          cadenceEnvRef.current = 1.0 // instant attack
        } else {
          // Slow exponential decay — the "exhale" of each syllable
          cadenceEnvRef.current *= 0.92
        }

        // Gate: if no energy at all, zero the envelope (silence = hold)
        const gatedEnv = rms < 0.003 ? 0 : cadenceEnvRef.current

        setCadenceLevel(gatedEnv)
        setRmsLevel(normalizedRms)

        rafRef.current = requestAnimationFrame(analyse)
      }

      rafRef.current = requestAnimationFrame(analyse)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Microphone access denied')
    }
  }, [])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
      if (streamRef.current) streamRef.current.getTracks().forEach(t => t.stop())
      if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
        audioCtxRef.current.close().catch(() => {})
      }
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current)
    }
  }, [])

  return (
    <div className="flex flex-col items-center gap-6">
      {/* Title + explanation */}
      <div className="flex flex-col items-center gap-2 max-w-xl text-center">
        <h3 className="text-sm font-bold text-white tracking-wide">
          Cadence Detection — Speech Rhythm
        </h3>
        <p className="text-xs text-slate-400 leading-relaxed">
          This reads your microphone and detects syllable onsets in real-time.
          The orb breathes with the <span className="text-white font-semibold">rhythm</span> of
          your speech, not the volume. Try speaking softly — the cadence still beats.
          Try humming — no beats, no breath.
        </p>
      </div>

      {/* Main demo area */}
      <div className="flex items-start gap-8 flex-wrap justify-center">
        {/* Orb + controls */}
        <div className="flex flex-col items-center gap-4">
          {/* Orb */}
          <div
            className="relative flex items-center justify-center"
            style={{ width: 240, height: 240 }}
          >
            <PrototypeOrbBreathing
              glowColor={glowColor}
              breathMode="D"
              breathLevel={cadenceLevel}
              isBreathing={isListening}
            />
          </div>

          {/* Start/Stop button */}
          <button
            onClick={isListening ? stopListening : startListening}
            className="px-5 py-2.5 rounded-lg text-sm font-bold tracking-wide transition-all"
            style={{
              background: isListening ? glowColor : '#1a1a1f',
              color: isListening ? '#0a0a0e' : '#e2e8f0',
              border: `1px solid ${isListening ? glowColor : '#334155'}`,
              boxShadow: isListening ? `0 0 20px ${glowColor}44` : 'none',
            }}
          >
            {isListening ? 'Stop Listening' : 'Start Listening'}
          </button>

          {error && (
            <p className="text-xs text-red-400 text-center max-w-xs">{error}</p>
          )}
        </div>

        {/* Meters panel */}
        <div className="flex flex-col gap-4 w-64">
          {/* Cadence level (the important one) */}
          <MeterBar
            label="Cadence (rhythm)"
            value={cadenceLevel}
            color={glowColor}
            flash={onsetFlash > 0}
          />

          {/* RMS level (for comparison) */}
          <MeterBar
            label="Volume (raw RMS)"
            value={rmsLevel}
            color="#64748b"
            flash={false}
          />

          {/* Onset counter */}
          <div
            className="flex items-center justify-between px-3 py-2 rounded-lg"
            style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}
          >
            <span className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold">
              Syllable Onsets
            </span>
            <span className="text-sm font-mono text-white font-bold">
              {onsetCount}
            </span>
          </div>

          {/* Explanation */}
          <div
            className="px-3 py-2 rounded-lg text-[11px] text-slate-500 leading-relaxed"
            style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid rgba(255,255,255,0.04)' }}
          >
            <span className="text-slate-300 font-semibold">Cadence</span> = speech rhythm beats.
            It spikes on syllable onsets and decays slowly (the "exhale").
            The orb follows this, not the raw volume — so even a whisper produces visible breath.
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Meter bar sub-component ──────────────────────────────────────────
function MeterBar({
  label,
  value,
  color,
  flash,
}: {
  label: string
  value: number
  color: string
  flash: boolean
}) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold">
          {label}
        </span>
        <span className="text-[10px] font-mono text-slate-400">
          {value.toFixed(2)}
        </span>
      </div>
      <div
        className="w-full h-3 rounded-full overflow-hidden"
        style={{ background: '#1a1a1f', border: '1px solid #1f2937' }}
      >
        <div
          style={{
            width: `${Math.min(100, value * 100)}%`,
            height: '100%',
            background: flash
              ? `linear-gradient(90deg, ${color}, white)`
              : `linear-gradient(90deg, ${color}88, ${color})`,
            transition: flash ? 'none' : 'width 0.05s ease-out',
            boxShadow: flash ? `0 0 8px ${color}` : 'none',
          }}
        />
      </div>
    </div>
  )
}
