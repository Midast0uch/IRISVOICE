"use client"

import React from "react"

interface TextFieldProps {
  id: string
  label: string
  value: string
  placeholder?: string
  onChange?: (value: string) => void
  glowColor: string
  readOnly?: boolean
}

const TextFieldComponent: React.FC<TextFieldProps> = ({
  id,
  label,
  value,
  placeholder,
  onChange,
  glowColor,
  readOnly = false,
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
        readOnly={readOnly}
        onChange={(e) => onChange?.(e.target.value)}
        className={`w-full px-4 py-3 text-[11px] font-bold text-white border rounded-xl focus:outline-none transition-all duration-300 placeholder:text-white/20 ${
          readOnly
            ? 'bg-black/10 border-white/5 cursor-default'
            : 'bg-black/20 border-white/10 focus:ring-2 focus:ring-white/20'
        }`}
        style={{
          caretColor: readOnly ? 'transparent' : glowColor,
        }}
        onFocus={(e) => {
          if (readOnly) return
          e.target.style.borderColor = `${glowColor}66`
          e.target.style.backgroundColor = "rgba(0, 0, 0, 0.3)"
        }}
        onBlur={(e) => {
          if (readOnly) return
          e.target.style.borderColor = "rgba(255, 255, 255, 0.1)"
          e.target.style.backgroundColor = "rgba(0, 0, 0, 0.2)"
        }}
      />
    </div>
  )
}

// Use React.memo for performance optimization as per requirement 12.1
export const TextField = React.memo(TextFieldComponent)
