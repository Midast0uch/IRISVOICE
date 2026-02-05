"use client"

import React, { useState, useCallback, useEffect, useRef, type ElementType } from "react"
import { motion, AnimatePresence } from "framer-motion"

// Tauri imports - only work in Tauri app, not browser
let getCurrentWindow: any = null
let PhysicalPosition: any = null
if (typeof window !== 'undefined' && (window as any).__TAURI__) {
  try {
    const tauriWindow = require('@tauri-apps/api/window')
    getCurrentWindow = tauriWindow.getCurrentWindow
    PhysicalPosition = tauriWindow.PhysicalPosition
  } catch (e) {
    console.log('Tauri not available, running in browser mode')
  }
}

import { Mic, Brain, Bot, Settings, Database, Activity, Volume2, Headphones, AudioWaveform as Waveform, Link, Cpu, Sparkles, MessageSquare, Palette, Power, Keyboard, Minimize2, RefreshCw, History, FileStack, Trash2, Timer, Clock, BarChart3, DollarSign, TrendingUp, Check, Wrench, Layers, Star, Monitor, HardDrive, Wifi, Bell, Sliders, FileText, Stethoscope, Smile } from "lucide-react"
import { useIRISWebSocket } from "@/hooks/useIRISWebSocket"
import { useNavigation } from "@/contexts/NavigationContext"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { MiniNodeStack } from "./mini-node-stack"
import { PrismNode } from "./iris/prism-node"

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
      { id: "endpoint", label: "LFM Endpoint", type: "text", placeholder: "http://localhost:1234", defaultValue: "http://localhost:1234" },
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
      { id: "wake_phrase", label: "Wake Phrase", type: "text", placeholder: "Hey IRIS", defaultValue: "Hey IRIS" },
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

// ===========================================
// MANUAL DRAG HOOK (Replaces useDragOrClick)
// Uses setPosition instead of startDragging to bypass Windows Snap Assist
// ===========================================
function useManualDragWindow(onClickAction: () => void, elementRef: React.RefObject<HTMLElement | null>) {
  const isDragging = useRef(false)
  const dragStartPos = useRef({ x: 0, y: 0 })
  const windowStartPos = useRef({ x: 0, y: 0 })
  const hasDragged = useRef(false)
  const isDraggingThisElement = useRef(false)
  const mouseDownTarget = useRef<EventTarget | null>(null)

  const handleMouseDown = useCallback(async (e: React.MouseEvent) => {
    if (e.button !== 0) return
    
    // Get fresh ref value - don't rely on closure
    const currentElement = elementRef.current
    const target = e.target as Node
    
    // CRITICAL FIX: Only start drag if clicking directly on this element or its children
    const shouldStartDrag = currentElement && currentElement.contains(target)
    
    if (!shouldStartDrag) {
      console.log('[Nav System] handleMouseDown: REJECTED - click not on iris orb')
      return
    }

    console.log('[Nav System] handleMouseDown: ACCEPTED - starting drag')
    mouseDownTarget.current = e.target
    isDragging.current = true
    isDraggingThisElement.current = true
    hasDragged.current = false
    dragStartPos.current = { x: e.screenX, y: e.screenY }
    
    // Only enable dragging in Tauri app
    if (!getCurrentWindow) return
    
    const win = getCurrentWindow()
    const pos = await win.outerPosition()
    windowStartPos.current = { x: pos.x, y: pos.y }
    
    document.body.style.cursor = 'grabbing'
    document.body.style.userSelect = 'none'
  }, [])

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!isDragging.current || !isDraggingThisElement.current) return
    
    // Only enable dragging in Tauri app
    if (!getCurrentWindow || !PhysicalPosition) return
    
    const dx = e.screenX - dragStartPos.current.x
    const dy = e.screenY - dragStartPos.current.y
    
    if (Math.abs(dx) > 5 || Math.abs(dy) > 5) {
      hasDragged.current = true
    }
    
    const win = getCurrentWindow()
    win.setPosition(new PhysicalPosition(windowStartPos.current.x + dx, windowStartPos.current.y + dy))
  }, [])

  const handleMouseUp = useCallback((e: MouseEvent) => {
    // Get fresh ref values - don't rely on closure
    const currentElement = elementRef.current
    const draggingThis = isDraggingThisElement.current
    const didDrag = hasDragged.current
    const downTarget = mouseDownTarget.current
    
    console.log('[Nav System] handleMouseUp:', { 
      draggingThis, 
      didDrag,
      hasElement: !!currentElement,
      downTarget,
      upTarget: e.target
    })
    
    isDragging.current = false
    document.body.style.cursor = 'default'
    document.body.style.userSelect = ''
    
    // CRITICAL FIX: Only trigger click if:
    // 1. We started dragging on this element
    // 2. We didn't actually drag (just clicked)
    // 3. BOTH mousedown AND mouseup targets are inside the iris orb element
    if (draggingThis && !didDrag && currentElement) {
      const upTarget = e.target as Node
      const downTargetNode = downTarget as Node
      
      // Check if mouseup target is inside the iris orb element
      const upInIris = currentElement.contains(upTarget)
      // Check if mousedown target was in iris
      const downInOrb = downTargetNode && currentElement.contains(downTargetNode)
      
      console.log('[Nav System] Click check:', { 
        upInIris, 
        downInOrb,
        shouldTrigger: upInIris && downInOrb
      })
      
      // Only click if BOTH mousedown AND mouseup happened on the iris orb
      if (upInIris && downInOrb) {
        console.log('[Nav System] Triggering onClickAction')
        onClickAction()
      } else {
        console.log('[Nav System] Click rejected - not in iris orb')
      }
    }
    
    // Always reset state
    isDraggingThisElement.current = false
    mouseDownTarget.current = null
    hasDragged.current = false
  }, [onClickAction])

  useEffect(() => {
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [handleMouseMove, handleMouseUp])

  return { handleMouseDown }
}

interface IrisOrbProps {
  isExpanded: boolean
  onClick: () => void
  centerLabel: string
  size: number
  glowColor: string
}

function IrisOrb({ isExpanded, onClick, centerLabel, size, glowColor }: IrisOrbProps) {
  const orbRef = useRef<HTMLDivElement>(null)
  const { handleMouseDown } = useManualDragWindow(onClick, orbRef)
  const [isWaking, setIsWaking] = useState(false)

  return (
    <motion.div
      ref={orbRef}
      className="relative flex items-center justify-center rounded-full cursor-grab active:cursor-grabbing z-50 pointer-events-auto"
      style={{ width: size, height: size }}
      onMouseDown={handleMouseDown}
    >
      {/* Outer breathe glow - more vibrant */}
      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{
          inset: -70,
          background: `radial-gradient(circle, ${glowColor}90 0%, ${glowColor}50 30%, transparent 70%)`,
          filter: "blur(40px)",
        }}
        animate={{ scale: [1, 1.7, 1], opacity: [0.7, 1, 0.7] }}
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
        animate={{ scale: [0.8, 1.4, 0.8], opacity: [0.7, 1, 0.7] }}
        transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
      />

      {/* Wake flash */}
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

      {/* Radar Sweep - rotating light across orb surface */}
      <motion.div
        className="absolute inset-0 rounded-full pointer-events-none overflow-hidden"
        style={{
          background: 'transparent',
        }}
      >
        <motion.div
          className="absolute inset-0"
          style={{
            background: `conic-gradient(from 0deg at 50% 50%,
              transparent 0deg,
              transparent 88deg,
              rgba(255,255,255,0.15) 98deg,
              rgba(255,255,255,0.8) 100deg,
              rgba(255,255,255,0.15) 102deg,
              transparent 112deg,
              transparent 360deg)`,
          }}
          animate={{ rotate: 360 }}
          transition={{ duration: 4, repeat: Infinity, ease: "linear" }}
        />
      </motion.div>

      {/* Thin liquid metal border - metallic reflection */}
      <motion.div
        className="absolute -inset-[3px] rounded-full pointer-events-none"
        style={{
          padding: "3px",
          background: `conic-gradient(from 0deg, 
            rgba(255,255,255,0) 0deg,
            rgba(255,255,255,0.5) 90deg,
            rgba(192,192,192,0.6) 180deg,
            rgba(255,255,255,0.5) 270deg,
            rgba(255,255,255,0) 360deg)`,
          WebkitMask: "linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)",
          WebkitMaskComposite: "xor",
        }}
        animate={{ rotate: -360 }}
        transition={{ duration: 12, repeat: Infinity, ease: "linear" }}
      />

      {/* Rotating shimmer */}
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

      {/* Orb body */}
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

        <AnimatePresence mode="wait">
          <motion.span
            key={centerLabel}
            className="text-lg font-medium tracking-[0.2em] select-none pointer-events-none"
            style={{ 
              color: "#ffffff",
              textShadow: '0 0 4px rgba(0,0,0,0.8), 0 2px 4px rgba(0,0,0,0.6)'
            }}
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0, opacity: 0 }}
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
          >
            <motion.span
              animate={{ textShadow: [`0 0 10px ${glowColor}4d`, `0 0 20px ${glowColor}99`, `0 0 10px ${glowColor}4d`] }}
              transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
            >
              {centerLabel}
            </motion.span>
          </motion.span>
        </AnimatePresence>
      </div>
    </motion.div>
  )
}

export function HexagonalControlCenter() {
  const nav = useNavigation()
  const { getThemeConfig, theme: brandTheme, setTheme } = useBrandColor()
  const theme = getThemeConfig()
  const themeGlowColor = theme.glow.color
  
  // DEBUG: Log theme state
  useEffect(() => {
    console.log('[Nav System] BrandColorContext theme:', brandTheme)
    console.log('[Nav System] Computed theme config:', theme.name, 'glow:', themeGlowColor)
  }, [brandTheme, theme, themeGlowColor])
  
  const {
    theme: wsTheme,
    confirmedNodes: wsConfirmedNodes,
    currentCategory,
    currentSubnode,
    selectCategory,
    selectSubnode,
    confirmMiniNode,
    updateTheme,
  } = useIRISWebSocket("ws://localhost:8000/ws/iris")

  const [currentView, setCurrentView] = useState<string | null>(null)
  const [pendingView, setPendingView] = useState<string | null>(null)
  const [exitingView, setExitingView] = useState<string | null>(null)
  const [isExpanded, setIsExpanded] = useState(false)
  const [isTransitioning, setIsTransitioning] = useState(false)
  const [activeMiniNodeIndex, setActiveMiniNodeIndex] = useState<number | null>(null)
  const isMobile = useIsMobile()

  // Refs for tracking navigation state and preventing stale closures
  const userNavigatedRef = useRef(false)
  const navLevelRef = useRef(nav.state.level)
  const nodeClickTimestampRef = useRef<number | null>(null)

  // Update navLevelRef on every render to keep it fresh
  useEffect(() => {
    navLevelRef.current = nav.state.level
  }, [nav.state.level])

  // Ensure window starts interactive (solid, not click-through) - Tauri only
  useEffect(() => {
    if (!getCurrentWindow) return
    
    const setupWindow = async () => {
      const appWindow = await getCurrentWindow()
      await appWindow.setIgnoreCursorEvents(false)
    }
    setupWindow()
  }, [])

  useEffect(() => {
    // Skip backend sync if user has manually navigated
    if (userNavigatedRef.current) {
      console.log('[Nav System] Skipping backend sync - user has manually navigated')
      return
    }
    
    // Skip if category is empty (user just cleared it)
    if (!currentCategory) {
      console.log('[Nav System] Skipping backend sync - currentCategory is empty')
      return
    }
    
    console.log('[Nav System] Backend sync useEffect running:', {
      currentCategory,
      currentView,
      isTransitioning,
      pendingView,
      exitingView,
      navLevel: nav.state.level,
      isExpanded,
      condition: !isTransitioning && !pendingView && currentCategory !== currentView && !exitingView
    })
    
    // CRITICAL FIX: Don't auto-navigate to Level 3 on initial load/refresh
    // Only sync the view without advancing navigation level automatically
    // This prevents the "random main node on refresh" issue
    if (!isTransitioning && !pendingView && currentCategory !== currentView && !exitingView) {
      console.log('[Nav System] Setting currentView to currentCategory (without auto-navigating):', currentCategory)
      setCurrentView(currentCategory)
      
      // Only expand to show main nodes (Level 2), don't auto-select a main node
      // This prevents the backend from forcing Level 3 on refresh
      if (!isExpanded && nav.state.level === 1) {
        console.log('[Nav System] Expanding to main nodes (Level 2) from backend category')
        setIsExpanded(true)
        nav.expandToMain()
      }
      // Note: We intentionally do NOT call nav.selectMain() here
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

  const irisSize = isMobile ? 110 : 140
  const nodeSize = isMobile ? 72 : 90
  const mainRadius = isMobile ? 140 : SPIN_CONFIG.radiusExpanded
  const subRadius = isMobile ? 110 : SUBMENU_CONFIG.radius
  const orbitRadius = isMobile ? 160 : ORBIT_CONFIG.radius

  const handleNodeClick = useCallback(
    (nodeId: string, nodeLabel: string, hasSubnodes: boolean) => {
      const currentNavLevel = nav.state.level
      
      console.log('[Nav System] handleNodeClick START:', { 
        nodeId, 
        nodeLabel, 
        hasSubnodes, 
        currentView, 
        isTransitioning, 
        navLevel: currentNavLevel,
        timestamp: Date.now()
      })
      
      if (isTransitioning) {
        console.log('[Nav System] handleNodeClick blocked - isTransitioning')
        return
      }

      // Navigate if:
      // 1. At Level 2 (main nodes showing) - clicking goes to Level 3
      // 2. At Level 3 but clicking a DIFFERENT main node - switch to that node's subnodes
      const shouldNavigate = currentNavLevel === 2 || 
        (currentNavLevel === 3 && nav.state.selectedMain !== nodeId)

      if (shouldNavigate) {
        console.log('[Nav System] Should navigate to subnodes:', { nodeId, fromLevel: currentNavLevel })
        if (SUB_NODES[nodeId]?.length > 0) {
          console.log('[Nav System] Found subnodes, proceeding with navigation')
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
          console.log('[Nav System] Calling nav.selectMain() for nodeId:', nodeId)
          nav.selectMain(nodeId)
          console.log('[Nav System] selectMain called:', { nodeId, level: nav.state.level })

          setTimeout(() => {
            console.log('[Nav System] Transition timeout completed')
            setExitingView(null)
            setIsTransitioning(false)
            selectCategory(nodeId)
            // Reset userNavigatedRef to allow backend sync again
            userNavigatedRef.current = false
          }, SPIN_CONFIG.spinDuration)
        } else {
          console.log('[Nav System] No subnodes found for nodeId:', nodeId)
        }
      } else {
        console.log('[Nav System] Skipping navigation:', { currentNavLevel, nodeId })
      }
    },
    [isTransitioning, selectCategory, nav, currentView]
  )

  const handleSubnodeClick = useCallback((subnodeId: string) => {
    // Read nav.state.level fresh to avoid stale closure
    const currentNavLevel = nav.state.level
    
    console.log('[Nav System] handleSubnodeClick START:', { 
      subnodeId, 
      activeSubnodeId,
      currentView,
      navLevel: currentNavLevel,
      navSelectedMain: nav.state.selectedMain,
      navSelectedSub: nav.state.selectedSub
    })

    if (activeSubnodeId === subnodeId) {
      console.log('[Nav System] Deselecting subnode, going back to Level 3')
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

      console.log('[Nav System] Attempting Level 4 navigation:', { 
        subnodeId, 
        subnodeFound: !!subnodeData,
        miniNodesCount: miniNodes.length,
        miniNodes: miniNodes,
      })
      
      // CRITICAL: Call nav.selectSub() FIRST to trigger Level 4 navigation
      // This updates the navigation state and sets miniNodeStack
      nav.selectSub(subnodeId, miniNodes)
      
      // Update backend state
      selectSubnode(subnodeId)
    }
  }, [activeSubnodeId, currentView, nav, selectSubnode])

  const handleIrisClick = useCallback((e?: React.MouseEvent) => {
    // CRITICAL FIX: Read nav level from the ref which is updated every render
    const freshNavLevel = navLevelRef.current
    
    console.log('[Nav System] handleIrisClick START:', { isTransitioning, activeSubnodeId, currentView, isExpanded, freshNavLevel, target: e?.target })

    // Check if a node was just clicked (within last 300ms) - prevents iris toggle when clicking nodes
    const timeSinceNodeClick = Date.now() - (nodeClickTimestampRef.current || 0)
    if (timeSinceNodeClick < 300) {
      console.log('[Nav System] handleIrisClick blocked - node was just clicked', timeSinceNodeClick, 'ms ago')
      return
    }

    if (isTransitioning) {
      console.log('[Nav System] handleIrisClick blocked - isTransitioning')
      return
    }

    // Use freshNavLevel to determine proper back navigation (not the stale closure value)
    const level = freshNavLevel
    
    // DEFENSIVE: Prevent any back navigation if we're transitioning
    if (isTransitioning) {
      console.log('[Nav System] handleIrisClick blocked - isTransitioning')
      return
    }
    
    // DEFENSIVE: Check if userNavigatedRef is already true (prevent double navigation)
    if (userNavigatedRef.current) {
      console.log('[Nav System] handleIrisClick blocked - userNavigatedRef already true')
      return
    }
    
    console.log('[Nav System] handleIrisClick proceeding with level:', level)
    
    if (level === 4) {
      // Level 4: Mini nodes active -> go back to level 3 (subnodes)
      console.log('[Nav System] handleIrisClick: Level 4->3, deselecting subnode')
      userNavigatedRef.current = true
      // IMPORTANT: Call nav.goBack() FIRST before clearing backend state
      // This ensures navigation state changes before backend sync can interfere
      nav.goBack()
      // Now clear backend state after navigation is initiated
      // Keep userNavigatedRef = true during this to prevent backend sync from interfering
      selectSubnode(null)
      setActiveMiniNodeIndex(null)
      // Reset userNavigatedRef AFTER a short delay to ensure navigation completes
      setTimeout(() => {
        userNavigatedRef.current = false
        console.log('[Nav System] userNavigatedRef reset after Level 4->3 navigation')
      }, 100)
    } else if (level === 3) {
      // Level 3: Subnodes showing -> go back to level 2 (main nodes)
      console.log('[Nav System] handleIrisClick: Level 3->2, going back to main nodes')
      userNavigatedRef.current = true
      nav.goBack()
      // Clear the currentView to show main nodes instead of subnodes
      setExitingView(currentView || "__main__")
      setIsTransitioning(true)
      setTimeout(() => {
        setCurrentView(null)
        setExitingView(null)
        setIsTransitioning(false)
        selectCategory("")
        // NOTE: Don't reset userNavigatedRef here - let it stay true until user selects a new node
        // This prevents backend sync from re-selecting the old category before it's cleared
      }, SPIN_CONFIG.spinDuration)
    } else if (level === 2) {
      // Level 2: Main nodes showing -> collapse to level 1 (idle)
      console.log('[Nav System] handleIrisClick: Level 2->1, collapsing to idle')
      userNavigatedRef.current = true
      nav.collapseToIdle()
      setIsExpanded(false)
      // Clear backend category to prevent it from restoring on refresh
      selectCategory("")
    } else {
      // Level 1: Idle -> expand to level 2 (main nodes)
      console.log('[Nav System] handleIrisClick: Level 1->2, expanding')
      userNavigatedRef.current = true
      nav.expandToMain()
      setIsExpanded(true)
    }
  }, [currentView, isExpanded, isTransitioning, activeSubnodeId, selectSubnode, selectCategory, nav])

  const currentNodes = currentView
    ? SUB_NODES[currentView].map((node, idx) => ({
        ...node,
        angle: (idx * (360 / SUB_NODES[currentView].length)) - 90,
        index: idx,
      }))
    : NODE_POSITIONS.map((n) => ({ ...n, fields: [] as any[] }))

  const exitingNodes = exitingView
    ? exitingView === "__main__"
      ? NODE_POSITIONS.map((n) => ({ ...n, fields: [] as any[] }))
      : SUB_NODES[exitingView].map((node, idx) => ({
          ...node,
          angle: (idx * (360 / SUB_NODES[exitingView].length)) - 90,
          index: idx,
        }))
    : null

  return (
    <div 
      className="relative w-full h-full flex items-center justify-center"
      style={{ 
        overflow: 'visible',
        pointerEvents: 'none' // Outer wrapper: click-through to desktop
      }}
    >
      {/* Inner container: No pointer-events-auto here! Only on specific children */}
      <div 
        className="relative"
        style={{ width: 800, height: 800 }}
      >
        
        {/* Ambient glow - click-through */}
        <motion.div
          className="absolute rounded-full pointer-events-none"
          style={{
            width: 400,
            height: 400,
            left: "50%",
            top: "50%",
            marginLeft: -200,
            marginTop: -200,
            background: `radial-gradient(circle, ${glowColor}20 0%, ${glowColor}08 40%, transparent 70%)`,
          }}
          animate={{ scale: [1, 1.2, 1], opacity: [0.5, 0.8, 0.5] }}
          transition={{ duration: 8, repeat: Infinity, ease: "easeInOut" }}
        />

        {/* Confirmed orbiting nodes - INTERACTIVE */}
        <AnimatePresence>
          {confirmedNodes.map(node => (
            <motion.div
              key={node.id}
              className="absolute flex items-center justify-center pointer-events-auto"
              style={{
                width: MINI_NODE_STACK_CONFIG.sizeConfirmed,
                height: MINI_NODE_STACK_CONFIG.sizeConfirmed,
                left: "50%",
                top: "50%",
                marginLeft: -MINI_NODE_STACK_CONFIG.sizeConfirmed / 2,
                marginTop: -MINI_NODE_STACK_CONFIG.sizeConfirmed / 2,
              }}
              initial={{ scale: 0, opacity: 0 }}
              animate={{
                scale: 1,
                x: Math.cos((node.orbitAngle * Math.PI) / 180) * orbitRadius,
                y: Math.sin((node.orbitAngle * Math.PI) / 180) * orbitRadius,
                opacity: 1,
              }}
              transition={{ type: "spring", stiffness: 100, damping: 15 }}
            >
              <div
                className="w-full h-full flex flex-col items-center justify-center gap-1 rounded-2xl cursor-pointer"
                style={{
                  background: "rgba(255, 255, 255, 0.08)",
                  backdropFilter: "blur(12px)",
                  border: "1px solid rgba(255, 255, 255, 0.1)",
                }}
              >
                {React.createElement(ICON_MAP[typeof node.icon === 'string' ? node.icon : 'Mic'] || Mic, {
                  className: "w-5 h-5",
                  style: { color: glowColor },
                  strokeWidth: 1.5
                })}
                <span className="text-[8px] font-medium tracking-wider text-muted-foreground">
                  {node.label}
                </span>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {/* Center IRIS Orb - INTERACTIVE (Drag + Click) */}
        <motion.div
          className="absolute left-1/2 top-1/2 flex items-center justify-center pointer-events-none z-10"
          style={{ 
            marginLeft: -(irisSize + 120) / 2,
            marginTop: -(irisSize + 120) / 2,
            width: irisSize + 120,
            height: irisSize + 120,
          }}
          animate={{
            scale: nav.state.level === 4 ? 0.43 : 1,
            x: 0,
          }}
          transition={{ type: "spring", stiffness: 200, damping: 20, duration: 0.5 }}
        >
          <div className="pointer-events-auto">
            <IrisOrb
              isExpanded={isExpanded}
              onClick={handleIrisClick}
              centerLabel={centerLabel}
              size={irisSize}
              glowColor={glowColor}
            />
          </div>
        </motion.div>

        {/* Connecting line between Iris Orb and Mini Stack - Liquid Metal */}
        <AnimatePresence>
          {nav.state.level === 4 && (
            <motion.div
              className="absolute left-1/2 top-1/2 pointer-events-none z-[55]"
              style={{
                height: 2,
                width: 200,
                marginTop: -1,
                marginLeft: 30,
                background: `linear-gradient(90deg, 
                  rgba(255,255,255,0.8) 0%, 
                  rgba(192,192,192,0.9) 20%, 
                  rgba(255,255,255,0.95) 40%, 
                  rgba(192,192,192,0.9) 60%, 
                  rgba(255,255,255,0.8) 80%,
                  rgba(128,128,128,0.6) 100%)`,
                boxShadow: '0 0 4px rgba(255,255,255,0.5)',
              }}
              initial={{ opacity: 0, scaleX: 0 }}
              animate={{ opacity: 1, scaleX: 1 }}
              exit={{ opacity: 0, scaleX: 0 }}
              transition={{ duration: 0.4 }}
            />
          )}
        </AnimatePresence>

        {/* Mini Node Stack - Level 4 - COMPLETELY ISOLATED with higher z-index */}
        <AnimatePresence>
          {nav.state.level === 4 && nav.state.miniNodeStack.length > 0 && (
            <motion.div
              className="absolute left-1/2 top-1/2 pointer-events-auto z-[200]"
              style={{ 
                marginLeft: 280,
                marginTop: -160,
                width: 240,
                height: 420,
              }}
              initial={{ opacity: 0, scale: 0.8, x: -20 }}
              animate={{ opacity: 1, scale: 1, x: 0 }}
              exit={{ opacity: 0, scale: 0.8, x: -20 }}
              transition={{ duration: 0.4 }}
            >
              <MiniNodeStack miniNodes={nav.state.miniNodeStack} />
            </motion.div>
          )}
        </AnimatePresence>

        {/* Exiting nodes */}
        <AnimatePresence>
          {(nav.state.level === 2 || nav.state.level === 3) && exitingNodes && (
            <>
              {exitingNodes.map((node, idx) => (
                <PrismNode
                  key={`exit-${node.id}`}
                  node={node}
                  angle={node.angle}
                  radius={exitingView ? subRadius : mainRadius}
                  nodeSize={nodeSize}
                  onClick={() => {}}
                  spinRotations={exitingView ? SUBMENU_CONFIG.rotations : SPIN_CONFIG.rotations}
                  spinDuration={exitingView ? SUBMENU_CONFIG.spinDuration : SPIN_CONFIG.spinDuration}
                  staggerIndex={idx}
                  isCollapsing={true}
                  isActive={false}
                  spinConfig={SPIN_CONFIG}
                />
              ))}
            </>
          )}
        </AnimatePresence>

        {/* Current nodes - INTERACTIVE - Hidden when mini-node stack is showing (Level 4) */}
        <AnimatePresence>
          {(nav.state.level === 2 || nav.state.level === 3) && (
            <>
              {currentNodes
                .filter(node => !activeSubnodeId || node.id !== activeSubnodeId)
                .map((node, idx) => (
                <PrismNode
                  key={node.id}
                  node={node}
                  angle={node.angle}
                  radius={currentView ? subRadius : mainRadius}
                  nodeSize={nodeSize}
                  onClick={(e) => {
                    // Track click timestamp to prevent iris orb toggle
                    nodeClickTimestampRef.current = Date.now()
                    // Stop event from bubbling
                    e?.stopPropagation()
                    currentView
                      ? handleSubnodeClick(node.id)
                      : handleNodeClick(node.id, node.label, (node as any).hasSubnodes)
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
        <AnimatePresence>
          {nav.state.level === 1 && (
            <motion.div
              className="absolute bottom-40 left-1/2 -translate-x-1/2 pointer-events-none"
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
      </div>
    </div>
  )
}