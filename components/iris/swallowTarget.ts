"use client"

import { useSyncExternalStore } from "react"

/**
 * Where the orb should fly TO when it is swallowed (REQ-16 AC2, T19).
 *
 * The swallow is a FLIP between two components that do not know about each
 * other: XurOrb renders near the viewport centre, AmbientCrawlTier renders its
 * logo slot at its own left edge, and the card's width is not knowable until it
 * has laid out. Without a shared point the orb can only shrink and fade where
 * it stands — which is exactly what read as "snapping out of existence" rather
 * than being absorbed.
 *
 * So the tier MEASURES its logo slot and publishes the viewport coordinates
 * here; XurOrb subscribes and animates the delta from its own measured centre.
 * A module-level store rather than context because the two components sit in
 * different subtrees, and the value changes on layout rather than on render —
 * the same shape the socket's conversation-id singleton already uses in this
 * codebase.
 *
 * Coordinates are VIEWPORT px (the centre of the slot), or null when nothing is
 * swallowed. Consumers must treat null as "no target — do not travel".
 */
export interface SwallowPoint {
  x: number
  y: number
}

let _point: SwallowPoint | null = null
const _subs = new Set<() => void>()

/** Publish the slot's centre, or null to clear it. No-ops when unchanged, so a
 *  ResizeObserver firing on every frame cannot storm subscribers. */
export function setSwallowTarget(p: SwallowPoint | null): void {
  if (p === _point) return
  if (p && _point && p.x === _point.x && p.y === _point.y) return
  _point = p
  for (const fn of _subs) fn()
}

function subscribe(fn: () => void): () => void {
  _subs.add(fn)
  return () => {
    _subs.delete(fn)
  }
}

const getSnapshot = (): SwallowPoint | null => _point
/** Server render has no layout, so there is never a target. Must be a stable
 *  reference or useSyncExternalStore loops. */
const getServerSnapshot = (): SwallowPoint | null => null

export function useSwallowTarget(): SwallowPoint | null {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
}
