"use client"

import { useState, useRef, useEffect } from "react"
import { ChevronDown } from "lucide-react"
import { FieldWrapper } from "./FieldWrapper"
import { useBrandColor } from "@/contexts/BrandColorContext"

interface DropdownOption {
  label: string
  value: string
  downloaded?: boolean
}

interface DropdownFieldProps {
  label: string
  value: string
  options?: string[] | DropdownOption[]
  loadOptions?: () => Promise<DropdownOption[]>
  onChange: (value: string) => void
  placeholder?: string
  description?: string
  searchable?: boolean
}

export function DropdownField({
  label,
  value,
  options,
  loadOptions,
  onChange,
  placeholder = "Select...",
  description,
  searchable = false,
}: DropdownFieldProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [loadedOptions, setLoadedOptions] = useState<DropdownOption[] | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [searchQuery, setSearchQuery] = useState("")
  const containerRef = useRef<HTMLDivElement>(null)
  const { getHSLString } = useBrandColor()
  const glowColor = getHSLString()

  // Load async options on first open
  useEffect(() => {
    if (isOpen && loadOptions && !loadedOptions && !isLoading) {
      setIsLoading(true)
      loadOptions()
        .then((opts) => {
          setLoadedOptions(opts)
          setIsLoading(false)
        })
        .catch(() => setIsLoading(false))
    }
  }, [isOpen, loadOptions, loadedOptions, isLoading])

  // Close on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener("mousedown", handleClickOutside)
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [])

  const allOptions: DropdownOption[] = loadedOptions ||
    (options
      ? options.map((opt) =>
          typeof opt === "string" ? { label: opt, value: opt } : opt
        )
      : [])

  const filteredOptions = searchable && searchQuery
    ? allOptions.filter((opt) =>
        opt.label.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : allOptions

  const selectedOption = allOptions.find((opt) => opt.value === value)
  const displayValue = selectedOption?.label || value || placeholder

  return (
    <FieldWrapper label={label} description={description}>
      <div ref={containerRef} className="relative">
        {/* Trigger */}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            setIsOpen(!isOpen)
          }}
          className="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-white/90 hover:border-white/20 focus:outline-none focus:border-white/30 transition-colors"
        >
          <span className="truncate">{displayValue}</span>
          <ChevronDown
            className={`w-4 h-4 text-white/40 transition-transform ${isOpen ? "rotate-180" : ""}`}
          />
        </button>

        {/* Menu */}
        {isOpen && (
          <div className="absolute z-50 mt-1 w-full max-h-48 overflow-auto rounded-lg bg-[#1c1f24] border border-white/10 shadow-xl">
            {/* Search input for searchable dropdowns */}
            {searchable && (
              <div className="sticky top-0 p-2 bg-[#1c1f24] border-b border-white/10">
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search..."
                  className="w-full px-2 py-1 text-xs bg-white/5 rounded border border-white/10 text-white/90 placeholder:text-white/30 focus:outline-none focus:border-white/30"
                  onClick={(e) => e.stopPropagation()}
                />
              </div>
            )}

            {isLoading ? (
              <div className="px-3 py-2 text-sm text-white/40">Loading...</div>
            ) : (
              <div className="py-1">
                {filteredOptions.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      onChange(option.value)
                      setIsOpen(false)
                    }}
                    className={`w-full px-3 py-2 text-left text-sm transition-colors ${
                      option.value === value
                        ? "text-white"
                        : "text-white/70 hover:bg-white/5"
                    }`}
                    style={{ backgroundColor: option.value === value ? `${glowColor}30` : 'transparent' }}
                  >
                    <div className="flex items-center justify-between">
                      <span>{option.label}</span>
                      {option.downloaded !== undefined && (
                        <span
                          className={`text-xs ${
                            option.downloaded ? "text-green-400" : "text-amber-400"
                          }`}
                        >
                          {option.downloaded ? "Downloaded" : "Download"}
                        </span>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </FieldWrapper>
  )
}
