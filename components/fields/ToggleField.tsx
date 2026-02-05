"use client"

import { FieldWrapper } from "./FieldWrapper"

interface ToggleFieldProps {
  label: string
  value: boolean
  onChange: (value: boolean) => void
  description?: string
}

export function ToggleField({
  label,
  value,
  onChange,
  description,
}: ToggleFieldProps) {
  return (
    <FieldWrapper label={label} description={description}>
      <button
        type="button"
        role="switch"
        aria-checked={value}
        onClick={() => onChange(!value)}
        className={`relative w-12 h-6 rounded-full transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-white/20 ${
          value ? "bg-white/40" : "bg-white/10"
        }`}
      >
        <span
          className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow-md transition-all duration-200 ${
            value ? "left-6 translate-x-0" : "left-0.5"
          }`}
        />
      </button>
    </FieldWrapper>
  )
}
