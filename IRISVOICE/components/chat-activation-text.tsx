"use client"

import React, { useState, useEffect, memo } from "react"
import { motion, AnimatePresence } from "framer-motion"

interface ChatActivationTextProps {
  isChatActive: boolean
  onChatClick: () => void
  isExpanded: boolean
  navigationLevel: number
}

export const ChatActivationText = React.memo(function ChatActivationText({ isChatActive, onChatClick, isExpanded, navigationLevel }: ChatActivationTextProps) {
  const [currentTextIndex, setCurrentTextIndex] = useState(0)
  const [isVisible, setIsVisible] = useState(true)

  const texts = [
    "Tap iris for menu",
    "Double-tap for 🎤", 
    "Tap here for 💬"
  ]

  // Cycle through texts every 3 seconds
  useEffect(() => {
    // Only show when at navigation level 1 and not expanded
    const shouldBeVisible = navigationLevel === 1 && !isExpanded && !isChatActive
    setIsVisible(shouldBeVisible)
    
    if (!shouldBeVisible) {
      return
    }

    const interval = setInterval(() => {
      setCurrentTextIndex((prev) => (prev + 1) % texts.length)
    }, 3000)

    return () => clearInterval(interval)
  }, [isChatActive, texts.length, navigationLevel, isExpanded])

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    // Make the entire text clickable to open chat
    onChatClick()
  }

  return (
    <div className="relative mt-4">
      {/* Invisible clickable area */}
      <div 
        className="absolute inset-0 w-full h-8 cursor-pointer z-10"
        onClick={handleClick}
        style={{
          background: "transparent",
          border: "1px solid transparent"
        }}
      />
      
      {/* Text display area */}
      <AnimatePresence mode="wait">
        {isVisible && (
          <motion.div
            key={currentTextIndex}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.3, ease: "easeInOut" }}
            className="text-center"
          >
            <p 
              className="text-sm font-semibold transition-all duration-300 text-white/80 cursor-pointer hover:text-white"
            >
              {texts[currentTextIndex]}
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
})