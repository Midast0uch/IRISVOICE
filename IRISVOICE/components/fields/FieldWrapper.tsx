"use client"

import { ReactNode } from "react"

interface FieldWrapperProps {
  label: string
  description?: string
  error?: string
  children: ReactNode
  compact?: boolean
}

export function FieldWrapper({
  label,
  description,
  error,
  children,
  compact = false,
}: FieldWrapperProps) {
  if (compact) {
    return (
      <div className="flex items-center justify-between gap-3">
        <div className="flex-1 min-w-0">
          <label className="text-[11px] font-medium uppercase tracking-wider text-white/60">
            {label}
          </label>
          {description && (
            <p className="text-[10px] text-white/40 truncate">{description}</p>
          )}
        </div>
        <div className="flex-shrink-0">{children}</div>
        {error && (
          <span className="text-[10px] text-red-400 absolute -bottom-4 right-0">
            {error}
          </span>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-2 relative">
      <label className="text-[11px] font-medium uppercase tracking-wider text-white/60">
        {label}
      </label>
      {description && (
        <p className="text-[10px] text-white/40 -mt-1">{description}</p>
      )}
      {children}
      {error && (
        <span className="text-[10px] text-red-400">{error}</span>
      )}
    </div>
  )
}
