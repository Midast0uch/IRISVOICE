"use client"

import { motion } from "framer-motion"

interface DeviceRowProps {
  label: string
  options: string[]
  value: string
  onChange: (value: string) => void
  glowColor: string
}

export function DeviceRow({ label, options, value, onChange, glowColor }: DeviceRowProps) {
  const selectedIndex = options.indexOf(value)
  
  return (
    <div className="py-2" onClick={(e) => e.stopPropagation()}>
      <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: `${glowColor}cc` }}>
        {label}
      </div>
      <div className="flex flex-wrap gap-1">
        {options.map((option, idx) => {
          const isSelected = option === value
          return (
            <motion.button
              key={option}
              onClick={(e) => {
                e.stopPropagation()
                onChange(option)
              }}
              className="px-2 py-1 rounded text-[10px] font-medium transition-all"
              style={{
                background: isSelected ? glowColor : 'rgba(255,255,255,0.08)',
                color: isSelected ? '#000' : '#ffffffcc',
                border: `1px solid ${isSelected ? glowColor : 'rgba(255,255,255,0.15)'}`,
              }}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.95 }}
            >
              {option}
            </motion.button>
          )
        })}
      </div>
    </div>
  )
}
