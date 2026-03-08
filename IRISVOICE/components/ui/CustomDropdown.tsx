"use client"

import React, { useState, useRef, useEffect, useCallback, useId } from "react"
import { injectDropdownStyles } from "@/lib/dropdown-styles"

// Ensure .iris-select hover/focus styles are present whenever this component is used
injectDropdownStyles()

interface OptionItem {
  label: string
  value: string
}

type OptionInput = string | OptionItem

interface CustomDropdownProps {
  value: string
  options: OptionInput[]
  onChange: (value: string) => void
  glowColor?: string
  disabled?: boolean
  /** id applied to the trigger button (for label htmlFor association) */
  id?: string
  /** Extra class names applied to the trigger button */
  className?: string
  /** Inline style on the trigger button (e.g. error border color) */
  style?: React.CSSProperties
  placeholder?: string
}

/**
 * CustomDropdown
 *
 * Fully-styled replacement for <select>. The open list is a positioned <div>
 * so it can be themed with brand colors — unlike the OS-native <select> popup
 * which cannot be styled with CSS.
 *
 * - Closed: transparent, barely-visible border
 * - Hover:  brand color bleeds in (via --glow CSS var)
 * - Open:   dark panel, each option highlights to brand color on hover
 * - Selected option: brand accent indicator
 * - Keyboard: arrow keys, enter, escape, tab
 * - Accepts string[] or {label, value}[] options (or a mix)
 */
export const CustomDropdown: React.FC<CustomDropdownProps> = ({
  value,
  options,
  onChange,
  glowColor = "#8b5cf6",
  disabled = false,
  id,
  className = "",
  style,
  placeholder = "Select…",
}) => {
  const [open, setOpen] = useState(false)
  const [focusedIdx, setFocusedIdx] = useState<number>(-1)
  const containerRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const uid = useId()

  // Normalize options to {label, value}[] for consistent handling
  const normalizedOpts: OptionItem[] = options.map(opt =>
    typeof opt === "string" ? { label: opt, value: opt } : opt
  )

  const selectedLabel = normalizedOpts.find(o => o.value === value)?.label ?? value
  const displayLabel = selectedLabel || placeholder

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handle = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", handle)
    return () => document.removeEventListener("mousedown", handle)
  }, [open])

  // Scroll focused option into view
  useEffect(() => {
    if (!open || focusedIdx < 0) return
    const item = listRef.current?.querySelector<HTMLElement>(`[data-idx="${focusedIdx}"]`)
    item?.scrollIntoView({ block: "nearest" })
  }, [focusedIdx, open])

  const currentIdx = normalizedOpts.findIndex(o => o.value === value)

  const handleTriggerKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (disabled) return
    if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown") {
      e.preventDefault()
      setOpen(true)
      setFocusedIdx(currentIdx >= 0 ? currentIdx : 0)
    }
  }, [disabled, currentIdx])

  const handleListKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      setOpen(false)
      triggerRef.current?.focus()
    } else if (e.key === "ArrowDown") {
      e.preventDefault()
      setFocusedIdx(i => Math.min(i + 1, normalizedOpts.length - 1))
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      setFocusedIdx(i => Math.max(i - 1, 0))
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault()
      if (focusedIdx >= 0 && focusedIdx < normalizedOpts.length) {
        onChange(normalizedOpts[focusedIdx].value)
        setOpen(false)
        triggerRef.current?.focus()
      }
    } else if (e.key === "Tab") {
      setOpen(false)
    }
  }, [focusedIdx, normalizedOpts, onChange])

  const selectOption = useCallback((optValue: string) => {
    onChange(optValue)
    setOpen(false)
    triggerRef.current?.focus()
  }, [onChange])

  // Determine if the list should open upward (if near bottom of viewport)
  const [openUp, setOpenUp] = useState(false)
  const handleOpen = () => {
    if (disabled) return
    if (!open && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect()
      const spaceBelow = window.innerHeight - rect.bottom
      setOpenUp(spaceBelow < 220)
    }
    setOpen(o => !o)
    setFocusedIdx(currentIdx >= 0 ? currentIdx : 0)
  }

  return (
    <div
      ref={containerRef}
      className="relative"
      style={{ "--glow": glowColor } as React.CSSProperties}
    >
      {/* Trigger */}
      <button
        ref={triggerRef}
        id={id}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={`${uid}-list`}
        disabled={disabled}
        onClick={handleOpen}
        onKeyDown={handleTriggerKeyDown}
        className={`iris-select w-full flex items-center justify-between gap-2 text-left text-white rounded-xl cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed select-none ${className}`}
        style={style}
      >
        <span className="truncate min-w-0 flex-1">{displayLabel}</span>
        {/* Chevron */}
        <svg
          width="10" height="6" viewBox="0 0 10 6" fill="none"
          className="shrink-0 opacity-50 transition-transform duration-200"
          style={{ transform: open ? "rotate(180deg)" : "rotate(0deg)" }}
        >
          <path d="M1 1L5 5L9 1" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {/* Options list */}
      {open && (
        <div
          id={`${uid}-list`}
          ref={listRef}
          role="listbox"
          tabIndex={-1}
          onKeyDown={handleListKeyDown}
          className="absolute z-50 w-full max-h-52 overflow-y-auto rounded-xl py-1"
          style={{
            ...(openUp ? { bottom: "calc(100% + 4px)" } : { top: "calc(100% + 4px)" }),
            background: "rgba(10, 10, 14, 0.96)",
            border: `1px solid color-mix(in srgb, ${glowColor} 30%, rgba(255,255,255,0.08))`,
            boxShadow: `0 8px 32px rgba(0,0,0,0.6), 0 0 20px color-mix(in srgb, ${glowColor} 10%, transparent)`,
            backdropFilter: "blur(12px)",
          }}
        >
          {normalizedOpts.length === 0 ? (
            <div className="px-4 py-2.5 text-[11px] text-white/30">No options available</div>
          ) : (
            normalizedOpts.map((opt, idx) => {
              const isSelected = opt.value === value
              const isFocused = idx === focusedIdx
              return (
                <div
                  key={`${opt.value}-${idx}`}
                  data-idx={idx}
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => selectOption(opt.value)}
                  onMouseEnter={() => setFocusedIdx(idx)}
                  className="flex items-center gap-2.5 px-3 py-2 text-[11px] font-medium text-white cursor-pointer transition-colors duration-100 select-none"
                  style={{
                    background: isFocused
                      ? `color-mix(in srgb, ${glowColor} 18%, rgba(255,255,255,0.04))`
                      : isSelected
                      ? `color-mix(in srgb, ${glowColor} 10%, transparent)`
                      : "transparent",
                  }}
                >
                  {/* Selected indicator dot */}
                  <span
                    className="shrink-0 w-1.5 h-1.5 rounded-full transition-opacity duration-150"
                    style={{
                      background: glowColor,
                      opacity: isSelected ? 1 : 0,
                    }}
                  />
                  <span className="truncate">{opt.label}</span>
                </div>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}
