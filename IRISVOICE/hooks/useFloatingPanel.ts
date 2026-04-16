'use client'

import { useState, useCallback, useEffect } from 'react'

interface PanelGeometry {
  x: number
  y: number
  width: number
  height: number
}

const STORAGE_KEY = 'iris-floating-terminal'
const MIN_W = 400
const MIN_H = 300
const DEFAULT: PanelGeometry = { x: -1, y: -1, width: 700, height: 450 }

function loadGeometry(): PanelGeometry {
  if (typeof window === 'undefined') return DEFAULT
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return { ...DEFAULT, ...JSON.parse(raw) }
  } catch { /* ignore */ }
  return DEFAULT
}

function saveGeometry(g: PanelGeometry) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(g)) } catch { /* ignore */ }
}

export function useFloatingPanel() {
  const [geo, setGeo] = useState<PanelGeometry>(loadGeometry)

  // Resolve default position (bottom-right) on mount when x/y are -1
  useEffect(() => {
    if (geo.x === -1 || geo.y === -1) {
      const x = window.innerWidth - geo.width - 24
      const y = window.innerHeight - geo.height - 24
      const resolved = { ...geo, x: Math.max(0, x), y: Math.max(0, y) }
      setGeo(resolved)
      saveGeometry(resolved)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const onDragEnd = useCallback((_e: unknown, info: { point: { x: number; y: number } }) => {
    setGeo(prev => {
      const next = { ...prev, x: info.point.x, y: info.point.y }
      saveGeometry(next)
      return next
    })
  }, [])

  const onResize = useCallback((deltaW: number, deltaH: number) => {
    setGeo(prev => {
      const maxW = window.innerWidth * 0.9
      const maxH = window.innerHeight * 0.8
      const width = Math.min(maxW, Math.max(MIN_W, prev.width + deltaW))
      const height = Math.min(maxH, Math.max(MIN_H, prev.height + deltaH))
      const next = { ...prev, width, height }
      saveGeometry(next)
      return next
    })
  }, [])

  return { position: { x: geo.x, y: geo.y }, size: { width: geo.width, height: geo.height }, onDragEnd, onResize }
}
