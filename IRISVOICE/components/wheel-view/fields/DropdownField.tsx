"use client"

import React, { useEffect, useState, useRef } from "react"

interface DropdownFieldProps {
  id: string
  label: string
  value: string
  options: string[]
  loadOptions?: () => Promise<{ label: string; value: string }[]>
  onChange: (value: string) => void
  glowColor: string
}

const DropdownFieldComponent: React.FC<DropdownFieldProps> = ({
  id,
  label,
  value,
  options,
  loadOptions,
  onChange,
  glowColor,
}) => {
  const [dynamicOptions, setDynamicOptions] = useState<
    { label: string; value: string }[]
  >([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const loadedRef = useRef(false)

  useEffect(() => {
    // Only load options if loadOptions is provided and we haven't loaded yet (caching)
    if (loadOptions && !loadedRef.current) {
      loadedRef.current = true
      setIsLoading(true)
      setError(null)

      loadOptions()
        .then((loadedOptions) => {
          setDynamicOptions(loadedOptions)
          setIsLoading(false)
        })
        .catch((err) => {
          console.error(`[DropdownField] Failed to load options for ${id}:`, err)
          setError("Failed to load options")
          setDynamicOptions([]) // Fallback to empty array
          setIsLoading(false)
        })
    }
  }, [loadOptions, id])

  // Determine which options to use
  const finalOptions = loadOptions ? dynamicOptions : options

  // Convert string options to label/value format
  const normalizedOptions = finalOptions.map((opt) =>
    typeof opt === "string" ? { label: opt, value: opt } : opt
  )

  return (
    <div className="flex flex-col gap-2.5">
      <label
        htmlFor={id}
        className="text-[9px] font-bold uppercase tracking-[0.08em] text-white/30 leading-tight"
      >
        {label}
      </label>
      <div className="relative">
        <select
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={isLoading}
          className="w-full px-4 py-3 text-[11px] font-bold text-white bg-black/20 border border-white/10 rounded-xl focus:outline-none focus:ring-2 focus:ring-white/20 appearance-none cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-300"
          onFocus={(e) => {
            e.target.style.borderColor = `${glowColor}66`
          }}
          onBlur={(e) => {
            e.target.style.borderColor = "rgba(255, 255, 255, 0.1)"
          }}
        >
          {isLoading ? (
            <option value="">Loading...</option>
          ) : error ? (
            <option value="">Error loading options</option>
          ) : normalizedOptions.length === 0 ? (
            <option value="">No options available</option>
          ) : (
            normalizedOptions.map((opt, i) => (
              <option key={`${opt.value}-${i}`} value={opt.value}>
                {opt.label}
              </option>
            ))
          )}
        </select>
        {/* Custom dropdown arrow - Premium Chevron */}
        <div className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none opacity-40">
          <svg width="10" height="6" viewBox="0 0 10 6" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M1 1L5 5L9 1" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
      </div>
      {error && (
        <span className="text-[9px] text-red-400/80 mt-0.5">{error}</span>
      )}
    </div>
  )
}

// Use React.memo for performance optimization as per requirement 12.1
export const DropdownField = React.memo(DropdownFieldComponent)
