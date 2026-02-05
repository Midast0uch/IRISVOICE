"use client"

import React, { useCallback, useEffect, useRef, useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { getCurrentWindow, PhysicalPosition } from "@tauri-apps/api/window"
import { ChevronLeft, ChevronDown, X } from "lucide-react"
import { useReducedMotion } from "@/hooks/useReducedMotion"

type OrbIcon = 'home' | 'close' | 'back'

interface IrisOrbProps {
  isExpanded: boolean
  onClick: () => void
  centerLabel: string
  size: number
  glowColor: string
  showBackIndicator?: boolean
  icon?: OrbIcon
}

const DEBOUNCE_MS = 150

function useManualDragWindow(onClickAction: () => void, elementRef: React.RefObject<HTMLElement | null>) {
  const isDragging = useRef(false)
  const dragStartPos = useRef({ x: 0, y: 0 })
  const windowStartPos = useRef({ x: 0, y: 0 })
  const hasDragged = useRef(false)
  const isDraggingThisElement = useRef(false)
  const mouseDownTarget = useRef<EventTarget | null>(null)

  const handleMouseDown = useCallback(async (e: React.MouseEvent) => {
    if (e.button !== 0) return

    mouseDownTarget.current = e.target
    isDragging.current = true
    isDraggingThisElement.current = true
    hasDragged.current = false
    dragStartPos.current = { x: e.screenX, y: e.screenY }

    try {
      const win = getCurrentWindow()
      const pos = await win.outerPosition()
      windowStartPos.current = { x: pos.x, y: pos.y }
    } catch (e) {
      // Tauri not available
    }

    document.body.style.cursor = "grabbing"
    document.body.style.userSelect = "none"
  }, [])

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!isDragging.current || !isDraggingThisElement.current) return

    const dx = e.screenX - dragStartPos.current.x
    const dy = e.screenY - dragStartPos.current.y

    if (Math.abs(dx) > 5 || Math.abs(dy) > 5) {
      hasDragged.current = true
    }

    try {
      const win = getCurrentWindow()
      win.setPosition(new PhysicalPosition(windowStartPos.current.x + dx, windowStartPos.current.y + dy))
    } catch (e) {
      // Window drag not available
    }
  }, [])

  const handleMouseUp = useCallback((e: MouseEvent) => {
    console.log('[Nav System] handleMouseUp:', { 
      isDraggingThisElement: isDraggingThisElement.current, 
      hasDragged: hasDragged.current,
      elementRefExists: !!elementRef.current,
      mouseDownTarget: mouseDownTarget.current,
      mouseUpTarget: e.target
    })
    
    isDragging.current = false
    document.body.style.cursor = "default"
    document.body.style.userSelect = ""

    // Only trigger click if:
    // 1. We started dragging on this element
    // 2. We didn't actually drag (just clicked)
    // 3. The mouseup target is the same as mousedown target (or inside the iris orb)
    if (isDraggingThisElement.current && !hasDragged.current && elementRef.current) {
      const mouseUpTarget = e.target
      // Check if both mousedown and mouseup happened on or within the iris orb element
      const mouseDownInOrb = mouseDownTarget.current && elementRef.current.contains(mouseDownTarget.current as Node)
      const mouseUpInOrb = elementRef.current.contains(mouseUpTarget as Node)
      
      console.log('[Nav System] Click check:', { mouseDownInOrb, mouseUpInOrb })
      
      if (mouseDownInOrb && mouseUpInOrb) {
        console.log('[Nav System] Triggering onClickAction')
        onClickAction()
      } else {
        console.log('[Nav System] Click rejected - not in iris orb')
      }
    }
    isDraggingThisElement.current = false
    mouseDownTarget.current = null
  }, [onClickAction, elementRef])

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

export function IrisOrb({ 
  isExpanded, 
  onClick, 
  centerLabel, 
  size, 
  glowColor,
  showBackIndicator = false,
  icon = 'home'
}: IrisOrbProps) {
  const [isDebouncing, setIsDebouncing] = useState(false)
  const [isPressed, setIsPressed] = useState(false)
  const debounceRef = useRef<NodeJS.Timeout | null>(null)

  const handleClick = useCallback((e: React.MouseEvent) => {
    console.log('[Nav System] IrisOrb handleClick called', { isDebouncing, target: e.target })
    if (isDebouncing) {
      console.log('[Nav System] IrisOrb click blocked by debounce')
      return
    }
    
    setIsDebouncing(true)
    setIsPressed(true)
    
    setTimeout(() => setIsPressed(false), 150)
    
    console.log('[Nav System] IrisOrb calling onClick')
    onClick()
    
    debounceRef.current = setTimeout(() => {
      setIsDebouncing(false)
    }, DEBOUNCE_MS)
  }, [isDebouncing, onClick])

  useEffect(() => {
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current)
      }
    }
  }, [])

  const [isWaking, setIsWaking] = useState(false)
  const prefersReducedMotion = useReducedMotion()

  const renderIcon = () => {
    if (!showBackIndicator) return null
    
    const iconSize = size * 0.14
    const iconStyle = { color: 'rgba(255, 255, 255, 0.7)' }
    
    switch (icon) {
      case 'back':
        return (
          <motion.div
            className="absolute pointer-events-none"
            style={{ top: size * 0.15 }}
            animate={{ x: [-2, 0, -2] }}
            transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
          >
            <ChevronLeft size={iconSize} style={iconStyle} strokeWidth={2} />
          </motion.div>
        )
      case 'close':
        return (
          <div className="absolute pointer-events-none" style={{ top: size * 0.15 }}>
            <ChevronDown size={iconSize} style={iconStyle} strokeWidth={2} />
          </div>
        )
      default:
        return null
    }
  }

  return (
    <motion.div
      className="relative flex items-center justify-center rounded-full cursor-pointer z-50 pointer-events-auto"
      style={{ width: size, height: size }}
      onClick={handleClick}
      animate={{ scale: isPressed ? 0.95 : 1 }}
      transition={{ type: "spring", stiffness: 400, damping: 25 }}
    >
      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{
          inset: -60,
          background: `radial-gradient(circle, ${glowColor}80 0%, ${glowColor}40 30%, transparent 70%)`,
          filter: "blur(30px)",
        }}
        animate={{ scale: [1, 1.6, 1], opacity: [0.6, 1, 0.6] }}
        transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
      />

      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{
          inset: -8,
          background: `radial-gradient(circle, ${glowColor}cc 0%, ${glowColor}60 30%, ${glowColor}20 60%, transparent 80%)`,
          filter: "blur(8px)",
        }}
        animate={{ scale: [0.8, 1.4, 0.8], opacity: [0.7, 1, 0.7] }}
        transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
      />

      <AnimatePresence>
        {isWaking && centerLabel !== "IRIS" && (
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

      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{
          inset: -3,
          borderRadius: "50%",
          padding: "3px",
          background: `conic-gradient(from 0deg, transparent 0deg, ${glowColor}4d 90deg, ${glowColor}cc 180deg, ${glowColor}4d 270deg, transparent 360deg)`,
          WebkitMask: "linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)",
          WebkitMaskComposite: "xor",
        }}
        animate={{ rotate: 360 }}
        transition={{ duration: 10, repeat: Infinity, ease: "linear" }}
      />

      <div
        className="relative w-full h-full flex items-center justify-center rounded-full pointer-events-none"
        style={{
          background: "rgba(255, 255, 255, 0.05)",
          backdropFilter: "blur(20px)",
          border: "1px solid rgba(255, 255, 255, 0.1)",
        }}
      >
        <div
          className="absolute inset-0 rounded-full pointer-events-none"
          style={{ background: `radial-gradient(circle at 30% 30%, ${glowColor}14, transparent 70%)` }}
        />

        {renderIcon()}
        
        <AnimatePresence mode="wait">
          <motion.span
            key={centerLabel}
            className="text-lg font-light tracking-[0.2em] select-none pointer-events-none"
            style={{ 
              color: "rgba(255, 255, 255, 0.95)",
              marginTop: showBackIndicator ? size * 0.08 : 0,
              fontSize: prefersReducedMotion && showBackIndicator 
                ? '1.25rem' 
                : (showBackIndicator && centerLabel.length > 5 ? '0.85rem' : '1.125rem'),
              fontWeight: prefersReducedMotion && showBackIndicator ? 500 : 300,
            }}
            initial={prefersReducedMotion ? { opacity: 1 } : { scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={prefersReducedMotion ? { opacity: 0 } : { scale: 0, opacity: 0 }}
            transition={prefersReducedMotion 
              ? { duration: 0.15 } 
              : { type: "spring", stiffness: 300, damping: 25 }
            }
          >
            <motion.span
              animate={prefersReducedMotion 
                ? {} 
                : { textShadow: [`0 0 10px ${glowColor}4d`, `0 0 20px ${glowColor}99`, `0 0 10px ${glowColor}4d`] }
              }
              transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
            >
              {showBackIndicator && icon === 'back' ? `← ${centerLabel}` : centerLabel}
            </motion.span>
          </motion.span>
        </AnimatePresence>
      </div>
    </motion.div>
  )
}
