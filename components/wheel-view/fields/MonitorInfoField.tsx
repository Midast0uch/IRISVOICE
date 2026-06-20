"use client"

import React from "react"

interface MonitorInfoFieldProps {
  id: string
  label: string
  value: string
  glowColor: string
}

/**
 * Read-only informational display for Monitor side panel sections.
 * Renders multi-line text data (analytics, logs, diagnostics) as
 * formatted key-value lines — NOT as an input bar.
 */
const MonitorInfoFieldComponent: React.FC<MonitorInfoFieldProps> = ({
  id,
  label,
  value,
  glowColor,
}) => {
  // Split value into lines for formatted display
  const lines = value ? value.split("\n").filter((l) => l.trim()) : []

  return (
    <div className="flex flex-col gap-1.5">
      <label
        htmlFor={id}
        className="text-[9px] font-bold uppercase tracking-[0.08em] text-white/30 leading-tight"
      >
        {label}
      </label>
      <div
        className="w-full px-3 py-2.5 rounded-xl border bg-black/20 border-white/5 min-h-[40px]"
        style={{ borderColor: `${glowColor}10` }}
      >
        {lines.length === 0 ? (
          <span className="text-[10px] text-white/20 italic">
            Waiting for backend data...
          </span>
        ) : (
          <div className="flex flex-col gap-0.5">
            {lines.map((line, i) => {
              // Check if line has a colon (key: value format)
              const colonIdx = line.indexOf(":")
              const isKeyValue = colonIdx > 0 && colonIdx < 40
              const keyPart = isKeyValue ? line.slice(0, colonIdx + 1) : null
              const valuePart = isKeyValue ? line.slice(colonIdx + 1).trim() : line

              // Check if it's a sub-item (starts with spaces)
              const isSubItem = line.startsWith("  ")

              return (
                <div
                  key={i}
                  className={`text-[10px] font-medium tabular-nums leading-relaxed ${
                    isSubItem ? "pl-3 text-white/35" : "text-white/55"
                  }`}
                >
                  {keyPart ? (
                    <>
                      <span className="text-white/40">{keyPart}</span>{" "}
                      <span style={{ color: `${glowColor}cc` }}>{valuePart}</span>
                    </>
                  ) : (
                    <span className={isSubItem ? "" : "text-white/50"}>{line}</span>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export const MonitorInfoField = React.memo(MonitorInfoFieldComponent)
