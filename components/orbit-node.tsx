"use client"

import React, { useState, useRef, useEffect } from "react"
import { motion } from "framer-motion"
import * as LucideIcons from "lucide-react"
import type { ConfirmedNode } from "@/types/navigation"
import { useIRISWebSocket } from "@/hooks/useIRISWebSocket"

interface OrbitNodeProps {
  node: {
    id: string
    label: string
    icon: string
    orbitAngle: number
    values?: Record<string, string | number | boolean>
  }
  orbitRadius: number
  onRecall: (nodeId: string) => void
  glowColor?: string
}

export function OrbitNode({
  node,
  orbitRadius,
  onRecall,
  glowColor = "#00D4FF",
}: OrbitNodeProps) {
  // Voice control states
  const [isRecording, setIsRecording] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [audioLevel, setAudioLevel] = useState(0)
  const [feedbackMessage, setFeedbackMessage] = useState("")
  
  const holdTimer = useRef<NodeJS.Timeout | null>(null)
  const audioLevelInterval = useRef<NodeJS.Timeout | null>(null)
  const { sendMessage } = useIRISWebSocket()
  
  // Use orbitAngle from node data (matches LiquidMetalLine positioning)
  const angleRad = (node.orbitAngle * Math.PI) / 180
  const x = Math.cos(angleRad) * orbitRadius
  const y = Math.sin(angleRad) * orbitRadius

  // Get icon component with proper typing
  const IconComponent = ((LucideIcons as unknown as Record<string, React.ComponentType<{ className?: string }>>)[node.icon]) || LucideIcons.Circle

  // Handle mouse down (start recording after hold)
  const handleMouseDown = () => {
    // Start recording after 200ms hold (prevent accidental clicks)
    holdTimer.current = setTimeout(() => {
      startRecording()
    }, 200)
  }

  // Handle mouse up (stop recording or trigger recall)
  const handleMouseUp = () => {
    // Clear the hold timer
    if (holdTimer.current) {
      clearTimeout(holdTimer.current)
      holdTimer.current = null
    }

    // If recording, stop it
    if (isRecording) {
      stopRecording()
    } else if (!isProcessing) {
      // If not recording and not processing, trigger normal recall
      onRecall(node.id)
    }
  }

  // Handle mouse leave (cancel recording if user drags away)
  const handleMouseLeave = () => {
    if (holdTimer.current) {
      clearTimeout(holdTimer.current)
      holdTimer.current = null
    }
    if (isRecording) {
      stopRecording()
    }
  }

  // Start voice recording
  const startRecording = () => {
    setIsRecording(true)
    setFeedbackMessage("Listening...")
    
    // Send WebSocket message to backend
    sendMessage({
      type: "voice_command_start"
    })
    
    // Simulate audio level visualization (will be replaced with real audio data)
    audioLevelInterval.current = setInterval(() => {
      // Generate random audio level for demo (0-1)
      const level = Math.random() * 0.8 + 0.2
      setAudioLevel(level)
    }, 100)
  }

  // Stop voice recording
  const stopRecording = () => {
    setIsRecording(false)
    setFeedbackMessage("Processing...")
    setIsProcessing(true)
    
    // Clear audio level interval
    if (audioLevelInterval.current) {
      clearInterval(audioLevelInterval.current)
      audioLevelInterval.current = null
    }
    
    // Send WebSocket message to backend
    sendMessage({
      type: "voice_command_end"
    })
    
    // Reset audio level
    setAudioLevel(0)
  }

  // Handle voice command result from backend
  useEffect(() => {
    // This would be connected to WebSocket message handling
    // For now, simulate processing completion
    if (isProcessing) {
      const timer = setTimeout(() => {
        setIsProcessing(false)
        setFeedbackMessage("")
      }, 2000)
      
      return () => clearTimeout(timer)
    }
  }, [isProcessing])

  // Determine current visual state
  const getVisualState = () => {
    if (isRecording) return "RECORDING"
    if (isProcessing) return "PROCESSING"
    return "IDLE"
  }

  // Get visual state properties
  const visualState = getVisualState()
  const stateConfig = {
    IDLE: {
      glowColor: glowColor,
      glowOpacity: [0.5, 1, 0.5],
      scale: 1,
      iconColor: glowColor,
    },
    RECORDING: {
      glowColor: "#FF4444",
      glowOpacity: [0.8, 1, 0.8],
      scale: 1.1,
      iconColor: "#FF4444",
    },
    PROCESSING: {
      glowColor: "#4444FF",
      glowOpacity: [0.6, 1, 0.6],
      scale: 1.05,
      iconColor: "#4444FF",
    },
  }

  const config = stateConfig[visualState]

  return (
    <motion.div
      className="absolute flex items-center justify-center pointer-events-auto cursor-pointer"
      style={{
        width: 90,
        height: 90,
        left: "50%",
        top: "50%",
        marginLeft: -45,
        marginTop: -45,
      }}
      initial={{ scale: 0, opacity: 0, x: 0, y: 0 }}
      animate={{
        scale: config.scale,
        opacity: 1,
        x,
        y,
      }}
      exit={{ scale: 0, opacity: 0 }}
      transition={{ type: "spring", stiffness: 100, damping: 15 }}
      onMouseDown={handleMouseDown}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseLeave}
      whileHover={{ scale: isRecording || isProcessing ? 1 : 1.1 }}
      whileTap={{ scale: isRecording || isProcessing ? 1 : 0.95 }}
    >
      {/* Glow effect */}
      <motion.div
        className="absolute inset-0 rounded-2xl pointer-events-none"
        style={{
          background: `radial-gradient(circle, ${config.glowColor}40 0%, transparent 70%)`,
          filter: "blur(8px)",
        }}
        animate={{ opacity: config.glowOpacity }}
        transition={{ duration: isRecording ? 0.5 : 2, repeat: Infinity, ease: "easeInOut" }}
      />
      
      {/* Audio level ring (only during recording) */}
      {isRecording && (
        <motion.div
          className="absolute inset-0 rounded-2xl pointer-events-none"
          style={{
            background: `radial-gradient(circle, ${config.glowColor}60 0%, transparent 70%)`,
            filter: "blur(12px)",
          }}
          animate={{ 
            opacity: [0.3, 0.8 * audioLevel, 0.3],
            scale: [0.9, 1 + (audioLevel * 0.2), 0.9]
          }}
          transition={{ duration: 0.1, repeat: Infinity }}
        />
      )}
      
      {/* Node content */}
      <div
        className="relative w-full h-full flex flex-col items-center justify-center gap-1 rounded-2xl"
        style={{
          background: "rgba(255, 255, 255, 0.08)",
          backdropFilter: "blur(12px)",
          border: `1px solid ${config.glowColor}40`,
        }}
      >
        <div style={{ color: config.iconColor }}>
          <IconComponent className="w-5 h-5" />
        </div>
        <span className="text-[8px] font-medium tracking-wider text-white/70">
          {node.label}
        </span>
        
        {/* Feedback message */}
        {feedbackMessage && (
          <motion.div
            className="absolute -top-6 left-1/2 transform -translate-x-1/2 text-[10px] font-medium text-white/80 whitespace-nowrap"
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -5 }}
          >
            {feedbackMessage}
          </motion.div>
        )}
      </div>
    </motion.div>
  )
}
