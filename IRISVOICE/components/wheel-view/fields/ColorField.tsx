"use client"

import React from "react"

interface ColorFieldProps {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  glowColor: string
}

const ColorFieldComponent: React.FC<ColorFieldProps> = ({
  id,
  label,
  value,
  onChange,
  glowColor,
}) => {
  return (
    <div className="flex flex-col gap-1 py-1">
      <label
        htmlFor={id}
        className="text-[10px] font-medium uppercase tracking-wider text-white/60"
      >
        {label}
      </label>
      <div className="flex items-center gap-2">
        <input
          id={id}
          type="color"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-10 h-8 rounded cursor-pointer border border-white/10 bg-white/5 focus:outline-none focus:ring-2 focus:ring-white/20 transition-colors duration-200"
          style={{
            borderColor: "rgba(255, 255, 255, 0.1)",
          }}
          onFocus={(e) => {
            e.target.style.borderColor = glowColor
          }}
          onBlur={(e) => {
            e.target.style.borderColor = "rgba(255, 255, 255, 0.1)"
          }}
        />
        <span className="text-[11px] font-mono text-white/80 uppercase">
          {value.toUpperCase()}
        </span>
      </div>
    </div>
  )
}

// Use React.memo for performance optimization as per requirement 12.1
export const ColorField = React.memo(ColorFieldComponent)
