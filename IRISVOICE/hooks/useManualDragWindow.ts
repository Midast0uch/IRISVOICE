/**
 * useManualDragWindow
 *
 * Shared hook for dragging the native app window by tracking mouse position deltas
 * and calling Tauri's setPosition() API. Falls back gracefully in browser/dev mode.
 *
 * Used by: IrisOrb, WheelView
 */
import { useRef, useCallback, useEffect } from "react"
import { getCurrentWindow, PhysicalPosition } from "@tauri-apps/api/window"

export function useManualDragWindow(
  elementRef: React.RefObject<HTMLElement | null>,
  onClickAction?: () => void
) {
  const isDragging = useRef(false)
  const dragStartPos = useRef({ x: 0, y: 0 })
  const windowStartPos = useRef({ x: 0, y: 0 })
  const hasDragged = useRef(false)
  const isDraggingThisElement = useRef(false)
  const mouseDownTarget = useRef<EventTarget | null>(null)

  const handleMouseDown = useCallback(async (e: React.MouseEvent) => {
    if (e.button !== 0) return

    const currentElement = elementRef.current
    const target = e.target as Node
    if (!(currentElement && currentElement.contains(target))) return

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
  }, [elementRef])

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
    isDraggingThisElement.current = false
    mouseDownTarget.current = null
    hasDragged.current = false
    document.body.style.cursor = "default"
    document.body.style.userSelect = ""

    // Treat a non-drag mousedown+up on the element as a click
    if (draggingThis && !didDrag && currentElement && onClickAction) {
      const upTarget = e.target as Node
      const downTargetNode = downTarget as Node
      if (
        currentElement.contains(upTarget) &&
        downTargetNode &&
        currentElement.contains(downTargetNode)
      ) {
        onClickAction()
      }
    }
  }, [elementRef, onClickAction])

  useEffect(() => {
    window.addEventListener("mousemove", handleMouseMove)
    window.addEventListener("mouseup", handleMouseUp)
    return () => {
      window.removeEventListener("mousemove", handleMouseMove)
      window.removeEventListener("mouseup", handleMouseUp)
    }
  }, [handleMouseMove, handleMouseUp])

  return { handleMouseDown }
}
