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
    <div className="flex items-center justify-between gap-2 py-1">
      <label
        htmlFor={id}
        className="text-[10px] font-medium uppercase tracking-wider text-white/60 flex-1"
      >
        {label}
      </label>
      <button
        id={id}
        type="button"
        role="switch"
        aria-pressed={value}
        onClick={() => onChange(!value)}
        className="relative w-11 h-5 rounded-full transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-white/20 flex-shrink-0"
        style={{
          backgroundColor: value ? glowColor : "rgba(255, 255, 255, 0.1)",
        }}
      >
        <motion.span
          className="absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-md"
          initial={false}
          animate={{
            x: value ? 24 : 2,
          }}
          transition={{
            type: "spring",
            stiffness: 300,
            damping: 25,
          }}
        />
      </button>
    </div>
  )
}

// Use React.memo for performance optimization as per requirement 12.1
export const ToggleField = React.memo(ToggleFieldComponent)
