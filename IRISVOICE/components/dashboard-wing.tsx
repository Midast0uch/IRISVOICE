"use client"

import React from "react"
import { motion, AnimatePresence } from "framer-motion"
import { X } from 'lucide-react'
import { DarkGlassDashboard } from "./dark-glass-dashboard"
import { useNavigation } from "@/contexts/NavigationContext"
import { SendMessageFunction } from "@/hooks/useIRISWebSocket"

interface DashboardWingProps {
  isOpen: boolean
  onClose: () => void
  sendMessage?: SendMessageFunction
  fieldValues?: Record<string, any>
  updateField?: (subnodeId: string, fieldId: string, value: any) => void
}

export function DashboardWing({ 
  isOpen, 
  onClose, 
  sendMessage, 
  fieldValues, 
  updateField 
}: DashboardWingProps) {
  const { activeTheme } = useNavigation()
  
  // Get theme colors with fallback
  const glowColor = activeTheme?.glow || "#00d4ff"
  const fontColor = activeTheme?.font || "#ffffff"

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          className="fixed z-[10]"
          initial={{ x: 120, opacity: 0, scale: 0.95 }}
          animate={{ x: 0, opacity: 1, scale: 1 }}
          exit={{ x: 120, opacity: 0, scale: 0.95 }}
          transition={{ 
            type: "spring", 
            stiffness: 280, 
            damping: 25,
            mass: 0.8
          }}
          style={{ 
            right: '3%',
            top: '50%',
            width: '248px',
            height: '50vh',
            perspective: '800px',
          }}
        >
          {/* Dashboard Container */}
          <div 
            className="h-full bg-black/30 backdrop-blur-xl border border-white/10 rounded-2xl overflow-hidden flex flex-col"
            style={{
              transform: 'translateY(-50%) rotateY(-15deg) rotateX(2deg)',
              transformOrigin: 'right center',
              transformStyle: 'preserve-3d',
              background: 'linear-gradient(225deg, rgba(10,10,20,0.9) 0%, rgba(5,5,10,0.95) 100%)',
              boxShadow: '-20px 0 60px rgba(0,0,0,0.5), 0 10px 40px rgba(0,0,0,0.3)',
            }}
          >
            {/* Header */}
            <div 
              className="flex items-center justify-between p-4 border-b flex-shrink-0" 
              style={{ borderColor: `${glowColor}20` }}
            >
              <div className="flex items-center space-x-3">
                <div 
                  className="w-2 h-2 rounded-full animate-pulse" 
                  style={{ backgroundColor: glowColor }}
                />
                <span 
                  className="font-medium" 
                  style={{ color: fontColor, opacity: 0.9 }}
                >
                  IRIS Dashboard
                </span>
              </div>
              <button
                onClick={onClose}
                className="p-2 rounded-lg hover:bg-white/10 transition-colors"
                style={{ color: fontColor, opacity: 0.6 }}
                onMouseEnter={(e) => e.currentTarget.style.opacity = '0.9'}
                onMouseLeave={(e) => e.currentTarget.style.opacity = '0.6'}
                title="Close Dashboard"
              >
                <X size={16} />
              </button>
            </div>

            {/* Dashboard Content */}
            <div className="flex-1 overflow-hidden p-4">
              <DarkGlassDashboard 
                fieldValues={fieldValues}
                updateField={updateField}
              />
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export default DashboardWing
