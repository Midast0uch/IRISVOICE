"use client"

import { useState, useRef, useCallback, useEffect } from "react"
import { FieldWrapper } from "./FieldWrapper"
import { useBrandColor } from "@/contexts/BrandColorContext"

interface SliderFieldProps {
  label: string
  value: number
  min: number
  max: number
  step?: number
  unit?: string
  onChange: (value: number) => void
  description?: string
  showValue?: "tooltip" | "beside" | "none"
}

export function SliderField({
  label,
  value,
  min,
  max,
  step = 1,
  unit = "",
  onChange,
  description,
  showValue = "beside",
}: SliderFieldProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [showTooltip, setShowTooltip] = useState(false)
  const trackRef = useRef<HTMLDivElement>(null)
  const { getHSLString } = useBrandColor()
  const glowColor = getHSLString()

  const currentValue = value ?? min
  const percentage = ((currentValue - min) / (max - min)) * 100

  const handleInteraction = useCallback(
    (clientX: number, isFineControl: boolean) => {
      if (!trackRef.current) return

      const rect = trackRef.current.getBoundingClientRect()
      const rawPercentage = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
      const rawValue = min + rawPercentage * (max - min)

      // Apply step and fine control
      const actualStep = isFineControl ? step / 10 : step
      const steppedValue = Math.round(rawValue / actualStep) * actualStep
      const clampedValue = Math.max(min, Math.min(max, steppedValue))

      onChange(Number(clampedValue.toFixed(2)))
    },
    [min, max, step, onChange]
  )

  const handleMouseDown = (e: React.MouseEvent) => {
    e.stopPropagation()
    setIsDragging(true)
    handleInteraction(e.clientX, e.shiftKey)
  }

  const handleMouseMove = useCallback(
    (e: MouseEvent) => {
      if (isDragging) {
        handleInteraction(e.clientX, e.shiftKey)
      }
    },
    [isDragging, handleInteraction]
  )

  const handleMouseUp = useCallback(() => {
    setIsDragging(false)
  }, [])

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
    <FieldWrapper label={label} description={description}>
      <div className="flex items-center gap-3">
        <div
          ref={trackRef}
          className="relative flex-1 h-1 bg-white/10 rounded-full cursor-pointer"
          onMouseDown={handleMouseDown}
          onMouseEnter={() => setShowTooltip(true)}
          onMouseLeave={() => !isDragging && setShowTooltip(false)}
        >
          {/* Fill */}
          <div
            className="absolute left-0 top-0 h-full rounded-full transition-all duration-75"
            style={{
              width: `${percentage}%`,
              background: glowColor,
              boxShadow: `0 0 8px ${glowColor}`,
            }}
          />

          {/* Thumb */}
          <div
            className="absolute top-1/2 w-4 h-4 bg-white rounded-full shadow-lg transform -translate-y-1/2 -translate-x-1/2 transition-transform hover:scale-110"
            style={{ left: `${percentage}%` }}
          />

          {/* Tooltip */}
          {showTooltip && showValue === "tooltip" && (
            <div
              className="absolute -top-8 px-2 py-1 bg-white/10 rounded text-xs text-white transform -translate-x-1/2"
              style={{ left: `${percentage}%` }}
            >
              {formattedValue}
            </div>
          )}
        </div>

        {showValue === "beside" && (
          <span className="text-xs text-white/60 w-12 text-right tabular-nums">
            {formattedValue}
          </span>
        )}
      </div>
    </FieldWrapper>
  )
}
