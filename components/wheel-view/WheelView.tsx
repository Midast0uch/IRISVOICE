"use client"

import React, { useState, useCallback, useEffect, useMemo, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ArrowLeft } from "lucide-react"
import { useManualDragWindow } from "@/hooks/useManualDragWindow"
import { HexPatternRingMechanism } from "./HexPatternRingMechanism"
import { SidePanel } from "./SidePanel"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"
import type { Card, FieldValue } from "@/types/navigation"
import { CARD_TO_SECTION_ID } from "@/data/navigation-constants"

interface WheelViewProps {
  categoryId: string
  glowColor: string
  expandedIrisSize: number
  initialValues?: Record<string, Record<string, FieldValue>>
  onConfirm: (values: Record<string, Record<string, FieldValue>>) => void
  onBackToCategories: () => void
  onBrowseMarketplace?: () => void
}

function validateGlowColor(color: string): string {
  if (color.startsWith('hsl')) return color
  const hexPattern = /^#[0-9A-Fa-f]{6}$/
  if (!hexPattern.test(color)) {
    return "#00D4FF"
  }
  return color
}

export const WheelView: React.FC<WheelViewProps> = ({
  categoryId,
  glowColor: rawGlowColor,
  expandedIrisSize,
  initialValues = {},
  onConfirm,
  onBackToCategories,
  onBrowseMarketplace,
}) => {
  const { state, updateCardValue, voiceState, audioLevel, startVoiceCommand, endVoiceCommand, sendMessage, fieldErrors, selectSectionWs } = useNavigation()
  const {
    getThemeConfig,
    basePlateColor,
    setTheme,
    setHue,
    setSaturation,
    setLightness,
    setBasePlateHue,
    setBasePlateSaturation,
    setBasePlateLightness,
    resetToThemeDefault
  } = useBrandColor()

  const glowColor = useMemo(() => validateGlowColor(rawGlowColor), [rawGlowColor])
  const cardStack = state.cardStack || []

  // Calculate if voice is active from NavigationContext
  const isVoiceActive = voiceState !== "idle"

  // Drag-to-move: attach to the outer container so the entire WheelView widget
  // can be grabbed and repositioned, matching IrisOrb / other navigation states.
  const containerRef = useRef<HTMLDivElement>(null)
  const { handleMouseDown: handleDragMouseDown } = useManualDragWindow(containerRef)

  const lastClickTime = React.useRef<number>(0)
  const clickCount = React.useRef<number>(0)
  const clickTimer = React.useRef<NodeJS.Timeout | null>(null)

  const [selectedIndex, setSelectedIndex] = useState(0)
  const [confirmFlash, setConfirmFlash] = useState(false)
  const [confirmSpinning, setConfirmSpinning] = useState(false)
  const [lineRetracted, setLineRetracted] = useState(false)
  const [showPanel, setShowPanel] = useState(true)
  const [isAnimating, setIsAnimating] = useState(false)

  const activeCard = useMemo(() => {
    return cardStack[selectedIndex] || cardStack[0]
  }, [cardStack, selectedIndex])

  const fieldValues = useMemo(() => {
    return state.cardValues[activeCard?.id] || {}
  }, [state.cardValues, activeCard])

  const handleSelect = useCallback((index: number) => {
    if (isAnimating) return
    setIsAnimating(true)
    setSelectedIndex(index)
    setShowPanel(true)

    // Sync dashboard: map selected card's ID to its section ID so the
    // dashboard highlights the same section without manual coordination.
    const selectedCard = cardStack[index]
    if (selectedCard) {
      const sectionId = CARD_TO_SECTION_ID[selectedCard.id]
      if (sectionId && selectSectionWs) {
        selectSectionWs(sectionId)
      }
    }

    setTimeout(() => setIsAnimating(false), 500)
  }, [isAnimating, cardStack, selectSectionWs])

  const handleValueChange = useCallback((fieldId: string, value: FieldValue) => {
    if (!activeCard) return

    // Real-time synchronization for Theme Mode fields
    if (activeCard.id === 'theme-mode') {
      switch (fieldId) {
        case 'active_theme':
          setTheme(value.toString().toLowerCase() as any)
          break
        case 'brand_hue':
          setHue(Number(value))
          break
        case 'brand_saturation':
          setSaturation(Number(value))
          break
        case 'brand_lightness':
          setLightness(Number(value))
          break
        case 'base_plate_hue':
          setBasePlateHue(Number(value))
          break
        case 'base_plate_saturation':
          setBasePlateSaturation(Number(value))
          break
        case 'base_plate_lightness':
          setBasePlateLightness(Number(value))
          break
        case 'reset_to_defaults':
          resetToThemeDefault()
          break
      }
    }

    // Update local state only — service changes are deferred to Confirm (confirm_card).
    updateCardValue(activeCard.id, fieldId, value)

    // Special case: when model_provider changes, fetch the available models for the
    // newly selected backend so the model dropdowns update before the user confirms.
    // This is a READ-only operation and does not reinitialize any service.
    if (fieldId === "model_provider") {
      sendMessage("get_available_models", { model_provider: value })
    }
  }, [activeCard, updateCardValue, sendMessage, setTheme, setHue, setSaturation, setLightness, setBasePlateHue, setBasePlateSaturation, setBasePlateLightness, resetToThemeDefault])

  const handleConfirm = useCallback(() => {
    if (isAnimating) return
    setIsAnimating(true)
    setLineRetracted(true)
    setConfirmSpinning(true)
    setConfirmFlash(true)

    setTimeout(() => {
      // Send confirm_card for the active card's section with all current field values.
      // This is the single authoritative signal for the backend to apply service changes.
      const sectionId = activeCard ? CARD_TO_SECTION_ID[activeCard.id] : null
      if (sectionId && activeCard) {
        const sectionValues = state.cardValues[activeCard.id] ?? {}
        sendMessage('confirm_card', {
          section_id: sectionId,
          values: sectionValues
        })
      }
      onConfirm(state.cardValues)
      setLineRetracted(false)
      setConfirmSpinning(false)
      setConfirmFlash(false)
      setIsAnimating(false)
    }, 900)
  }, [isAnimating, onConfirm, state.cardValues, activeCard, sendMessage])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter", "Escape"].includes(e.key)) {
        e.preventDefault()
      }
      if (isAnimating && e.key !== "Escape") return

      switch (e.key) {
        case "ArrowRight":
        case "ArrowDown":
          setSelectedIndex((prev) => (prev + 1) % cardStack.length)
          break
        case "ArrowLeft":
        case "ArrowUp":
          setSelectedIndex((prev) => (prev - 1 + cardStack.length) % cardStack.length)
          break
        case "Enter":
          handleConfirm()
          break
        case "Escape":
          onBackToCategories()
          break
      }
    }

    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [cardStack.length, isAnimating, handleConfirm, onBackToCategories])

  // Cleanup click timer on unmount
  useEffect(() => {
    return () => {
      if (clickTimer.current) {
        clearTimeout(clickTimer.current)
      }
    }
  }, [])

  if (cardStack.length === 0) {
    return (
      <div className="absolute inset-0 flex items-center justify-center">
        <div className="text-white/40 text-sm">No settings available</div>
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 flex items-center justify-center bg-transparent"
      onMouseDown={handleDragMouseDown}
      style={{ cursor: "grab" }}
    >
      <div
        className="relative flex items-center justify-start pointer-events-none"
        style={{ width: 595, height: 525, paddingLeft: "28px", overflow: 'visible' }}
      >
        {/* Mechanics Stage: 420x420 — 0.7x of original 600x600 */}
        {/* Clip overflow to prevent outer ring from spinning outside container bounds */}
        <div
          className="relative pointer-events-none flex items-center justify-center shrink-0"
          style={{ width: 420, height: 420, overflow: 'hidden' }}
        >
          {/* Centered Mechanims Layer - Absolute Visibility (Phase 50) */}
          <div className="relative" style={{ width: 210, height: 210, overflow: 'visible' }}>

            {/* 1. AmbientGlowLayer (z-20) - Extreme Soft Pulse */}
            <motion.div
              style={{
                position: 'absolute',
                top: '50%',
                left: '50%',
                width: '160%',
                height: '160%',
                background: `radial-gradient(circle, ${glowColor}0F 0%, transparent 70%)`,
                filter: 'blur(30px)',
                zIndex: -20,
                pointerEvents: 'none',
              }}
              animate={{
                scale: [1, 1.1, 1],
                opacity: [0.7, 1, 0.7]
              }}
              transition={{
                duration: 8,
                repeat: Infinity,
                ease: "easeInOut"
              }}
            />

            {/* 2. BasePlateLayer (z-10) - Industrial Foundation (Phase 99: Gunmetal Skin) */}
            <div
              style={{
                position: 'absolute',
                top: '50%',
                left: '50%',
                width: '98%',
                height: '98%',
                transform: 'translate(-50%, -50%)',
                background: 'radial-gradient(circle at 50% 50%, #1C2026 0%, #0F1115 100%)',
                borderRadius: '50%',
                border: `1px solid ${glowColor}26`,
                boxShadow: `
                  0 5px 20px rgba(0,0,0,0.6),
                  inset 0 0 10px rgba(255,255,255,0.02)
                `,
                zIndex: -10,
                pointerEvents: 'none',
              }}
            />

            {/* 3. DepthGrooveLayer (z-0) - Recessed Well Effect */}
            <div
              style={{
                position: 'absolute',
                top: '50%',
                left: '50%',
                width: '92%',
                height: '92%',
                transform: 'translate(-50%, -50%)',
                background: 'transparent',
                borderRadius: '50%',
                boxShadow: `
                  inset 0 4px 8px rgba(0,0,0,0.8),
                  inset 0 -2px 4px rgba(255,255,255,0.03),
                  0 0 5px rgba(0,0,0,0.4)
                `,
                zIndex: 0,
                pointerEvents: 'none',
              }}
            />

            <HexPatternRingMechanism
              items={cardStack}
              selectedIndex={selectedIndex}
              onSelect={handleSelect}
              glowColor={glowColor}
              basePlateColor={`hsl(${basePlateColor.hue}, ${basePlateColor.saturation}%, ${basePlateColor.lightness}%)`}
              orbSize={210}
              confirmSpinning={confirmSpinning}
              isVoiceActive={isVoiceActive}
              voiceIntensity={audioLevel}
            />

            {/* Voice Active Atmospheric Pulse - Behind Button (z-index: 98) */}
            <AnimatePresence>
              {isVoiceActive && (
                <motion.div
                  className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full pointer-events-none"
                  style={{
                    width: 70,
                    height: 70,
                    background: `radial-gradient(circle, ${glowColor}40 0%, ${glowColor}20 50%, transparent 100%)`,
                    filter: "blur(10px)",
                    zIndex: 98
                  }}
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{
                    opacity: [0.6, 1, 0.6],
                    scale: [0.9, 1.3, 0.9]
                  }}
                  exit={{ opacity: 0, scale: 0.8 }}
                  transition={{
                    duration: 2.5,
                    repeat: Infinity,
                    ease: "easeInOut"
                  }}
                />
              )}
            </AnimatePresence>

            {/* Audio Level Visualization - Concentric Rings (z-index: 97) */}
            <AnimatePresence>
              {voiceState === 'listening' && audioLevel > 0 && (
                <>
                  {[0, 1, 2].map((ringIndex) => (
                    <motion.div
                      key={ringIndex}
                      className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full pointer-events-none"
                      style={{
                        width: 70 + ringIndex * 21,
                        height: 70 + ringIndex * 21,
                        border: `1px solid ${glowColor}`,
                        opacity: 0.3 - ringIndex * 0.1,
                        zIndex: 97 - ringIndex
                      }}
                      initial={{ scale: 1.0, opacity: 0 }}
                      animate={{
                        scale: 1.0 + (audioLevel * 0.3),
                        opacity: (0.3 - ringIndex * 0.1) * audioLevel
                      }}
                      exit={{ scale: 1.0, opacity: 0 }}
                      transition={{
                        duration: 0.016,
                        ease: "linear"
                      }}
                    />
                  ))}
                </>
              )}
            </AnimatePresence>

            {/* Processing Spinner - Rotating Orbital Animation (z-index: 96) */}
            <AnimatePresence>
              {(voiceState === 'processing_conversation' || voiceState === 'processing_tool') && (
                <motion.div
                  className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none"
                  style={{
                    width: 84,
                    height: 84,
                    zIndex: 96
                  }}
                  initial={{ opacity: 0, rotate: 0 }}
                  animate={{ 
                    opacity: 1,
                    rotate: 360
                  }}
                  exit={{ opacity: 0 }}
                  transition={{
                    opacity: { duration: 0.3 },
                    rotate: { duration: 2, repeat: Infinity, ease: "linear" }
                  }}
                >
                  {/* Orbital dots */}
                  {[0, 120, 240].map((angle) => (
                    <div
                      key={angle}
                      className="absolute rounded-full"
                      style={{
                        width: 6,
                        height: 6,
                        background: glowColor,
                        boxShadow: `0 0 5px ${glowColor}`,
                        top: '50%',
                        left: '50%',
                        transform: `translate(-50%, -50%) rotate(${angle}deg) translateY(-42px)`
                      }}
                    />
                  ))}
                </motion.div>
              )}
            </AnimatePresence>

            {/* Error State - Red Pulsing Effect (z-index: 95) */}
            <AnimatePresence>
              {voiceState === 'error' && (
                <motion.div
                  className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full pointer-events-none"
                  style={{
                    width: 84,
                    height: 84,
                    background: 'radial-gradient(circle, rgba(255, 50, 50, 0.4) 0%, rgba(255, 50, 50, 0.2) 50%, transparent 100%)',
                    filter: "blur(14px)",
                    zIndex: 95
                  }}
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{
                    opacity: [0.6, 1, 0.6],
                    scale: [0.9, 1.2, 0.9]
                  }}
                  exit={{ opacity: 0, scale: 0.8 }}
                  transition={{
                    duration: 1.5,
                    repeat: Infinity,
                    ease: "easeInOut"
                  }}
                />
              )}
            </AnimatePresence>

            {/* Error Message Display (z-index: 94) */}
            <AnimatePresence>
              {voiceState === 'error' && (
                <motion.div
                  className="absolute top-full left-1/2 -translate-x-1/2 mt-2 pointer-events-none"
                  style={{
                    zIndex: 94,
                    maxWidth: 175,
                    textAlign: 'center'
                  }}
                  initial={{ opacity: 0, y: -5 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -5 }}
                  transition={{ duration: 0.3 }}
                >
                  <div
                    className="px-3 py-1.5 rounded text-[11px] font-medium"
                    style={{
                      background: 'rgba(255, 50, 50, 0.15)',
                      border: '1px solid rgba(255, 50, 50, 0.4)',
                      color: '#ff6b6b',
                      backdropFilter: 'blur(5px)',
                      boxShadow: '0 2px 6px rgba(255, 50, 50, 0.2)'
                    }}
                  >
                    {Object.keys(fieldErrors).length > 0 
                      ? Object.values(fieldErrors)[0] 
                      : 'Voice command error occurred'}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* 5-Layer Core Architecture + Interactive Button (Phase 110) */}
            <motion.button
              className="absolute rounded-full focus:outline-none"
              style={{
                left: '50%',
                top: '50%',
                marginLeft: -23,
                marginTop: -23,
                width: 45,
                height: 45,
                zIndex: 100,
                overflow: 'visible',
                background: 'transparent',
                border: 'none',
                padding: 0,
                cursor: 'pointer',
                pointerEvents: 'auto'
              }}
              initial={{ opacity: 0, scale: 1.1 }}
              animate={{
                opacity: 1,
                scale: voiceState === 'listening'
                  ? [1.0, 1.1, 1.0] // Pulsing animation when listening
                  : voiceState === 'error'
                  ? [1.0, 1.05, 1.0] // Subtle pulse for error
                  : isVoiceActive 
                  ? 1 + (audioLevel * 0.15) // Voice intensity modulates breathing
                  : 1,
                boxShadow: voiceState === 'error'
                  ? `0 0 30px rgba(255, 50, 50, 0.8)` // Red glow for error
                  : isVoiceActive 
                  ? `0 0 ${20 + audioLevel * 40}px ${glowColor}` // Reactive glow
                  : "none",
                filter: voiceState === 'error'
                  ? `drop-shadow(0 0 20px rgba(255, 50, 50, 0.8))` // Red shadow for error
                  : isVoiceActive 
                  ? `drop-shadow(0 0 ${10 + audioLevel * 20}px ${glowColor})` // Reactive shadow
                  : "none"
              }}
              transition={{ 
                type: "spring", 
                stiffness: 100, 
                damping: 20, 
                delay: 0.7,
                scale: voiceState === 'listening' 
                  ? { duration: 1.5, repeat: Infinity, ease: "easeInOut" } // 1.5s pulsing for listening
                  : voiceState === 'error'
                  ? { duration: 1.5, repeat: Infinity, ease: "easeInOut" } // 1.5s pulsing for error
                  : { duration: 0.15 }, // Fast response to voice intensity
                boxShadow: { duration: 0.15 },
                filter: { duration: 0.15 }
              }}
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.92 }}
              onMouseDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.preventDefault()
                
                clickCount.current += 1

                if (clickCount.current === 1) {
                  // Single click — navigate back immediately
                  clickTimer.current = setTimeout(() => {
                    if (clickCount.current === 1) {
                      if (isVoiceActive) {
                        endVoiceCommand()
                      } else {
                        onBackToCategories()
                      }
                    }
                    clickCount.current = 0
                  }, 180) // Short window just to catch accidental double-click
                } else if (clickCount.current === 2) {
                  // Double click — toggle voice
                  if (clickTimer.current) {
                    clearTimeout(clickTimer.current)
                    clickTimer.current = null
                  }
                  if (isVoiceActive) {
                    endVoiceCommand()
                  } else {
                    startVoiceCommand()
                  }
                  clickCount.current = 0
                }
              }}
            >
              {/* 0. ATMOSPHERIC BRAND PULSE */}
              <motion.div
                className="absolute rounded-full pointer-events-none"
                style={{
                  inset: isVoiceActive ? -28 : -22,
                  background: `radial-gradient(circle, color-mix(in srgb, ${glowColor}, transparent 60%) 0%, transparent 70%)`,
                  filter: "blur(17px)",
                  zIndex: 0
                }}
                animate={{
                  opacity: isVoiceActive ? [0.6, 1, 0.6] : [0.4, 0.8, 0.4],
                  scale: isVoiceActive ? [0.9, 1.3, 0.9] : [0.95, 1.15, 0.95],
                }}
                transition={{
                  duration: isVoiceActive ? 2.5 : 4,
                  repeat: Infinity,
                  ease: "easeInOut"
                }}
              />

              {/* 1. NEON LAYER STACK - Phase 111: Vibrant & Shimmering */}
              {/* 1.1 NEON CORE (Solid Edge) */}
              <motion.div
                className="absolute rounded-full pointer-events-none"
                style={{
                  inset: -1,
                  background: `radial-gradient(circle, ${glowColor} 0%, transparent 80%)`,
                  border: "1px solid",
                  borderColor: glowColor,
                  filter: "blur(1px)",
                  opacity: 0.8,
                  zIndex: 1
                }}
              />

              {/* 1.2 NEON EDGE BLOOM with KINETIC SHIMMER */}
              <motion.div
                className="absolute rounded-full pointer-events-none"
                style={{
                  inset: -8,
                  background: `radial-gradient(circle, color-mix(in srgb, ${glowColor}, transparent 35%) 0%, transparent 75%)`,
                  filter: "blur(6px)",
                  opacity: 0.6,
                  zIndex: 1
                }}
              >
                {/* Kinetic Shimmer Spike */}
                <motion.div
                  className="absolute inset-0 rounded-full"
                  style={{
                    background: `conic-gradient(from 0deg, 
                      transparent 0deg, 
                      rgba(255,255,255,0.4) 45deg, 
                      ${glowColor} 90deg, 
                      transparent 180deg)`,
                    mixBlendMode: "overlay"
                  }}
                  animate={{ rotate: 360 }}
                  transition={{ duration: 4, repeat: Infinity, ease: "linear" }}
                />
              </motion.div>

              {/* 2. HEX PATTERN NEON EDGE — matches ring segment neon edge */}
              <div
                className="absolute inset-0 rounded-full pointer-events-none"
                style={{
                  border: `1px solid ${glowColor}`,
                  filter: `drop-shadow(0 0 3px ${glowColor}) drop-shadow(0 0 6px ${glowColor})`,
                  zIndex: 2
                }}
              />

              {/* 3. HEX PATTERN BASE — hex-active gradient + honeycomb texture */}
              <div
                className="absolute inset-0 rounded-full pointer-events-none"
                style={{
                  background: `linear-gradient(135deg, ${glowColor}40 0%, rgba(10,10,12,0.7) 50%, ${glowColor}1a 100%)`,
                  backdropFilter: "blur(6px)",
                  WebkitBackdropFilter: "blur(6px)",
                  boxShadow: "0 2px 6px rgba(0,0,0,0.5), inset 0 1px 1px rgba(255,255,255,0.2)",
                  zIndex: 2
                }}
              />
              {/* 3.1 HEX PATTERN TEXTURE OVERLAY — honeycomb SVG pattern as CSS background */}
              <div
                className="absolute inset-0 rounded-full pointer-events-none"
                style={{
                  backgroundImage: `url("data:image/svg+xml,${encodeURIComponent(
                    `<svg xmlns='http://www.w3.org/2000/svg' width='8' height='9.24'>
                      <polygon points='4,0 8,2.31 8,6.93 4,9.24 0,6.93 0,2.31'
                        fill='none' stroke='${glowColor}' stroke-width='0.4' opacity='0.4'/>
                    </svg>`
                  )}")`,
                  backgroundRepeat: 'repeat',
                  opacity: 0.4,
                  zIndex: 3
                }}
              />

              {/* Invisible clickable surface - ensures entire button area is clickable */}
              <div
                className="absolute inset-0 rounded-full"
                style={{
                  background: 'transparent',
                  cursor: 'pointer',
                  zIndex: 5,
                  pointerEvents: 'auto' as const,
                }}
              />

              {/* 5. CONTENT AREA */}
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none" style={{ zIndex: 10 }}>
                <span className="text-[7px] font-black uppercase tracking-[0.1em] text-white select-none" style={{ textShadow: '0 1px 2px rgba(0,0,0,0.5)' }}>
                  {categoryId}
                </span>
              </div>
            </motion.button>
          </div>
        </div>

        {/* Side Panel: Positioning uses 240 as base for orbSize logic */}
        <AnimatePresence>
          {showPanel && activeCard && (
            <SidePanel
              card={activeCard}
              glowColor={glowColor}
              values={fieldValues}
              onValueChange={handleValueChange}
              onConfirm={handleConfirm}
              lineRetracted={lineRetracted}
              orbSize={210}
              onBrowseMarketplace={onBrowseMarketplace}
            />
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
