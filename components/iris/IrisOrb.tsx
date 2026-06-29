"use client"

/**
 * IrisOrb — thin re-export shim wrapping XurOrb.
 *
 * This preserves the IrisOrbProps interface so app/page.tsx doesn't break.
 * The shim maps old props to XurOrbProps and passes them through.
 *
 * Key mappings:
 * - centerLabel → unused in v2 (glitch labels carry this info), passed for compat
 * - uiState → used for wings-open state
 * - size → passed through
 * - glowColor → passed through
 *
 * The shim does NOT intercept clicks — XurOrb handles single/double click
 * internally via useManualDragWindow with the same 500ms timer pattern.
 *
 * Removed (PR 2026-06-29): onCallbacksReady + wakeFlash — wake word is
 * now driven by the backend's WebSocket broadcast, no frontend bridge needed.
 */

import { XurOrb } from "./XurOrb"
import type { IrisOrbProps } from "./types"

export function IrisOrb(props: IrisOrbProps) {
  const {
    isExpanded,
    onClick,
    onDoubleClick,
    onChatClick,
    centerLabel,
    size,
    glowColor,
    uiState,
  } = props

  return (
    <XurOrb
      isExpanded={isExpanded}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      onChatClick={onChatClick}
      centerLabel={centerLabel}
      size={size}
      glowColor={glowColor}
      uiState={uiState}
    />
  )
}
