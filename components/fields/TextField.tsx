"use client"

import { FieldWrapper } from "./FieldWrapper"

interface TextFieldProps {
  label: string
  value: string
  placeholder?: string
  onChange: (value: string) => void
  description?: string
  error?: string
}

export function TextField({
  label,
  value,
  placeholder,
  onChange,
  description,
  error,
}: TextFieldProps) {
  return (
    <FieldWrapper label={label} description={description} error={error}>
      <input
        type="text"
        value={value || ""}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-white/90 placeholder:text-white/30 focus:outline-none focus:border-white/30 transition-colors"
      />
    </FieldWrapper>
  )
}
