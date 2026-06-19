"use client"

/**
 * IrisOrb — thin re-export shim wrapping XurOrb.
 *
 * This preserves the IrisOrbProps interface so app/page.tsx doesn't break.
 * The shim maps old props to XurOrbProps and passes them through.
 *
 * Key mappings:
 * - onCallbacksReady → passed through to XurOrb (wake word bridge)
 * - centerLabel → unused in v2 (glitch labels carry this info), mapped to undefined
 * - wakeFlash → combined with XurOrb's internal doubleClickFlash
 * - uiState → used for wings-open state
 * - size → passed through
 * - glowColor → passed through
 *
 * The shim does NOT intercept clicks — XurOrb handles single/double click
 * internally via useManualDragWindow with the same 500ms timer pattern.
 */

import { XurOrb } from "./XurOrb"
import type { IrisOrbProps } from "./types"

export function IrisOrb(props: IrisOrbProps) {
  const {
    isExpanded,
    onClick,
    onDoubleClick,
    centerLabel,
    size,
    glowColor,
    wakeFlash,
    uiState,
    onCallbacksReady,
  } = props

  return (
    <XurOrb
      isExpanded={isExpanded}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      centerLabel={centerLabel}
      size={size}
      glowColor={glowColor}
      wakeFlash={wakeFlash}
      uiState={uiState}
      onCallbacksReady={onCallbacksReady}
    />
  )
}
