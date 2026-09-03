"use client"

import React, { useState, useRef, useEffect, useCallback, useId } from "react"
import { createPortal } from "react-dom"
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
  /** Force the list to open upward (used when the trigger sits low in the
   * viewport, e.g. the ModelSwitcher's nested dropdowns inside its panel). */
  forceOpenUp?: boolean
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
  forceOpenUp = false,
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
  const displayLabel = typeof selectedLabel === 'string' ? selectedLabel : placeholder || ''

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handle = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        // Ignore clicks inside the portaled list (rendered at document.body)
        if (listRef.current && listRef.current.contains(e.target as Node)) return
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", handle)
    return () => document.removeEventListener("mousedown", handle)
  }, [open])

  // Close on scroll/resize so the portaled list doesn't drift from the trigger.
  // Scrolls originating INSIDE the list itself (e.g. scrollIntoView on hover /
  // keyboard focus) must NOT close it — only ancestor/page scrolls that would
  // make the fixed-position list drift from its trigger.
  useEffect(() => {
    if (!open) return
    const close = (e: Event) => {
      const t = e.target as Node | null
      if (t && listRef.current && listRef.current.contains(t)) return
      if (t && containerRef.current && containerRef.current.contains(t)) return
      setOpen(false)
    }
    const closeResize = () => setOpen(false)
    window.addEventListener("scroll", close, true)
    window.addEventListener("resize", closeResize)
    return () => {
      window.removeEventListener("scroll", close, true)
      window.removeEventListener("resize", closeResize)
    }
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
  // Viewport-relative coords for the portaled list (computed from the trigger
  // rect so the list escapes any ancestor overflow:hidden/auto clipping).
  const [listPos, setListPos] = useState<{
    top?: number
    bottom?: number
    left: number
    width: number
  } | null>(null)
  const handleOpen = () => {
    if (disabled) return
    if (!open && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect()
      const spaceBelow = window.innerHeight - rect.bottom
      const shouldOpenUp = forceOpenUp || spaceBelow < 220
      setOpenUp(shouldOpenUp)
      setListPos(
        shouldOpenUp
          ? { bottom: window.innerHeight - rect.top + 4, left: rect.left, width: rect.width }
          : { top: rect.bottom + 4, left: rect.left, width: rect.width }
      )
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
        <span className="min-w-0 flex-1 truncate">{displayLabel}</span>
        {/* Chevron */}
        <svg
          width="10" height="6" viewBox="0 0 10 6" fill="none"
          className="shrink-0 opacity-50 transition-transform duration-200"
          style={{ transform: open ? "rotate(180deg)" : "rotate(0deg)" }}
        >
          <path d="M1 1L5 5L9 1" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {/* Options list — rendered in a portal so it escapes ancestor
          overflow:hidden/auto clipping (e.g. ModelSwitcher panel, Dashboard
          scroll containers) that would otherwise cut off the options. */}
      {open && listPos && createPortal(
        <div
          id={`${uid}-list`}
          ref={listRef}
          role="listbox"
          tabIndex={-1}
          onKeyDown={handleListKeyDown}
          className="max-h-52 overflow-y-auto py-1"
          style={{
            position: "fixed",
            top: listPos.top,
            bottom: listPos.bottom,
            left: listPos.left,
            width: listPos.width,
            zIndex: 9050,
            background: "rgba(10, 10, 14, 0.96)",
            border: "1px solid rgba(255,255,255,0.08)",
            boxShadow: "0 8px 32px rgba(0,0,0,0.7)",
            borderRadius: "6px",
            backdropFilter: "blur(8px)",
            WebkitBackdropFilter: "blur(8px)",
          }}
        >
          {normalizedOpts.length === 0 ? (
            <div className="px-2 py-1.5 text-[10px] text-white/30">No options available</div>
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
                  className="flex items-center gap-2 px-2 py-1.5 text-[10px] font-medium text-white cursor-pointer transition-colors duration-100 select-none"
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
                  <span className="min-w-0 flex-1 truncate">{String(opt.label ?? '')}</span>
                </div>
              )
            })
          )}
        </div>,
        document.body
      )}
    </div>
  )
}
