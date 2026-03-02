"use client"

import React, { useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { UILayoutState } from "@/hooks/useUILayoutState"

interface ChatActivationTextProps {
  uiState: UILayoutState
  navigationLevel: number
  onClick: () => void
}

export const ChatActivationText = React.memo(function ChatActivationText({ 
  uiState, 
  navigationLevel, 
  onClick 
}: ChatActivationTextProps) {
  const [currentTextIndex, setCurrentTextIndex] = useState(0)

  const texts = [
    "Tap iris for menu",
    "Double-click for🎙️",
    "Tap here for chat"
  ]

  // Cycle through texts every 3 seconds when visible
  useEffect(() => {
    // Only rotate text when at navigation level 1 and UI is idle
    if (navigationLevel !== 1 || uiState !== UILayoutState.UI_STATE_IDLE) {
      return
    }

    const interval = setInterval(() => {
      setCurrentTextIndex((prev) => (prev + 1) % texts.length)
    }, 3000)

    return () => clearInterval(interval)
  }, [navigationLevel, uiState, texts.length])

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    onClick()
  }

  // Only render when NavigationContext level equals 1
  if (navigationLevel !== 1) {
    return null
  }

  // Calculate opacity based on UI state
  const opacity = uiState === UILayoutState.UI_STATE_IDLE ? 0.7 : 0

  return (
    <motion.div
      className="fixed left-1/2 -translate-x-1/2 cursor-pointer"
      style={{
        top: "60%",
        zIndex: 1,
        pointerEvents: "auto"
      }}
      onClick={handleClick}
      initial={{ opacity: 0, scale: 1 }}
      animate={{ 
        opacity,
        scale: uiState === UILayoutState.UI_STATE_IDLE ? [1, 1.02, 1] : 1
      }}
      transition={{
        opacity: { duration: 0.3 },
        scale: {
          duration: 3,
          repeat: Infinity,
          ease: "easeInOut"
        }
      }}
      whileHover={{
        opacity: 1,
        scale: 1.05
      }}
    >
      <AnimatePresence mode="wait">
        <motion.p
          key={currentTextIndex}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          transition={{ duration: 0.3, ease: "easeInOut" }}
          className="text-sm font-semibold text-white text-center whitespace-nowrap"
        >
          {texts[currentTextIndex]}
        </motion.p>
      </AnimatePresence>
    </motion.div>
  )
})