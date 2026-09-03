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
    <div className="flex flex-col gap-2.5">
      <label
        htmlFor={id}
        className="text-[9px] font-bold uppercase tracking-[0.08em] text-white/30 leading-tight"
      >
        {label}
      </label>
      <div className="flex items-center justify-between gap-3 px-4 py-3 rounded-xl border border-white/10 bg-black/20 transition-all duration-300">
        <div className="flex items-center gap-3">
          <input
            id={id}
            type="color"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            className="w-10 h-8 rounded-lg cursor-pointer border border-white/10 bg-black/40 focus:outline-none focus:ring-2 focus:ring-white/20 transition-all duration-300"
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
          <span className="text-[11px] font-bold font-mono text-white/90 uppercase tracking-wider">
            {value.toUpperCase()}
          </span>
        </div>
        <div
          className="w-4 h-4 rounded-full shadow-inner"
          style={{ backgroundColor: value, border: `1px solid rgba(255,255,255,0.1)` }}
        />
      </div>
    </div>
  )
}

// Use React.memo for performance optimization as per requirement 12.1
export const ColorField = React.memo(ColorFieldComponent)
