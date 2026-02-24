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
    <div className="flex flex-col gap-1 py-1">
      <label
        htmlFor={id}
        className="text-[10px] font-medium uppercase tracking-wider text-white/60"
      >
        {label}
      </label>
      <input
        id={id}
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-2 py-1.5 text-[11px] text-white bg-white/5 border border-white/10 rounded focus:outline-none focus:ring-2 focus:ring-white/20 transition-colors duration-200 placeholder:text-white/30"
        style={{
          caretColor: glowColor,
          borderColor: "rgba(255, 255, 255, 0.1)",
        }}
        onFocus={(e) => {
          e.target.style.borderColor = glowColor
        }}
        onBlur={(e) => {
          e.target.style.borderColor = "rgba(255, 255, 255, 0.1)"
        }}
      />
    </div>
  )
}

// Use React.memo for performance optimization as per requirement 12.1
export const TextField = React.memo(TextFieldComponent)
