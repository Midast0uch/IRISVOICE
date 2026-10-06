'use client'

import { useEffect, useRef, type RefObject } from 'react'

export type CanvasDraw = (ctx: CanvasRenderingContext2D, w: number, h: number, now: number, still: boolean) => void

const DPR_MAX = 2

/**
 * One canvas, one requestAnimationFrame loop, for the edge chrome.
 *  - paused while `document.hidden` (resumes on visibilitychange)
 *  - under prefers-reduced-motion: ONE static frame (`still` = true), no loop;
 *    it is drawn again when `redrawKey` changes or the canvas is resized
 * `draw` may change on every render; the loop always calls the latest one.
 * Size comes from clientWidth/clientHeight (layout size, not the 3D-tilted
 * bounding box).
 */
export function useCanvasLoop(canvasRef: RefObject<HTMLCanvasElement | null>, draw: CanvasDraw, redrawKey: string) {
  const drawRef = useRef(draw)
  drawRef.current = draw

  useEffect(() => {
    const cv = canvasRef.current
    if (!cv) return
    const ctx = cv.getContext('2d')
    if (!ctx) return
    const still = typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const dpr = Math.min(DPR_MAX, window.devicePixelRatio || 1)

    const paint = (now: number) => {
      const w = cv.clientWidth, h = cv.clientHeight
      if (w < 1 || h < 1) return
      const pw = Math.round(w * dpr), ph = Math.round(h * dpr)
      if (cv.width !== pw || cv.height !== ph) { cv.width = pw; cv.height = ph }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      drawRef.current(ctx, w, h, now, still)
    }

    if (still) {
      paint(0)
      if (typeof ResizeObserver === 'undefined') return
      const ro = new ResizeObserver(() => paint(0))
      ro.observe(cv)
      return () => ro.disconnect()
    }

    let raf = 0
    const frame = (now: number) => {
      raf = 0
      if (document.hidden) return
      paint(now)
      raf = requestAnimationFrame(frame)
    }
    const start = () => { if (!raf && !document.hidden) raf = requestAnimationFrame(frame) }
    const onVisibility = () => {
      if (document.hidden) { if (raf) cancelAnimationFrame(raf); raf = 0 } else start()
    }
    document.addEventListener('visibilitychange', onVisibility)
    start()
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [canvasRef, redrawKey])
}
