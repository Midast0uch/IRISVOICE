import React from 'react'
import { motion } from 'framer-motion'

interface ConnectionLineProps {
  glowColor: string
  lineRetracted: boolean
  orbSize: number
  panelOffset: number
}

/**
 * ConnectionLine Component
 * 
 * Animated glowing line connecting the orb to the side panel.
 * Features:
 * - Base gradient: glowColor with alpha fade (cc → 44)
 * - Glow layer: Blurred gradient (44 → 11)
 * - Shimmer effect: Traveling highlight (28px width)
 * - Animation: Continuous linear motion (2s loop)
 * - Spring-based extension/retraction
 */
export const ConnectionLine: React.FC<ConnectionLineProps> = ({
  glowColor,
  lineRetracted,
  orbSize,
  panelOffset
}) => {
  // Convert hex to rgba helper
  const hexToRgba = (hex: string, alpha: number): string => {
    const cleanHex = hex.replace('#', '')
    const r = parseInt(cleanHex.substring(0, 2), 16)
    const g = parseInt(cleanHex.substring(2, 4), 16)
    const b = parseInt(cleanHex.substring(4, 6), 16)
    return `rgba(${r}, ${g}, ${b}, ${alpha})`
  }

  // Calculate line dimensions: anchor precisely to stationary structural frame (Phase 66)
  // Parent Stage Center: 40 (padding) + 250 (500/2) = 290.
  // Static Frame Radius 148: center + radius => 290 + 148 = 438.
  const startX = 438 // Corrected Absolute Anchor relative to 850px container
  const lineWidth = Math.max(0, panelOffset - startX)
  const lineHeight = 3.2 // Kinetic-Level Visibility (Phase 63)
  const containerHeight = 60 // Expanded safety gutter for high-intensity blooms

  return (
    <motion.div
      className="absolute flex items-center"
      style={{
        left: startX,
        top: '50%',
        width: lineWidth,
        height: containerHeight,
        transformOrigin: 'left center',
        pointerEvents: 'auto',
        overflow: 'visible',
        zIndex: 50 // Above aura, below panel card
      }}
      initial={{ scaleX: lineRetracted ? 0 : 1, opacity: lineRetracted ? 0 : 1, y: "-50%" }}
      animate={{
        scaleX: lineRetracted ? 0 : 1,
        opacity: lineRetracted ? 0 : 1,
        y: "-50%"
      }}
      transition={{
        type: 'spring',
        stiffness: 140,
        damping: 22
      }}
    >
      <svg
        width={lineWidth}
        height={containerHeight}
        viewBox={`0 0 ${lineWidth} ${containerHeight}`}
        style={{ overflow: 'visible' }}
      >
        <defs>
          {/* Base gradient: glowColor with alpha fade (cc → 44) */}
          <linearGradient id="line-base-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor={hexToRgba(glowColor, 1.0)} />
            <stop offset="100%" stopColor={hexToRgba(glowColor, 0.9)} />
          </linearGradient>

          {/* Shimmer gradient: traveling highlight */}
          <linearGradient id="line-shimmer-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor={hexToRgba(glowColor, 0)} />
            <stop offset="50%" stopColor="#FFFFFF" />
            <stop offset="100%" stopColor={hexToRgba(glowColor, 0)} />
          </linearGradient>

          {/* Blur filter for high-intensity bloom */}
          <filter id="line-glow-blur-hot">
            <feGaussianBlur in="SourceGraphic" stdDeviation="4" />
          </filter>
        </defs>

        {/* 1. Brand Color Saturation Layer (Backlight) - Phase 64 */}
        <line
          x1="0"
          y1={containerHeight / 2}
          x2={lineWidth}
          y2={containerHeight / 2}
          stroke={glowColor}
          strokeWidth={lineHeight * 3}
          strokeLinecap="round"
          opacity="0.7"
          style={{ filter: `blur(2px)` }}
        />

        {/* 2. Neon Edge Bloom Overlay (Atmospheric) */}
        <line
          x1="0"
          y1={containerHeight / 2}
          x2={lineWidth}
          y2={containerHeight / 2}
          stroke={glowColor}
          strokeWidth={lineHeight * 6}
          strokeLinecap="round"
          filter="url(#line-glow-blur-hot)"
          opacity="0.6" // Restored Vibrancy (Phase 64)
        />

        {/* 3. Main High-Intensity Energy Beam */}
        <line
          x1="0"
          y1={containerHeight / 2}
          x2={lineWidth}
          y2={containerHeight / 2}
          stroke="url(#line-base-gradient)"
          strokeWidth={lineHeight}
          strokeLinecap="round"
          style={{
            filter: `drop-shadow(0 0 10px ${glowColor}) drop-shadow(0 0 4px ${glowColor})`,
            opacity: 1.0
          }}
        />

        {/* 4. Needle Hotspot: Pressurized White Core (Phase 63) */}
        <line
          x1="0"
          y1={containerHeight / 2}
          x2={lineWidth}
          y2={containerHeight / 2}
          stroke="white"
          strokeWidth="1.2"
          strokeLinecap="round"
          opacity="0.95"
          style={{ filter: "drop-shadow(0 0 1px white)" }}
        />

        {/* 5. Kinetic Shimmer (Traveling Spark) */}
        <motion.line
          x1="0"
          y1={containerHeight / 2}
          x2={lineWidth}
          y2={containerHeight / 2}
          stroke="url(#line-shimmer-gradient)"
          strokeWidth="4"
          strokeLinecap="round"
          animate={{
            strokeDashoffset: [-lineWidth, lineWidth]
          }}
          initial={{ strokeDasharray: `${lineWidth / 4} ${lineWidth * 2}` }}
          transition={{
            duration: 1.5,
            repeat: Infinity,
            ease: "linear"
          }}
        />
      </svg>
    </motion.div>
  )
}
