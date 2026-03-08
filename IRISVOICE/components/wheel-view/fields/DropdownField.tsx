"use client"

import React, { useEffect, useState, useRef } from "react"
import { CustomDropdown } from "@/components/ui/CustomDropdown"

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
          setDynamicOptions([])
          setIsLoading(false)
        })
    }
  }, [loadOptions, id])

  // Determine which options to use and normalise to {label, value} format
  const finalOptions: { label: string; value: string }[] = loadOptions
    ? dynamicOptions
    : options.map(o => ({ label: o, value: o }))

  return (
    <div className="flex flex-col gap-2.5">
      <label
        htmlFor={id}
        className="text-[9px] font-bold uppercase tracking-[0.08em] text-white/30 leading-tight"
      >
        {label}
      </label>

      <CustomDropdown
        id={id}
        value={value}
        options={isLoading || error ? [] : finalOptions}
        onChange={onChange}
        glowColor={glowColor}
        disabled={isLoading}
        placeholder={isLoading ? "Loading…" : error ? "Error loading options" : "Select…"}
        className="px-4 py-3 text-[11px] font-bold"
      />

      {error && (
        <span className="text-[9px] text-red-400/80 mt-0.5">{error}</span>
      )}
    </div>
  )
}

// Use React.memo for performance optimization as per requirement 12.1
export const DropdownField = React.memo(DropdownFieldComponent)
