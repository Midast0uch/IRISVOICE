"use client"

import React from "react"
import { motion, AnimatePresence } from "framer-motion"
import { UILayoutState } from "@/hooks/useUILayoutState"

interface BackdropBlurProps {
  uiState: UILayoutState
}

/**
 * BackdropBlur Component
 * 
 * Provides a full-screen backdrop blur effect when wings are open.
 * 
 * Features:
 * - Transparent background (NO solid color)
 * - backdrop-filter: blur(20px) saturate(180%)
 * - position: fixed, inset: 0
 * - z-index: 5 (above orb and chat activation text, below wings)
 * - pointer-events: none (allows clicks through to elements below)
 * - Renders only when wings are open (UI_STATE_CHAT_OPEN or UI_STATE_BOTH_OPEN)
 * - Fade in/out animations (300ms duration)
 * 
 * @param uiState - Current UI layout state from useUILayoutState hook
 */
export const BackdropBlur = React.memo(function BackdropBlur({ uiState }: BackdropBlurProps) {
  // Only render when wings are open
  const isVisible = 
    uiState === UILayoutState.UI_STATE_CHAT_OPEN || 
    uiState === UILayoutState.UI_STATE_BOTH_OPEN

  return (
    <AnimatePresence>
      {isVisible && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.3, ease: "easeOut" }}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 5,
            pointerEvents: "none",
            background: "transparent",
            backdropFilter: "blur(20px) saturate(180%)",
            WebkitBackdropFilter: "blur(20px) saturate(180%)", // Safari support
          }}
          aria-hidden="true"
        />
      )}
    </AnimatePresence>
  )
})
