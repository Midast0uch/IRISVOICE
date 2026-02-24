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

  // Calculate line dimensions
  const lineWidth = panelOffset - orbSize / 2
  const lineHeight = 24

  return (
    <motion.div
      className="absolute"
      style={{
        left: orbSize / 2,
        top: '50%',
        transform: 'translateY(-50%)',
        width: lineWidth,
        height: lineHeight,
        transformOrigin: 'left center'
      }}
      animate={{
        scaleX: lineRetracted ? 0 : 1
      }}
      transition={{
        type: 'spring',
        stiffness: 200,
        damping: 25
      }}
    >
      <svg
        width={lineWidth}
        height={lineHeight}
        viewBox={`0 0 ${lineWidth} ${lineHeight}`}
        style={{ overflow: 'visible' }}
      >
        <defs>
          {/* Base gradient: glowColor with alpha fade (cc → 44) */}
          <linearGradient id="line-base-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor={hexToRgba(glowColor, 0.8)} />
            <stop offset="100%" stopColor={hexToRgba(glowColor, 0.27)} />
          </linearGradient>

          {/* Glow layer gradient: alpha 44 → 11 */}
          <linearGradient id="line-glow-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor={hexToRgba(glowColor, 0.27)} />
            <stop offset="100%" stopColor={hexToRgba(glowColor, 0.07)} />
          </linearGradient>

          {/* Shimmer gradient: traveling highlight */}
          <linearGradient id="line-shimmer-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor={hexToRgba(glowColor, 0)} />
            <stop offset="50%" stopColor={hexToRgba(glowColor, 0.6)} />
            <stop offset="100%" stopColor={hexToRgba(glowColor, 0)} />
          </linearGradient>

          {/* Blur filter for glow layer */}
          <filter id="line-glow-blur">
            <feGaussianBlur in="SourceGraphic" stdDeviation="3" />
          </filter>
        </defs>

        {/* Glow layer (blurred, behind base line) */}
        <line
          x1="0"
          y1={lineHeight / 2}
          x2={lineWidth}
          y2={lineHeight / 2}
          stroke="url(#line-glow-gradient)"
          strokeWidth="8"
          strokeLinecap="round"
          filter="url(#line-glow-blur)"
        />

        {/* Base line with gradient */}
        <line
          x1="0"
          y1={lineHeight / 2}
          x2={lineWidth}
          y2={lineHeight / 2}
          stroke="url(#line-base-gradient)"
          strokeWidth="2"
          strokeLinecap="round"
        />

        {/* Shimmer effect: traveling highlight (28px width) */}
        <motion.line
          x1="0"
          y1={lineHeight / 2}
          x2={lineWidth}
          y2={lineHeight / 2}
          stroke="url(#line-shimmer-gradient)"
          strokeWidth="4"
          strokeLinecap="round"
          initial={{ strokeDasharray: `28 ${lineWidth}`, strokeDashoffset: 0 }}
          animate={{
            strokeDashoffset: [-lineWidth - 28, 0]
          }}
          transition={{
            duration: 2,
            repeat: Infinity,
            ease: 'linear'
          }}
        />
      </svg>
    </motion.div>
  )
}
