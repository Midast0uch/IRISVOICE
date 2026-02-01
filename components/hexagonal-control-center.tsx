"use client"

import React, { useState, useCallback, useEffect, useRef, type ElementType } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { getCurrentWindow,PhysicalPosition } from '@tauri-apps/api/window'
import { Mic, Brain, Bot, Settings, Database, Activity, Volume2, Headphones, AudioWaveform as Waveform, Link, Cpu, Sparkles, MessageSquare, Palette, Power, Keyboard, Minimize2, RefreshCw, History, FileStack, Trash2, Timer, Clock, BarChart3, DollarSign, TrendingUp, Check } from "lucide-react"
import { useIRISWebSocket } from "@/hooks/useIRISWebSocket"

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
  { index: 1, angle: -30, id: "model", label: "MODEL", icon: Brain, hasSubnodes: true },
  { index: 2, angle: 30, id: "agent", label: "AGENT", icon: Bot, hasSubnodes: true },
  { index: 3, angle: 90, id: "settings", label: "SETTINGS", icon: Settings, hasSubnodes: true },
  { index: 4, angle: 150, id: "memory", label: "MEMORY", icon: Database, hasSubnodes: true },
  { index: 5, angle: 210, id: "analytics", label: "ANALYTICS", icon: Activity, hasSubnodes: true },
]

const SUB_NODES: Record<string, { id: string; label: string; icon: ElementType; fields: any[] }[]> = {
  voice: [
    { id: "input", label: "INPUT", icon: Mic, fields: [
      { id: "input_device", label: "Input Device", type: "dropdown", options: ["Default", "USB Microphone", "Headset", "Webcam"] },
      { id: "input_sensitivity", label: "Input Sensitivity", type: "slider", min: 0, max: 100, unit: "%" },
      { id: "noise_gate", label: "Noise Gate", type: "toggle" },
    ]},
    { id: "output", label: "OUTPUT", icon: Volume2, fields: [
      { id: "output_device", label: "Output Device", type: "dropdown", options: ["Default", "Headphones", "Speakers", "HDMI"] },
      { id: "master_volume", label: "Master Volume", type: "slider", min: 0, max: 100, unit: "%" },
    ]},
    { id: "processing", label: "PROCESSING", icon: Waveform, fields: [
      { id: "noise_reduction", label: "Noise Reduction", type: "toggle" },
      { id: "echo_cancellation", label: "Echo Cancellation", type: "toggle" },
    ]},
  ],
  model: [
    { id: "connection", label: "CONNECTION", icon: Link, fields: [
      { id: "endpoint", label: "LM Studio Endpoint", type: "text", placeholder: "http://localhost:1234" },
    ]},
    { id: "parameters", label: "PARAMETERS", icon: Cpu, fields: [
      { id: "temperature", label: "Temperature", type: "slider", min: 0, max: 2, step: 0.1, unit: "" },
    ]},
  ],
  agent: [
    { id: "identity", label: "IDENTITY", icon: MessageSquare, fields: [
      { id: "assistant_name", label: "Assistant Name", type: "text", placeholder: "IRIS" },
    ]},
    { id: "wake", label: "WAKE", icon: Sparkles, fields: [
      { id: "wake_phrase", label: "Wake Phrase", type: "text", placeholder: "Hey IRIS" },
    ]},
  ],
  settings: [
    { id: "theme_mode", label: "Theme", icon: Palette, fields: [
      { id: "theme", label: "Theme Mode", type: "dropdown", options: ["Dark", "Light", "Auto"] },
    ]},
    { id: "startup", label: "Startup", icon: Power, fields: [
      { id: "launch_startup", label: "Launch at Startup", type: "toggle" },
    ]},
  ],
  memory: [
    { id: "history", label: "History", icon: History, fields: [
      { id: "conversation_history", label: "Conversation History", type: "text", placeholder: "View history..." },
    ]},
  ],
  analytics: [
    { id: "tokens", label: "Tokens", icon: BarChart3, fields: [
      { id: "token_usage", label: "Token Usage", type: "text", placeholder: "0 tokens" },
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
}

// ===========================================
// MANUAL DRAG HOOK (Replaces useDragOrClick)
// Uses setPosition instead of startDragging to bypass Windows Snap Assist
// ===========================================
function useManualDragWindow(onClickAction: () => void) {
  const isDragging = useRef(false)
  const dragStartPos = useRef({ x: 0, y: 0 })
  const windowStartPos = useRef({ x: 0, y: 0 })
  const hasDragged = useRef(false)

  const handleMouseDown = useCallback(async (e: React.MouseEvent) => {
    if (e.button !== 0) return
    
    isDragging.current = true
    hasDragged.current = false
    dragStartPos.current = { x: e.screenX, y: e.screenY }
    
    const win = getCurrentWindow()
    const pos = await win.outerPosition()
    windowStartPos.current = { x: pos.x, y: pos.y }
    
    document.body.style.cursor = 'grabbing'
    document.body.style.userSelect = 'none'
  }, [])

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!isDragging.current) return
    
    const dx = e.screenX - dragStartPos.current.x
    const dy = e.screenY - dragStartPos.current.y
    
    if (Math.abs(dx) > 5 || Math.abs(dy) > 5) {
      hasDragged.current = true
    }
    
    const win = getCurrentWindow()
    win.setPosition(new PhysicalPosition(windowStartPos.current.x + dx, windowStartPos.current.y + dy))
  }, [])

  const handleMouseUp = useCallback(() => {
    isDragging.current = false
    document.body.style.cursor = 'default'
    document.body.style.userSelect = ''
    
    // If we didn't drag significantly, it was a click
    if (!hasDragged.current) {
      onClickAction()
    }
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
  const { handleMouseDown } = useManualDragWindow(onClick)
  const [isWaking, setIsWaking] = useState(false)

  return (
    <motion.div
      className="relative flex items-center justify-center rounded-full cursor-grab active:cursor-grabbing z-50 pointer-events-auto"
      style={{ width: size, height: size }}
      onMouseDown={handleMouseDown}
    >
      {/* Outer breathe glow */}
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

      {/* Inner core pulse */}
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
            className="text-lg font-light tracking-[0.2em] select-none pointer-events-none"
            style={{ color: "rgba(255, 255, 255, 0.95)" }}
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

interface HexagonalNodeProps {
  node: { id: string; label: string; icon: ElementType; fields?: InputField[] }
  angle: number
  radius: number
  nodeSize: number
  onClick: () => void
  spinRotations: number
  spinDuration: number
  staggerIndex: number
  isCollapsing: boolean
  isActive: boolean
  glowColor: string
}

function HexagonalNode({
  node,
  angle,
  radius,
  nodeSize,
  onClick,
  spinRotations,
  spinDuration,
  staggerIndex,
  isCollapsing,
  isActive,
  glowColor,
}: HexagonalNodeProps) {
  const Icon = node.icon
  const pos = getSpiralPosition(angle, radius, spinRotations)
  const counterRotation = -pos.rotation

  const spiralVariants = {
    collapsed: { x: 0, y: 0, scale: 0.5, opacity: 0, rotate: 0 },
    expanded: {
      x: pos.x,
      y: pos.y,
      scale: 1,
      opacity: 1,
      rotate: pos.rotation,
      transition: {
        duration: spinDuration / 1000,
        delay: staggerIndex * (SPIN_CONFIG.staggerDelay / 1000),
        ease: SPIN_CONFIG.ease,
      },
    },
    exit: {
      x: 0,
      y: 0,
      scale: 0.5,
      opacity: 0,
      rotate: -360,
      transition: {
        duration: spinDuration / 1000,
        delay: staggerIndex * (SPIN_CONFIG.staggerDelay / 1000),
        ease: SPIN_CONFIG.ease,
      },
    },
  }

  const contentVariants = {
    collapsed: { rotate: 0 },
    expanded: {
      rotate: counterRotation,
      transition: {
        duration: spinDuration / 1000,
        delay: staggerIndex * (SPIN_CONFIG.staggerDelay / 1000),
        ease: SPIN_CONFIG.ease,
      },
    },
    exit: {
      rotate: 360,
      transition: {
        duration: spinDuration / 1000,
        delay: staggerIndex * (SPIN_CONFIG.staggerDelay / 1000),
        ease: SPIN_CONFIG.ease,
      },
    },
  }

  return (
    <motion.button
      className="absolute flex flex-col items-center justify-center cursor-pointer z-10 pointer-events-auto"
      style={{
        left: "50%",
        top: "50%",
        marginLeft: -nodeSize / 2,
        marginTop: -nodeSize / 2,
        width: nodeSize,
        height: nodeSize,
      }}
      variants={spiralVariants}
      initial="collapsed"
      animate={isCollapsing ? "exit" : "expanded"}
      exit="exit"
      onClick={onClick}
      whileHover={{ scale: 1.05 }}
      whileTap={{ scale: 0.95 }}
    >
      <motion.div
        className="absolute -inset-0.5 pointer-events-none"
        style={{
          borderRadius: "24px",
          padding: "2px",
          background: `conic-gradient(from 0deg, transparent 0deg, ${glowColor}1a 60deg, ${isActive ? glowColor : `${glowColor}e6`} 180deg, ${glowColor}1a 300deg, transparent 360deg)`,
          WebkitMask: "linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)",
          WebkitMaskComposite: "xor",
        }}
        animate={{ rotate: 360 }}
        transition={{ duration: 8, repeat: Infinity, ease: "linear" }}
      />

      {isActive && (
        <motion.div
          className="absolute -inset-2 pointer-events-none"
          style={{
            borderRadius: "28px",
            background: `radial-gradient(circle, ${glowColor}33 0%, transparent 70%)`,
            filter: "blur(8px)",
          }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        />
      )}

      <div
        className="relative w-full h-full flex flex-col items-center justify-center pointer-events-auto"
        style={{
          borderRadius: "24px",
          background: "rgba(255, 255, 255, 0.06)",
          backdropFilter: "blur(12px)",
          border: "1px solid rgba(255, 255, 255, 0.08)",
        }}
      >
        <motion.div
          className="flex flex-col items-center justify-center gap-1 pointer-events-none"
          variants={contentVariants}
          initial="collapsed"
          animate={isCollapsing ? "exit" : "expanded"}
        >
          <Icon className="w-6 h-6 text-silver" strokeWidth={1.5} />
          <span className="text-[10px] font-medium tracking-wider text-muted-foreground">
            {node.label}
          </span>
        </motion.div>
      </div>
    </motion.button>
  )
}

export function HexagonalControlCenter() {
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

  // Ensure window starts interactive (solid, not click-through)
  useEffect(() => {
    const setupWindow = async () => {
      const appWindow = await getCurrentWindow()
      await appWindow.setIgnoreCursorEvents(false)
    }
    setupWindow()
  }, [])

  useEffect(() => {
    if (!isTransitioning && !pendingView && currentCategory !== currentView && !exitingView) {
      setCurrentView(currentCategory)
    }
    if (pendingView && currentCategory === pendingView) {
      setPendingView(null)
    }
  }, [currentCategory, currentView, exitingView, isTransitioning, pendingView])

  const glowColor = wsTheme?.glow || "#00ff88"

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
      if (isTransitioning) return

      if (!currentView) {
        if (SUB_NODES[nodeId]?.length > 0) {
          setExitingView("__main__")
          setIsTransitioning(true)
          setActiveMiniNodeIndex(null)
          setPendingView(nodeId)
          setCurrentView(nodeId)

          setTimeout(() => {
            setExitingView(null)
            setIsTransitioning(false)
            selectCategory(nodeId)
          }, SPIN_CONFIG.spinDuration)
        }
      }
    },
    [currentView, isTransitioning, selectCategory]
  )

  const handleSubnodeClick = useCallback((subnodeId: string) => {
    if (activeSubnodeId === subnodeId) {
      selectSubnode(null)
      setActiveMiniNodeIndex(null)
    } else {
      selectSubnode(subnodeId)
      setActiveMiniNodeIndex(null)
    }
  }, [activeSubnodeId, selectSubnode])

  const handleIrisClick = useCallback(() => {
    if (isTransitioning) return

    if (activeSubnodeId) {
      selectSubnode(null)
      setActiveMiniNodeIndex(null)
    } else if (currentView) {
      setExitingView(currentView)
      setIsTransitioning(true)
      setTimeout(() => {
        setCurrentView(null)
        setExitingView(null)
        setIsTransitioning(false)
        selectCategory("")
      }, SPIN_CONFIG.spinDuration)
    } else {
      setIsExpanded(!isExpanded)
    }
  }, [currentView, isExpanded, isTransitioning, activeSubnodeId, selectSubnode, selectCategory])

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
        <div
          className="absolute left-1/2 top-1/2 flex items-center justify-center pointer-events-auto"
          style={{ 
            marginLeft: -(irisSize + 120) / 2,
            marginTop: -(irisSize + 120) / 2,
            width: irisSize + 120,
            height: irisSize + 120,
          }}
        >
          <IrisOrb
            isExpanded={isExpanded}
            onClick={handleIrisClick}
            centerLabel={centerLabel}
            size={irisSize}
            glowColor={glowColor}
          />
        </div>

        {/* Exiting nodes */}
        <AnimatePresence>
          {isExpanded && exitingNodes && (
            <>
              {exitingNodes.map((node, idx) => (
                <HexagonalNode
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
                  glowColor={glowColor}
                />
              ))}
            </>
          )}
        </AnimatePresence>

        {/* Current nodes - INTERACTIVE */}
        <AnimatePresence>
          {isExpanded && (
            <>
              {currentNodes
                .filter(node => !activeSubnodeId || node.id !== activeSubnodeId)
                .map((node, idx) => (
                <HexagonalNode
                  key={node.id}
                  node={node}
                  angle={node.angle}
                  radius={currentView ? subRadius : mainRadius}
                  nodeSize={nodeSize}
                  onClick={() =>
                    currentView
                      ? handleSubnodeClick(node.id)
                      : handleNodeClick(node.id, node.label, (node as any).hasSubnodes)
                  }
                  spinRotations={currentView ? SUBMENU_CONFIG.rotations : SPIN_CONFIG.rotations}
                  spinDuration={currentView ? SUBMENU_CONFIG.spinDuration : SPIN_CONFIG.spinDuration}
                  staggerIndex={idx}
                  isCollapsing={false}
                  isActive={activeSubnodeId === node.id}
                  glowColor={glowColor}
                />
              ))}
            </>
          )}
        </AnimatePresence>

        {/* Tap hint - click-through */}
        <AnimatePresence>
          {!isExpanded && (
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