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
import { RadialArcNodes } from "./radial/RadialArcNodes"

// ── Label configuration (matches PrototypeOrbShellsRotating winner) ────
// Positions are relative to orb center in a 180px container.
// CHAT at bottom, MENU at top, VOICE at left — exactly as the winner.

const CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789→↑←'

const LABELS = [
  { final: '→ Chat ←', x: 0, y: 68, swirl: '180deg', action: 'chat' as const },
  { final: '↑ Menu', x: 0, y: -68, swirl: '-120deg', action: 'menu' as const },
  { final: '↑↑ Voice', x: -68, y: 30, swirl: '240deg', action: 'voice' as const },
]

const CANVAS_SIZE = 90
const CONTAINER_SIZE = 180

/**
 * XurOrb — the Spiral Dissolve Winner orb component.
 *
 * Replaces IrisOrb.tsx. Composes:
 * - OrbCanvas (canvas particle shells with cadence breathing)
 * - Glitch labels (→ Chat ← / ↑ Menu / ↑↑ Voice) — always visible at level 1 idle
 *   with scramble cycling every 2800ms and C/D/A click text animations
 * - RadialArcNodes (6 hex category nodes) — level 2 menu when MENU clicked
 * - 3 animation modes (C-opening, D-burst, A-bloom) cycled C→D→A→C on clicks
 * - Cadence breathing at ALL navigation levels (via useCadenceDetection)
 * - Voice activation: VOICE label, double-click, wake word (onCallbacksReady)
 * - Click interception: cancel voice, close wings, navigate back
 * - Transparent background — XurOrb is the only thing visible
 */
export function XurOrb({
  isExpanded,
  onClick,
  onDoubleClick,
  size = CONTAINER_SIZE,
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
    handleSelectMain,
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

  // ── Label scramble state (matches PrototypeOrbShellsRotating) ─────
  const [activeIdx, setActiveIdx] = useState(0)
  const [scrambledSet, setScrambledSet] = useState<Set<number>>(new Set())
  const [displayTexts, setDisplayTexts] = useState<string[]>(['', '', ''])
  const [isAnimatingText, setIsAnimatingText] = useState(false)
  const scrambleTimersRef = useRef<ReturnType<typeof setInterval>[]>([])
  const switchTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

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

  // ── Label scramble function (from PrototypeOrbShellsRotating) ─────
  const scramble = useCallback((idx: number, finalText: string) => {
    const len = finalText.length
    let frame = 0
    const totalFrames = 24
    if (scrambleTimersRef.current[idx]) clearInterval(scrambleTimersRef.current[idx])
    const timer = setInterval(() => {
      frame++
      let out = ''
      for (let i = 0; i < len; i++) {
        if (frame / totalFrames > i / len) {
          out += finalText[i]
        } else {
          out += CHARS[Math.floor(Math.random() * CHARS.length)]
        }
      }
      setDisplayTexts(prev => {
        const next = [...prev]
        next[idx] = out
        return next
      })
      if (frame >= totalFrames) {
        clearInterval(timer)
        setDisplayTexts(prev => {
          const next = [...prev]
          next[idx] = finalText
          return next
        })
      }
    }, 30)
    scrambleTimersRef.current[idx] = timer
  }, [])

  // ── Label cycling — switch active label every 2800ms ──────────────
  useEffect(() => {
    switchTimerRef.current = setInterval(() => {
      setActiveIdx(prev => {
        const next = (prev + 1) % 3
        setScrambledSet(s => {
          const ns = new Set(s)
          ns.delete(next)
          return ns
        })
        return next
      })
    }, 2800)
    return () => {
      if (switchTimerRef.current) clearInterval(switchTimerRef.current)
    }
  }, [])

  // ── Trigger scramble when active label changes ────────────────────
  useEffect(() => {
    if (!scrambledSet.has(activeIdx)) {
      scramble(activeIdx, LABELS[activeIdx].final)
      setScrambledSet(s => new Set([...s, activeIdx]))
    }
  }, [activeIdx, scrambledSet, scramble])

  // ── Cleanup scramble timers ───────────────────────────────────────
  useEffect(() => {
    return () => {
      scrambleTimersRef.current.forEach(t => clearInterval(t))
    }
  }, [])

  // ── Animation trigger ────────────────────────────────────────────
  const triggerAnimation = useCallback(() => {
    if (prefersReducedMotion) return
    setAnimationMode((cur) => nextAnimationMode(cur))
    setAnimActive(true)
    setIsAnimatingText(true)
    if (animTimerRef.current) clearTimeout(animTimerRef.current)
    animTimerRef.current = setTimeout(() => setAnimActive(false), ANIM_DURATION_MS[animationMode])
  }, [prefersReducedMotion, animationMode])

  const handleTextAnimEnd = useCallback(() => {
    setTimeout(() => setIsAnimatingText(false), 700)
  }, [])

  // ── Click handlers ───────────────────────────────────────────────

  const handleOrbClick = useCallback(() => {
    if (isVoiceActive) {
      cancelVoiceCommand()
      return
    }
    if (isWingsOpen) {
      onClick()
      return
    }
    triggerAnimation()
    if (menuOpen) {
      setMenuOpen(false)
    }
    onClick()
  }, [isVoiceActive, cancelVoiceCommand, isWingsOpen, onClick, menuOpen, triggerAnimation])

  const handleDoubleClick = useCallback(() => {
    if (isVoiceActive) {
      endVoiceCommand()
    } else {
      startVoiceCommand()
    }
    onDoubleClick()
  }, [isVoiceActive, startVoiceCommand, endVoiceCommand, onDoubleClick])

  // Label click handlers — cycle animation + trigger action
  const handleLabelClick = useCallback((action: 'chat' | 'menu' | 'voice', e: React.MouseEvent) => {
    e.stopPropagation()
    triggerAnimation()
    if (action === 'menu') {
      setMenuOpen((prev) => !prev)
      onMenuClick?.()
    } else if (action === 'voice') {
      if (isVoiceActive) {
        endVoiceCommand()
      } else {
        startVoiceCommand()
      }
    } else if (action === 'chat') {
      onChatClick?.()
    }
  }, [triggerAnimation, onMenuClick, onChatClick, isVoiceActive, startVoiceCommand, endVoiceCommand])

  const handleCategorySelect = useCallback((categoryId: string) => {
    onCategorySelect?.(categoryId)
    // handleSelectMain aggregates cards for the category and dispatches
    // SELECT_MAIN (level 3 → WheelView) with the correct card data.
    // It also sends the select_category WS message to the backend.
    handleSelectMain(categoryId)
  }, [onCategorySelect, handleSelectMain])

  // ── Window drag + double-click ───────────────────────────────────
  const { handleMouseDown } = useManualDragWindow(
    orbRef,
    handleOrbClick,
    handleDoubleClick,
    setDoubleClickFlash,
    setIsPressed
  )

  // ── Wake word bridge ──────────────────────────────────────────────
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
  // Color does NOT change based on clicks or voice state — color changes
  // only happen through the customize category in the side panel.
  // Voice state affects scale/shape only, not color.
  const labelsVisible = !isWingsOpen && !menuOpen

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

  // ── Text animation class + CSS variables (from PrototypeOrbShellsRotating) ──
  const getTextClass = () => {
    if (!isAnimatingText || !animActive) return ''
    if (animationMode === 'C') return 'xur-text-anim-iris'
    if (animationMode === 'D') return 'xur-text-anim-pull'
    return 'xur-text-anim-fade' // A
  }

  const getTextVars = (label: { x: number; y: number }) => {
    if (animationMode === 'C') {
      const axisCollapse =
        label.x === 0
          ? { x: 0, y: -label.y, sx: 1, sy: 0.1 }
          : { x: -label.x, y: 0, sx: 0.1, sy: 1 }
      return {
        ['--iris-x' as any]: `${axisCollapse.x}px`,
        ['--iris-y' as any]: `${axisCollapse.y}px`,
        ['--iris-sx' as any]: axisCollapse.sx,
        ['--iris-sy' as any]: axisCollapse.sy,
      }
    } else if (animationMode === 'D') {
      return {
        ['--pull-x' as any]: `${-label.x}px`,
        ['--pull-y' as any]: `${-label.y}px`,
      }
    }
    return {}
  }

  return (
    <>
      <motion.div
        ref={orbRef}
        className="relative flex items-center justify-center cursor-pointer pointer-events-auto"
        style={{
          width: CONTAINER_SIZE,
          height: CONTAINER_SIZE,
          perspective: '900px',
          transformStyle: 'preserve-3d',
          overflow: 'visible',
          zIndex: 0,
          background: 'transparent',
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
                background: `radial-gradient(circle, ${glowColor}22 0%, transparent 70%)`,
              }}
            />
          )}
        </AnimatePresence>

        {/* Inner 3D layer — canvas + labels */}
        <div
          className="absolute inset-0 rounded-full flex flex-col items-center justify-center"
          style={{ transform: 'translateZ(12px)', background: 'transparent' }}
        >
          {/* OrbCanvas — floating particle shell visual */}
          <div
            className="relative"
            style={{
              width: `${CANVAS_SIZE}px`,
              height: `${CANVAS_SIZE}px`,
              zIndex: 2,
              animation: 'xurFloat 4s ease-in-out infinite',
            }}
          >
            <OrbCanvas
              glowColor={glowColor}
              breathMode={cadence.breathMode}
              breathLevel={cadence.breathLevel}
              isBreathing={cadence.isBreathing}
              animationMode={animationMode}
              animActive={animActive}
            />
          </div>

          {/* Glitch labels — → Chat ← / ↑ Menu / ↑↑ Voice */}
          <div className="absolute inset-0" style={{ zIndex: 1 }}>
            {LABELS.map((label, i) => (
              <div
                key={i}
                className="absolute"
                style={{
                  left: '50%',
                  top: '50%',
                  transform: `translate(-50%, -50%) translate(${label.x}px, ${label.y}px)`,
                  pointerEvents: labelsVisible ? 'auto' : 'none',
                  opacity: labelsVisible ? 1 : 0,
                  transition: 'opacity 0.3s ease',
                }}
                onClick={(e) => handleLabelClick(label.action, e)}
              >
                <span
                  className={getTextClass()}
                  onAnimationEnd={isAnimatingText ? handleTextAnimEnd : undefined}
                  style={{
                    display: 'block',
                    fontSize: '11px',
                    fontWeight: 700,
                    letterSpacing: '0.12em',
                    textTransform: 'uppercase' as const,
                    color: activeIdx === i ? '#e2e8f0' : '#475569',
                    textShadow: activeIdx === i
                      ? `0 0 16px ${glowColor}55, 0 0 4px ${glowColor}88`
                      : '0 0 6px rgba(148,163,184,0.1)',
                    whiteSpace: 'nowrap',
                    opacity: activeIdx === i ? 1 : 0.4,
                    fontFamily: "'Courier New', Courier, monospace",
                    transformOrigin: 'center center',
                    cursor: 'pointer',
                    userSelect: 'none',
                    ...getTextVars(label),
                  } as React.CSSProperties}
                >
                  {displayTexts[i] || ''}
                </span>
              </div>
            ))}
          </div>
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
            glowColor={glowColor}
            isVisible={menuOpen}
            onCategorySelect={handleCategorySelect}
          />
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
                color: glowColor,
                fontFamily: "'Courier New', Courier, monospace",
                textShadow: `0 0 8px ${glowColor}80`,
              }}
            >
              {feedbackMessage}
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      {/* CSS keyframes for label text animations (C/D/A pairs) */}
      <style>{`
        @keyframes xurFloat {
          0%, 100% { transform: translateY(0px); }
          50% { transform: translateY(-6px); }
        }
        /* C-pair text: iris shutter (axis-specific collapse) */
        @keyframes xurTextAnimIris {
          0% { transform: translate(0, 0) scale(1, 1); opacity: 1; }
          100% { transform: translate(var(--iris-x), var(--iris-y)) scale(var(--iris-sx), var(--iris-sy)); opacity: 0; }
        }
        .xur-text-anim-iris {
          animation: xurTextAnimIris 0.9s cubic-bezier(0.6, 0, 0.8, 1) forwards;
        }
        /* D-pair text: magnetic pull (translate to center, spiral, scale to 0) */
        @keyframes xurTextAnimPull {
          0% { transform: translate(0, 0) scale(1) rotate(0deg); opacity: 1; }
          60% { transform: translate(calc(var(--pull-x) * 0.6), calc(var(--pull-y) * 0.6)) scale(0.6) rotate(180deg); opacity: 0.6; }
          100% { transform: translate(var(--pull-x), var(--pull-y)) scale(0) rotate(360deg); opacity: 0; }
        }
        .xur-text-anim-pull {
          animation: xurTextAnimPull 1s cubic-bezier(0.6, 0, 0.8, 1) forwards;
        }
        /* A-pair text: simple fade out */
        @keyframes xurTextAnimFade {
          0% { opacity: 1; }
          100% { opacity: 0; }
        }
        .xur-text-anim-fade {
          animation: xurTextAnimFade 0.8s ease-out forwards;
        }
      `}</style>
    </>
  )
}
