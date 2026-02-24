"use client"

import { FieldWrapper } from "./FieldWrapper"

interface ColorFieldProps {
  label: string
  value: string
  onChange: (value: string) => void
  description?: string
}

export function ColorField({
  label,
  value,
  onChange,
  description,
}: ColorFieldProps) {
  const currentValue = value || "#00ff88"

  const isValidHex = (hex: string) => /^#[0-9A-Fa-f]{6}$/.test(hex)

  const handleTextChange = (input: string) => {
    let hex = input.trim()
    if (!hex.startsWith("#")) {
      hex = "#" + hex
    }
    if (isValidHex(hex)) {
      onChange(hex.toLowerCase())
    }
  }

  return (
    <FieldWrapper label={label} description={description}>
      <div className="flex items-center gap-3">
        <div className="relative">
          <input
            type="color"
            value={currentValue}
            onChange={(e) => onChange(e.target.value)}
            onClick={(e) => e.stopPropagation()}
            className="w-10 h-8 rounded bg-transparent border border-white/20 cursor-pointer"
            style={{ padding: 0 }}
          />
          <div
            className="absolute inset-0 rounded pointer-events-none border border-white/10"
            style={{ background: currentValue }}
          />
        </div>
        <input
          type="text"
          value={currentValue}
          onChange={(e) => handleTextChange(e.target.value)}
          onClick={(e) => e.stopPropagation()}
          className="flex-1 px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-white/90 font-mono uppercase focus:outline-none focus:border-white/30 transition-colors"
          maxLength={7}
        />
      </div>
    </FieldWrapper>
  )
}
