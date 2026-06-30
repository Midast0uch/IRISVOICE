"use client"

import { useNavigation } from "@/contexts/NavigationContext"
import { useClientMicCadence } from "./useClientMicCadence"

export interface CadenceData {
  /** Always "D" (the winner breathing mode) */
  breathMode: string
  /** 0-1 audio level driving the orb's breath */
  breathLevel: number
  /** Is the orb actively breathing (voice active) */
  isBreathing: boolean
}

/**
 * useCadenceDetection — maps voiceState → breathMode/breathLevel/isBreathing.
 *
 * XurOrb uses this hook to get the right cadence parameters for OrbCanvas
 * based on the current voice state. Cadence data is NOT passed as props —
 * XurOrb reads it internally via this hook, which pulls voiceState,
 * cadenceLevel, and ttsAudioLevel from useNavigation().
 *
 * Voice state → cadence mapping:
 *   idle:                     breathLevel 0,     not breathing
 *   listening:                cadenceLevel,       breathing (backend spectral flux)
 *                             or audioLevel,      breathing (backend RMS fallback)
 *                             or clientCadence,   breathing (browser mic fallback)
 *   processing_conversation:  0.3,                breathing (gentle pulse)
 *   processing_tool:          0.2,                breathing (gentle pulse)
 *   speaking:                 ttsAudioLevel,      breathing (RMS from backend TTS)
 *   error:                    0,                  not breathing
 *
 * Priority chain for listening state:
 *   1. Backend cadence (spectral flux from audio_envelope)
 *   2. Backend RMS (audioLevel fallback)
 *   3. Client-side mic cadence (useClientMicCadence — browser getUserMedia)
 *
 * This ensures the orb always breathes when listening, even if the
 * backend input device is wrong or VAD isn't engaged.  The client-side
 * fallback mirrors CadenceBreathDemo's spectral flux algorithm.
 */
export function useCadenceDetection(): CadenceData {
  const { voiceState, cadenceLevel, ttsAudioLevel, audioLevel } = useNavigation()

  // Client-side mic cadence: starts when listening begins, stops when it ends.
  // Provides a fallback if the backend isn't sending audio_envelope messages.
  const isListening = voiceState === "listening"
  const clientCadence = useClientMicCadence(isListening)

  switch (voiceState) {
    case "listening": {
      // STT / user speaking: Mode C = big dramatic halo + shell expansion.
      // Matches the orb-preview demo's "voice breath glow" Option C.
      // Priority: backend cadence → backend RMS proxy → client mic cadence
      const level = cadenceLevel > 0 ? cadenceLevel
                   : audioLevel > 0 ? audioLevel * 0.7
                   : clientCadence
      return { breathMode: "C", breathLevel: level, isBreathing: true }
    }
    case "speaking": {
      // TTS / agent responding: Mode D = subtle contained pulse + faint halo.
      // Matches the orb-preview demo's winning Option D.
      const speechLevel = cadenceLevel > 0 ? cadenceLevel : audioLevel
      return { breathMode: "D", breathLevel: speechLevel, isBreathing: true }
    }
    case "processing_conversation":
      return { breathMode: "D", breathLevel: 0.3, isBreathing: true }
    case "processing_tool":
      return { breathMode: "D", breathLevel: 0.2, isBreathing: true }
    case "error":
    case "idle":
    default:
      return { breathMode: "D", breathLevel: 0, isBreathing: false }
  }
}
