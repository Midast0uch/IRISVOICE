
import type { ElementType } from "react";

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

export interface IrisOrbProps {
  isExpanded: boolean;
  onClick: () => void;
  centerLabel: string;
  size: number;
  glowColor: string;
  voiceState: "idle" | "listening" | "processing_conversation" | "processing_tool" | "speaking" | "error";
  wakeFlash: boolean;
  sendMessage: (type: string, payload?: any) => boolean;
  onCallbacksReady?: (callbacks: { handleWakeDetected: () => void; handleNativeAudioResponse: (payload: any) => void }) => void;
}
