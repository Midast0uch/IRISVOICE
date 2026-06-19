import React from 'react'
import { motion } from 'framer-motion'
import { ENERGY_CYCLE } from '@/lib/timing-config'

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

  // Calculate line dimensions: anchor precisely to stationary structural frame
  // Container layout: 28px paddingLeft + 420px Mechanics Stage
  // Mechanics Stage center: 28 + 210 = 238px
  // Structural Frame Radius: outerRadius + 10.5 = (orbSize * 0.39) + 10.5 = 81.9 + 10.5 = 92.4px
  // Right edge of structural ring: 238 + 92.4 = 330.4px
  const startX = 330 // Absolute anchor to structural ring edge relative to 595px container
  const lineWidth = Math.max(0, panelOffset - startX)
  const lineHeight = 1.2
  const containerHeight = 30

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

          {/* Hex pattern texture for connection line */}
          <pattern id="line-hex-pattern" x="0" y="0" width="8" height="9.24" patternUnits="userSpaceOnUse">
            <polygon
              points="4,0 8,2.31 8,6.93 4,9.24 0,6.93 0,2.31"
              fill="none"
              stroke={hexToRgba(glowColor, 0.4)}
              strokeWidth="0.4"
            />
          </pattern>
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

        {/* 2. Neon Edge Bloom — matches hex pattern segment neon edge */}
        <line
          x1="0"
          y1={containerHeight / 2}
          x2={lineWidth}
          y2={containerHeight / 2}
          stroke={glowColor}
          strokeWidth={lineHeight * 6}
          strokeLinecap="round"
          style={{
            filter: `drop-shadow(0 0 6px ${glowColor}) drop-shadow(0 0 12px ${glowColor})`,
            opacity: 0.6
          }}
        />

        {/* 3. Main High-Intensity Energy Beam - Reduced to atmospheric guide (Phase 73) */}
        <line
          x1="0"
          y1={containerHeight / 2}
          x2={lineWidth}
          y2={containerHeight / 2}
          stroke="url(#line-base-gradient)"
          strokeWidth={lineHeight}
          strokeLinecap="round"
          style={{
            filter: `drop-shadow(0 0 10px ${glowColor})`,
            opacity: 0.15
          }}
        />

        {/* Base conduit - Perpetual High-Intensity Beam (Phase 85) */}
        <line
          x1="0"
          y1={containerHeight / 2}
          x2={lineWidth}
          y2={containerHeight / 2}
          stroke={glowColor}
          strokeWidth={lineHeight * 1.5}
          strokeLinecap="round"
          style={{
            opacity: 0.95,
            filter: `drop-shadow(0 0 15px ${glowColor}) drop-shadow(0 0 5px white)`,
          }}
        />

        {/* 5. Hex Pattern Texture Overlay — matches ring segment hex pattern */}
        <line
          x1="0"
          y1={containerHeight / 2}
          x2={lineWidth}
          y2={containerHeight / 2}
          stroke="url(#line-hex-pattern)"
          strokeWidth={lineHeight * 1.5}
          strokeLinecap="round"
          style={{ opacity: 0.3 }}
        />
      </svg>
    </motion.div>
  )
}
