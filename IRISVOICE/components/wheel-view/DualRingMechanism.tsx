"use client"

import React, { useMemo, useCallback } from "react"
import { motion, AnimatePresence } from 'framer-motion'
import type { Card } from "@/types/navigation"
import { ENERGY_CYCLE } from '@/lib/timing-config'

interface DualRingMechanismProps {
  items: Card[]
  selectedIndex: number
  onSelect: (index: number) => void
  glowColor: string
  basePlateColor?: string
  orbSize: number
  confirmSpinning?: boolean
  isVoiceActive?: boolean
  voiceIntensity?: number
}

/**
 * Helper function to convert hex color to rgba with alpha
 * Validates: Property 36 - HexToRgba Color Conversion
 */
/**
 * Helper function to convert hex color to rgba with alpha
 * Validates: Property 36 - HexToRgba Color Conversion
 */
function hexToRgba(color: string, alpha: number): string {
  if (color.startsWith('hsl')) {
    return color.replace('hsl(', 'hsla(').replace(')', `, ${alpha})`)
  }

  // Remove # if present
  const hex = color.replace("#", "")

  // Parse hex values
  const r = parseInt(hex.substring(0, 2), 16)
  const g = parseInt(hex.substring(2, 4), 16)
  const b = parseInt(hex.substring(4, 6), 16)

  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

/**
 * DualRingMechanism Component
 * 
 * SVG-based visualization of outer and inner orbital rings with clickable segments.
 * 
 * Features:
 * - Distributes mini-nodes across outer (first half) and inner (second half) rings
 * - Outer ring: radius 0.42, stroke 28px, diamond markers
 * - Inner ring: radius 0.18, stroke 22px, circle markers, depth styling
 * - Rotation: Centers selected item at 12 o'clock using spring physics
 * - Decorative rings with dashed patterns and continuous rotation
 * - Counter-spin animation on confirm
 * - Theme color integration with varying alpha values
 * 
 * Validates: Requirements 2.2, 2.3, 2.5, 3.1, 3.2, 3.4, 3.5, 3.6, 3.7, 6.1, 6.2, 6.3, 11.2, 11.3, 11.4, 11.5, 12.5
 * Validates: Properties 4, 6, 8, 9, 10, 11, 20, 36, 37
 */
export const DualRingMechanism: React.FC<DualRingMechanismProps> = ({
  items,
  selectedIndex,
  onSelect,
  glowColor,
  basePlateColor = "hsl(220, 15%, 15%)",
  orbSize,
  confirmSpinning = false,
  isVoiceActive = false,
  voiceIntensity = 0,
}) => {
  // Phase 9.1: Consolidated 2-ring distribution logic
  // Equal distribution: 50/50 split between outer and inner rings
  const { outerItems, innerItems, splitPoint } = useMemo(() => {
    const total = items.length
    const split = Math.ceil(total / 2)

    return {
      outerItems: items.slice(0, split),
      innerItems: items.slice(split),
      splitPoint: split,
    }
  }, [items])

  // Consolidated Radii (Phase 86: Precision Symmetry)
  const outerRadius = orbSize * 0.39
  const innerRadius = orbSize * 0.2575 // Perfectly equidistant between gliders (Phase 86)

  // Phase 47: SVG Viewport Buffer (Universal Clipping Fix)
  // 300px provides massive safety for high-intensity blooms, text labels, and all ring effects
  const buffer = 300
  const center = (orbSize + buffer) / 2
  
  // Calculate maximum radius to ensure all elements stay within bounds
  const maxElementRadius = outerRadius + 35 // Accounts for outermost decorative elements

  // Sector angle calculations
  const outerSegmentAngle = outerItems.length > 0 ? 360 / outerItems.length : 0
  const innerSegmentAngle = innerItems.length > 0 ? 360 / innerItems.length : 0

  // Rotation calculations for 2 rings
  const isOuterSelected = selectedIndex < splitPoint
  const outerSelectedIndex = isOuterSelected ? selectedIndex : -1
  const outerBaseRotation = outerSelectedIndex >= 0 ? -(outerSelectedIndex * outerSegmentAngle) : 0

  const isInnerSelected = selectedIndex >= splitPoint
  const innerSelectedIndex = isInnerSelected ? selectedIndex - splitPoint : -1
  const innerBaseRotation = innerSelectedIndex >= 0 ? -(innerSelectedIndex * innerSegmentAngle) : 0

  // Counter-spin rotations for 2 rings
  const outerRotation = confirmSpinning ? outerBaseRotation + 360 : outerBaseRotation
  const innerRotation = confirmSpinning ? innerBaseRotation - 360 : innerBaseRotation

  // Spring physics configuration (Requirements 3.4, 6.1, 6.2)
  const springConfig = {
    type: "spring" as const,
    stiffness: 80,
    damping: 16,
  }

  // Confirm animation configuration (Requirement 6.3)
  const confirmSpinConfig = {
    duration: 0.8,
    ease: "easeInOut" as const,
  }

  /**
   * Convert polar coordinates to cartesian (memoized for performance - Requirement 12.3)
   */
  const polarToCartesian = useCallback((
    centerX: number,
    centerY: number,
    radius: number,
    angleInDegrees: number
  ) => {
    const angleInRadians = ((angleInDegrees - 90) * Math.PI) / 180.0
    return {
      x: centerX + radius * Math.cos(angleInRadians),
      y: centerY + radius * Math.sin(angleInRadians),
    }
  }, [])

  /**
   * Generate SVG path for a ring segment arc (memoized for performance - Requirement 12.3)
   */
  const generateArcPath = useCallback((
    radius: number,
    startAngle: number,
    endAngle: number
  ): string => {
    const start = polarToCartesian(center, center, radius, endAngle)
    const end = polarToCartesian(center, center, radius, startAngle)
    const largeArcFlag = endAngle - startAngle <= 180 ? "0" : "1"

    return [
      "M", start.x, start.y,
      "A", radius, radius, 0, largeArcFlag, 0, end.x, end.y,
    ].join(" ")
  }, [center, polarToCartesian])

  /**
   * Render segment text along arc path
   */
  const renderSegmentText = (
    radius: number,
    startAngle: number,
    endAngle: number,
    id: string,
    label: string,
    isSelected: boolean,
    fontSize: number = 9
  ): React.ReactNode => {
    const textPathId = `textpath-${id}`
    const path = generateArcPath(radius, startAngle, endAngle)

    return (
      <g key={`text-${id}`}>
        <defs>
          <path id={textPathId} d={path} fill="none" />
        </defs>
        <text
          fill={isSelected ? "rgba(255, 255, 255, 0.95)" : "rgba(255, 255, 255, 0.4)"}
          fontSize={fontSize}
          fontWeight="600"
          textAnchor="middle"
          style={{
            pointerEvents: "none",
            textTransform: "uppercase",
            letterSpacing: "0.05em"
          }}
        >
          <textPath
            href={`#${textPathId}`}
            startOffset="50%"
          >
            {label}
          </textPath>
        </text>
      </g>
    )
  }

  return (
    <svg
      width={orbSize + buffer}
      height={orbSize + buffer}
      viewBox={`0 0 ${orbSize + buffer} ${orbSize + buffer}`}
      className="absolute"
      style={{
        pointerEvents: "none",
        left: -buffer / 2,
        top: -buffer / 2,
        overflow: "visible" // Absolute absolute visibility (Phase 50)
      }}
    >
      {/* 1. Dynamic Background Aura (Absolute Bottom - Refined Phase 50) */}
      <motion.g
        style={{ pointerEvents: "none" }}
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{
          opacity: isVoiceActive ? [0.95, 1.2, 0.95] : 0.95, // Heavy Engine Overdrive (Phase 61)
          scale: isVoiceActive ? [1, 1.08, 1] : 1 // Increased pulse scale (Phase 61)
        }}
        transition={{
          opacity: isVoiceActive
            ? { duration: 1.2, repeat: Infinity, ease: "easeInOut" }
            : { duration: 1.5, ease: "easeOut" },
          scale: isVoiceActive ? { duration: 1.2, repeat: Infinity, ease: "easeInOut" } : { duration: 1.5 },
          default: { duration: 1 }
        }}
      >
        <circle
          cx={center}
          cy={center}
          r={orbSize * 0.7}
          fill="url(#voice-aura-gradient)"
          style={{
            opacity: isVoiceActive ? 1.0 : 0.95, // Max Entry Vibrance (Phase 57)
            transition: 'opacity 0.4s ease-out'
          }}
        />

        {/* Subtle Edge Softening */}
        <circle
          cx={center}
          cy={center}
          r={orbSize * 0.52}
          fill="none"
          stroke={hexToRgba(glowColor, 0.1)}
          strokeWidth="40"
          style={{ filter: "blur(40px)", opacity: 0.3 }}
        />
      </motion.g>

      {/* 3. Integrated BasePlate (Phase 101: Industrial Foundation) */}
      <circle
        cx={center}
        cy={center}
        r={orbSize * 0.49}
        fill="url(#base-plate-gradient)"
        style={{ opacity: 0.8 }}
      />

      {/* 4. Integrated DepthGroove (Phase 101: Recessed Industrial Well) */}
      <circle
        cx={center}
        cy={center}
        r={orbSize * 0.46}
        fill="none"
        stroke="rgba(0, 0, 0, 0.4)"
        strokeWidth="8"
        style={{ filter: "blur(4px)", opacity: 0.6 }}
      />

      <defs>
        {/* Phase 51: Wide-Field Voice Aura Gradient (Smooth Wide-Field Dissipation) */}
        <radialGradient id="voice-aura-gradient" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={hexToRgba(glowColor, 0.7)} />
          <stop offset="30%" stopColor={hexToRgba(glowColor, 0.3)} />
          <stop offset="70%" stopColor={hexToRgba(glowColor, 0.1)} />
          <stop offset="100%" stopColor="transparent" />
        </radialGradient>

        {/* Phase 101: Base Plate Gradient (Industrial Foundation) */}
        <radialGradient id="base-plate-gradient" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={basePlateColor} />
          <stop offset="70%" stopColor={hexToRgba(basePlateColor, 0.6)} />
          <stop offset="100%" stopColor={hexToRgba(basePlateColor, 0.3)} />
        </radialGradient>

        {/* Liquid Metal Refraction Gradient - Dynamic Phase 115 */}
        <linearGradient id="liquid-metal-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#ffffff" />
          <stop offset="25%" stopColor={hexToRgba(glowColor, 0.7)} />
          <stop offset="50%" stopColor="#101014" />
          <stop offset="75%" stopColor="#ffffff" />
          <stop offset="100%" stopColor={hexToRgba(glowColor, 0.7)} />
        </linearGradient>

        {/* Muted Metal Gradient for Interactive Segments */}
        <linearGradient id="muted-metal-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="rgba(100, 110, 120, 0.25)" />
          <stop offset="40%" stopColor="rgba(200, 210, 220, 0.15)" />
          <stop offset="60%" stopColor="rgba(100, 110, 120, 0.2)" />
          <stop offset="100%" stopColor="rgba(80, 90, 100, 0.25)" />
        </linearGradient>

        {/* Liquid Metal Specular Filter */}
        <filter id="liquid-metal-sheen">
          <feGaussianBlur in="SourceAlpha" stdDeviation="1" result="blur" />
          <feSpecularLighting
            in="blur"
            surfaceScale="5"
            specularConstant="1.2"
            specularExponent="40"
            lightingColor="#ffffff"
            result="specular"
          >
            <fePointLight x="-50" y="-50" z="100" />
          </feSpecularLighting>
          <feComposite in="specular" in2="SourceAlpha" operator="in" result="specularIn" />
          <feComposite in="SourceGraphic" in2="specularIn" operator="arithmetic" k1="0" k2="1" k3="1" k4="0" />
        </filter>
      </defs>

      {/* Liquid Metal Structural Frame (Mercury Material) */}
      <motion.g
        initial={{ opacity: 0, scale: 1.1 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{
          type: "spring",
          stiffness: 100,
          damping: 20,
          delay: 0.1
        }}
      >
        <circle
          cx={center}
          cy={center}
          r={outerRadius + 30}
          fill="none"
          stroke="url(#liquid-metal-gradient)"
          strokeWidth="5"
          style={{ filter: "url(#liquid-metal-sheen)", opacity: 0.9 }}
        />

        {/* Sharp Edge Glow (High Intensity Boundary) */}
        <circle
          cx={center}
          cy={center}
          r={outerRadius + 32.5}
          fill="none"
          stroke={glowColor}
          strokeWidth="0.75"
          style={{
            opacity: 0.8,
            filter: `drop-shadow(0 0 4px ${glowColor})`
          }}
        />

        {/* Phase 46: Neon Edge Bloom (High Vibrancy Outer Glow) */}
        <circle
          cx={center}
          cy={center}
          r={outerRadius + 32.5}
          fill="none"
          stroke={glowColor}
          strokeWidth="2"
          style={{
            opacity: 0.4,
            filter: `blur(8px)`
          }}
        />

        {/* Specular Edge (Razor thin white highlight) */}
        <circle
          cx={center}
          cy={center}
          r={outerRadius + 32.5}
          fill="none"
          stroke="rgba(255, 255, 255, 0.4)"
          strokeWidth="0.5"
        />
        {/* Phase 93: Structural Counter-Beams (Hyper-Flux CCW - Reliable) */}
        <motion.circle
          cx={center}
          cy={center}
          r={outerRadius + 30}
          fill="none"
          stroke="white"
          strokeWidth="1.8"
          pathLength="1"
          strokeDasharray="0.02 0.48"
          animate={{ rotate: -360 }}
          transition={{
            duration: 6,
            repeat: Infinity,
            ease: "linear"
          }}
          style={{
            pointerEvents: "none",
            filter: `drop-shadow(0 0 8px white)`,
            opacity: 0.9,
            originX: "50%",
            originY: "50%"
          }}
        />
      </motion.g>

      {/* 2. Top-Level Edge Frame (Ticks + Barrier Glider) */}
      <motion.g
        style={{ pointerEvents: "none" }}
        initial={{ opacity: 0, scale: 1.1 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{
          type: "spring",
          stiffness: 100,
          damping: 20,
          delay: 0.2
        }}
      >
        {/* Barrier Kinetic Glider */}
        <motion.circle
          cx={center}
          cy={center}
          r={outerRadius + 23}
          fill="none"
          stroke={hexToRgba(glowColor, 0.45)}
          strokeWidth="2.7"
          strokeDasharray="18.57 4"
          className="ring-outer-anim"
          style={{ pointerEvents: "none" }}
        />

        {/* Orbital Ticks (12 count) */}
        <g className="ring-outer-anim">
          {Array.from({ length: 12 }).map((_, i) => {
            const angle = (i * 360) / 12
            const tickRadius = outerRadius + 18
            const innerPoint = polarToCartesian(center, center, tickRadius - 5, angle)
            const outerPoint = polarToCartesian(center, center, tickRadius + 5, angle)

            const isWhiteTick = i % 2 === 0
            const tickColor = isWhiteTick ? "white" : glowColor

            return (
              <g key={`tick-lite-${i}`}>
                {/* Tick Bloom Layer */}
                <line
                  x1={innerPoint.x}
                  y1={innerPoint.y}
                  x2={outerPoint.x}
                  y2={outerPoint.y}
                  stroke={tickColor}
                  strokeWidth={isWhiteTick ? "3.5" : "2.5"}
                  style={{
                    pointerEvents: "none",
                    opacity: isWhiteTick ? 0.45 : 0.35,
                    filter: isWhiteTick ? "blur(3px)" : "blur(2px)"
                  }}
                />
                {/* Tick Core Layer */}
                <line
                  x1={innerPoint.x}
                  y1={innerPoint.y}
                  x2={outerPoint.x}
                  y2={outerPoint.y}
                  stroke={isWhiteTick ? "white" : hexToRgba(glowColor, 0.6)}
                  strokeWidth={isWhiteTick ? "2.2" : "1.8"}
                  style={{
                    pointerEvents: "none",
                    filter: isWhiteTick ? "drop-shadow(0 0 5px white)" : "none"
                  }}
                />
              </g>
            )
          })}
        </g>
      </motion.g>

      {/* 2.5 Core Shimmer Engine (Phase 87 - White Bright Light Halo) */}
      <g style={{ pointerEvents: 'none' }}>
        {/* Outer White Glare (Soft Bloom) */}
        <motion.circle
          cx={center}
          cy={center}
          r={orbSize * 0.125}
          fill="none"
          stroke="white"
          strokeWidth="6"
          initial={{ opacity: 0.1 }}
          animate={{
            opacity: [0.1, 0.35, 0.1],
            scale: [1, 1.1, 1]
          }}
          transition={{
            duration: 4,
            repeat: Infinity,
            ease: "easeInOut"
          }}
          style={{
            filter: "blur(12px)",
            originX: "50%",
            originY: "50%"
          }}
        />
        {/* Core Halo (Continuous White Light at Button Edge) */}
        <circle
          cx={center}
          cy={center}
          r={orbSize * 0.12}
          fill="none"
          stroke="white"
          strokeWidth="2"
          style={{
            opacity: 0.9,
            filter: `drop-shadow(0 0 10px white) drop-shadow(0 0 15px white)`,
          }}
        />
      </g>

      {/* 3. Outer Interactive Ring (Liquid Metal Refraction) */}
      <motion.g
        initial={{ opacity: 0, scale: 1.15 }}
        animate={{
          rotate: outerRotation,
          opacity: 1,
          scale: 1
        }}
        transition={{
          rotate: confirmSpinning ? confirmSpinConfig : springConfig,
          opacity: { duration: 0.4, delay: 0.3 },
          scale: {
            type: "spring",
            stiffness: 100,
            damping: 20,
            delay: 0.3
          }
        }}
        style={{ 
          transformOrigin: 'center center',
          transformBox: 'view-box'
        }}
      >
        {outerItems.map((item, index) => {
          const startAngle = index * outerSegmentAngle
          const endAngle = (index + 1) * outerSegmentAngle
          const isSelected = selectedIndex === index
          const path = generateArcPath(outerRadius, startAngle + 1, endAngle - 1)
          const glowPath = generateArcPath(outerRadius + 14.5, startAngle + 1, endAngle - 1)

          return (
            <g key={`outer-${item.id}`}>
              {/* Segment Glow Background (Interactive) */}
              <path
                d={path}
                fill="none"
                stroke={isSelected ? hexToRgba(glowColor, 0.12) : "rgba(255, 255, 255, 0.02)"}
                strokeWidth="28"
                style={{ filter: isSelected ? `blur(8px)` : "none" }}
              />
              {/* Liquid Metal Segment Body */}
              <path
                d={path}
                fill="none"
                stroke={isSelected ? `url(#liquid-metal-gradient)` : "url(#muted-metal-gradient)"}
                strokeWidth="28"
                style={{
                  cursor: "pointer",
                  pointerEvents: "auto",
                  filter: "url(#liquid-metal-sheen)",
                  opacity: 0.95 // Solid Metal Polish (Phase 52)
                }}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => onSelect(index)}
              />
              {/* Micro Edge Highlight */}
              <path
                d={glowPath}
                fill="none"
                stroke={isSelected ? glowColor : "rgba(255, 255, 255, 0.1)"}
                strokeWidth="0.5"
                style={{ opacity: 0.6 }}
              />
              {renderSegmentText(outerRadius, startAngle, endAngle, item.id, item.label, isSelected, 10.5)}
            </g>
          )
        })}
      </motion.g>

      {/* 4. Gap Kinetic Gliding Structure (Phase 49) */}
      <motion.g
        initial={{ opacity: 0, scale: 1.1 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{
          type: "spring",
          stiffness: 100,
          damping: 20,
          delay: 0.4
        }}
      >
        {/* Structural Glider Segments (Phase 91: Reverted to Dashed) */}
        <circle
          cx={center}
          cy={center}
          r={orbSize * 0.33}
          fill="none"
          stroke={hexToRgba(glowColor, 0.4)}
          strokeWidth="2.7"
          strokeDasharray="45 15"
          className="ring-middle-anim"
          style={{ pointerEvents: "none" }}
        />
        {/* Phase 93: Inter-Segment Energy Beam (Hyper-Flux CCW - Reliable) */}
        <motion.circle
          cx={center}
          cy={center}
          r={orbSize * 0.33}
          fill="none"
          stroke="white"
          strokeWidth="2.2"
          pathLength="1"
          strokeDasharray="0.02 0.48"
          animate={{ rotate: -360 }}
          transition={{
            duration: 3.5,
            repeat: Infinity,
            ease: "linear"
          }}
          style={{
            pointerEvents: "none",
            filter: `drop-shadow(0 0 8px white)`,
            opacity: 0.85,
            originX: "50%",
            originY: "50%"
          }}
        />
      </motion.g>

      {/* 5. Inner Interactive Ring (Liquid Metal Refraction) */}
      <motion.g
        initial={{ opacity: 0, scale: 1.15 }}
        animate={{
          rotate: innerRotation,
          opacity: 1,
          scale: 1
        }}
        transition={{
          rotate: confirmSpinning ? confirmSpinConfig : springConfig,
          opacity: { duration: 0.4, delay: 0.5 },
          scale: {
            type: "spring",
            stiffness: 100,
            damping: 20,
            delay: 0.5
          }
        }}
        style={{ 
          transformOrigin: 'center center',
          transformBox: 'view-box'
        }}
      >
        {innerItems.map((item, index) => {
          const startAngle = index * innerSegmentAngle
          const endAngle = (index + 1) * innerSegmentAngle
          const isSelected = selectedIndex === splitPoint + index
          const globalIndex = splitPoint + index
          const path = generateArcPath(innerRadius, startAngle + 1, endAngle - 1)
          const glowPath = generateArcPath(innerRadius + 11.5, startAngle + 1, endAngle - 1)

          return (
            <g key={`inner-${item.id}-${index}`}>
              {/* Segment Glow Background */}
              <path
                d={path}
                fill="none"
                stroke={isSelected ? hexToRgba(glowColor, 0.15) : "rgba(255, 255, 255, 0.02)"}
                strokeWidth="22"
                style={{ filter: isSelected ? `blur(6px)` : "none" }}
              />
              {/* Liquid Metal Segment Body */}
              <path
                d={path}
                fill="none"
                stroke={isSelected ? `url(#liquid-metal-gradient)` : "url(#muted-metal-gradient)"}
                strokeWidth="22"
                style={{
                  cursor: "pointer",
                  pointerEvents: "auto",
                  filter: "url(#liquid-metal-sheen)",
                  opacity: 0.95 // Solid Metal Polish (Phase 52)
                }}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => onSelect(globalIndex)}
              />
              {/* Micro Edge Highlight */}
              <path
                d={glowPath}
                fill="none"
                stroke={isSelected ? glowColor : "rgba(255, 255, 255, 0.1)"}
                strokeWidth="0.5"
                style={{ opacity: 0.6 }}
              />
              {renderSegmentText(innerRadius, startAngle, endAngle, item.id, item.label, isSelected, 9.5)}
            </g>
          )
        })}
      </motion.g>

      {/* 6. Core Kinetic Gliding Structure (Phase 49) */}
      <motion.g
        initial={{ opacity: 0, scale: 1.1 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{
          type: "spring",
          stiffness: 100,
          damping: 20,
          delay: 0.6
        }}
      >
        <circle
          cx={center}
          cy={center}
          r={orbSize * 0.185}
          fill="none"
          stroke={hexToRgba(glowColor, 0.4)}
          strokeWidth="2.7"
          strokeDasharray="15 35"
          className="ring-inner-anim"
          style={{ pointerEvents: "none" }}
        />
        {/* Phase 93: Core Energy Beam (Hyper-Flux CW - Reliable) */}
        <motion.circle
          cx={center}
          cy={center}
          r={orbSize * 0.185}
          fill="none"
          stroke="white"
          strokeWidth="2.2"
          pathLength="1"
          strokeDasharray="0.02 0.98"
          animate={{ rotate: 360 }}
          transition={{
            duration: 4,
            repeat: Infinity,
            ease: "linear"
          }}
          style={{
            pointerEvents: "none",
            filter: `drop-shadow(0 0 8px white)`,
            opacity: 0.85,
            originX: "50%",
            originY: "50%"
          }}
        />
      </motion.g>

      {/* 7. Structural Energy Circuit: Rotating "Power Spark" (Phase 67) */}
      <motion.circle
        cx={center}
        cy={center}
        r={outerRadius + 29}
        fill="none"
        stroke={hexToRgba(glowColor, 0.4)}
        strokeWidth="1.5"
        style={{ pointerEvents: "none" }}
      />

      {/* 7. S2: Perpetual Dual Particle "Chase" Relay (Phase 83) - Slot: 0-3s Active */}
      {/* Particle Alpha: Circles constantly at 0.35, flares to 0.95 during 0-3s */}
      <motion.circle
        cx={center}
        cy={center}
        r={outerRadius + 29}
        fill="none"
        stroke="white"
        strokeWidth="3"
        strokeLinecap="round"
        pathLength="1"
        initial={{ strokeDasharray: "0.08 0.92", strokeDashoffset: 0.75, opacity: 0.35 }}
        animate={{
          strokeDashoffset: [0.75, -0.25], // 1 Full loop constant
          opacity: [0.35, 0.95, 0.95, 0.35] // Ambient, High, High, Ambient
        }}
        transition={{
          strokeDashoffset: {
            duration: ENERGY_CYCLE.duration / 4, // 2s per loop
            repeat: Infinity,
            ease: "linear"
          },
          opacity: {
            duration: ENERGY_CYCLE.duration,
            repeat: Infinity,
            ease: "linear",
            times: [
              0, // Start at ambient
              ENERGY_CYCLE.segments.s2Wheel.start, // Flare up to high
              ENERGY_CYCLE.segments.s2Wheel.end, // Stay high
              1.0 // Drop back to ambient
            ]
          }
        }}
        style={{
          pointerEvents: "none",
          filter: `blur(0.5px) drop-shadow(0 0 15px ${glowColor}) drop-shadow(0 0 6px white)`,
        }}
      />

      {/* Particle Beta: Circles constantly, flaring to relay intensity during 0-3s */}
      <motion.circle
        cx={center}
        cy={center}
        r={outerRadius + 29}
        fill="none"
        stroke="white"
        strokeWidth="3"
        strokeLinecap="round"
        pathLength="1"
        initial={{ strokeDasharray: "0.08 0.92", strokeDashoffset: 0.25, opacity: 0.35 }}
        animate={{
          strokeDashoffset: [0.25, -0.75], // 1 Full loop constant
          opacity: [0.35, 0.95, 0.95, 0.35] // Ambient, High, High, Ambient
        }}
        transition={{
          strokeDashoffset: {
            duration: ENERGY_CYCLE.duration / 4,
            repeat: Infinity,
            ease: "linear"
          },
          opacity: {
            duration: ENERGY_CYCLE.duration,
            repeat: Infinity,
            ease: "linear",
            times: [
              0, // Start at ambient
              ENERGY_CYCLE.segments.s2Wheel.start, // Flare up to high
              ENERGY_CYCLE.segments.s2Wheel.end, // Stay high
              1.0 // Drop back to ambient
            ]
          }
        }}
        style={{
          pointerEvents: "none",
          filter: `blur(0.5px) drop-shadow(0 0 15px ${glowColor}) drop-shadow(0 0 6px white)`,
        }}
      />

      <style jsx>{`
        .ring-outer-anim {
          animation: rotate-slow 60s linear infinite;
          transform-origin: center;
        }

        .ring-middle-anim {
          animation: rotate-slow 45s linear infinite reverse;
          transform-origin: center;
        }

        .ring-inner-anim {
          animation: rotate-slow 30s linear infinite;
          transform-origin: center;
        }

        @keyframes rotate-slow {
          from {
            transform: rotate(0deg);
          }
          to {
            transform: rotate(360deg);
          }
        }
      `}</style>
    </svg >
  )
}
