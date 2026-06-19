"use client"

import React, { useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { UILayoutState } from "@/hooks/useUILayoutState"

interface ChatActivationGlitchProps {
  uiState: UILayoutState
  navigationLevel: number
  onClick: () => void
}

const DISMISS_KEY = "iris-chat-hint-dismissed"

/**
 * ChatActivationGlitch — one-shot "tap the CHAT label" hint.
 *
 * Replaces the old ChatActivationText cycling hints. Shows a single
 * glitchy hint at level 1 idle, dismisses on click (persisted in
 * localStorage so it never shows again after first interaction).
 *
 * Positioned near the orb, same slot as the old ChatActivationText.
 */
export const ChatActivationGlitch = React.memo(function ChatActivationGlitch({
  uiState,
  navigationLevel,
  onClick,
}: ChatActivationGlitchProps) {
  const [dismissed, setDismissed] = useState(false)
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
    try {
      const stored = localStorage.getItem(DISMISS_KEY)
      if (stored === "1") setDismissed(true)
    } catch {
      // localStorage may be unavailable (SSR / privacy mode) — treat as not dismissed
    }
  }, [])

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      localStorage.setItem(DISMISS_KEY, "1")
    } catch {
      // ignore write failure
    }
    setDismissed(true)
    onClick()
  }

  // Only render at level 1 idle, and only before first dismissal
  if (!mounted || dismissed || navigationLevel !== 1) {
    return null
  }

  const isVisible = uiState === UILayoutState.UI_STATE_IDLE

  return (
    <AnimatePresence>
      {isVisible && (
        <motion.div
          className="relative cursor-pointer"
          style={{
            zIndex: 1,
            pointerEvents: "auto",
          }}
          onClick={handleClick}
          initial={{ opacity: 0, scale: 1 }}
          animate={{
            opacity: 0.7,
            scale: [1, 1.02, 1],
          }}
          exit={{ opacity: 0, scale: 0.95 }}
          transition={{
            opacity: { duration: 0.3 },
            scale: {
              duration: 3,
              repeat: Infinity,
              ease: "easeInOut",
            },
          }}
          whileHover={{
            opacity: 1,
            scale: 1.05,
          }}
        >
          <motion.p
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, ease: "easeInOut" }}
            className="text-sm font-semibold text-white text-center whitespace-nowrap"
            style={{
              fontFamily: "'Courier New', Courier, monospace",
              letterSpacing: "0.08em",
              textShadow: "0 0 12px rgba(255,255,255,0.3)",
            }}
          >
            tap the CHAT label to open chat
          </motion.p>
        </motion.div>
      )}
    </AnimatePresence>
  )
})
