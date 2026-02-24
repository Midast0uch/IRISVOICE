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
    <div className="flex flex-col gap-1 py-1">
      <label
        htmlFor={id}
        className="text-[10px] font-medium uppercase tracking-wider text-white/60"
      >
        {label}
      </label>
      <div className="relative">
        <select
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={isLoading}
          className="w-full px-2 py-1.5 text-[10px] text-white bg-white/5 border border-white/10 rounded focus:outline-none focus:ring-2 focus:ring-white/20 appearance-none cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          style={{
            borderColor: `rgba(255, 255, 255, 0.1)`,
          }}
          onFocus={(e) => {
            e.target.style.borderColor = glowColor
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
            normalizedOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))
          )}
        </select>
        {/* Custom dropdown arrow */}
        <div className="absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none">
          {isLoading ? (
            <svg
              className="w-3 h-3 animate-spin"
              style={{ color: glowColor }}
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              />
            </svg>
          ) : (
            <svg
              className="w-3 h-3 text-white/40"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M19 9l-7 7-7-7"
              />
            </svg>
          )}
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
