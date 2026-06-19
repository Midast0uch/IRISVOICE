"use client"

import { useNavigation } from "@/contexts/NavigationContext"

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
 *   listening:                cadenceLevel,       breathing (spectral flux from backend)
 *   processing_conversation:  0.3,                breathing (gentle pulse)
 *   processing_tool:          0.2,                breathing (gentle pulse)
 *   speaking:                 ttsAudioLevel,      breathing (RMS from backend TTS)
 *   error:                    0,                  not breathing
 *
 * Client-side fallback (dev mode without backend):
 *   If cadenceLevel is 0 but voiceState is "listening", fall back to
 *   audioLevel (RMS) as a proxy for cadence so the orb still breathes.
 */
export function useCadenceDetection(): CadenceData {
  const { voiceState, cadenceLevel, ttsAudioLevel, audioLevel } = useNavigation()

  switch (voiceState) {
    case "listening": {
      // Fallback: if backend cadence is 0 (not running), use RMS as proxy
      const level = cadenceLevel > 0 ? cadenceLevel : audioLevel * 0.7
      return { breathMode: "D", breathLevel: level, isBreathing: true }
    }
    case "speaking":
      return { breathMode: "D", breathLevel: ttsAudioLevel, isBreathing: true }
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
