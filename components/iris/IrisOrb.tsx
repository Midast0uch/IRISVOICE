
import React, { useState, useCallback, useRef, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { getCurrentWindow, PhysicalPosition } from "@tauri-apps/api/window"
import { ChevronLeft, ChevronDown } from "lucide-react"
import { useReducedMotion } from "@/hooks/useReducedMotion"
import { useNavigation } from "@/contexts/NavigationContext"
import type { IrisOrbProps, OrbIcon } from "./types"

// --- Helper Hook for Window Dragging ---
function useManualDragWindow(onClickAction: () => void, elementRef: React.RefObject<HTMLElement | null>) {
  const isDragging = useRef(false)
  const dragStartPos = useRef({ x: 0, y: 0 })
  const windowStartPos = useRef({ x: 0, y: 0 })
  const hasDragged = useRef(false)
  const isDraggingThisElement = useRef(false)
  const mouseDownTarget = useRef<EventTarget | null>(null)

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

    if (Math.abs(dx) > 5 || Math.abs(dy) > 5) {
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
        if (typeof onClickAction === 'function') {
          onClickAction()
        }
      }
    }
    
    isDraggingThisElement.current = false
    mouseDownTarget.current = null
    hasDragged.current = false
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




// --- Main IrisOrb Component ---
export function IrisOrb({ 
  isExpanded, 
  onClick, 
  onDoubleClick,
  centerLabel, 
  size = 200, 
  glowColor, 
  voiceState, 
  wakeFlash, 
  sendMessage, 
  onCallbacksReady,

}: IrisOrbProps) {
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
  const orbRef = useRef<HTMLDivElement>(null)
  const prefersReducedMotion = useReducedMotion()

  // --- Combined Click & Drag Handling ---

    const { handleIrisClick } = useNavigation()
  const { handleMouseDown } = useManualDragWindow(handleIrisClick, orbRef)


  // --- Voice Recording Logic ---

  const startRecording = () => {
    setIsRecording(true)
    setFeedbackMessage("Listening...")
    const success = sendMessage("voice_command_start", {})
    
    audioLevelInterval.current = setInterval(() => {
      const level = Math.random() * 0.8 + 0.2
      setAudioLevel(level)
    }, 100)
  }

  const stopRecording = () => {
    setIsRecording(false)
    setFeedbackMessage("Processing...")
    setIsVoiceProcessing(true)

    if (audioLevelInterval.current) {
      clearInterval(audioLevelInterval.current)
      audioLevelInterval.current = null
    }
    
    const success = sendMessage("voice_command_end", {})
    setAudioLevel(0)

    setTimeout(() => {
      setIsVoiceProcessing(false)
      setFeedbackMessage("")
    }, 2000)
  }

  // --- Callbacks for Parent Component ---

  const handleWakeDetected = useCallback(() => {
    if (isRecording || isVoiceProcessing) {
      return
    }
    startRecording()
  }, [isRecording, isVoiceProcessing])

  const handleNativeAudioResponse = useCallback((payload: any) => {
    if (payload.debug_text) {
      setFeedbackMessage(payload.debug_text)
      setTimeout(() => setFeedbackMessage(""), 5000)
    }
  }, [])

  useEffect(() => {
    if (onCallbacksReady) {
      onCallbacksReady({
        handleWakeDetected,
        handleNativeAudioResponse
      })
    }
  }, [onCallbacksReady, handleWakeDetected, handleNativeAudioResponse])

  // --- Visuals ---

  const makeVibrant = (color: string): string => {
    const hex = color.replace('#', '')
    const r = parseInt(hex.substring(0, 2), 16)
    const g = parseInt(hex.substring(2, 4), 16)
    const b = parseInt(hex.substring(4, 6), 16)
    const rNorm = r / 255, gNorm = g / 255, bNorm = b / 255
    const max = Math.max(rNorm, gNorm, bNorm), min = Math.min(rNorm, gNorm, bNorm)
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
    s = Math.min(1, s * 2.0)
    l = Math.min(0.75, l * 1.6)
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
    const toHex = (n: number) => Math.round(n * 255).toString(16).padStart(2, '0')
    return `#${toHex(rOut)}${toHex(gOut)}${toHex(bOut)}`
  }



  const effectiveGlowColor = isRecording ? makeVibrant(glowColor) : isVoiceProcessing ? "#4444FF" : glowColor
  const effectiveScale = isRecording ? 1.1 : isVoiceProcessing ? 1.05 : 1

  return (
    <motion.div
      ref={orbRef}
      className="relative flex items-center justify-center rounded-full cursor-pointer z-50 pointer-events-auto"
      style={{ width: size, height: size }}
      onMouseDown={handleMouseDown}
      animate={{ scale: effectiveScale }}
      transition={{ type: "spring", stiffness: 300, damping: 25 }}
    >
      {/* Outer breathe glow */}
      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{ inset: -30, background: `radial-gradient(circle, ${effectiveGlowColor}80 0%, ${effectiveGlowColor}40 30%, transparent 65%)`, filter: "blur(25px)" }}
        animate={{
          scale: isSpeaking ? [1.05, 1.3, 1.05] : isRecording ? [1, 1.25, 1] : [1, 1.15, 1],
          opacity: isSpeaking ? [0.8, 1, 0.8] : isRecording ? [0.9, 1, 0.9] : [0.4, 0.75, 0.4],
        }}
        transition={{ duration: isRecording ? 0.8 : 5, repeat: Infinity, ease: "easeInOut" }}
      />

      {/* Audio level ring */}
      {isRecording && (
        <motion.div
          className="absolute rounded-full pointer-events-none"
          style={{ inset: -30, background: `radial-gradient(circle, ${effectiveGlowColor}60 0%, transparent 70%)`, filter: "blur(12px)" }}
          animate={{ opacity: [0.3, 0.8 * audioLevel, 0.3], scale: [0.9, 1 + (audioLevel * 0.2), 0.9] }}
          transition={{ duration: 0.1, repeat: Infinity }}
        />
      )}

      {/* Inner core pulse */}
      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{ inset: -8, background: `radial-gradient(circle at 30% 30%, ${effectiveGlowColor}14, transparent 70%)`, filter: "blur(8px)" }}
        animate={{
          scale: isProcessing || isVoiceProcessing ? [0.9, 1.1, 0.9] : isSpeaking ? [0.8, 1.5, 0.8] : [0.8, 1.2, 0.8],
          opacity: isProcessing || isVoiceProcessing ? [0.5, 0.8, 0.5] : [0.6, 1, 0.6],
        }}
        transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
      />

      {/* Wake/Double-click flash */}
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
        style={{ background: "rgba(255, 255, 255, 0.05)", backdropFilter: "blur(20px)", border: `1px solid ${glowColor}33` }}
      >
        <div className="absolute inset-0 rounded-full pointer-events-none" style={{ background: `radial-gradient(circle at 30% 30%, ${glowColor}14, transparent 70%)` }} />

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
          animate={{ rotate: isProcessing ? 360 : isSpeaking ? [0, 360] : 8 }}
          transition={{ duration: isProcessing ? 2 : isSpeaking ? 1.5 : 8, repeat: Infinity, ease: "linear" }}
        />
        


        <AnimatePresence mode="wait">
          <motion.span
            key={feedbackMessage || centerLabel}
            className="text-lg font-light tracking-[0.2em] select-none pointer-events-none z-10 text-center"
            style={{
              color: "rgba(255, 255, 255, 0.95)",
              textShadow: `0 0 10px ${glowColor}40`,
              fontSize: (feedbackMessage || centerLabel || '').length > 8 ? '0.75rem' : '1.125rem',
              maxWidth: size - 20,
              lineHeight: 1.2,
              marginTop: 0,
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
