"use client"

import React, { useId } from "react"
import { motion, AnimatePresence } from "framer-motion"

const LINE_CONFIG = {
  thickness: 1.5,
  glowThickness: 4,
  animationDuration: 600,
  retractDuration: 400,
}

interface LiquidMetalLineProps {
  start: { x: number; y: number }
  end: { x: number; y: number }
  glowColor: string
  isRetracting?: boolean
  isVisible?: boolean
}

export function LiquidMetalLine({ 
  start, 
  end, 
  glowColor,
  isRetracting = false,
  isVisible = true
}: LiquidMetalLineProps) {
  const id = useId()
  const gradientId = `metallic-gradient-${id}`
  const turbulenceId = `liquid-turbulence-${id}`
  const glowFilterId = `liquid-glow-${id}`

  const duration = isRetracting 
    ? LINE_CONFIG.retractDuration / 1000 
    : LINE_CONFIG.animationDuration / 1000

  return (
    <AnimatePresence>
      {isVisible && (
        <motion.svg
          className="absolute left-1/2 top-1/2 pointer-events-none"
          width={800}
          height={800}
          viewBox="-400 -400 800 800"
          style={{ marginLeft: -400, marginTop: -400 }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          <defs>
            <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor={glowColor} stopOpacity="0.6" />
              <stop offset="25%" stopColor="#ffffff" stopOpacity="0.9" />
              <stop offset="50%" stopColor={glowColor} stopOpacity="1" />
              <stop offset="75%" stopColor="#ffffff" stopOpacity="0.9" />
              <stop offset="100%" stopColor={glowColor} stopOpacity="0.6" />
              <animate
                attributeName="x1"
                values="-100%;100%"
                dur="2s"
                repeatCount="indefinite"
              />
              <animate
                attributeName="x2"
                values="0%;200%"
                dur="2s"
                repeatCount="indefinite"
              />
            </linearGradient>

            <filter id={turbulenceId} x="-20%" y="-20%" width="140%" height="140%">
              <feTurbulence
                type="fractalNoise"
                baseFrequency="0.02"
                numOctaves="3"
                result="noise"
              >
                <animate
                  attributeName="baseFrequency"
                  values="0.02;0.04;0.02"
                  dur="3s"
                  repeatCount="indefinite"
                />
              </feTurbulence>
              <feDisplacementMap
                in="SourceGraphic"
                in2="noise"
                scale="2"
                xChannelSelector="R"
                yChannelSelector="G"
              />
            </filter>

            <filter id={glowFilterId} x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          <motion.line
            x1={start.x}
            y1={start.y}
            x2={end.x}
            y2={end.y}
            stroke={`${glowColor}40`}
            strokeWidth={LINE_CONFIG.glowThickness + 4}
            strokeLinecap="round"
            initial={{ pathLength: isRetracting ? 1 : 0, opacity: 0 }}
            animate={{ 
              pathLength: isRetracting ? 0 : 1, 
              opacity: isRetracting ? 0 : 0.4 
            }}
            transition={{ duration, ease: "easeInOut" }}
            filter={`url(#${glowFilterId})`}
          />

          <motion.line
            x1={start.x}
            y1={start.y}
            x2={end.x}
            y2={end.y}
            stroke={`url(#${gradientId})`}
            strokeWidth={LINE_CONFIG.thickness}
            strokeLinecap="round"
            initial={{ pathLength: isRetracting ? 1 : 0, opacity: 0 }}
            animate={{ 
              pathLength: isRetracting ? 0 : 1, 
              opacity: isRetracting ? 0 : 1 
            }}
            transition={{ duration, ease: "easeInOut" }}
            filter={`url(#${turbulenceId})`}
          />

          <motion.line
            x1={start.x}
            y1={start.y}
            x2={end.x}
            y2={end.y}
            stroke="#ffffff"
            strokeWidth={0.5}
            strokeLinecap="round"
            initial={{ pathLength: isRetracting ? 1 : 0, opacity: 0 }}
            animate={{ 
              pathLength: isRetracting ? 0 : 1, 
              opacity: isRetracting ? 0 : 0.6 
            }}
            transition={{ duration: duration * 0.8, ease: "easeOut", delay: duration * 0.2 }}
          />
        </motion.svg>
      )}
    </AnimatePresence>
  )
}

export function EdgeToEdgeLine({ start, end, glowColor }: { 
  start: { x: number; y: number }
  end: { x: number; y: number }
  glowColor: string 
}) {
  return (
    <LiquidMetalLine 
      start={start} 
      end={end} 
      glowColor={glowColor} 
      isRetracting={false}
      isVisible={true}
    />
  )
}
