"use client"

import React from "react"

interface TextFieldProps {
  id: string
  label: string
  value: string
  placeholder?: string
  onChange: (value: string) => void
  glowColor: string
}

const TextFieldComponent: React.FC<TextFieldProps> = ({
  id,
  label,
  value,
  placeholder,
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
      <input
        id={id}
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-4 py-3 text-[11px] font-bold text-white bg-black/20 border border-white/10 rounded-xl focus:outline-none focus:ring-2 focus:ring-white/20 transition-all duration-300 placeholder:text-white/20"
        style={{
          caretColor: glowColor,
        }}
        onFocus={(e) => {
          e.target.style.borderColor = `${glowColor}66`
          e.target.style.backgroundColor = "rgba(0, 0, 0, 0.3)"
        }}
        onBlur={(e) => {
          e.target.style.borderColor = "rgba(255, 255, 255, 0.1)"
          e.target.style.backgroundColor = "rgba(0, 0, 0, 0.2)"
        }}
      />
    </div>
  )
}

// Use React.memo for performance optimization as per requirement 12.1
export const TextField = React.memo(TextFieldComponent)
