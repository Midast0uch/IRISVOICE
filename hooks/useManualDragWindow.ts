/**
 * useManualDragWindow
 *
 * Shared hook for dragging the native app window by tracking mouse position deltas
 * and calling Tauri's setPosition() API. Falls back gracefully in browser/dev mode.
 *
 * Supports optional double-click detection (500ms timer) for components that need
 * it (e.g. XurOrb: single-click navigates, double-click activates voice).
 * When `onDoubleClickAction` is not provided, single clicks fire immediately
 * (backward compatible with WheelView and other existing consumers).
 *
 * Used by: XurOrb, WheelView
 */
import { useRef, useCallback, useEffect } from "react"
import { getCurrentWindow, PhysicalPosition } from "@tauri-apps/api/window"

export function useManualDragWindow(
  elementRef: React.RefObject<HTMLElement | null>,
  onClickAction?: () => void,
  onDoubleClickAction?: () => void,
  onDoubleClickFlash?: (show: boolean) => void,
  onPressUpdate?: (pressed: boolean) => void
) {
  const isDragging = useRef(false)
  const dragStartPos = useRef({ x: 0, y: 0 })
  const windowStartPos = useRef({ x: 0, y: 0 })
  const hasDragged = useRef(false)
  const isDraggingThisElement = useRef(false)
  const mouseDownTarget = useRef<EventTarget | null>(null)

  // Double-click detection state (only used when onDoubleClickAction is provided)
  const clickCount = useRef<number>(0)
  const clickTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleMouseDown = useCallback(async (e: React.MouseEvent) => {
    if (e.button !== 0) return

    const currentElement = elementRef.current
    const target = e.target as Node
    if (!(currentElement && currentElement.contains(target))) return

    if (onPressUpdate) onPressUpdate(true)

    isDragging.current = true
    isDraggingThisElement.current = true
    hasDragged.current = false
    mouseDownTarget.current = e.target
    dragStartPos.current = { x: e.screenX, y: e.screenY }

    try {
      const win = getCurrentWindow()
      const pos = await win.outerPosition()
      windowStartPos.current = { x: pos.x, y: pos.y }
    } catch {
      // Tauri not available in browser dev mode — drag still tracks position
    }

    document.body.style.cursor = "grabbing"
    document.body.style.userSelect = "none"
  }, [elementRef, onPressUpdate])

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!isDragging.current || !isDraggingThisElement.current) return

    const dx = e.screenX - dragStartPos.current.x
    const dy = e.screenY - dragStartPos.current.y

    if (Math.abs(dx) > 12 || Math.abs(dy) > 12) {
      hasDragged.current = true
    }

    try {
      const win = getCurrentWindow()
      win.setPosition(new PhysicalPosition(
        windowStartPos.current.x + dx,
        windowStartPos.current.y + dy
      ))
    } catch {
      // Browser dev mode — no-op
    }
  }, [])

  const handleMouseUp = useCallback((e: MouseEvent) => {
    const currentElement = elementRef.current
    const draggingThis = isDraggingThisElement.current
    const didDrag = hasDragged.current
    const downTarget = mouseDownTarget.current

    isDragging.current = false
    document.body.style.cursor = "default"
    document.body.style.userSelect = ""

    // A drag that STARTED on an interactive child still ends with the browser
    // firing that child's click on release. Pressing the Close button and
    // dragging the window would therefore also close the panel. Swallow
    // exactly one click, in the capture phase, after a real drag.
    // Registered only when a drag actually happened (>12px), so ordinary
    // clicks are untouched; `once` means it cannot leak into a later click.
    if (didDrag && typeof document !== "undefined") {
      const swallow = (ev: MouseEvent) => {
        ev.stopPropagation()
        ev.preventDefault()
      }
      document.addEventListener("click", swallow, { capture: true, once: true })
      // Safety net: if no click follows (some browsers skip it when the
      // pointer moved far), drop the listener rather than leaving it armed
      // for the next unrelated click.
      setTimeout(() => {
        document.removeEventListener("click", swallow, { capture: true } as EventListenerOptions)
      }, 300)
    }

    // Treat a non-drag mousedown+up on the element as a click
    if (draggingThis && !didDrag && currentElement && onClickAction) {
      const upTarget = e.target as Node
      const downTargetNode = downTarget as Node
      if (
        currentElement.contains(upTarget) &&
        downTargetNode &&
        currentElement.contains(downTargetNode)
      ) {
        // ── Double-click path (when onDoubleClickAction is provided) ──
        // First click starts a 500ms timer. If a second click arrives
        // within that window, fire onDoubleClickAction instead. If the
        // timer expires, fire onClickAction (single click).
        if (onDoubleClickAction) {
          clickCount.current += 1

          if (clickCount.current === 1) {
            clickTimer.current = setTimeout(() => {
              if (clickCount.current === 1) {
                onClickAction()
              }
              clickCount.current = 0
            }, 500)
          } else if (clickCount.current === 2) {
            if (clickTimer.current) {
              clearTimeout(clickTimer.current)
              clickTimer.current = null
            }
            onDoubleClickAction()
            if (onDoubleClickFlash) {
              onDoubleClickFlash(true)
              setTimeout(() => onDoubleClickFlash(false), 500)
            }
            clickCount.current = 0
          }
        } else {
          // ── Single-click path (backward compatible) ──
          onClickAction()
        }
      }
    }

    if (onPressUpdate) onPressUpdate(false)
    isDraggingThisElement.current = false
    mouseDownTarget.current = null
    hasDragged.current = false
  }, [elementRef, onClickAction, onDoubleClickAction, onDoubleClickFlash, onPressUpdate])

  useEffect(() => {
    window.addEventListener("mousemove", handleMouseMove)
    window.addEventListener("mouseup", handleMouseUp)
    return () => {
      window.removeEventListener("mousemove", handleMouseMove)
      window.removeEventListener("mouseup", handleMouseUp)
      if (clickTimer.current) clearTimeout(clickTimer.current)
    }
  }, [handleMouseMove, handleMouseUp])

  return { handleMouseDown }
}
