"use client"

import { useState, useRef, useCallback, useEffect } from "react"
import { motion } from "framer-motion"

interface CompactSliderProps {
  label: string
  value: number
  min: number
  max: number
  step?: number
  unit?: string
  onChange: (value: number) => void
  glowColor: string
}

export function CompactSlider({
  label,
  value,
  min,
  max,
  step = 1,
  unit = "",
  onChange,
  glowColor,
}: CompactSliderProps) {
  const [isDragging, setIsDragging] = useState(false)
  const trackRef = useRef<HTMLDivElement>(null)

  const currentValue = value ?? min
  const percentage = ((currentValue - min) / (max - min)) * 100

  const handleInteraction = useCallback(
    (clientX: number) => {
      if (!trackRef.current) return
      const rect = trackRef.current.getBoundingClientRect()
      const rawPercentage = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
      const rawValue = min + rawPercentage * (max - min)
      const steppedValue = Math.round(rawValue / step) * step
      const clampedValue = Math.max(min, Math.min(max, steppedValue))
      onChange(Number(clampedValue.toFixed(2)))
    },
    [min, max, step, onChange]
  )

  const handleMouseDown = (e: React.MouseEvent) => {
    e.stopPropagation()
    setIsDragging(true)
    handleInteraction(e.clientX)
  }

  const handleMouseMove = useCallback(
    (e: MouseEvent) => {
      if (isDragging) handleInteraction(e.clientX)
    },
    [isDragging, handleInteraction]
  )

  const handleMouseUp = useCallback(() => setIsDragging(false), [])

  useEffect(() => {
    if (isDragging) {
      window.addEventListener("mousemove", handleMouseMove)
      window.addEventListener("mouseup", handleMouseUp)
      return () => {
        window.removeEventListener("mousemove", handleMouseMove)
        window.removeEventListener("mouseup", handleMouseUp)
      }
    }
  }, [isDragging, handleMouseMove, handleMouseUp])

  const formattedValue = `${Math.round(currentValue)}${unit}`

  return (
    <div className="py-2" onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] uppercase tracking-wider" style={{ color: `${glowColor}cc` }}>
          {label}
        </span>
        <span className="text-[10px] tabular-nums" style={{ color: '#ffffffcc' }}>
          {formattedValue}
        </span>
      </div>
      <div
        ref={trackRef}
        className="relative h-1 bg-white/10 rounded-full cursor-pointer"
        onMouseDown={handleMouseDown}
      >
        <motion.div
          className="absolute left-0 top-0 h-full rounded-full"
          style={{
            width: `${percentage}%`,
            background: glowColor,
            boxShadow: `0 0 6px ${glowColor}`,
          }}
        />
        <motion.div
          className="absolute top-1/2 w-3 h-3 bg-white rounded-full shadow"
          style={{ 
            left: `${percentage}%`,
            transform: 'translate(-50%, -50%)',
          }}
          whileHover={{ scale: 1.2 }}
          whileTap={{ scale: 0.9 }}
        />
      </div>
    </div>
  )
}
