"use client"

import React, { useState, useCallback, useEffect, useMemo } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ArrowLeft } from "lucide-react"
import { getCurrentWindow } from "@tauri-apps/api/window"
import { DualRingMechanism } from "./DualRingMechanism"
import { SidePanel } from "./SidePanel"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"
import type { MiniNode, FieldValue } from "@/types/navigation"

interface WheelViewProps {
  categoryId: string
  glowColor: string
  expandedIrisSize: number
  initialValues?: Record<string, Record<string, FieldValue>>
  onConfirm: (values: Record<string, Record<string, FieldValue>>) => void
  onBackToCategories: () => void
}

function validateGlowColor(color: string): string {
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
}) => {
  const { state, updateMiniNodeValue, sendMessage } = useNavigation()
  const { getThemeConfig } = useBrandColor()

  const glowColor = useMemo(() => validateGlowColor(rawGlowColor), [rawGlowColor])
  const miniNodeStack = state.miniNodeStack || []

  const lastClickTime = React.useRef<number>(0)
  const clickTimer = React.useRef<NodeJS.Timeout | null>(null)

  const [selectedIndex, setSelectedIndex] = useState(0)
  const [confirmFlash, setConfirmFlash] = useState(false)
  const [confirmSpinning, setConfirmSpinning] = useState(false)
  const [lineRetracted, setLineRetracted] = useState(false)
  const [showPanel, setShowPanel] = useState(true)
  const [isVoiceActive, setIsVoiceActive] = useState(false)
  const [voiceIntensity, setVoiceIntensity] = useState(0)
  const [isAnimating, setIsAnimating] = useState(false)

  const activeMiniNode = useMemo(() => {
    return miniNodeStack[selectedIndex] || miniNodeStack[0]
  }, [miniNodeStack, selectedIndex])

  const fieldValues = useMemo(() => {
    return state.miniNodeValues[activeMiniNode?.id] || {}
  }, [state.miniNodeValues, activeMiniNode])

  const handleSelect = useCallback((index: number) => {
    if (isAnimating) return
    setIsAnimating(true)
    setSelectedIndex(index)
    setShowPanel(true)
    setTimeout(() => setIsAnimating(false), 500)
  }, [isAnimating])

  const handleValueChange = useCallback((fieldId: string, value: FieldValue) => {
    if (!activeMiniNode) return
    updateMiniNodeValue(activeMiniNode.id, fieldId, value)
  }, [activeMiniNode, updateMiniNodeValue])

  const handleConfirm = useCallback(() => {
    if (isAnimating) return
    setIsAnimating(true)
    setLineRetracted(true)
    setConfirmSpinning(true)
    setConfirmFlash(true)

    setTimeout(() => {
      onConfirm(state.miniNodeValues)
      setLineRetracted(false)
      setConfirmSpinning(false)
      setConfirmFlash(false)
      setIsAnimating(false)
    }, 900)
  }, [isAnimating, onConfirm, state.miniNodeValues])

  // Simulate speech pulse when voice is active
  useEffect(() => {
    if (!isVoiceActive) {
      setVoiceIntensity(0)
      return
    }
    const interval = setInterval(() => {
      // Create a "breathing" intensity pulse (0.3 to 1.0 range)
      setVoiceIntensity(0.3 + Math.random() * 0.7)
    }, 150)
    return () => clearInterval(interval)
  }, [isVoiceActive])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter", "Escape"].includes(e.key)) {
        e.preventDefault()
      }
      if (isAnimating && e.key !== "Escape") return

      switch (e.key) {
        case "ArrowRight":
        case "ArrowDown":
          setSelectedIndex((prev) => (prev + 1) % miniNodeStack.length)
          break
        case "ArrowLeft":
        case "ArrowUp":
          setSelectedIndex((prev) => (prev - 1 + miniNodeStack.length) % miniNodeStack.length)
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
  }, [miniNodeStack.length, isAnimating, handleConfirm, onBackToCategories])

  if (miniNodeStack.length === 0) {
    return (
      <div className="absolute inset-0 flex items-center justify-center">
        <div className="text-white/40 text-sm">No settings available</div>
      </div>
    )
  }

  return (
    <div
      className="absolute inset-0 flex items-center justify-center bg-transparent"
      onMouseDown={(e) => {
        if (e.button === 0) getCurrentWindow().startDragging()
      }}
    >
      <div
        className="relative flex items-center justify-start pointer-events-none"
        style={{ width: 850, height: 750, paddingLeft: "40px" }}
      >
        {/* Mechanics Stage: 500x500 provides room for 300px orb + 200px buffer safety (Phase 49) */}
        {/* Force overflow: visible (Phase 50) to ensure soft blooms are never clipped */}
        <div
          className="relative pointer-events-none flex items-center justify-center shrink-0"
          style={{ width: 500, height: 500, overflow: 'visible' }}
        >
          {/* Centered Mechanims Layer - Absolute Visibility (Phase 50) */}
          <div className="relative" style={{ width: 300, height: 300, overflow: 'visible' }}>
            <DualRingMechanism
              items={miniNodeStack}
              selectedIndex={selectedIndex}
              onSelect={handleSelect}
              glowColor={glowColor}
              orbSize={300}
              confirmSpinning={confirmSpinning}
              isVoiceActive={isVoiceActive}
              voiceIntensity={voiceIntensity}
            />

            {/* Perfectly Aligned Core Center */}
            <motion.button
              className="absolute top-1/2 left-1/2 flex items-center justify-center rounded-full focus:outline-none overflow-hidden"
              style={{
                width: 64,
                height: 64,
                background: `linear-gradient(135deg, ${glowColor}66 0%, rgba(200, 210, 220, 0.2) 50%, ${glowColor}44 100%)`,
                border: `1px solid rgba(255, 255, 255, 0.2)`,
                backdropFilter: "blur(8px)",
                boxShadow: `0 0 15px ${glowColor}33`,
                filter: "url(#liquid-metal-sheen)",
                zIndex: 100,
                pointerEvents: "auto"
              }}
              initial={{ opacity: 0, scale: 1.1, x: "-50%", y: "-50%" }}
              animate={{ opacity: 1, scale: 1, x: "-50%", y: "-50%" }}
              transition={{ type: "spring", stiffness: 100, damping: 20, delay: 0.7 }}
              whileHover={{
                scale: 1.05,
                x: "-50%",
                y: "-50%",
                boxShadow: `0 0 25px ${glowColor}66`,
                borderColor: "rgba(255, 255, 255, 0.4)",
              }}
              whileTap={{ scale: 0.94, x: "-50%", y: "-50%" }}
              onMouseDown={(e) => e.stopPropagation()}
              onClick={() => {
                const now = Date.now()
                if (now - lastClickTime.current < 300) {
                  if (clickTimer.current) clearTimeout(clickTimer.current)
                  setIsVoiceActive(prev => !prev) // Toggle Voice Aura on double-click (Phase 50)
                  sendMessage("voice_command_start", {})
                  lastClickTime.current = 0
                } else {
                  lastClickTime.current = now
                  const activeAtClick = isVoiceActive // Capture state at click time (Phase 63)
                  clickTimer.current = setTimeout(() => {
                    if (activeAtClick) {
                      setIsVoiceActive(false) // Single click stops speech mode ONLY (Phase 62/63)
                    } else {
                      onBackToCategories() // Single click navigates back ONLY when idle (Phase 62/63)
                    }
                    clickTimer.current = null
                    lastClickTime.current = 0
                  }, 300)
                }
              }}
            >
              {/* Specular Top Edge Highlight */}
              <div
                className="absolute top-0 left-0 right-0 h-[2px] opacity-60 pointer-events-none"
                style={{
                  background: "linear-gradient(to bottom, rgba(255,255,255,0.7), transparent)",
                  borderRadius: "50% 50% 0 0"
                }}
              />

              <div className="flex flex-col items-center justify-center pointer-events-none relative z-10">
                <span className="text-[11px] font-black uppercase tracking-[0.1em] text-white">
                  {categoryId}
                </span>
              </div>
            </motion.button>
          </div>
        </div>

        {/* Side Panel: Positioning uses 240 as base for orbSize logic */}
        <AnimatePresence>
          {showPanel && activeMiniNode && (
            <SidePanel
              miniNode={activeMiniNode}
              glowColor={glowColor}
              values={fieldValues}
              onValueChange={handleValueChange}
              onConfirm={handleConfirm}
              lineRetracted={lineRetracted}
              orbSize={300}
            />
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
