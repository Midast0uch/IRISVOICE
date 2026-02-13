"use client"

import React, { useState, useCallback, useEffect, useRef, type ElementType } from "react"
import { motion, AnimatePresence } from "framer-motion"

// Tauri v2 API - imported statically but guarded for browser
import { getCurrentWindow, PhysicalPosition } from '@tauri-apps/api/window'

const isTauri = typeof window !== 'undefined' && (!!(window as any).__TAURI_INTERNALS__ || !!(window as any).__TAURI__)
if (typeof window !== 'undefined') console.log('[IRIS] isTauri:', isTauri, '__TAURI_INTERNALS__:', !!(window as any).__TAURI_INTERNALS__, '__TAURI__:', !!(window as any).__TAURI__)

import { Mic, Brain, Bot, Settings, Database, Activity, Volume2, Headphones, AudioWaveform as Waveform, Link, Cpu, Sparkles, MessageSquare, Palette, Power, Keyboard, Minimize2, RefreshCw, History, FileStack, Trash2, Timer, Clock, BarChart3, DollarSign, TrendingUp, Check, Wrench, Layers, Star, Monitor, HardDrive, Wifi, Bell, Sliders, FileText, Stethoscope, Smile } from "lucide-react"
import { useIRISWebSocket } from "@/hooks/useIRISWebSocket"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { MiniNodeStack } from "./mini-node-stack"
import { PrismNode } from "./iris/prism-node"
import { MenuWindowSlider } from "./menu-window-slider"
import { DarkGlassDashboard } from "./dark-glass-dashboard"

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

const SUB_NODES: Record<string, { id: string; label: string; icon: ElementType; fields: any[] }[]> = {
  voice: [
    { id: "input", label: "INPUT", icon: Mic, fields: [
      { id: "input_device", label: "Input Device", type: "dropdown", options: ["Default", "USB Microphone", "Headset", "Webcam"], defaultValue: "Default" },
      { id: "input_sensitivity", label: "Input Sensitivity", type: "slider", min: 0, max: 100, unit: "%", defaultValue: 50 },
      { id: "noise_gate", label: "Noise Gate", type: "toggle", defaultValue: false },
      { id: "vad", label: "VAD", type: "toggle", defaultValue: true },
    ]},
    { id: "output", label: "OUTPUT", icon: Volume2, fields: [
      { id: "output_device", label: "Output Device", type: "dropdown", options: ["Default", "Headphones", "Speakers", "HDMI"], defaultValue: "Default" },
      { id: "master_volume", label: "Master Volume", type: "slider", min: 0, max: 100, unit: "%", defaultValue: 70 },
    ]},
    { id: "processing", label: "PROCESSING", icon: Waveform, fields: [
      { id: "noise_reduction", label: "Noise Reduction", type: "toggle", defaultValue: true },
      { id: "echo_cancellation", label: "Echo Cancellation", type: "toggle", defaultValue: true },
      { id: "voice_enhancement", label: "Voice Enhancement", type: "toggle", defaultValue: false },
      { id: "automatic_gain", label: "Automatic Gain", type: "toggle", defaultValue: true },
    ]},
    { id: "model", label: "MODEL", icon: Brain, fields: [
      { id: "endpoint", label: "LFM Endpoint", type: "text", placeholder: "http://192.168.0.32:1234", defaultValue: "http://192.168.0.32:1234" },
      { id: "temperature", label: "Temperature", type: "slider", min: 0, max: 2, step: 0.1, defaultValue: 0.7 },
      { id: "max_tokens", label: "Max Tokens", type: "slider", min: 256, max: 8192, step: 256, defaultValue: 2048 },
      { id: "context_window", label: "Context Window", type: "slider", min: 1024, max: 32768, step: 1024, defaultValue: 8192 },
    ]},
  ],
  agent: [
    { id: "identity", label: "IDENTITY", icon: Smile, fields: [
      { id: "assistant_name", label: "Assistant Name", type: "text", placeholder: "IRIS", defaultValue: "IRIS" },
      { id: "personality", label: "Personality", type: "dropdown", options: ["Professional", "Friendly", "Concise", "Creative", "Technical"], defaultValue: "Friendly" },
      { id: "knowledge", label: "Knowledge Focus", type: "dropdown", options: ["General", "Coding", "Writing", "Research", "Conversation"], defaultValue: "General" },
      { id: "response_length", label: "Response Length", type: "dropdown", options: ["Brief", "Balanced", "Detailed", "Comprehensive"], defaultValue: "Balanced" },
    ]},
    { id: "wake", label: "WAKE", icon: Sparkles, fields: [
      { id: "wake_phrase", label: "Wake Phrase", type: "text", placeholder: "Hey Computer", defaultValue: "Hey Computer" },
      { id: "detection_sensitivity", label: "Detection Sensitivity", type: "slider", min: 0, max: 100, defaultValue: 70, unit: "%" },
      { id: "activation_sound", label: "Activation Sound", type: "toggle", defaultValue: true },
      { id: "sleep_timeout", label: "Sleep Timeout", type: "slider", min: 5, max: 300, defaultValue: 60, unit: "s" },
    ]},
    { id: "speech", label: "SPEECH", icon: MessageSquare, fields: [
      { id: "tts_voice", label: "TTS Voice", type: "dropdown", options: ["Nova", "Alloy", "Echo", "Fable", "Onyx", "Shimmer"], defaultValue: "Nova" },
      { id: "speaking_rate", label: "Speaking Rate", type: "slider", min: 0.5, max: 2, step: 0.1, defaultValue: 1.0, unit: "x" },
      { id: "pitch_adjustment", label: "Pitch Adjustment", type: "slider", min: -20, max: 20, defaultValue: 0, unit: "semitones" },
      { id: "pause_duration", label: "Pause Duration", type: "slider", min: 0, max: 2, step: 0.1, defaultValue: 0.2, unit: "s" },
    ]},
    { id: "memory", label: "MEMORY", icon: Database, fields: [
      { id: "context_visualization", label: "Context Visualization", type: "text", placeholder: "View context" },
      { id: "token_count", label: "Token Count", type: "text", placeholder: "0 tokens" },
      { id: "conversation_history", label: "Conversation History", type: "text", placeholder: "Browse history" },
      { id: "clear_memory", label: "Clear Memory", type: "text", placeholder: "Clear" },
    ]},
  ],
  automate: [
    { id: "tools", label: "TOOLS", icon: Wrench, fields: [
      { id: "active_servers", label: "Active Servers", type: "text", placeholder: "Server status" },
      { id: "tool_browser", label: "Tool Browser", type: "text", placeholder: "Browse tools" },
      { id: "quick_actions", label: "Quick Actions", type: "text", placeholder: "Recent tools" },
    ]},
    { id: "workflows", label: "WORKFLOWS", icon: Layers, fields: [
      { id: "workflow_list", label: "Workflow List", type: "text", placeholder: "Saved workflows" },
      { id: "create_workflow", label: "Create Workflow", type: "text", placeholder: "Builder" },
      { id: "schedule", label: "Schedule", type: "text", placeholder: "Schedule" },
    ]},
    { id: "favorites", label: "FAVORITES", icon: Star, fields: [
      { id: "favorite_commands", label: "Favorite Commands", type: "text", placeholder: "Pinned actions" },
      { id: "recent_actions", label: "Recent Actions", type: "text", placeholder: "Recent" },
      { id: "success_rate", label: "Success Rate", type: "text", placeholder: "0%" },
    ]},
    { id: "shortcuts", label: "SHORTCUTS", icon: Keyboard, fields: [
      { id: "global_hotkey", label: "Global Hotkey", type: "text", placeholder: "Ctrl+Space", defaultValue: "Ctrl+Space" },
      { id: "voice_commands", label: "Voice Commands", type: "text", placeholder: "Map commands" },
    ]},
    { id: "gui", label: "GUI AUTOMATION", icon: Monitor, fields: [
      { id: "ui_tars_provider", label: "UI-TARS Provider", type: "dropdown", options: ["cli_npx", "native_python", "api_cloud"], defaultValue: "native_python" },
      { id: "model_provider", label: "Vision Model", type: "dropdown", options: ["anthropic", "volcengine", "local"], defaultValue: "anthropic" },
      { id: "api_key", label: "API Key", type: "text", placeholder: "sk-..." },
      { id: "max_steps", label: "Max Automation Steps", type: "slider", min: 5, max: 50, defaultValue: 25 },
      { id: "safety_confirmation", label: "Require Confirmation", type: "toggle", defaultValue: true },
    ]},
  ],
  system: [
    { id: "power", label: "POWER", icon: Power, fields: [
      { id: "shutdown", label: "Shutdown", type: "text", placeholder: "Shutdown" },
      { id: "restart", label: "Restart", type: "text", placeholder: "Restart" },
      { id: "sleep", label: "Sleep", type: "text", placeholder: "Sleep" },
      { id: "power_profile", label: "Power Profile", type: "dropdown", options: ["Balanced", "Performance", "Battery"], defaultValue: "Balanced" },
    ]},
    { id: "display", label: "DISPLAY", icon: Monitor, fields: [
      { id: "brightness", label: "Brightness", type: "slider", min: 0, max: 100, defaultValue: 50, unit: "%" },
      { id: "resolution", label: "Resolution", type: "dropdown", options: ["Auto", "1920x1080", "2560x1440", "3840x2160"], defaultValue: "Auto" },
      { id: "night_mode", label: "Night Mode", type: "toggle", defaultValue: false },
    ]},
    { id: "storage", label: "STORAGE", icon: HardDrive, fields: [
      { id: "disk_usage", label: "Disk Usage", type: "text", placeholder: "Usage" },
      { id: "quick_folders", label: "Quick Folders", type: "text", placeholder: "Desktop/Downloads/Documents" },
      { id: "cleanup", label: "Cleanup", type: "text", placeholder: "Cleanup" },
    ]},
    { id: "network", label: "NETWORK", icon: Wifi, fields: [
      { id: "wifi_toggle", label: "WiFi", type: "toggle", defaultValue: true },
      { id: "ethernet_status", label: "Ethernet Status", type: "text", placeholder: "Connected" },
      { id: "vpn_connection", label: "VPN Connection", type: "dropdown", options: ["None", "Work", "Personal"], defaultValue: "None" },
    ]},
  ],
  customize: [
    { id: "theme", label: "THEME", icon: Palette, fields: [
      { id: "theme_mode", label: "Theme Mode", type: "dropdown", options: ["Dark", "Light", "Auto"], defaultValue: "Dark" },
      { id: "glow_color", label: "Glow Color", type: "color", defaultValue: "#00ff88" },
      { id: "state_colors", label: "State Colors", type: "toggle", defaultValue: false },
    ]},
    { id: "startup", label: "STARTUP", icon: Power, fields: [
      { id: "launch_startup", label: "Launch at Startup", type: "toggle", defaultValue: false },
      { id: "startup_behavior", label: "Startup Behavior", type: "dropdown", options: ["Show Widget", "Start Minimized", "Start Hidden"], defaultValue: "Show Widget" },
      { id: "welcome_message", label: "Welcome Message", type: "toggle", defaultValue: true },
    ]},
    { id: "behavior", label: "BEHAVIOR", icon: Sliders, fields: [
      { id: "confirm_destructive", label: "Confirm Destructive", type: "toggle", defaultValue: true },
      { id: "undo_history", label: "Undo History", type: "slider", min: 0, max: 50, defaultValue: 10, unit: "actions" },
      { id: "auto_save", label: "Auto Save", type: "toggle", defaultValue: true },
    ]},
    { id: "notifications", label: "NOTIFICATIONS", icon: Bell, fields: [
      { id: "dnd_toggle", label: "Do Not Disturb", type: "toggle", defaultValue: false },
      { id: "notification_sound", label: "Notification Sound", type: "dropdown", options: ["Default", "Chime", "Pulse", "Silent"], defaultValue: "Default" },
      { id: "app_notifications", label: "App Notifications", type: "toggle", defaultValue: true },
    ]},
  ],
  monitor: [
    { id: "analytics", label: "ANALYTICS", icon: BarChart3, fields: [
      { id: "token_usage", label: "Token Usage", type: "text", placeholder: "Usage" },
      { id: "response_latency", label: "Response Latency", type: "text", placeholder: "Latency" },
      { id: "session_duration", label: "Session Duration", type: "text", placeholder: "Duration" },
    ]},
    { id: "logs", label: "LOGS", icon: FileText, fields: [
      { id: "system_logs", label: "System Logs", type: "text", placeholder: "System" },
      { id: "voice_logs", label: "Voice Logs", type: "text", placeholder: "Voice" },
      { id: "mcp_logs", label: "MCP Logs", type: "text", placeholder: "MCP" },
      { id: "export_logs", label: "Export Logs", type: "text", placeholder: "Export" },
    ]},
    { id: "diagnostics", label: "DIAGNOSTICS", icon: Stethoscope, fields: [
      { id: "health_check", label: "Health Check", type: "text", placeholder: "Run" },
      { id: "lfm_benchmark", label: "LFM Benchmark", type: "text", placeholder: "Benchmark" },
      { id: "mcp_test", label: "MCP Test", type: "text", placeholder: "Test MCP" },
    ]},
    { id: "updates", label: "UPDATES", icon: RefreshCw, fields: [
      { id: "update_channel", label: "Update Channel", type: "dropdown", options: ["Stable", "Beta", "Nightly"], defaultValue: "Stable" },
      { id: "check_updates", label: "Check Updates", type: "text", placeholder: "Check" },
      { id: "auto_update", label: "Auto Update", type: "toggle", defaultValue: true },
    ]},
  ],
}

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
  Wrench, Layers, Star, Monitor, HardDrive, Wifi, Bell, Sliders, FileText, Stethoscope, Smile,
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
}

function IrisOrb({ isExpanded, onClick, centerLabel, size, glowColor, voiceState, wakeFlash }: IrisOrbProps) {
  const isSpeaking = voiceState === "speaking"
  const isProcessing = voiceState === "processing_conversation" || voiceState === "processing_tool"

  return (
    <motion.div
      className="relative flex items-center justify-center rounded-full cursor-pointer z-50 pointer-events-auto"
      style={{ width: size, height: size }}
      onMouseDown={onDragMouseDown}
      onClick={onClick}
    >
      {/* Outer breathe glow - more vibrant */}
      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{
          inset: -30,
          background: `radial-gradient(circle, ${glowColor}80 0%, ${glowColor}40 30%, transparent 65%)`,
          filter: "blur(25px)",
        }}
        animate={{
          scale: isSpeaking ? [1.05, 1.3, 1.05] : [1, 1.15, 1],
          opacity: isSpeaking ? [0.8, 1, 0.8] : [0.4, 0.75, 0.4],
        }}
        transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
      />

      {/* Inner core pulse */}
      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{
          inset: -8,
          background: `radial-gradient(circle at 30% 30%, ${glowColor}14, transparent 70%)`,
          filter: "blur(8px)",
        }}
        animate={{
          scale: isProcessing ? [0.9, 1.1, 0.9] : isSpeaking ? [0.8, 1.5, 0.8] : [0.8, 1.2, 0.8],
          opacity: isProcessing ? [0.5, 0.8, 0.5] : [0.6, 1, 0.6],
        }}
        transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
      />

      {/* Wake flash */}
      <AnimatePresence>
        {wakeFlash && (
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
            key={centerLabel}
            className="text-lg font-light tracking-[0.2em] select-none pointer-events-none z-10"
            style={{ 
              color: "rgba(255, 255, 255, 0.95)",
              textShadow: `0 0 10px ${glowColor}40`,
              fontSize: centerLabel.length > 8 ? '0.75rem' : '1.125rem'
            }}
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.8, opacity: 0 }}
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
          >
            {centerLabel}
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

  const handleWakeDetected = useCallback(() => {
    setWakeDetected(true)
    setWakeFlash(true)
    setTimeout(() => setWakeDetected(false), 2000)
    setTimeout(() => setWakeFlash(false), 500)
  }, [])

  const handleOpenDashboard = useCallback(() => {
    setDashboardOpen(true)
  }, [])

  const handleCloseDashboard = useCallback(() => {
    setDashboardOpen(false)
  }, [])

  const {
    confirmedNodes: wsConfirmedNodes,
    currentCategory,
    currentSubnode,
    voiceState,
    selectCategory,
    selectSubnode,
    confirmMiniNode,
  } = useIRISWebSocket("ws://localhost:8000/ws/iris", true, handleWakeDetected)

  useEffect(() => {
    navLevelRef.current = nav.state.level
  }, [nav.state.level])

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
  const centerLabel = activeSubnodeId 
    ? (currentView && SUB_NODES[currentView]?.find(n => n.id === activeSubnodeId)?.label || "IRIS")
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
        if (SUB_NODES[nodeId]?.length > 0) {
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
      const subnodeData = SUB_NODES[currentView!]?.find(n => n.id === subnodeId)
      // Transform fields into proper MiniNode objects - each field becomes a card in the stack
      const fields = subnodeData?.fields || []
      const miniNodes: import("@/types/navigation").MiniNode[] = fields.map((field, index) => ({
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

  const currentNodes = (currentView && SUB_NODES[currentView])
    ? SUB_NODES[currentView].map((node, idx) => ({
        ...node,
        angle: (idx * (360 / SUB_NODES[currentView].length)) - 90,
        index: idx,
      }))
    : NODE_POSITIONS.map((n) => ({ ...n, fields: [] as any[] }))

  const exitingNodes = (exitingView && SUB_NODES[exitingView])
    ? SUB_NODES[exitingView].map((node, idx) => ({
        ...node,
        angle: (idx * (360 / SUB_NODES[exitingView].length)) - 90,
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
              <IrisOrb
                isExpanded={isExpanded}
                onClick={handleIrisClick}
                centerLabel={centerLabel}
                size={irisSize}
                glowColor={glowColor}
                voiceState={voiceState}
                wakeFlash={wakeFlash}
              />
            </div>
          </motion.div>

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
                <MiniNodeStack miniNodes={nav.state.miniNodeStack} onOpenDashboard={handleOpenDashboard} dashboardOpen={dashboardOpen} onCloseDashboard={handleCloseDashboard} />
              </motion.div>
            )}
          </AnimatePresence>

          {/* Exiting nodes */}
          <AnimatePresence>
            {(nav.state.level === 2 || nav.state.level === 3) && exitingNodes && (
              <>
                {exitingNodes.map((node, idx) => (
                  <PrismNode key={`exit-${node.id}`} node={node} angle={node.angle} radius={exitingView ? subRadius : mainRadius} nodeSize={nodeSize} onClick={() => {}} spinRotations={exitingView ? SUBMENU_CONFIG.rotations : SPIN_CONFIG.rotations} spinDuration={exitingView ? SUBMENU_CONFIG.spinDuration : SPIN_CONFIG.spinDuration} staggerIndex={idx} isCollapsing={true} isActive={false} spinConfig={SPIN_CONFIG} />
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
                    />
                  ))}
              </>
            )}
          </AnimatePresence>

          {/* TAP IRIS hint */}
          <AnimatePresence>
            {nav.state.level === 1 && (
              <motion.div
                className="absolute bottom-24 left-1/2 -translate-x-1/2 pointer-events-none"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 10 }}
                transition={{ delay: 0.5, duration: 0.4 }}
              >
                <motion.span
                  className="text-xs text-muted-foreground/60 tracking-widest uppercase"
                  animate={{ opacity: [0.4, 0.8, 0.4] }}
                  transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                >
                  TAP IRIS TO EXPAND
                </motion.span>
              </motion.div>
            )}
          </AnimatePresence>

          <DarkGlassDashboard
            isOpen={dashboardOpen}
            onClose={handleCloseDashboard}
            theme="nebula"
          />
      </div>
    </div>
  )
}
