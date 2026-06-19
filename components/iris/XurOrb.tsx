"use client"

import React, { useState, useCallback, useRef, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { useReducedMotion } from "@/hooks/useReducedMotion"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { useManualDragWindow } from "@/hooks/useManualDragWindow"
import { useCadenceDetection } from "@/hooks/useCadenceDetection"
import { UILayoutState } from "@/hooks/useUILayoutState"
import type { XurOrbProps } from "./types"
import { OrbCanvas } from "./orb/OrbCanvas"
import {
  type AnimationMode,
  nextAnimationMode,
  ANIM_DURATION_MS,
} from "./orb/animationModes"
import { GlitchText } from "./radial/GlitchText"
import { RadialArcNodes } from "./radial/RadialArcNodes"

/**
 * XurOrb — the Spiral Dissolve Winner orb component.
 *
 * Replaces IrisOrb.tsx. Composes:
 * - OrbCanvas (canvas particle shells with cadence breathing)
 * - GlitchText labels (MENU / VOICE / CHAT) — always visible at level 1 idle
 * - RadialArcNodes (6 hex category nodes) — level 2 menu when MENU clicked
 * - 3 animation modes (C-opening, D-burst, A-bloom) cycled C→D→A→C on clicks
 * - Cadence breathing at ALL navigation levels (via useCadenceDetection)
 * - Voice activation: VOICE label, double-click, wake word (onCallbacksReady)
 * - Click interception: cancel voice, close wings, navigate back
 */
export function XurOrb({
  isExpanded,
  onClick,
  onDoubleClick,
  size = 200,
  wakeFlash,
  glowColor: glowColorProp,
  uiState = UILayoutState.UI_STATE_IDLE,
  onCategorySelect,
  onMenuClick,
  onChatClick,
  onCallbacksReady,
}: XurOrbProps) {
  // ── Context ──────────────────────────────────────────────────────
  const {
    voiceState,
    startVoiceCommand,
    endVoiceCommand,
    cancelVoiceCommand,
    dispatch,
    setMainView,
  } = useNavigation()
  const { getThemeConfig } = useBrandColor()
  const cadence = useCadenceDetection()

  // ── State ────────────────────────────────────────────────────────
  const [animationMode, setAnimationMode] = useState<AnimationMode>('C')
  const [animActive, setAnimActive] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [doubleClickFlash, setDoubleClickFlash] = useState(false)
  const [isPressed, setIsPressed] = useState(false)
  const [feedbackMessage, setFeedbackMessage] = useState("")

  // ── Refs ─────────────────────────────────────────────────────────
  const orbRef = useRef<HTMLDivElement>(null)
  const prefersReducedMotion = useReducedMotion()
  const animTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── Derived values ───────────────────────────────────────────────
  const theme = getThemeConfig()
  const glowColor = glowColorProp ?? theme.glow.color
  const isVoiceActive = voiceState !== "idle"
  const isListening = voiceState === "listening"
  const isSpeaking = voiceState === "speaking"
  const isProcessing = voiceState === "processing_conversation" || voiceState === "processing_tool"
  const isError = voiceState === "error"
  const isWingsOpen =
    uiState === UILayoutState.UI_STATE_CHAT_OPEN ||
    uiState === UILayoutState.UI_STATE_BOTH_OPEN

  // ── Animation trigger ────────────────────────────────────────────
  const triggerAnimation = useCallback(() => {
    if (prefersReducedMotion) return
    setAnimationMode((cur) => nextAnimationMode(cur))
    setAnimActive(true)
    if (animTimerRef.current) clearTimeout(animTimerRef.current)
    animTimerRef.current = setTimeout(() => setAnimActive(false), ANIM_DURATION_MS[animationMode])
  }, [prefersReducedMotion, animationMode])

  // ── Click handlers ───────────────────────────────────────────────

  // Orb click — cycle animation mode + do navigation
  const handleOrbClick = useCallback(() => {
    // Interception: if voice active → cancel voice
    if (isVoiceActive) {
      cancelVoiceCommand()
      return
    }
    // If wings open → close
    if (isWingsOpen) {
      onClick()
      return
    }
    // Cycle animation mode
    triggerAnimation()
    // Navigation: go back if level > 1 (close menu if open)
    if (menuOpen) {
      setMenuOpen(false)
    }
    onClick()
  }, [isVoiceActive, cancelVoiceCommand, isWingsOpen, onClick, menuOpen, triggerAnimation])

  // Double-click toggles voice: starts if idle, stops if active
  const handleDoubleClick = useCallback(() => {
    if (isVoiceActive) {
      endVoiceCommand()
    } else {
      startVoiceCommand()
    }
    onDoubleClick()
  }, [isVoiceActive, startVoiceCommand, endVoiceCommand, onDoubleClick])

  // Glitch label handlers — also cycle animation mode
  const handleMenuClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    triggerAnimation()
    setMenuOpen((prev) => !prev)
    onMenuClick?.()
  }, [triggerAnimation, onMenuClick])

  const handleVoiceClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    if (isVoiceActive) {
      endVoiceCommand()
    } else {
      startVoiceCommand()
    }
  }, [isVoiceActive, startVoiceCommand, endVoiceCommand])

  const handleChatClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    triggerAnimation()
    onChatClick?.()
  }, [triggerAnimation, onChatClick])

  // Hex node click — goes directly to WheelView, no animation
  const handleCategorySelect = useCallback((categoryId: string) => {
    onCategorySelect?.(categoryId)
    dispatch({ type: "EXPAND_TO_MAIN" })
  }, [onCategorySelect, dispatch])

  // ── Window drag + double-click ───────────────────────────────────
  const { handleMouseDown } = useManualDragWindow(
    orbRef,
    handleOrbClick,
    handleDoubleClick,
    setDoubleClickFlash,
    setIsPressed
  )

  // ── Wake word bridge (Task 15) ───────────────────────────────────
  const isListeningRef = useRef(isListening)
  isListeningRef.current = isListening

  const handleWakeDetected = useCallback(() => {
    if (isListeningRef.current) return
    startVoiceCommand()
  }, [startVoiceCommand])

  const handleNativeAudioResponse = useCallback((payload: Record<string, unknown>) => {
    if (payload.debug_text && typeof payload.debug_text === 'string') {
      setFeedbackMessage(payload.debug_text)
      setTimeout(() => setFeedbackMessage(""), 5000)
    }
  }, [])

  useEffect(() => {
    onCallbacksReady?.({
      handleWakeDetected,
      handleNativeAudioResponse,
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Flash on voice state transition into listening
  const prevVoiceStateRef = useRef(voiceState)
  useEffect(() => {
    const prev = prevVoiceStateRef.current
    prevVoiceStateRef.current = voiceState
    if (prev !== "listening" && voiceState === "listening") {
      setDoubleClickFlash(true)
      setTimeout(() => setDoubleClickFlash(false), 600)
    }
  }, [voiceState])

  // Cleanup animation timer
  useEffect(() => {
    return () => {
      if (animTimerRef.current) clearTimeout(animTimerRef.current)
    }
  }, [])

  // ── Visual scaling ───────────────────────────────────────────────
  const isWingsOpenForLabels = isWingsOpen
  const labelsVisible = !isWingsOpenForLabels && !menuOpen

  const orbRetreatScale = isWingsOpen ? 0.85 : 1.0
  const orbBlur = isWingsOpen ? 2 : 0
  const orbOpacity = isWingsOpen ? 0.6 : 1.0
  const baseScale = isExpanded ? 1.1 : 1
  const effectiveScale = isPressed
    ? 0.92
    : isSpeaking ? 1.2
      : isListening ? 1.15
        : isProcessing ? 1.08
          : isError ? 1.0
            : baseScale
  const finalScale = effectiveScale * orbRetreatScale

  // Active color for voice states
  const activeColor = isError
    ? "#ff0000"
    : isSpeaking
      ? `color-mix(in srgb, ${glowColor}, #ffffff 25%)`
      : isListening
        ? glowColor
        : isProcessing
          ? "#7000ff"
          : glowColor
  const effectiveGlowColor = isVoiceActive ? activeColor : glowColor

  // Canvas size — smaller than container to leave room for labels
  const canvasSize = Math.min(size * 0.45, 90)

  return (
    <motion.div
      ref={orbRef}
      className="relative flex items-center justify-center rounded-full cursor-pointer pointer-events-auto"
      style={{
        width: size,
        height: size,
        overflow: 'visible',
        zIndex: 0,
      }}
      onMouseDown={handleMouseDown}
      onDoubleClick={(e) => {
        e.preventDefault()
        handleDoubleClick()
      }}
      animate={{
        scale: finalScale,
        filter: `blur(${orbBlur}px)`,
        opacity: orbOpacity,
        x: isError ? [0, -10, 10, -10, 10, 0] : 0,
      }}
      transition={{
        scale: { type: "spring", stiffness: 300, damping: 25 },
        filter: { duration: 0.3, ease: "easeOut" },
        opacity: { duration: 0.3, ease: "easeOut" },
        x: isError ? { duration: 0.5, repeat: Infinity, repeatDelay: 2 } : { duration: 0 },
      }}
    >
      {/* Voice-active haze */}
      <AnimatePresence>
        {isVoiceActive && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 0.25 }}
            exit={{ opacity: 0 }}
            className="absolute rounded-full pointer-events-none"
            style={{
              inset: -60,
              background: `radial-gradient(circle, ${effectiveGlowColor}22 0%, transparent 70%)`,
            }}
          />
        )}
      </AnimatePresence>

      {/* OrbCanvas — the particle shell visual */}
      <div className="relative flex items-center justify-center" style={{ width: canvasSize, height: canvasSize }}>
        <OrbCanvas
          glowColor={effectiveGlowColor}
          breathMode={cadence.breathMode}
          breathLevel={cadence.breathLevel}
          isBreathing={cadence.isBreathing}
          animationMode={animationMode}
          animActive={animActive}
        />
      </div>

      {/* RadialArcNodes — level 2 category menu (visible when MENU clicked) */}
      <div
        className="absolute"
        style={{
          left: '50%',
          top: '50%',
          transform: 'translate(-50%, -50%)',
          zIndex: 5,
          pointerEvents: menuOpen ? 'auto' : 'none',
        }}
      >
        <RadialArcNodes
          glowColor={effectiveGlowColor}
          isVisible={menuOpen}
          onCategorySelect={handleCategorySelect}
        />
      </div>

      {/* GlitchText labels — MENU / VOICE / CHAT (always visible at level 1 idle) */}
      <div
        className="absolute"
        style={{
          left: '50%',
          top: '50%',
          transform: 'translate(-50%, -50%)',
          width: size,
          height: size,
          pointerEvents: 'none',
          zIndex: 10,
        }}
      >
        {/* MENU — bottom */}
        <div
          style={{
            position: 'absolute',
            left: '50%',
            bottom: -8,
            transform: 'translateX(-50%)',
            pointerEvents: 'auto',
          }}
          onClick={handleMenuClick}
        >
          <GlitchText
            text="MENU"
            visible={labelsVisible}
            color={effectiveGlowColor}
            fontSize={11}
          />
        </div>

        {/* VOICE — left */}
        <div
          style={{
            position: 'absolute',
            left: -4,
            top: '50%',
            transform: 'translateY(-50%)',
            pointerEvents: 'auto',
          }}
          onClick={handleVoiceClick}
        >
          <GlitchText
            text="VOICE"
            visible={labelsVisible}
            color={effectiveGlowColor}
            fontSize={11}
          />
        </div>

        {/* CHAT — right */}
        <div
          style={{
            position: 'absolute',
            right: -4,
            top: '50%',
            transform: 'translateY(-50%)',
            pointerEvents: 'auto',
          }}
          onClick={handleChatClick}
        >
          <GlitchText
            text="CHAT"
            visible={labelsVisible}
            color={effectiveGlowColor}
            fontSize={11}
          />
        </div>
      </div>

      {/* Wake flash / double-click flash overlay */}
      <AnimatePresence>
        {(wakeFlash || doubleClickFlash) && (
          <motion.div
            initial={{ opacity: 0.8 }}
            animate={{ opacity: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.5 }}
            className="absolute rounded-full pointer-events-none"
            style={{ inset: 0, background: 'white' }}
          />
        )}
      </AnimatePresence>

      {/* Feedback message (from native audio response) */}
      <AnimatePresence>
        {feedbackMessage && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            className="absolute pointer-events-none"
            style={{
              bottom: -30,
              left: '50%',
              transform: 'translateX(-50%)',
              whiteSpace: 'nowrap',
              fontSize: 10,
              color: effectiveGlowColor,
              fontFamily: "'Courier New', Courier, monospace",
              textShadow: `0 0 8px ${effectiveGlowColor}80`,
            }}
          >
            {feedbackMessage}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
