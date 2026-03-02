
import React, { useState, useCallback, useRef, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { getCurrentWindow, PhysicalPosition } from "@tauri-apps/api/window"
import { ChevronLeft, ChevronDown } from "lucide-react"
import { useReducedMotion } from "@/hooks/useReducedMotion"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor, type FloatingOrb } from "@/contexts/BrandColorContext"
import { UILayoutState } from "@/hooks/useUILayoutState"
import type { IrisOrbProps, OrbIcon } from "./types"

// --- Helper Hook for Window Dragging ---
function useManualDragWindow(
  elementRef: React.RefObject<HTMLElement | null>,
  onClickAction: () => void,
  onDoubleClickAction?: () => void,
  onDoubleClickFlash?: (show: boolean) => void,
  onPressUpdate?: (pressed: boolean) => void
) {
  const isDragging = useRef(false)
  const dragStartPos = useRef({ x: 0, y: 0 })
  const windowStartPos = useRef({ x: 0, y: 0 })
  const hasDragged = useRef(false)
  const isDraggingThisElement = useRef(false)
  const mouseDownTarget = useRef<EventTarget | null>(null)

  // Double click detection state
  const clickCount = useRef<number>(0)
  const clickTimer = useRef<NodeJS.Timeout | null>(null)

  const handleMouseDown = useCallback(async (e: React.MouseEvent) => {
    if (e.button !== 0) return

    const currentElement = elementRef.current
    const target = e.target as Node

    const shouldStartDrag = currentElement && currentElement.contains(target)

    isDraggingThisElement.current = false
    isDragging.current = false
    hasDragged.current = false
    mouseDownTarget.current = null

    if (!shouldStartDrag) {
      return
    }

    if (onPressUpdate) onPressUpdate(true)
    mouseDownTarget.current = e.target
    isDragging.current = true
    isDraggingThisElement.current = true
    hasDragged.current = false
    dragStartPos.current = { x: e.screenX, y: e.screenY }

    try {
      const win = getCurrentWindow()
      const pos = await win.outerPosition()
      windowStartPos.current = { x: pos.x, y: pos.y }
    } catch (err) {
      // Tauri not available
    }

    document.body.style.cursor = "grabbing"
    document.body.style.userSelect = "none"
  }, [elementRef])

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!isDragging.current || !isDraggingThisElement.current) return

    const dx = e.screenX - dragStartPos.current.x
    const dy = e.screenY - dragStartPos.current.y

    if (Math.abs(dx) > 12 || Math.abs(dy) > 12) {
      hasDragged.current = true
    }

    try {
      const win = getCurrentWindow()
      win.setPosition(new PhysicalPosition(windowStartPos.current.x + dx, windowStartPos.current.y + dy))
    } catch (err) {
      // Window drag not available
    }
  }, [])

  const handleMouseUp = useCallback((e: MouseEvent) => {
    const currentElement = elementRef.current
    const draggingThis = isDraggingThisElement.current
    const didDrag = hasDragged.current
    const downTarget = mouseDownTarget.current

    isDragging.current = false
    document.body.style.cursor = "default"
    document.body.style.userSelect = ""

    if (draggingThis && !didDrag && currentElement) {
      const upTarget = e.target as Node
      const downTargetNode = downTarget as Node

      const upInIris = currentElement.contains(upTarget)
      const downInOrb = downTargetNode && currentElement.contains(downTargetNode)

      if (upInIris && downInOrb) {
        clickCount.current += 1

        if (clickCount.current === 1) {
          clickTimer.current = setTimeout(() => {
            if (clickCount.current === 1) {
              if (typeof onClickAction === 'function') onClickAction()
            }
            clickCount.current = 0
          }, 500) // 500ms standard double-click window for maximum reliability
        } else if (clickCount.current === 2) {
          if (clickTimer.current) {
            clearTimeout(clickTimer.current)
            clickTimer.current = null
          }

          if (typeof onDoubleClickAction === 'function') {
            onDoubleClickAction()
            if (onDoubleClickFlash) {
              onDoubleClickFlash(true)
              setTimeout(() => onDoubleClickFlash(false), 500)
            }
          } else if (typeof onClickAction === 'function') {
            onClickAction()
          }

          clickCount.current = 0
        }
      }
    }

    if (onPressUpdate) onPressUpdate(false)
    isDraggingThisElement.current = false
    mouseDownTarget.current = null
    hasDragged.current = false
  }, [onClickAction, onDoubleClickAction, elementRef, onDoubleClickFlash, onPressUpdate])

  useEffect(() => {
    window.addEventListener("mousemove", handleMouseMove)
    window.addEventListener("mouseup", handleMouseUp)

    return () => {
      window.removeEventListener("mousemove", handleMouseMove)
      window.removeEventListener("mouseup", handleMouseUp)
    }
  }, [handleMouseMove, handleMouseUp])

  return { handleMouseDown }
}




// --- Main IrisOrb Component ---
export function IrisOrb({
  isExpanded,
  onClick,
  onDoubleClick,
  centerLabel,
  size = 200,
  wakeFlash,
  uiState = UILayoutState.UI_STATE_IDLE,
  onCallbacksReady,
}: IrisOrbProps) {
  // Get voice state and actions from NavigationContext
  const { voiceState, audioLevel, startVoiceCommand, endVoiceCommand, sendMessage } = useNavigation()
  
  const [feedbackMessage, setFeedbackMessage] = useState("")
  const [doubleClickFlash, setDoubleClickFlash] = useState(false)
  const [isPressed, setIsPressed] = useState(false)

  const orbRef = useRef<HTMLDivElement>(null)
  const prefersReducedMotion = useReducedMotion()

  const { orbState } = useNavigation()
  const { getThemeConfig } = useBrandColor()

  // Phase 124: Sync with prop
  // isExpanded is now passed as a single source of truth from page.tsx level

  // Use voice state from context
  const isVoiceActive = voiceState !== "idle"
  const isListening = voiceState === "listening"
  const isSpeaking = voiceState === "speaking"
  const isProcessing = voiceState === "processing_conversation" || voiceState === "processing_tool"
  const isError = voiceState === "error"

  // Theme consumption
  const theme = getThemeConfig()
  const glowColor = theme.glow.color
  const isCleanTheme = theme.name === 'Verdant' || theme.name === 'Aurum'

  // Intensity multipliers
  const intensityMultipliers = {
    glowOpacity: isCleanTheme ? 1.5 : 1.0,
    glassOpacity: isCleanTheme ? 1.2 : 1.0,
    shimmerOpacity: 1.0,
  }

  // Calculate dynamic opacities
  const glassOpacity = Math.min(theme.glass.opacity * intensityMultipliers.glassOpacity, 0.45)
  const glowOpacity = Math.min(theme.glow.opacity * intensityMultipliers.glowOpacity, 0.6)
  const shimmerOpacity = Math.min(1 * intensityMultipliers.shimmerOpacity, 1)
  
  // Audio level visualization - apply smooth interpolation
  const audioLevelScale = isListening ? 1 + (audioLevel * 0.15) : 1 // Scale glow by up to 15% based on audio level

  const handleInterceptedClick = useCallback(() => {
    // Stop voice command if listening
    if (isListening) {
      endVoiceCommand()
      return // Intercept: don't propagate to the prop's navigation logic
    }

    // If wings are open (chat or both), clicking orb should close them and return to idle
    if (uiState === UILayoutState.UI_STATE_CHAT_OPEN || uiState === UILayoutState.UI_STATE_BOTH_OPEN) {
      // Trigger navigation/exit - the parent component will handle closing wings
      if (onClick) onClick()
      return
    }

    // Not active and at idle state, proceed with normal prop logic (navigation)
    if (onClick) onClick()
  }, [isListening, endVoiceCommand, uiState, onClick])

  // BUG-04 FIX: Memoize double-click handler to prevent stale closure
  const handleDoubleClick = useCallback(() => {
    // Double-click starts voice command
    if (!isListening) {
      startVoiceCommand()
    }
    if (onDoubleClick) onDoubleClick()
  }, [isListening, startVoiceCommand, onDoubleClick])

  const { handleMouseDown } = useManualDragWindow(
    orbRef,
    handleInterceptedClick,
    handleDoubleClick,  // Stable reference now
    setDoubleClickFlash,
    setIsPressed
  )

  // --- Voice Recording Logic ---
  // Removed local startRecording/stopRecording - now using context actions

  // BUG-09 FIX: Use refs to break dependency chain and prevent re-registration
  const isListeningRef = useRef(isListening)
  isListeningRef.current = isListening

  // --- Callbacks for Parent Component ---
  // Stable callback that doesn't recreate on isListening changes
  const handleWakeDetected = useCallback(() => {
    if (isListeningRef.current) return
    startVoiceCommand()
  }, [startVoiceCommand])  // Only depends on stable startVoiceCommand

  const handleNativeAudioResponse = useCallback((payload: Record<string, unknown>) => {
    if (payload.debug_text && typeof payload.debug_text === 'string') {
      setFeedbackMessage(payload.debug_text)
      setTimeout(() => setFeedbackMessage(""), 5000)
    }
  }, [])

  // Register callbacks only once on mount
  useEffect(() => {
    if (onCallbacksReady) {
      onCallbacksReady({
        handleWakeDetected,
        handleNativeAudioResponse
      })
    }
  }, [])  // Empty deps - register once, refs keep values current

  // --- Visual Scaling & Color Unification ---
  // Phase 132: Structural Stability & Absolute Color Fidelity
  // Remove all whitening mixes to ensure 100% theme accuracy
  const activeColor = isError
    ? "#ff0000" // Red for error state
    : (isListening || isSpeaking)
      ? glowColor
      : isProcessing
        ? "#7000ff"
        : glowColor
  const effectiveGlowColor = isVoiceActive ? activeColor : glowColor

  // Orb retreat effects when wings are open
  // When UI_STATE_CHAT_OPEN or UI_STATE_BOTH_OPEN: scale 0.85, blur 2px, opacity 0.6
  // When UI_STATE_IDLE: scale 1, blur 0px, opacity 1
  const isWingsOpen = uiState === UILayoutState.UI_STATE_CHAT_OPEN || uiState === UILayoutState.UI_STATE_BOTH_OPEN
  const orbRetreatScale = isWingsOpen ? 0.85 : 1.0
  const orbBlur = isWingsOpen ? 2 : 0
  const orbOpacity = isWingsOpen ? 0.6 : 1.0

  // Phase 128: Toned down expansion for better balance
  const baseScale = isExpanded ? 1.1 : 1
  const effectiveScale = isPressed
    ? 0.92
    : isListening ? 1.15 // Reduced from 1.3
      : isSpeaking ? 1.1 // Reduced from 1.2
        : isProcessing ? 1.08 // Reduced from 1.15
          : isError ? 1.0 // No scale change for error, just shake animation
            : baseScale
  
  // Apply orb retreat scale on top of other scales
  const finalScale = effectiveScale * orbRetreatScale

  return (
    <motion.div
      ref={orbRef}
      className="relative flex items-center justify-center rounded-full cursor-pointer pointer-events-auto"
      style={{ 
        width: size, 
        height: size, 
        overflow: 'visible',
        zIndex: 0 // Set z-index to 0 as per requirements
      }}
      onMouseDown={handleMouseDown}
      animate={{ 
        scale: finalScale,
        filter: `blur(${orbBlur}px)`,
        opacity: orbOpacity,
        // Shake animation for error state
        x: isError ? [0, -10, 10, -10, 10, 0] : 0,
      }}
      transition={{ 
        scale: { type: "spring", stiffness: 300, damping: 25 },
        filter: { duration: 0.3, ease: "easeOut" },
        opacity: { duration: 0.3, ease: "easeOut" },
        x: isError ? { duration: 0.5, repeat: Infinity, repeatDelay: 2 } : { duration: 0 }
      }}
    >
      {/* 0.0 STATIC PERSISTENT HAZE - Phase 125: Base Persistence Layer */}
      <AnimatePresence>
        {isVoiceActive && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 0.25 }} // Reduced from 0.4
            exit={{ opacity: 0 }}
            className="absolute rounded-full pointer-events-none"
            style={{
              inset: -60, // Pulled in from -100
              background: `radial-gradient(circle, color-mix(in srgb, ${effectiveGlowColor}, transparent 20%) 0%, transparent 75%)`,
              filter: "blur(40px)", // Sharpened from 60px
              zIndex: 0
            }}
          />
        )}
      </AnimatePresence>

      {/* 0. ATMOSPHERIC BRAND PULSE - Phase 123: Overdrive Expansion */}
      <motion.div
        className="absolute rounded-full pointer-events-none"
        animate={{
          opacity: isVoiceActive ? [0.4, 0.7, 0.4] : [0.3, 0.6, 0.3],
          scale: isVoiceActive 
            ? [audioLevelScale * 1.0, audioLevelScale * 1.15, audioLevelScale * 1.0] 
            : [0.95, 1.05, 0.95], // Tightened scaling
        }}
        transition={{
          duration: isVoiceActive ? 0.8 : 4, // Even faster heartbeat in active mode
          repeat: Infinity,
          ease: "easeInOut"
        }}
        style={{
          inset: isVoiceActive ? -90 : -60, // Pulled in from -140/-80
          background: `radial-gradient(circle, color-mix(in srgb, ${effectiveGlowColor}, transparent 10%) 0%, transparent 75%)`,
          filter: "blur(70px)",
          zIndex: 0
        }}
      />

      {/* 1. NEON LAYER STACK (Outermost) - Phase 111: Vibrant & Shimmering */}
      {/* 1.1 NEON CORE (Solid Edge) */}
      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{
          inset: -4,
          background: `radial-gradient(circle, ${effectiveGlowColor} 0%, transparent 80%)`,
          border: `2px solid ${effectiveGlowColor}`,
          filter: "blur(2px)",
          opacity: isVoiceActive ? 1.0 : 0.8,
          boxShadow: isVoiceActive ? `0 0 20px ${effectiveGlowColor}` : "none",
          zIndex: 1
        }}
      />

      {/* 1.15 PLASMA CORONA - Phase 124: Enhanced Energy Swirl */}
      <AnimatePresence mode="popLayout">
        {isVoiceActive && (
          <motion.div
            initial={{ opacity: 0, scale: 0.5, rotate: -45 }}
            animate={{ opacity: 1, scale: 1, rotate: 0 }}
            exit={{ opacity: 0, scale: 0.5, rotate: 45 }}
            className="absolute rounded-full pointer-events-none"
            style={{
              inset: -55,
              background: `conic-gradient(from 0deg, 
                transparent, 
                ${effectiveGlowColor}, 
                transparent, 
                #ffffff, 
                transparent,
                ${effectiveGlowColor},
                transparent)`,
              filter: "blur(12px)",
              mixBlendMode: "screen",
              zIndex: 1
            }}
          >
            <motion.div
              className="absolute inset-0 rounded-full"
              animate={{ rotate: 360 }}
              transition={{ duration: 0.6, repeat: Infinity, ease: "linear" }}
              style={{
                background: `conic-gradient(from 0deg, transparent, #ffffff 40%, transparent)`,
                opacity: 0.8,
                mixBlendMode: "overlay"
              }}
            />
            {/* Energy Spine Ring */}
            <div
              className="absolute inset-2 border-[1.5px] border-white/40 rounded-full"
              style={{ filter: "blur(1px)" }}
            />
          </motion.div>
        )}
      </AnimatePresence>

      {/* 1.2 NEON EDGE BLOOM with KINETIC SHIMMER */}
      <motion.div
        className="absolute rounded-full pointer-events-none"
        animate={{
          scale: isVoiceActive ? [audioLevelScale, audioLevelScale * 1.15, audioLevelScale] : 1,
          opacity: isVoiceActive ? [0.6 + (audioLevel * 0.3), 0.9, 0.6 + (audioLevel * 0.3)] : 0.6
        }}
        transition={{
          duration: isVoiceActive ? 0.8 : 3,
          repeat: Infinity,
          ease: "easeInOut"
        }}
        style={{
          inset: -30, // Edge bloom spread
          background: `radial-gradient(circle, color-mix(in srgb, ${effectiveGlowColor}, transparent 30%) 0%, transparent 75%)`,
          filter: "blur(20px)",
          zIndex: 1
        }}
      >
        {/* The "Shimmer off the edge" rotating light spike */}
        <motion.div
          className="absolute inset-0 rounded-full"
          style={{
            background: `conic-gradient(from 0deg, 
              transparent 0deg, 
              rgba(255,255,255,0.4) 45deg, 
              ${effectiveGlowColor} 90deg, 
              transparent 180deg)`,
            mixBlendMode: "overlay"
          }}
          animate={{ rotate: 360 }}
          transition={{ duration: isVoiceActive ? 1.2 : 4, repeat: Infinity, ease: "linear" }}
        />
      </motion.div>

      {/* 2. LIQUID METAL RING (Structural Refinement) - Phase 112: Flowing Mercury */}
      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{
          inset: 0,
          border: "2.5px solid transparent",
          background: `conic-gradient(from 0deg, 
            #ffffff 0deg, 
            ${effectiveGlowColor} 45deg, 
            ${isVoiceActive ? "#000000" : "#101014"} 120deg, 
            #ffffff 180deg, 
            ${effectiveGlowColor} 225deg, 
            ${isVoiceActive ? "#000000" : "#101014"} 300deg, 
            #ffffff 360deg) border-box`,
          WebkitMask: "linear-gradient(#fff 0 0) padding-box, linear-gradient(#fff 0 0)",
          WebkitMaskComposite: "destination-out",
          maskComposite: "exclude",
          filter: "drop-shadow(0 0 3px rgba(255,255,255,0.6))", // Enhanced specularity
          zIndex: 2
        }}
        animate={{
          rotate: 360,
          // Phase 132: Dramatic Audio Jitter (Mechanical reaction to speech)
          scale: isSpeaking ? [1, 1.05, 0.98, 1.03, 1] : 1
        }}
        transition={{
          rotate: { duration: isVoiceActive ? 1.5 : 6, repeat: Infinity, ease: "linear" },
          scale: { duration: 0.2, repeat: Infinity, ease: "easeInOut" }
        }}
      />

      {/* 3. GLASSMORPHIC BASE & 4. CONVEX HIGHLIGHT - Phase 113: Inverted Groove */}
      <div
        className="relative w-full h-full flex items-center justify-center rounded-full pointer-events-none overflow-hidden"
        style={{
          // Phase 132: Static Structural Body (Never changes background/filter/shadow)
          background: `linear-gradient(135deg, rgba(30, 32, 40, 0.7) 0%, color-mix(in srgb, ${glowColor}, transparent 75%) 100%)`,
          backdropFilter: "blur(12px)",
          WebkitBackdropFilter: "blur(12px)",
          boxShadow: "0 10px 30px rgba(0,0,0,0.5), inset 0 2px 4px rgba(255,255,255,0.2)",
          zIndex: 3
        }}
      >
        {/* Phase 132: Additive Internal Aura Tint (No material change) */}
        <AnimatePresence>
          {isVoiceActive && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 0.3 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 rounded-full"
              style={{
                background: `radial-gradient(circle at 30% 30%, color-mix(in srgb, ${effectiveGlowColor}, transparent 40%) 0%, transparent 80%)`,
                mixBlendMode: "screen",
                zIndex: 0
              }}
            />
          )}
        </AnimatePresence>
        {/* 4.5 REACTOR BACKLIGHT - Phase 125/128: Backlit Content Core */}
        <AnimatePresence>
          {isVoiceActive && (
            <motion.div
              initial={{ opacity: 0, scale: 0.5 }}
              animate={{ opacity: 0.25, scale: 1.1 }} // Reduced further from 0.4
              exit={{ opacity: 0, scale: 0.5 }}
              className="absolute rounded-full pointer-events-none"
              style={{
                width: "60%",
                height: "60%",
                background: `radial-gradient(circle, #ffffff 0%, ${effectiveGlowColor} 40%, transparent 100%)`,
                filter: "blur(15px)",
                opacity: 0.2, // Reduced from 0.5
                zIndex: 1
              }}
            />
          )}
        </AnimatePresence>

        {/* Subtle inner gradient for extra depth depth */}
        <div
          className="absolute inset-0 rounded-full"
          style={{
            background: `radial-gradient(circle at 30% 30%, rgba(255,255,255,0.05) 0%, transparent 60%)`
          }}
        />

        {/* 5. CONTENT AREA (Center) - Phase 107 */}
        <AnimatePresence mode="wait">
          <motion.div
            key={feedbackMessage || centerLabel}
            className="relative z-10 flex flex-col items-center justify-center p-4 text-center"
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{
              scale: isSpeaking ? [1, 1.03, 0.98, 1.01, 1] : 1,
              opacity: 1,
              filter: (isSpeaking || isListening || isProcessing)
                ? `drop-shadow(0 0 15px ${effectiveGlowColor})`
                : "none"
            }}
            exit={{ scale: 0.9, opacity: 0 }}
            transition={{
              scale: isSpeaking ? { duration: 0.4, repeat: Infinity, ease: "linear" } : { type: "spring", stiffness: 300, damping: 25 },
              opacity: { type: "spring", stiffness: 300, damping: 25 }
            }}
          >
            {isError ? (
              <span
                className="text-red-500 font-black uppercase tracking-[0.2em] select-none pointer-events-none"
                style={{
                  fontSize: '0.75rem',
                  textShadow: '0 2px 4px rgba(0,0,0,0.5)',
                  lineHeight: 1.2
                }}
              >
                ERROR
              </span>
            ) : feedbackMessage || centerLabel ? (
              <span
                className="text-white font-black uppercase tracking-[0.2em] select-none pointer-events-none"
                style={{
                  fontSize: (feedbackMessage || centerLabel || '').length > 8 ? '0.75rem' : '0.9rem',
                  textShadow: '0 2px 4px rgba(0,0,0,0.5)',
                  lineHeight: 1.2
                }}
              >
                {feedbackMessage || centerLabel}
              </span>
            ) : (
              <div className="w-8 h-8 rounded-full bg-white/10 blur-sm animate-pulse" />
            )}
          </motion.div>
        </AnimatePresence>
      </div>

      {/* 7. Double-click/Wake Flash Overlay */}
      <AnimatePresence>
        {(wakeFlash || doubleClickFlash) && (
          <motion.div
            className="absolute rounded-full pointer-events-none"
            style={{ inset: 0, backgroundColor: `${effectiveGlowColor}99`, zIndex: 60 }}
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1.5 }}
            exit={{ opacity: 0, scale: 2 }}
            transition={{ duration: 0.5 }}
          />
        )}
      </AnimatePresence>
    </motion.div>
  )
}
