"use client"

import { motion } from "framer-motion"

interface ToggleRowProps {
  label: string
  value: boolean
  onChange: (value: boolean) => void
  glowColor: string
}

export function ToggleRow({ label, value, onChange, glowColor }: ToggleRowProps) {
  return (
    <div 
      className="flex items-center justify-between py-2"
      onClick={(e) => e.stopPropagation()}
    >
      <span className="text-[11px] font-medium tracking-wide" style={{ color: '#ffffffcc' }}>
        {label}
      </span>
      <motion.button
        type="button"
        role="switch"
        aria-checked={value}
        onClick={(e) => {
          e.stopPropagation()
          onChange(!value)
        }}
        className="relative w-11 h-5 rounded-full transition-colors duration-200"
        style={{ backgroundColor: value ? glowColor : 'rgba(255, 255, 255, 0.15)' }}
        whileTap={{ scale: 0.95 }}
      >
        <motion.span
          className="absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-md"
          animate={{ 
            left: value ? '22px' : '2px',
          }}
          transition={{ type: "spring", stiffness: 500, damping: 30 }}
        />
      </motion.button>
    </div>
  )
}
