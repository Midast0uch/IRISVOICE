import type { ElementType } from "react";
import type { UILayoutState } from "@/hooks/useUILayoutState";

export interface InputField {
  id: string;
  label: string;
  type: "text" | "slider" | "dropdown" | "toggle" | "color";
  placeholder?: string;
  options?: string[];
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  defaultValue?: string | number | boolean;
}

export type OrbIcon = 'home' | 'close' | 'back'

export interface IrisOrbProps {
  isExpanded: boolean
  onClick: () => void
  onDoubleClick: () => void
  onChatClick?: () => void
  centerLabel: string
  size: number
  glowColor?: string
  uiState?: UILayoutState
}

/**
 * XurOrbProps — props for the XurOrb component (IrisOrb v2).
 *
 * Cadence data (breathMode, breathLevel, isBreathing) is NOT passed as props.
 * XurOrb reads it internally via the useCadenceDetection() hook, which pulls
 * voiceState, cadenceLevel, and ttsAudioLevel from useNavigation().
 *
 * Wake word + native audio callbacks were removed (PR 2026-06-29): the
 * backend now fires `voice_command_start` directly via WebSocket, so the
 * frontend no longer needs a bridge callback.
 */
export interface XurOrbProps {
  isExpanded: boolean
  onClick: () => void
  onDoubleClick: () => void
  /** Kept for shim compat, unused in XurOrb (glitch labels carry this info) */
  centerLabel?: string
  size?: number
  glowColor?: string
  uiState?: UILayoutState
  onCategorySelect?: (categoryId: string) => void
  onMenuClick?: () => void
  onChatClick?: () => void
}

