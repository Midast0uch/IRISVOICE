
import React, { useState, useCallback, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import type { IrisOrbProps } from "./types"

export function IrisOrb({ isExpanded, onClick, centerLabel, size, glowColor, voiceState, wakeFlash, sendMessage, onCallbacksReady }: IrisOrbProps) {
  const isSpeaking = voiceState === "speaking"
  const isProcessing = voiceState === "processing_conversation" || voiceState === "processing_tool"

  // Voice command states
  const [isRecording, setIsRecording] = useState(false)
  const [isVoiceProcessing, setIsVoiceProcessing] = useState(false)
  const [audioLevel, setAudioLevel] = useState(0)
  const [feedbackMessage, setFeedbackMessage] = useState("")
  const [doubleClickFlash, setDoubleClickFlash] = useState(false)

  const clickTimer = useRef<NodeJS.Timeout | null>(null)
  const clickCount = useRef<number>(0)
  const audioLevelInterval = useRef<NodeJS.Timeout | null>(null)

  // Handle mouse down (double-click detection)
  const handleMouseDown = (e: React.MouseEvent) => {
    console.log("[IrisOrb] Mouse down, isRecording:", isRecording)

    // If already recording, stop it (single click stops)
    if (isRecording) {
      stopRecording()
      return
    }

    // If processing, don't allow new recording
    if (isVoiceProcessing) {
      return
    }

    // Double-click detection
    clickCount.current += 1

    if (clickCount.current === 1) {
      // First click - set timer for double-click window
      clickTimer.current = setTimeout(() => {
        // No second click within window - this is a single click
        clickCount.current = 0
        clickTimer.current = null
        // Trigger normal click for widget movement
        onClick()
      }, 300) // 300ms double-click window
    } else if (clickCount.current === 2) {
      // Second click within window - this is a double click
      if (clickTimer.current) {
        clearTimeout(clickTimer.current)
        clickTimer.current = null
      }
      clickCount.current = 0

      // Brief visual flash for double-click detection
      setDoubleClickFlash(true)
      setTimeout(() => setDoubleClickFlash(false), 100)

      // Start recording
      startRecording()
    }
  }

  // Handle mouse up (no longer needed for double-click logic)
  const handleMouseUp = () => {
    // Mouse up is no longer needed for double-click detection
    // All logic is handled in mouse down
  }

  // Handle mouse leave (clean up any pending timers)
  const handleMouseLeave = () => {
    // Cancel double-click timer if still active
    if (clickTimer.current) {
      clearTimeout(clickTimer.current)
      clickTimer.current = null
      clickCount.current = 0
    }
  }

  // Start voice recording
  const startRecording = () => {
    console.log("[IrisOrb] Starting recording...")
    setIsRecording(true)
    setFeedbackMessage("Listening...")

    // Send WebSocket message to backend
    const success = sendMessage("voice_command_start", {})
    console.log("[IrisOrb] Sent voice_command_start, success:", success)

    // Simulate audio level visualization (will be replaced with real audio data)
    audioLevelInterval.current = setInterval(() => {
      // Generate random audio level for demo (0-1)
      const level = Math.random() * 0.8 + 0.2
      setAudioLevel(level)
    }, 100)
  }

  // Stop voice recording
  const stopRecording = () => {
    console.log("[IrisOrb] Stopping recording...")
    setIsRecording(false)
    setFeedbackMessage("Processing...")
    setIsVoiceProcessing(true)

    // Clear audio level interval
    if (audioLevelInterval.current) {
      clearInterval(audioLevelInterval.current)
      audioLevelInterval.current = null
    }

    // Send WebSocket message to backend
    const success = sendMessage("voice_command_end", {})
    console.log("[IrisOrb] Sent voice_command_end, success:", success)

    // Reset audio level
    setAudioLevel(0)

    // Reset processing state after delay
    setTimeout(() => {
      setIsVoiceProcessing(false)
      setFeedbackMessage("")
    }, 2000)
  }

  // Handle wake word detection
  const handleWakeDetected = useCallback(() => {
    console.log("[IrisOrb] Wake word detected - starting recording")
    // Prevent multiple simultaneous recordings
    if (isRecording || isVoiceProcessing) {
      console.log("[IrisOrb] Recording already active, ignoring wake word")
      return
    }
    startRecording()
  }, [isRecording, isVoiceProcessing])

  // Handle native audio response
  const handleNativeAudioResponse = useCallback((payload: any) => {
    console.log("[IrisOrb] Native audio response received:", payload)
    if (payload.debug_text) {
      setFeedbackMessage(payload.debug_text)
      // Clear the response after a few seconds
      setTimeout(() => setFeedbackMessage(""), 5000)
    }
  }, [])

  // Expose callbacks to parent when ready
  React.useEffect(() => {
    if (onCallbacksReady) {
      onCallbacksReady({
        handleWakeDetected,
        handleNativeAudioResponse
      })
    }
  }, [onCallbacksReady, handleWakeDetected, handleNativeAudioResponse])

  // Helper function to make color more vibrant (increase saturation and brightness)
  const makeVibrant = (color: string): string => {
    // Convert hex to RGB
    const hex = color.replace('#', '')
    const r = parseInt(hex.substring(0, 2), 16)
    const g = parseInt(hex.substring(2, 4), 16)
    const b = parseInt(hex.substring(4, 6), 16)

    // Convert to HSL for easier manipulation
    const rNorm = r / 255
    const gNorm = g / 255
    const bNorm = b / 255

    const max = Math.max(rNorm, gNorm, bNorm)
    const min = Math.min(rNorm, gNorm, bNorm)
    let h = 0, s = 0, l = (max + min) / 2

    if (max !== min) {
      const d = max - min
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min)

      switch (max) {
        case rNorm: h = ((gNorm - bNorm) / d + (gNorm < bNorm ? 6 : 0)) / 6; break
        case gNorm: h = ((bNorm - rNorm) / d + 2) / 6; break
        case bNorm: h = ((rNorm - gNorm) / d + 4) / 6; break
      }
    }

    // Increase saturation and brightness for vibrancy (Siri-like effect)
    s = Math.min(1, s * 2.0) // Double the saturation
    l = Math.min(0.75, l * 1.6) // 60% brighter, capped at 0.75

    // Convert back to RGB
    const hue2rgb = (p: number, q: number, t: number) => {
      if (t < 0) t += 1
      if (t > 1) t -= 1
      if (t < 1/6) return p + (q - p) * 6 * t
      if (t < 1/2) return q
      if (t < 2/3) return p + (q - p) * (2/3 - t) * 6
      return p
    }

    let rOut, gOut, bOut
    if (s === 0) {
      rOut = gOut = bOut = l
    } else {
      const q = l < 0.5 ? l * (1 + s) : l + s - l * s
      const p = 2 * l - q
      rOut = hue2rgb(p, q, h + 1/3)
      gOut = hue2rgb(p, q, h)
      bOut = hue2rgb(p, q, h - 1/3)
    }

    // Convert back to hex
    const toHex = (n: number) => {
      const hex = Math.round(n * 255).toString(16)
      return hex.length === 1 ? '0' + hex : hex
    }

    return `#${toHex(rOut)}${toHex(gOut)}${toHex(bOut)}`
  }

  // Determine visual state (voice commands override normal states)
  const effectiveGlowColor = isRecording
    ? makeVibrant(glowColor) // Use vibrant version of theme color
    : isVoiceProcessing
      ? "#4444FF" // Keep blue for processing
      : glowColor
  const effectiveScale = isRecording ? 1.1 : isVoiceProcessing ? 1.05 : 1

  return (
    <motion.div
      className="relative flex items-center justify-center rounded-full cursor-pointer z-50 pointer-events-auto"
      style={{ width: size, height: size }}
      onMouseDown={handleMouseDown}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseLeave}
      animate={{ scale: effectiveScale }}
      transition={{ type: "spring", stiffness: 300, damping: 25 }}
    >
      {/* Outer breathe glow - more vibrant */}
      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{
          inset: -30,
          background: `radial-gradient(circle, ${effectiveGlowColor}80 0%, ${effectiveGlowColor}40 30%, transparent 65%)`,
          filter: "blur(25px)",
        }}
        animate={{
          scale: isSpeaking ? [1.05, 1.3, 1.05] : isRecording ? [1, 1.25, 1] : [1, 1.15, 1],
          opacity: isSpeaking ? [0.8, 1, 0.8] : isRecording ? [0.9, 1, 0.9] : [0.4, 0.75, 0.4],
        }}
        transition={{
          duration: isRecording ? 0.8 : 5,
          repeat: Infinity,
          ease: isRecording ? "easeInOut" : "easeInOut"
        }}
      />

      {/* Audio level ring (only during recording) */}
      {isRecording && (
        <motion.div
          className="absolute rounded-full pointer-events-none"
          style={{
            inset: -30,
            background: `radial-gradient(circle, ${effectiveGlowColor}60 0%, transparent 70%)`,
            filter: "blur(12px)",
          }}
          animate={{
            opacity: [0.3, 0.8 * audioLevel, 0.3],
            scale: [0.9, 1 + (audioLevel * 0.2), 0.9]
          }}
          transition={{ duration: 0.1, repeat: Infinity }}
        />
      )}

      {/* Inner core pulse */}
      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{
          inset: -8,
          background: `radial-gradient(circle at 30% 30%, ${effectiveGlowColor}14, transparent 70%)`,
          filter: "blur(8px)",
        }}
        animate={{
          scale: isProcessing || isVoiceProcessing ? [0.9, 1.1, 0.9] : isSpeaking ? [0.8, 1.5, 0.8] : [0.8, 1.2, 0.8],
          opacity: isProcessing || isVoiceProcessing ? [0.5, 0.8, 0.5] : [0.6, 1, 0.6],
        }}
        transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
      />

      {/* Wake flash */}
      <AnimatePresence>
        {(wakeFlash || doubleClickFlash) && (
          <motion.div
            className="absolute rounded-full pointer-events-none"
            style={{ inset: -20, backgroundColor: `${glowColor}99` }}
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1.5 }}
            exit={{ opacity: 0, scale: 2 }}
            transition={{ duration: 0.3 }}
          />
        )}
      </AnimatePresence>

      {/* Orb body and label */}
      <div
        className="relative w-full h-full flex items-center justify-center rounded-full pointer-events-none overflow-hidden"
        style={{
          background: "rgba(255, 255, 255, 0.05)",
          backdropFilter: "blur(20px)",
          border: `1px solid ${glowColor}33`,
        }}
      >
        <div
          className="absolute inset-0 rounded-full pointer-events-none"
          style={{ background: `radial-gradient(circle at 30% 30%, ${glowColor}14, transparent 70%)` }}
        />

        {/* Rotating shimmer ring */}
        <motion.div
          className="absolute rounded-full pointer-events-none"
          style={{
            inset: -2,
            borderRadius: "50%",
            padding: "2px",
            background: `conic-gradient(from 0deg, transparent 0deg, ${glowColor}33 90deg, ${glowColor}aa 180deg, ${glowColor}33 270deg, transparent 360deg)`,
            WebkitMask: "linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)",
            WebkitMaskComposite: "xor",
          }}
          animate={{ rotate: isProcessing ? 360 : isSpeaking ? [0, 360] : 360 }}
          transition={{
            duration: isProcessing ? 2 : isSpeaking ? 1.5 : 8,
            repeat: Infinity,
            ease: "linear"
          }}
        />

        <AnimatePresence mode="wait">
          <motion.span
            key={feedbackMessage || centerLabel}
            className="text-lg font-light tracking-[0.2em] select-none pointer-events-none z-10 text-center"
            style={{
              color: "rgba(255, 255, 255, 0.95)",
              textShadow: `0 0 10px ${glowColor}40`,
              fontSize: (feedbackMessage || centerLabel).length > 8 ? '0.75rem' : '1.125rem',
              maxWidth: size - 20,
              lineHeight: 1.2
            }}
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.8, opacity: 0 }}
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
          >
            {feedbackMessage || centerLabel}
          </motion.span>
        </AnimatePresence>
      </div>
    </motion.div>
  )
}