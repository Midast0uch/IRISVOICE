"use client"

import React, { useState, useCallback, useEffect, useRef, type ElementType } from "react"
import { motion, AnimatePresence } from "framer-motion"

// Tauri v2 API - imported statically but guarded for browser
import { getCurrentWindow, PhysicalPosition } from '@tauri-apps/api/window'

const isTauri = typeof window !== 'undefined' && (!!(window as any).__TAURI_INTERNALS__ || !!(window as any).__TAURI__)
if (typeof window !== 'undefined') console.log('[IRIS] isTauri:', isTauri, '__TAURI_INTERNALS__:', !!(window as any).__TAURI_INTERNALS__, '__TAURI__:', !!(window as any).__TAURI__)

import { Mic, Brain, Bot, Settings, Database, Activity, Volume2, Headphones, AudioWaveform as Waveform, Link, Cpu, Sparkles, MessageSquare, Palette, Power, Keyboard, Minimize2, RefreshCw, History, FileStack, Trash2, Timer, Clock, BarChart3, DollarSign, TrendingUp, Check, Wrench, Layers, Star, Monitor, HardDrive, Wifi, Bell, Sliders, FileText, Stethoscope, Smile, Eye } from "lucide-react"
import { useIRISWebSocket } from "@/hooks/useIRISWebSocket"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { MiniNodeStack } from "./mini-node-stack"
import { PrismNode } from "./iris/prism-node"
import { MenuWindowSlider } from "./menu-window-slider"
import { DarkGlassDashboard } from "./dark-glass-dashboard"
import { ChatView } from "./chat-view"

const SPIN_CONFIG = {
  radiusCollapsed: 0,
  radiusExpanded: 180,
  spinDuration: 1500,
  staggerDelay: 100,
  rotations: 2,
  ease: [0.4, 0, 0.2, 1] as const,
}

const SUBMENU_CONFIG = {
  radius: 140,
  spinDuration: 1500,
  rotations: 2,
}

const MINI_NODE_STACK_CONFIG = {
  size: 90,
  sizeConfirmed: 90,
  borderRadius: 16,
  stackDepth: 50,
  maxVisible: 4,
  offsetX: 0,
  offsetY: 0,
  distanceFromCenter: 260,
  scaleReduction: 0.08,
  padding: 16,
  fieldHeight: 36,
  fieldGap: 12,
}

const ORBIT_CONFIG = {
  radius: 200,
  duration: 800,
  ease: [0.34, 1.56, 0.64, 1] as const,
}

const NODE_POSITIONS = [
  { index: 0, angle: -90, id: "voice", label: "VOICE", icon: Mic, hasSubnodes: true },
  { index: 1, angle: -30, id: "agent", label: "AGENT", icon: Bot, hasSubnodes: true },
  { index: 2, angle: 30, id: "automate", label: "AUTOMATE", icon: Cpu, hasSubnodes: true },
  { index: 3, angle: 90, id: "system", label: "SYSTEM", icon: Settings, hasSubnodes: true },
  { index: 4, angle: 150, id: "customize", label: "CUSTOMIZE", icon: Palette, hasSubnodes: true },
  { index: 5, angle: 210, id: "monitor", label: "MONITOR", icon: Activity, hasSubnodes: true },
]



interface InputField {
  id: string
  label: string
  type: "text" | "slider" | "dropdown" | "toggle" | "color"
  placeholder?: string
  options?: string[]
  min?: number
  max?: number
  step?: number
  unit?: string
  defaultValue?: string | number | boolean
}

interface ConfirmedMiniNode {
  id: string
  label: string
  icon: ElementType | string
  orbitAngle: number
  values: Record<string, string | number | boolean>
}

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(false)
  useEffect(() => {
    const checkMobile = () => setIsMobile(window.innerWidth < 640)
    checkMobile()
    window.addEventListener("resize", checkMobile)
    return () => window.removeEventListener("resize", checkMobile)
  }, [])
  return isMobile
}

function getSpiralPosition(baseAngle: number, radius: number, spinRotations: number) {
  const finalAngleRad = (baseAngle * Math.PI) / 180
  return {
    x: Math.cos(finalAngleRad) * radius,
    y: Math.sin(finalAngleRad) * radius,
    rotation: spinRotations * 360,
  }
}

const ICON_MAP: Record<string, ElementType> = {
  Mic, Brain, Bot, Settings, Database, Activity, Volume2, Headphones, Waveform,
  Link, Cpu, Sparkles, MessageSquare,
  Palette, Power, Keyboard, Minimize2, RefreshCw, History,
  FileStack, Trash2, Timer, Clock, BarChart3, DollarSign, TrendingUp,
  Wrench, Layers, Star, Monitor, HardDrive, Wifi, Bell, Sliders, FileText, Stethoscope, Smile, Eye,
}

// Manual window drag - tracks mouse delta and calls setPosition()
let _dragState: { startX: number; startY: number; winX: number; winY: number } | null = null
let _dragListenersAttached = false

function onDragMouseDown(e: React.MouseEvent) {
  if (!isTauri || e.button !== 0) return
  // Capture screen coords IMMEDIATELY before React recycles the event
  const startX = e.screenX
  const startY = e.screenY
  console.log('[DRAG] mousedown fired', startX, startY)

  // Attach listeners right away so we don't miss any mousemove
  const onMove = (ev: MouseEvent) => {
    if (!_dragState) return
    const dx = ev.screenX - _dragState.startX
    const dy = ev.screenY - _dragState.startY
    getCurrentWindow().setPosition(new PhysicalPosition(_dragState.winX + dx, _dragState.winY + dy))
  }
  const onUp = () => {
    console.log('[DRAG] mouseup - drag ended')
    _dragState = null
    _dragListenersAttached = false
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }

  if (!_dragListenersAttached) {
    _dragListenersAttached = true
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  // Get window position async - drag starts as soon as this resolves
  getCurrentWindow().outerPosition().then(pos => {
    console.log('[DRAG] window position:', pos.x, pos.y)
    _dragState = { startX, startY, winX: pos.x, winY: pos.y }
  }).catch(err => {
    console.error('[DRAG] outerPosition failed:', err)
    // Fallback: try native startDragging
    _dragListenersAttached = false
    window.removeEventListener('mousemove', onMove)
  })
}

interface IrisOrbProps {
  isExpanded: boolean
  onClick: () => void
  centerLabel: string
  size: number
  glowColor: string
  voiceState: "idle" | "listening" | "processing_conversation" | "processing_tool" | "speaking" | "error"
  wakeFlash: boolean
  sendMessage: (type: string, payload?: any) => boolean
  onCallbacksReady?: (callbacks: { handleWakeDetected: () => void; handleNativeAudioResponse: (payload: any) => void }) => void
}

function IrisOrb({ isExpanded, onClick, centerLabel, size, glowColor, voiceState, wakeFlash, sendMessage, onCallbacksReady }: IrisOrbProps) {
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
useEffect(() => {
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

export default function HexagonalControlCenter() {
  const nav = useNavigation()
  const { getThemeConfig } = useBrandColor()
  const theme = getThemeConfig()
  const themeGlowColor = theme.glow.color
  const isMobile = useIsMobile()
  const userNavigatedRef = useRef(false)
  const navLevelRef = useRef(nav.state.level)
  const nodeClickTimestampRef = useRef<number | null>(null)
  const hasUserInteractedRef = useRef(false)

  const [currentView, setCurrentView] = useState<string | null>(null)
  const [pendingView, setPendingView] = useState<string | null>(null)
  const [exitingView, setExitingView] = useState<string | null>(null)
  const [isExpanded, setIsExpanded] = useState(false)
  const [isTransitioning, setIsTransitioning] = useState(false)
  const [activeMiniNodeIndex, setActiveMiniNodeIndex] = useState<number | null>(null)
  const [wakeDetected, setWakeDetected] = useState(false)
  const [dashboardOpen, setDashboardOpen] = useState(false)
  const [wakeFlash, setWakeFlash] = useState(false)
  const [nativeAudioResponse, setNativeAudioResponse] = useState<string | null>(null)
  const [irisCallbacks, setIrisCallbacks] = useState<{ handleWakeDetected: () => void; handleNativeAudioResponse: (payload: any) => void } | null>(null)
  const [isChatActive, setIsChatActive] = useState(false)
  const [hintText, setHintText] = useState("Tap IRIS to expand")

  const handleOpenDashboard = useCallback(() => {
    setDashboardOpen(true)
  }, [])

  const handleCloseDashboard = useCallback(() => {
    setDashboardOpen(false)
  }, [])

  const handleToggleChat = useCallback(() => {
    setIsChatActive(prev => !prev)
  }, [])

  const handleCloseChat = useCallback(() => {
    setIsChatActive(false)
  }, [])

  const handleUpdateField = (subnodeId: string, fieldId: string, value: any) => {
    // This is a placeholder for the actual implementation
    console.log(`Updating field: ${subnodeId}.${fieldId} = ${value}`)
  }

  const handleWakeDetected = useCallback(() => {
    console.log("[HexagonalControlCenter] Wake word detected")
    setWakeDetected(true)
    setWakeFlash(true)
    setTimeout(() => setWakeDetected(false), 2000)
    setTimeout(() => setWakeFlash(false), 500)
    
    // Call the IrisOrb callback if available
    if (irisCallbacks?.handleWakeDetected) {
      irisCallbacks.handleWakeDetected()
    }
  }, [irisCallbacks])

  const handleNativeAudioResponse = useCallback((payload: any) => {
    console.log("[HexagonalControlCenter] Native audio response received:", payload)
    if (payload.debug_text) {
      setNativeAudioResponse(payload.debug_text)
      // Clear the response after a few seconds
      setTimeout(() => setNativeAudioResponse(null), 5000)
    }
    
    // Call the IrisOrb callback if available
    if (irisCallbacks?.handleNativeAudioResponse) {
      irisCallbacks.handleNativeAudioResponse(payload)
    }
  }, [irisCallbacks])

  const {
    confirmedNodes: wsConfirmedNodes,
    currentCategory,
    currentSubnode,
    voiceState,
    fieldValues,
    subnodes,
    updateField,
    selectCategory,
    selectSubnode,
    confirmMiniNode,
    sendMessage,
  } = useIRISWebSocket("ws://localhost:8000/ws/iris", true, handleWakeDetected, handleNativeAudioResponse)

  const updateModelConfig = (config: any) => {
    sendMessage(JSON.stringify({
      type: "update_model_config",
      config: config,
    }));
  };

  useEffect(() => {
    navLevelRef.current = nav.state.level
  }, [nav.state.level])

  // Text cycling effect
  useEffect(() => {
    const textCycle = ["Tap to expand", "Open chat", "Double-tap for voice"]
    let currentIndex = 0
    const interval = setInterval(() => {
      currentIndex = (currentIndex + 1) % textCycle.length
      setHintText(textCycle[currentIndex])
    }, 3000) // Change text every 3 seconds

    return () => clearInterval(interval)
  }, [])

  // Ensure window starts interactive (solid, not click-through) - Tauri only
  useEffect(() => {
    if (!isTauri) return

    const setupWindow = async () => {
      const appWindow = await getCurrentWindow()
      await appWindow.setIgnoreCursorEvents(false)
    }
    setupWindow()
  }, [])

  useEffect(() => {
    // Skip backend sync if user has manually navigated
    if (userNavigatedRef.current) {
      return
    }

    // CRITICAL: Never auto-expand from backend on initial load
    // Only sync backend state after user has explicitly interacted
    if (!hasUserInteractedRef.current) {
      return
    }

    // Skip if category is empty (user just cleared it)
    if (!currentCategory) {
      return
    }

    // CRITICAL: If we are at Level 1 (Idle), DO NOT allow the backend to force an expansion.
    // The user must manually click the Iris orb to enter Level 2.
    if ((nav.state.level as number) === 1) {
      return
    }

    // CRITICAL FIX: Don't auto-navigate to Level 3 on initial load/refresh
    // Only sync the view without advancing navigation level automatically
    // This prevents the "random main node on refresh" issue
    if (!isTransitioning && !pendingView && currentCategory !== currentView && !exitingView) {
      // Only expand to show main nodes (Level 2), don't set currentView to show subnodes
      // This prevents the backend from forcing Level 3 on refresh
      if (!isExpanded && (nav.state.level as number) === 1) {
        setIsExpanded(true)

        nav.expandToMain()
      }
      // Note: We intentionally do NOT call nav.selectMain() or setCurrentView here
      // User must explicitly click a main node to reach Level 3
    }

    if (pendingView && currentCategory === pendingView) {
      setPendingView(null)
    }
  }, [currentCategory, currentView, exitingView, isTransitioning, pendingView, isExpanded, nav])

  const glowColor = themeGlowColor || "#00ff88"

  const activeSubnodeId = currentSubnode
  const centerLabel = isChatActive
    ? "" // Hide center label when chat is active
    : activeSubnodeId
      ? (currentView && subnodes[currentView]?.find(n => n.id === activeSubnodeId)?.label || "IRIS")
      : (currentView ? NODE_POSITIONS.find(n => n.id === currentView)?.label : "IRIS") || "IRIS"

  const confirmedNodes: ConfirmedMiniNode[] = wsConfirmedNodes.map(n => ({
    id: n.id,
    label: n.label,
    icon: n.icon,
    orbitAngle: n.orbit_angle,
    values: n.values
  }))

  const irisSize = isMobile ? 120 : 140
  const nodeSize = isMobile ? 80 : 90
  const mainRadius = isMobile ? 140 : SPIN_CONFIG.radiusExpanded
  const subRadius = isMobile ? 110 : SUBMENU_CONFIG.radius
  const orbitRadius = isMobile ? 160 : ORBIT_CONFIG.radius

  const handleNodeClick = useCallback(
    (nodeId: string, nodeLabel: string, hasSubnodes: boolean) => {
      const currentNavLevel = nav.state.level

      if (isTransitioning) {
        return
      }

      // Navigate if:
      // 1. At Level 2 (main nodes showing) - clicking goes to Level 3
      // 2. At Level 3 but clicking a DIFFERENT main node - switch to that node's subnodes
      const shouldNavigate = currentNavLevel === 2 ||
        (currentNavLevel === 3 && nav.state.selectedMain !== nodeId)

      if (shouldNavigate) {
        if (subnodes[nodeId]?.length > 0) {
          userNavigatedRef.current = true
          setExitingView(currentNavLevel === 3 ? nav.state.selectedMain : "__main__")
          setIsTransitioning(true)
          setActiveMiniNodeIndex(null)
          setPendingView(nodeId)
          setCurrentView(nodeId)

          // If at Level 3, go back first then to new main
          if (currentNavLevel === 3) {
            nav.goBack() // Go from Level 3→2 first
          }

          // Use NavigationContext to advance to Level 3
          nav.selectMain(nodeId)

          setTimeout(() => {
            setExitingView(null)
            setIsTransitioning(false)
            selectCategory(nodeId)
            // Reset userNavigatedRef to allow backend sync again
            userNavigatedRef.current = false
          }, SPIN_CONFIG.spinDuration)
        }
      }
    },
    [isTransitioning, selectCategory, nav, currentView]
  )

  const handleSubnodeClick = useCallback((subnodeId: string) => {
    // Read nav.state.level fresh to avoid stale closure
    const currentNavLevel = nav.state.level

    if (activeSubnodeId === subnodeId) {
      selectSubnode(null)
      nav.goBack()
      setActiveMiniNodeIndex(null)
    } else {
      // Get mini nodes for this subnode and navigate to level 4
      const subnodeData = subnodes[currentView!]?.find(n => n.id === subnodeId)
      // Transform fields into proper MiniNode objects - each field becomes a card in the stack
      const fields = subnodeData?.fields || []
      const miniNodes: import("@/types/navigation").MiniNode[] = fields.map((field: import("@/types/navigation").FieldConfig, index: number) => ({
        id: `${subnodeId}_${field.id}`,
        label: field.label,
        icon: "Settings",
        fields: [field]
      }))

      // CRITICAL: Call nav.selectSub() FIRST to trigger Level 4 navigation
      // This updates the navigation state and sets miniNodeStack
      nav.selectSub(subnodeId, miniNodes)

      // Update backend state
      selectSubnode(subnodeId)
    }
  }, [activeSubnodeId, currentView, nav, selectSubnode])

  const handleIrisClick = useCallback((e?: React.MouseEvent) => {
    // Check if a node was just clicked (within last 300ms) - prevents iris toggle when clicking nodes
    const timeSinceNodeClick = Date.now() - (nodeClickTimestampRef.current || 0)
    if (timeSinceNodeClick < 300) {
      return
    }

    if (isTransitioning) {
      return
    }

    // Use current level from nav state directly
    const level = nav.state.level

    // DEFENSIVE: Check if userNavigatedRef is already true (prevent double navigation)
    if (userNavigatedRef.current) {
      return
    }

    // Mark that user has explicitly interacted - enables backend sync
    hasUserInteractedRef.current = true

    if (level === 4) {
      // Level 4: Mini nodes active -> go back to level 3 (subnodes)
      userNavigatedRef.current = true
      nav.goBack()
      selectSubnode(null)
      setActiveMiniNodeIndex(null)
      setTimeout(() => {
        userNavigatedRef.current = false
      }, SPIN_CONFIG.spinDuration)
    } else if (level === 3) {
      // Level 3: Subnodes showing -> go back to level 2 (main nodes)
      userNavigatedRef.current = true
      nav.goBack()

      // Immediately transition view state to show main nodes
      setExitingView(currentView)
      setCurrentView(null)
      setIsTransitioning(true)

      // Clear backend category
      selectCategory("")

      setTimeout(() => {
        setExitingView(null)
        setIsTransitioning(false)
        userNavigatedRef.current = false
      }, SPIN_CONFIG.spinDuration)
    } else if (level === 2) {
      // Level 2: Main nodes showing -> collapse to level 1 (idle)
      userNavigatedRef.current = true
      nav.collapseToIdle()
      setIsExpanded(false)
      setIsTransitioning(true)

      // Clear backend category to prevent it from restoring on refresh
      selectCategory("")

      setTimeout(() => {
        setIsTransitioning(false)
        userNavigatedRef.current = false
      }, SPIN_CONFIG.spinDuration)
    } else {
      // Level 1: Idle -> expand to level 2 (main nodes)
      userNavigatedRef.current = true
      nav.expandToMain()
      setIsExpanded(true)
      setIsTransitioning(true)

      setTimeout(() => {
        setIsTransitioning(false)
        userNavigatedRef.current = false
      }, SPIN_CONFIG.spinDuration)
    }
  }, [currentView, isExpanded, isTransitioning, activeSubnodeId, selectSubnode, selectCategory, nav])

  const currentNodes = (currentView && subnodes && subnodes[currentView])
    ? subnodes[currentView].map((node: any, idx: number) => ({
      ...node,
      angle: (idx * (360 / subnodes[currentView].length)) - 90,
      index: idx,
    }))
    : NODE_POSITIONS.map((n) => ({ ...n, fields: [] as any[] }))

  const exitingNodes = (exitingView && subnodes && subnodes[exitingView])
    ? subnodes[exitingView].map((node: any, idx: number) => ({
      ...node,
      angle: (idx * (360 / subnodes[exitingView].length)) - 90,
      index: idx,
    }))
    : NODE_POSITIONS.map((n) => ({ ...n, fields: [] as any[] }))


  return (
    <div className="relative w-full h-full">
      <div className="relative w-full h-full overflow-hidden">
        {/* Center IRIS Orb */}
        <motion.div
          className="absolute left-1/2 top-1/2 flex items-center justify-center pointer-events-none z-[150]"
          style={{
            marginLeft: -(irisSize + 120) / 2,
            marginTop: -(irisSize + 120) / 2,
            width: irisSize + 120,
            height: irisSize + 120,
          }}
          animate={{ scale: nav.state.level === 4 ? 0.43 : 1, x: 0 }}
          transition={{ type: "spring", stiffness: 200, damping: 20, duration: 0.5 }}
          onMouseDown={onDragMouseDown}
        >
          <div
            className="pointer-events-auto flex items-center justify-center"
            style={{ width: irisSize, height: irisSize }}
            role="button"
            data-no-drag
            data-tauri-drag-region="false"
            aria-label={`IRIS Control Center - ${centerLabel}`}
            aria-live="polite"
          >
            <div className="relative z-50 pointer-events-auto">
              <IrisOrb
                isExpanded={isExpanded}
                onClick={handleIrisClick}
                centerLabel={centerLabel}
                size={irisSize}
                glowColor={glowColor}
                voiceState={voiceState}
                wakeFlash={wakeFlash}
                sendMessage={sendMessage}
                onCallbacksReady={setIrisCallbacks}
              />
            </div>
          </div>
        </motion.div>

        {/* Chat view overlay */}
        <ChatView 
          isActive={isChatActive}
          onClose={handleCloseChat}
          sendMessage={sendMessage}
          fieldValues={confirmedNodes.reduce((acc, node) => ({ ...acc, ...node.values }), {})}
          updateField={handleUpdateField}
        />

        {/* Connecting line between Iris Orb and Mini Stack */}
        <AnimatePresence>
          {nav.state.level === 4 && (() => {
            const activeIndex = nav.state.activeMiniNodeIndex ?? 0
            const targetY = -80 + (activeIndex * 32) + 14
            const lineLength = 80
            const rotation = (Math.atan2(targetY, lineLength) * 180) / Math.PI
            return (
              <motion.div
                className="absolute left-1/2 top-1/2 pointer-events-none z-[55]"
                style={{
                  height: 2, width: lineLength, marginTop: 0, marginLeft: 30,
                  background: `linear-gradient(90deg, rgba(255,255,255,0.8) 0%, rgba(192,192,192,0.9) 20%, rgba(255,255,255,0.95) 40%, rgba(192,192,192,0.9) 60%, rgba(255,255,255,0.8) 80%, rgba(128,128,128,0.6) 100%)`,
                  boxShadow: '0 0 4px rgba(255,255,255,0.5)', transformOrigin: 'left center',
                }}
                initial={{ opacity: 0, scaleX: 0, rotate: 0 }}
                animate={{ opacity: 1, scaleX: 1, rotate: rotation }}
                exit={{ opacity: 0, scaleX: 0 }}
                transition={{ duration: 0.3 }}
              />
            )
          })()}
        </AnimatePresence>

        {/* Mini Node Stack - Level 4 */}
        <AnimatePresence>
          {nav.state.level === 4 && nav.state.miniNodeStack.length > 0 && (
            <motion.div
              className="absolute left-1/2 top-1/2 pointer-events-auto z-[200]"
              style={{ marginLeft: 80, marginTop: -80, width: 160, height: 200 }}
              initial={{ opacity: 0, scale: 0.8, x: -20 }}
              animate={{ opacity: 1, scale: 1, x: 0 }}
              exit={{ opacity: 0, scale: 0.8, x: -20 }}
              transition={{ duration: 0.4 }}
            >
              <MiniNodeStack miniNodes={nav.state.miniNodeStack} onOpenDashboard={handleOpenDashboard} dashboardOpen={dashboardOpen} onCloseDashboard={handleCloseDashboard} updateModelConfig={updateModelConfig} />
            </motion.div>
          )}
        </AnimatePresence>

        {/* Exiting nodes */}
        <AnimatePresence>
          {(nav.state.level === 2 || nav.state.level === 3) && exitingNodes && (
            <>
              {exitingNodes.map((node, idx) => (
                <PrismNode key={`exit-${node.id}`} node={node} angle={node.angle} radius={exitingView ? subRadius : mainRadius} nodeSize={nodeSize} onClick={() => { }} spinRotations={exitingView ? SUBMENU_CONFIG.rotations : SPIN_CONFIG.rotations} spinDuration={exitingView ? SUBMENU_CONFIG.spinDuration : SPIN_CONFIG.spinDuration} staggerIndex={idx} isCollapsing={true} isActive={false} spinConfig={SPIN_CONFIG} />
              ))}
            </>
          )}
        </AnimatePresence>

        {/* Current nodes - INTERACTIVE */}
        <AnimatePresence>
          {(nav.state.level === 2 || nav.state.level === 3) && (
            <>
              {currentNodes
                .filter((node) => !activeSubnodeId || node.id !== activeSubnodeId)
                .map((node, idx) => (
                  <PrismNode
                    key={node.id}
                    node={node}
                    angle={node.angle}
                    radius={currentView ? subRadius : mainRadius}
                    nodeSize={nodeSize}
                    onClick={(e) => {
                      nodeClickTimestampRef.current = Date.now()
                      e?.stopPropagation()
                      currentView ? handleSubnodeClick(node.id) : handleNodeClick(node.id, node.label, (node as any).hasSubnodes)
                    }}
                    spinRotations={currentView ? SUBMENU_CONFIG.rotations : SPIN_CONFIG.rotations}
                    spinDuration={currentView ? SUBMENU_CONFIG.spinDuration : SPIN_CONFIG.spinDuration}
                    staggerIndex={idx}
                    isCollapsing={false}
                    isActive={activeSubnodeId === node.id}
                    spinConfig={SPIN_CONFIG}
                    isChatActive={isChatActive}
                  />
                ))}
            </>
          )}
        </AnimatePresence>

        {/* Cycling hint text */}
        <AnimatePresence>
          {nav.state.level === 1 && (
            <motion.div
              className="absolute bottom-24 left-1/2 -translate-x-1/2 pointer-events-auto cursor-pointer"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 10 }}
              transition={{ delay: 0.5, duration: 0.4 }}
              onClick={() => {
                if (hintText === "Open chat") {
                  handleToggleChat()
                }
              }}
            >
              <motion.span
                key={hintText}
                className="text-xs text-muted-foreground/60 tracking-widest uppercase"
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ opacity: [0.4, 0.8, 0.4] }}
                transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                exit={{ scale: 0.9, opacity: 0 }}
              >
                {hintText}
              </motion.span>
            </motion.div>
          )}
        </AnimatePresence>

        <DarkGlassDashboard
          isOpen={dashboardOpen}
          onClose={handleCloseDashboard}
          theme="nebula"
          fieldValues={fieldValues}
          updateField={updateField}
        />
      </div>
    </div>
  )
}