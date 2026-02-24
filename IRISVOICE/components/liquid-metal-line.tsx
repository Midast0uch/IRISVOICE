"use client"

import { motion } from "framer-motion"

interface LiquidMetalLineProps {
  startX: number
  startY: number
  endX: number
  endY: number
  glowColor?: string
  isActive?: boolean
}

export function LiquidMetalLine({
  startX,
  startY,
  endX,
  endY,
  glowColor = "#00D4FF",
  isActive = true,
}: LiquidMetalLineProps) {
  // Calculate control point for slight curve
  const midX = (startX + endX) / 2
  const midY = (startY + endY) / 2
  const controlX = midX + (startY - endY) * 0.2
  const controlY = midY + (endX - startX) * 0.2

  // Create path data with quadratic bezier curve
  const pathData = `M ${startX} ${startY} Q ${controlX} ${controlY} ${endX} ${endY}`

  // Calculate gradient offset animation
  const gradientId = `gradient-${Math.random().toString(36).substr(2, 9)}`

  return (
    <motion.svg
      className="absolute inset-0 pointer-events-none"
      style={{ width: "100%", height: "100%", overflow: "visible" }}
      initial={{ opacity: 0 }}
      animate={{ opacity: isActive ? 1 : 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.3 }}
    >
      <defs>
        {/* Animated gradient for flowing effect */}
        <linearGradient
          id={gradientId}
          x1="0%"
          y1="0%"
          x2="100%"
          y2="100%"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0%" stopColor={glowColor} stopOpacity="0.1" />
          <stop offset="30%" stopColor={glowColor} stopOpacity="0.6" />
          <stop offset="50%" stopColor={glowColor} stopOpacity="1" />
          <stop offset="70%" stopColor={glowColor} stopOpacity="0.6" />
          <stop offset="100%" stopColor={glowColor} stopOpacity="0.1" />
          
          {/* Animate the gradient stops for flowing effect */}
          <animate
            attributeName="x1"
            values="-100%;0%;100%;200%"
            dur="2s"
            repeatCount="indefinite"
          />
          <animate
            attributeName="x2"
            values="0%;100%;200%;300%"
            dur="2s"
            repeatCount="indefinite"
          />
        </linearGradient>
        
        {/* Glow filter */}
        <filter id={`glow-${gradientId}`} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="3" result="coloredBlur" />
          <feMerge>
            <feMergeNode in="coloredBlur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      
      {/* Background line (dimmer) */}
      <path
        d={pathData}
        fill="none"
        stroke={glowColor}
        strokeWidth="1"
        strokeOpacity="0.2"
        strokeLinecap="round"
      />
      
      {/* Animated gradient line */}
      <motion.path
        d={pathData}
        fill="none"
        stroke={`url(#${gradientId})`}
        strokeWidth="2"
        strokeLinecap="round"
        filter={`url(#glow-${gradientId})`}
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
      />
    </motion.svg>
  )
}
