"use client"

import React, { useState, useCallback, useEffect, useMemo } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ArrowLeft } from "lucide-react"
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

/**
 * Helper function to validate hex color
 * Validates: Property 48 - Invalid Glow Color Fallback
 */
function validateGlowColor(color: string): string {
  const hexPattern = /^#[0-9A-Fa-f]{6}$/
  if (!hexPattern.test(color)) {
    console.warn(`[WheelView] Invalid glow color: ${color}, using default`)
    return "#00D4FF" // Default cyan
  }
  return color
}

/**
 * WheelView Component
 * 
 * Main container that orchestrates DualRingMechanism, SidePanel, and all animations.
 * 
 * Features:
 * - Displays both sub-nodes (outer ring) and mini-nodes (inner ring) simultaneously
 * - Side panel for input field configuration
 * - Smooth animations with spring physics
 * - Keyboard navigation support (arrows, enter, escape)
 * - Confirm animation sequence (counter-spin, flash, glow breathe)
 * - Animation race condition prevention
 * - Empty state handling
 * - Error handling for invalid colors
 * - Theme integration with BrandColorContext
 * 
 * Validates: Requirements 2.1, 2.7, 6.3, 6.4, 6.5, 6.7, 11.1, 15.1, 15.4, 15.6
 * Validates: Properties 3, 7, 21, 22, 48
 */
export const WheelView: React.FC<WheelViewProps> = ({
  categoryId,
  glowColor: rawGlowColor,
  expandedIrisSize,
  initialValues = {},
  onConfirm,
  onBackToCategories,
}) => {
  // Task 6.1: Integrate with NavigationContext and BrandColorContext
  const { state, updateMiniNodeValue } = useNavigation()
  const { getThemeConfig } = useBrandColor()
  
  // Validate glow color (Requirement 15.4)
  const glowColor = useMemo(() => validateGlowColor(rawGlowColor), [rawGlowColor])
  
  // Get mini-node stack from context
  const miniNodeStack = state.miniNodeStack || []
  
  // Task 6.11: Empty state handling (Requirement 15.1)
  if (miniNodeStack.length === 0) {
    return (
      <div className="absolute inset-0 flex items-center justify-center">
        <div className="text-white/40 text-sm">
          No settings available for this category
        </div>
      </div>
    )
  }
  
  // Task 6.2: Internal state management
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [confirmFlash, setConfirmFlash] = useState(false)
  const [confirmSpinning, setConfirmSpinning] = useState(false)
  const [lineRetracted, setLineRetracted] = useState(false)
  const [showPanel, setShowPanel] = useState(true)
  
  // Task 6.5: Animation race condition prevention (Requirement 6.7, 15.6)
  const [isAnimating, setIsAnimating] = useState(false)
  
  // Task 6.3: Mini-node selection logic
  const activeMiniNode = useMemo(() => {
    return miniNodeStack[selectedIndex] || miniNodeStack[0]
  }, [miniNodeStack, selectedIndex])
  
  // Get field values for active mini-node
  const fieldValues = useMemo(() => {
    return state.miniNodeValues[activeMiniNode?.id] || {}
  }, [state.miniNodeValues, activeMiniNode])
  
  // Task 6.3: Selection handler with animation prevention
  const handleSelect = useCallback((index: number) => {
    if (isAnimating) {
      console.log("[WheelView] Animation in progress, ignoring selection")
      return
    }
    
    setIsAnimating(true)
    setSelectedIndex(index)
    setShowPanel(true)
    
    // Animation completes after spring settles (~500ms)
    setTimeout(() => setIsAnimating(false), 500)
  }, [isAnimating])
  
  // Task 6.3: Value change handler
  const handleValueChange = useCallback((fieldId: string, value: FieldValue) => {
    if (!activeMiniNode) return
    updateMiniNodeValue(activeMiniNode.id, fieldId, value)
  }, [activeMiniNode, updateMiniNodeValue])
  
  // Task 6.4: Confirm animation sequence (Requirements 6.3, 6.4, 6.5)
  const handleConfirm = useCallback(() => {
    if (isAnimating) return
    
    setIsAnimating(true)
    
    // Start animations
    setLineRetracted(true)
    setConfirmSpinning(true)
    setConfirmFlash(true)
    
    // Schedule onConfirm callback after 900ms (Property 21)
    setTimeout(() => {
      onConfirm(state.miniNodeValues)
      
      // Reset animation states
      setLineRetracted(false)
      setConfirmSpinning(false)
      setConfirmFlash(false)
      setIsAnimating(false)
    }, 900)
  }, [isAnimating, onConfirm, state.miniNodeValues])
  
  // Task 7.1-7.3: Keyboard navigation (Requirements 7.1-7.7)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Prevent default browser behavior (Requirement 7.7)
      if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter", "Escape"].includes(e.key)) {
        e.preventDefault()
      }
      
      // Block input during animations
      if (isAnimating && e.key !== "Escape") {
        return
      }
      
      switch (e.key) {
        case "ArrowRight":
          // Next item (wrap around)
          setSelectedIndex((prev) => (prev + 1) % miniNodeStack.length)
          break
          
        case "ArrowLeft":
          // Previous item (wrap around)
          setSelectedIndex((prev) => (prev - 1 + miniNodeStack.length) % miniNodeStack.length)
          break
          
        case "ArrowDown":
          // Next item (same as right for single ring)
          setSelectedIndex((prev) => (prev + 1) % miniNodeStack.length)
          break
          
        case "ArrowUp":
          // Previous item (same as left for single ring)
          setSelectedIndex((prev) => (prev - 1 + miniNodeStack.length) % miniNodeStack.length)
          break
          
        case "Enter":
          // Confirm current selection
          handleConfirm()
          break
          
        case "Escape":
          // Back to categories
          onBackToCategories()
          break
      }
    }
    
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [miniNodeStack.length, isAnimating, handleConfirm, onBackToCategories])
  
  return (
    <div className="absolute inset-0 flex items-center justify-center">
      {/* Task 6.10: Glow breathe animation */}
      <motion.div
        className="absolute"
        style={{
          width: expandedIrisSize * 1.5,
          height: expandedIrisSize * 1.5,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${glowColor}22 0%, transparent 70%)`,
          filter: `blur(${confirmFlash ? 24 : 12}px)`,
          pointerEvents: "none",
        }}
        animate={{
          scale: confirmFlash ? [1, 2.2, 1] : 1,
          opacity: confirmFlash ? [0.3, 0.6, 0.3] : 0.3,
        }}
        transition={{
          duration: confirmFlash ? 0.8 : 2,
          repeat: confirmFlash ? 0 : Infinity,
          repeatType: "reverse",
        }}
      />
      
      {/* Container for orb and rings */}
      <div
        className="relative"
        style={{
          width: expandedIrisSize,
          height: expandedIrisSize,
        }}
      >
        {/* Task 6.6: Render DualRingMechanism */}
        <DualRingMechanism
          items={miniNodeStack}
          selectedIndex={selectedIndex}
          onSelect={handleSelect}
          glowColor={glowColor}
          orbSize={expandedIrisSize}
          confirmSpinning={confirmSpinning}
        />
        
        {/* Task 6.8: Center back button */}
        <motion.button
          className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 flex items-center justify-center rounded-full transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-white/20"
          style={{
            width: 48,
            height: 48,
            backgroundColor: "rgba(0, 0, 0, 0.6)",
            border: `1px solid ${glowColor}44`,
          }}
          onClick={onBackToCategories}
          aria-label="Back to categories"
          whileHover={{
            scale: 1.1,
            backgroundColor: "rgba(0, 0, 0, 0.8)",
            borderColor: `${glowColor}66`,
          }}
          whileTap={{ scale: 0.95 }}
          whileFocus={{
            boxShadow: `0 0 0 2px ${glowColor}44`,
          }}
        >
          <ArrowLeft
            className="w-5 h-5"
            style={{ color: glowColor }}
          />
        </motion.button>
        
        {/* Task 6.7: Render SidePanel */}
        {showPanel && activeMiniNode && (
          <SidePanel
            miniNode={activeMiniNode}
            glowColor={glowColor}
            values={fieldValues}
            onValueChange={handleValueChange}
            onConfirm={handleConfirm}
            lineRetracted={lineRetracted}
            orbSize={expandedIrisSize}
          />
        )}
      </div>
      
      {/* Task 6.9: Flash overlay animation */}
      <AnimatePresence>
        {confirmFlash && (
          <motion.div
            className="absolute inset-0 pointer-events-none"
            style={{
              background: `radial-gradient(circle, ${glowColor}44 0%, transparent 60%)`,
            }}
            initial={{ opacity: 0.3, scale: 0.8 }}
            animate={{ opacity: [0.3, 1, 0.3], scale: [0.8, 1.4, 0.8] }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.8 }}
          />
        )}
      </AnimatePresence>
    </div>
  )
}
