
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

export interface ConfirmedMiniNode {
  id: string;
  label: string;
  icon: ElementType | string;
  orbitAngle: number;
  values: Record<string, string | number | boolean>;
}

export type OrbIcon = 'home' | 'close' | 'back'

export interface IrisOrbProps {
  isExpanded: boolean
  onClick: () => void
  onDoubleClick: () => void
  centerLabel: string
  size: number
  glowColor?: string
  wakeFlash: boolean
  uiState?: UILayoutState
  onCallbacksReady?: (callbacks: { handleWakeDetected: () => void; handleNativeAudioResponse: (payload: Record<string, unknown>) => void }) => void
}
