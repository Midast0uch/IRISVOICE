"use client"

import React, { useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ChevronDown } from "lucide-react"

interface CollapsibleSectionProps {
  title: string
  children: React.ReactNode
  defaultExpanded?: boolean
  isExpanded?: boolean
  onToggle?: () => void
}

/**
 * CollapsibleSection Component
 * 
 * A reusable collapsible section for the SidePanel.
 * Features:
 * - Title with expand/collapse chevron
 * - Smooth height animation
 * - Dark glass styling to match SidePanel
 * - Can be controlled or uncontrolled
 * 
 * Validates: Requirement 4.2
 */
export const CollapsibleSection: React.FC<CollapsibleSectionProps> = ({
  title,
  children,
  defaultExpanded = false,
  isExpanded: controlledExpanded,
  onToggle,
}) => {
  const [internalExpanded, setInternalExpanded] = useState(defaultExpanded)
  
  // Use controlled state if provided, otherwise use internal state
  const isExpanded = controlledExpanded !== undefined ? controlledExpanded : internalExpanded
  
  const handleToggle = () => {
    if (onToggle) {
      onToggle()
    } else {
      setInternalExpanded(!internalExpanded)
    }
  }

  return (
    <div className="border-b border-white/10">
      <button
        onClick={handleToggle}
        className="w-full flex items-center justify-between py-3"
      >
        <span className="text-[10px] font-bold uppercase tracking-wider text-white/60">
          {title}
        </span>
        <motion.div
          animate={{ rotate: isExpanded ? 180 : 0 }}
          transition={{ duration: 0.2 }}
        >
          <ChevronDown className="w-4 h-4 text-white/40" />
        </motion.div>
      </button>
      <AnimatePresence initial={false}>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            onMouseUp={(e) => e.stopPropagation()}
          >
            <div className="pb-4 space-y-3">
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export default CollapsibleSection
