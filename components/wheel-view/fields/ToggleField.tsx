"use client"

import React from "react"
import { motion } from "framer-motion"

interface ToggleFieldProps {
  id: string
  label: string
  value: boolean
  onChange: (value: boolean) => void
  glowColor: string
}

const ToggleFieldComponent: React.FC<ToggleFieldProps> = ({
  id,
  label,
  value,
  onChange,
  glowColor,
}) => {
  return (
    <div className="flex flex-col gap-2.5">
      <label
        htmlFor={id}
        className="text-[9px] font-bold uppercase tracking-[0.08em] text-white/30 leading-tight"
      >
        {label}
      </label>
      <div
        className="flex items-center justify-between gap-3 px-4 py-3 rounded-xl border border-white/10 bg-black/20"
      >
        <span className="text-[11px] font-bold text-white/90">
          {value ? "Enabled" : "Disabled"}
        </span>
        <button
          id={id}
          type="button"
          role="switch"
          aria-pressed={value}
          onClick={() => onChange(!value)}
          className="relative w-10 h-5 rounded-full transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-white/20 flex-shrink-0"
          style={{
            backgroundColor: value ? glowColor : "rgba(255, 255, 255, 0.1)",
          }}
        >
          <motion.span
            className="absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-md"
            initial={false}
            animate={{
              x: value ? 22 : 2,
            }}
            transition={{
              type: "spring",
              stiffness: 350,
              damping: 25,
            }}
          />
        </button>
      </div>
    </div>
  )
}

// Use React.memo for performance optimization as per requirement 12.1
export const ToggleField = React.memo(ToggleFieldComponent)
