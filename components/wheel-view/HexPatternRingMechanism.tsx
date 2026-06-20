"use client"

import React, { useMemo, useCallback } from "react"
import { motion } from 'framer-motion'
import type { Card } from "@/types/navigation"
import { ENERGY_CYCLE } from '@/lib/timing-config'

interface HexPatternRingMechanismProps {
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
 * Helper function to convert hex/hsl color to rgba with alpha.
 * Handles both hex (#rrggbb) and hsl(h, s%, l%) color formats.
 */
function hexToRgba(color: string, alpha: number): string {
  if (color.startsWith('hsl')) {
    return color.replace('hsl(', 'hsla(').replace(')', `, ${alpha})`)
  }
  const hex = color.replace("#", "")
  const r = parseInt(hex.substring(0, 2), 16)
  const g = parseInt(hex.substring(2, 4), 16)
  const b = parseInt(hex.substring(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

/**
 * HexPatternRingMechanism Component
 *
 * Replaces DualRingMechanism with a hex pattern surface aesthetic.
 * Segments use honeycomb SVG pattern overlay + neon edge outline
 * instead of liquid metal gradients and GPU-expensive specular filters.
 *
 * Everything else (kinetic gliders, energy beams, orbital ticks,
 * particle chase relay, spring physics, confirm spin) is identical.
 */
export const HexPatternRingMechanism: React.FC<HexPatternRingMechanismProps> = ({
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
  const { outerItems, innerItems, splitPoint } = useMemo(() => {
    const total = items.length
    const split = Math.ceil(total / 2)
    return {
      outerItems: items.slice(0, split),
      innerItems: items.slice(split),
      splitPoint: split,
    }
  }, [items])

  const outerRadius = orbSize * 0.39
  const innerRadius = orbSize * 0.2575
  const buffer = 300
  const center = (orbSize + buffer) / 2

  const outerSegmentAngle = outerItems.length > 0 ? 360 / outerItems.length : 0
  const innerSegmentAngle = innerItems.length > 0 ? 360 / innerItems.length : 0

  const isOuterSelected = selectedIndex < splitPoint
  const outerSelectedIndex = isOuterSelected ? selectedIndex : -1
  const outerBaseRotation = outerSelectedIndex >= 0 ? -(outerSelectedIndex * outerSegmentAngle) : 0

  const isInnerSelected = selectedIndex >= splitPoint
  const innerSelectedIndex = isInnerSelected ? selectedIndex - splitPoint : -1
  const innerBaseRotation = innerSelectedIndex >= 0 ? -(innerSelectedIndex * innerSegmentAngle) : 0

  const outerRotation = confirmSpinning ? outerBaseRotation + 360 : outerBaseRotation
  const innerRotation = confirmSpinning ? innerBaseRotation - 360 : innerBaseRotation

  const springConfig = { type: "spring" as const, stiffness: 80, damping: 16 }
  const confirmSpinConfig = { duration: 0.8, ease: "easeInOut" as const }

  const polarToCartesian = useCallback((
    centerX: number, centerY: number, radius: number, angleInDegrees: number
  ) => {
    const angleInRadians = ((angleInDegrees - 90) * Math.PI) / 180.0
    return {
      x: centerX + radius * Math.cos(angleInRadians),
      y: centerY + radius * Math.sin(angleInRadians),
    }
  }, [])

  const generateArcPath = useCallback((
    radius: number, startAngle: number, endAngle: number
  ): string => {
    const start = polarToCartesian(center, center, radius, endAngle)
    const end = polarToCartesian(center, center, radius, startAngle)
    const largeArcFlag = endAngle - startAngle <= 180 ? "0" : "1"
    return ["M", start.x, start.y, "A", radius, radius, 0, largeArcFlag, 0, end.x, end.y].join(" ")
  }, [center, polarToCartesian])

  const renderSegmentText = (
    radius: number, startAngle: number, endAngle: number,
    id: string, label: string, isSelected: boolean, fontSize: number = 9
  ): React.ReactNode => {
    const textPathId = `textpath-${id}`
    const path = generateArcPath(radius, startAngle, endAngle)
    return (
      <g key={`text-${id}`}>
        <defs><path id={textPathId} d={path} fill="none" /></defs>
        <text
          fill={isSelected ? "rgba(255, 255, 255, 0.95)" : "rgba(255, 255, 255, 0.4)"}
          fontSize={fontSize} fontWeight="600" textAnchor="middle"
          style={{ pointerEvents: "none", textTransform: "uppercase", letterSpacing: "0.05em" }}
        >
          <textPath href={`#${textPathId}`} startOffset="50%">{label}</textPath>
        </text>
      </g>
    )
  }

  const gapRadius = (outerRadius + innerRadius) / 2

  return (
    <svg
      width={orbSize + buffer} height={orbSize + buffer}
      viewBox={`0 0 ${orbSize + buffer} ${orbSize + buffer}`}
      className="absolute"
      style={{ pointerEvents: "none", left: -buffer / 2, top: -buffer / 2, overflow: "visible" }}
    >
      {/* 1. Dynamic Background Aura */}
      <motion.g
        style={{ pointerEvents: "none" }}
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{
          opacity: isVoiceActive ? [0.95, 1.2, 0.95] : 0.95,
          scale: isVoiceActive ? [1, 1.08, 1] : 1
        }}
        transition={{
          opacity: isVoiceActive ? { duration: 1.2, repeat: Infinity, ease: "easeInOut" } : { duration: 1.5, ease: "easeOut" },
          scale: isVoiceActive ? { duration: 1.2, repeat: Infinity, ease: "easeInOut" } : { duration: 1.5 },
          default: { duration: 1 }
        }}
      >
        <circle cx={center} cy={center} r={orbSize * 0.7} fill="url(#voice-aura-gradient)"
          style={{ opacity: isVoiceActive ? 1.0 : 0.95, transition: 'opacity 0.4s ease-out' }} />
        <circle cx={center} cy={center} r={orbSize * 0.52} fill="none"
          stroke={hexToRgba(glowColor, 0.1)} strokeWidth="40"
          style={{ filter: "blur(40px)", opacity: 0.3 }} />
      </motion.g>

      {/* 3. Integrated BasePlate */}
      <circle cx={center} cy={center} r={orbSize * 0.49} fill="url(#base-plate-gradient)" style={{ opacity: 0.8 }} />

      {/* 4. Integrated DepthGroove */}
      <circle cx={center} cy={center} r={orbSize * 0.46} fill="none"
        stroke="rgba(0, 0, 0, 0.4)" strokeWidth="8"
        style={{ filter: "blur(4px)", opacity: 0.6 }} />

      <defs>
        <radialGradient id="voice-aura-gradient" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={hexToRgba(glowColor, 0.7)} />
          <stop offset="30%" stopColor={hexToRgba(glowColor, 0.3)} />
          <stop offset="70%" stopColor={hexToRgba(glowColor, 0.1)} />
          <stop offset="100%" stopColor="transparent" />
        </radialGradient>
        <radialGradient id="base-plate-gradient" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={basePlateColor} />
          <stop offset="70%" stopColor={hexToRgba(basePlateColor, 0.6)} />
          <stop offset="100%" stopColor={hexToRgba(basePlateColor, 0.3)} />
        </radialGradient>

        {/* ── HEX PATTERN SURFACE DEFS (replaces liquid metal) ── */}
        <linearGradient id="hex-active" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor={hexToRgba(glowColor, 0.25)} />
          <stop offset="50%" stopColor="rgba(10,10,12,0.7)" />
          <stop offset="100%" stopColor={hexToRgba(glowColor, 0.1)} />
        </linearGradient>
        <linearGradient id="hex-idle" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="rgba(30,32,40,0.5)" />
          <stop offset="100%" stopColor={hexToRgba(glowColor, 0.03)} />
        </linearGradient>
        <pattern id="hex-pattern" x="0" y="0" width="8" height="9.24" patternUnits="userSpaceOnUse">
          <polygon points="4,0 8,2.31 8,6.93 4,9.24 0,6.93 0,2.31"
            fill="none" stroke={hexToRgba(glowColor, 0.4)} strokeWidth="0.4" />
        </pattern>
      </defs>

      {/* 5. Decorative Outer Frame (no liquid metal filter) */}
      <motion.g
        initial={{ opacity: 0, scale: 1.1 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ type: "spring", stiffness: 100, damping: 20, delay: 0.1 }}
      >
        <circle cx={center} cy={center} r={outerRadius + 30} fill="none"
          stroke={hexToRgba(glowColor, 0.3)} strokeWidth="5" style={{ opacity: 0.9 }} />
        {/* 6. Sharp Edge Glow */}
        <circle cx={center} cy={center} r={outerRadius + 32.5} fill="none"
          stroke={glowColor} strokeWidth="0.75"
          style={{ opacity: 0.8, filter: `drop-shadow(0 0 4px ${glowColor})` }} />
        {/* Neon Edge Bloom */}
        <circle cx={center} cy={center} r={outerRadius + 32.5} fill="none"
          stroke={glowColor} strokeWidth="2" style={{ opacity: 0.4, filter: "blur(8px)" }} />
        {/* Specular Edge */}
        <circle cx={center} cy={center} r={outerRadius + 32.5} fill="none"
          stroke="rgba(255, 255, 255, 0.4)" strokeWidth="0.5" />
        {/* 7. Structural Counter-Beams (2 CCW + 2 CW) */}
        <motion.circle cx={center} cy={center} r={outerRadius + 30} fill="none"
          stroke="white" strokeWidth="1.8" pathLength="1" strokeDasharray="0.02 0.48"
          animate={{ rotate: -360 }} transition={{ duration: 6, repeat: Infinity, ease: "linear" }}
          style={{ pointerEvents: "none", filter: "drop-shadow(0 0 8px white)", opacity: 0.9, originX: "50%", originY: "50%" }} />
        <motion.circle cx={center} cy={center} r={outerRadius + 28} fill="none"
          stroke="white" strokeWidth="1.4" pathLength="1" strokeDasharray="0.02 0.48"
          animate={{ rotate: -360 }} transition={{ duration: 4.5, repeat: Infinity, ease: "linear" }}
          style={{ pointerEvents: "none", filter: "drop-shadow(0 0 6px white)", opacity: 0.7, originX: "50%", originY: "50%" }} />
        <motion.circle cx={center} cy={center} r={outerRadius + 30} fill="none"
          stroke="white" strokeWidth="1.8" pathLength="1" strokeDasharray="0.02 0.48"
          animate={{ rotate: 360 }} transition={{ duration: 7, repeat: Infinity, ease: "linear" }}
          style={{ pointerEvents: "none", filter: "drop-shadow(0 0 8px white)", opacity: 0.9, originX: "50%", originY: "50%" }} />
        <motion.circle cx={center} cy={center} r={outerRadius + 28} fill="none"
          stroke="white" strokeWidth="1.4" pathLength="1" strokeDasharray="0.02 0.48"
          animate={{ rotate: 360 }} transition={{ duration: 5, repeat: Infinity, ease: "linear" }}
          style={{ pointerEvents: "none", filter: "drop-shadow(0 0 6px white)", opacity: 0.7, originX: "50%", originY: "50%" }} />
      </motion.g>

      {/* 8. Barrier Kinetic Glider + Orbital Ticks — matches winner preview */}
      <motion.g
        style={{ pointerEvents: "none" }}
        initial={{ opacity: 0, scale: 1.1 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ type: "spring", stiffness: 100, damping: 20, delay: 0.2 }}
      >
        {/* Barrier dashed ring — white, faster CW */}
        <motion.circle cx={center} cy={center} r={outerRadius + 23} fill="none"
          stroke="white" strokeWidth="2.7" strokeDasharray="18.57 4"
          animate={{ rotate: 360 }} transition={{ duration: 8, repeat: Infinity, ease: "linear" }}
          style={{ pointerEvents: "none", opacity: 0.6, filter: "drop-shadow(0 0 4px white)", transformOrigin: `${center}px ${center}px` }} />
        {/* Orbital ticks — 12 dual-layer, thick bloom + bright neon core */}
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
                {/* Bloom layer — thick, low opacity, heavy blur */}
                <line x1={innerPoint.x} y1={innerPoint.y} x2={outerPoint.x} y2={outerPoint.y}
                  stroke={tickColor}
                  strokeWidth={isWhiteTick ? 6.5 : 5.2}
                  style={{ pointerEvents: "none", opacity: isWhiteTick ? 0.3 : 0.2, filter: isWhiteTick ? "drop-shadow(0 0 5px white)" : `drop-shadow(0 0 4px ${glowColor})` }} />
                {/* Core layer — bright neon line */}
                <line x1={innerPoint.x} y1={innerPoint.y} x2={outerPoint.x} y2={outerPoint.y}
                  stroke={isWhiteTick ? "white" : glowColor}
                  strokeWidth={isWhiteTick ? 2.8 : 2.2}
                  style={{
                    pointerEvents: "none",
                    opacity: isWhiteTick ? 0.75 : 0.6,
                    filter: isWhiteTick
                      ? `drop-shadow(0 0 6px white) drop-shadow(0 0 12px ${glowColor})`
                      : `drop-shadow(0 0 4px ${glowColor})`,
                  }} />
              </g>
            )
          })}
        </g>
      </motion.g>

      {/* 9. Core Shimmer Engine (White Bright Light Halo) — bright white, surrounds center button */}
      <g style={{ pointerEvents: 'none' }}>
        {/* Soft glare layer — pulsing white, large radius for visible halo */}
        <motion.circle cx={center} cy={center} r={orbSize * 0.14} fill="none"
          stroke="white" strokeWidth="10" initial={{ opacity: 0.15 }}
          animate={{ opacity: [0.15, 0.4, 0.15], scale: [1, 1.1, 1] }}
          transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
          style={{ filter: "blur(14px)", transformOrigin: `${center}px ${center}px` }} />
        {/* Sharp halo ring — bright white, just outside the 64px button */}
        <circle cx={center} cy={center} r={orbSize * 0.125} fill="none"
          stroke="white" strokeWidth="2.5"
          style={{ opacity: 1, filter: "drop-shadow(0 0 8px white) drop-shadow(0 0 16px white)" }} />
        {/* Inner sharp ring — white, hugging the button edge */}
        <circle cx={center} cy={center} r={orbSize * 0.115} fill="none"
          stroke="white" strokeWidth="1"
          style={{ opacity: 0.7, filter: "drop-shadow(0 0 4px white)" }} />
      </g>

      {/* 10. Outer Interactive Ring — HEX PATTERN SURFACE */}
      <motion.g
        initial={{ opacity: 0, scale: 1.15 }}
        animate={{ rotate: outerRotation, opacity: 1, scale: 1 }}
        transition={{
          rotate: confirmSpinning ? confirmSpinConfig : springConfig,
          opacity: { duration: 0.4, delay: 0.3 },
          scale: { type: "spring", stiffness: 100, damping: 20, delay: 0.3 }
        }}
        style={{ transformOrigin: 'center center', transformBox: 'view-box' }}
      >
        {outerItems.map((item, index) => {
          const startAngle = index * outerSegmentAngle
          const endAngle = (index + 1) * outerSegmentAngle
          const isSelected = selectedIndex === index
          const path = generateArcPath(outerRadius, startAngle + 1, endAngle - 1)

          return (
            <g key={`outer-${item.id}`}>
              {/* Layer 1: Glow Background */}
              <path d={path} fill="none"
                stroke={isSelected ? hexToRgba(glowColor, 0.12) : "rgba(255, 255, 255, 0.02)"}
                strokeWidth="28" style={{ filter: isSelected ? "blur(8px)" : "none" }} />
              {/* Layer 2: Base Metal Body (hex-active / hex-idle) */}
              <path d={path} fill="none"
                stroke={isSelected ? "url(#hex-active)" : "url(#hex-idle)"}
                strokeWidth="28"
                style={{ cursor: "pointer", pointerEvents: "auto", opacity: 0.95 }}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => onSelect(index)} />
              {/* Layer 3: Hex Pattern Texture Overlay */}
              <path d={path} fill="none" stroke="url(#hex-pattern)" strokeWidth="28"
                style={{ cursor: "pointer", pointerEvents: "auto", opacity: isSelected ? 0.35 : 0.18 }}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => onSelect(index)} />
              {/* Layer 4: Neon Edge Outline */}
              <path d={path} fill="none"
                stroke={isSelected ? glowColor : hexToRgba(glowColor, 0.2)}
                strokeWidth={isSelected ? 1.5 : 0.75}
                style={{
                  pointerEvents: "none",
                  filter: isSelected ? `drop-shadow(0 0 6px ${glowColor}) drop-shadow(0 0 12px ${glowColor})` : "none",
                }} />
              {renderSegmentText(outerRadius, startAngle, endAngle, item.id, item.label, isSelected, 10.5)}
            </g>
          )
        })}
      </motion.g>

      {/* 11. Gap Kinetic Glider */}
      <motion.g
        initial={{ opacity: 0, scale: 1.1 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ type: "spring", stiffness: 100, damping: 20, delay: 0.4 }}
      >
        <circle cx={center} cy={center} r={gapRadius} fill="none"
          stroke={hexToRgba(glowColor, 0.4)} strokeWidth="2.7" strokeDasharray="45 15"
          className="ring-middle-anim" style={{ pointerEvents: "none" }} />
        <motion.circle cx={center} cy={center} r={gapRadius} fill="none"
          stroke="white" strokeWidth="2.2" pathLength="1" strokeDasharray="0.02 0.48"
          animate={{ rotate: -360 }} transition={{ duration: 3.5, repeat: Infinity, ease: "linear" }}
          style={{ pointerEvents: "none", filter: "drop-shadow(0 0 8px white)", opacity: 0.85, originX: "50%", originY: "50%" }} />
      </motion.g>

      {/* 12. Inner Interactive Ring — HEX PATTERN SURFACE */}
      <motion.g
        initial={{ opacity: 0, scale: 1.15 }}
        animate={{ rotate: innerRotation, opacity: 1, scale: 1 }}
        transition={{
          rotate: confirmSpinning ? confirmSpinConfig : springConfig,
          opacity: { duration: 0.4, delay: 0.5 },
          scale: { type: "spring", stiffness: 100, damping: 20, delay: 0.5 }
        }}
        style={{ transformOrigin: 'center center', transformBox: 'view-box' }}
      >
        {innerItems.map((item, index) => {
          const startAngle = index * innerSegmentAngle
          const endAngle = (index + 1) * innerSegmentAngle
          const isSelected = selectedIndex === splitPoint + index
          const globalIndex = splitPoint + index
          const path = generateArcPath(innerRadius, startAngle + 1, endAngle - 1)

          return (
            <g key={`inner-${item.id}-${index}`}>
              {/* Layer 1: Glow Background */}
              <path d={path} fill="none"
                stroke={isSelected ? hexToRgba(glowColor, 0.12) : "rgba(255, 255, 255, 0.02)"}
                strokeWidth="22" style={{ filter: isSelected ? "blur(8px)" : "none" }} />
              {/* Layer 2: Base Metal Body (hex-active / hex-idle) */}
              <path d={path} fill="none"
                stroke={isSelected ? "url(#hex-active)" : "url(#hex-idle)"}
                strokeWidth="22"
                style={{ cursor: "pointer", pointerEvents: "auto", opacity: 0.95 }}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => onSelect(globalIndex)} />
              {/* Layer 3: Hex Pattern Texture Overlay */}
              <path d={path} fill="none" stroke="url(#hex-pattern)" strokeWidth="22"
                style={{ cursor: "pointer", pointerEvents: "auto", opacity: isSelected ? 0.35 : 0.18 }}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => onSelect(globalIndex)} />
              {/* Layer 4: Neon Edge Outline */}
              <path d={path} fill="none"
                stroke={isSelected ? glowColor : hexToRgba(glowColor, 0.2)}
                strokeWidth={isSelected ? 1.5 : 0.75}
                style={{
                  pointerEvents: "none",
                  filter: isSelected ? `drop-shadow(0 0 6px ${glowColor}) drop-shadow(0 0 12px ${glowColor})` : "none",
                }} />
              {renderSegmentText(innerRadius, startAngle, endAngle, item.id, item.label, isSelected, 8.5)}
            </g>
          )
        })}
      </motion.g>

      {/* 13. Core Kinetic Glider — 3-prong white beam rotating CCW */}
      <motion.g
        initial={{ opacity: 0, scale: 1.1 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ type: "spring", stiffness: 100, damping: 20, delay: 0.6 }}
      >
        {/* Dashed ring — neon white */}
        <circle cx={center} cy={center} r={orbSize * 0.185} fill="none"
          stroke="white" strokeWidth="2.7" strokeDasharray="15 35"
          className="ring-inner-anim" style={{ pointerEvents: "none", opacity: 0.5, filter: "drop-shadow(0 0 6px white)" }} />
        {/* 3-prong white beam — rotating counter-clockwise */}
        <motion.circle cx={center} cy={center} r={orbSize * 0.185} fill="none"
          stroke="white" strokeWidth="2.2" pathLength="1" strokeDasharray="0.02 0.98"
          animate={{ rotate: -360 }} transition={{ duration: 4, repeat: Infinity, ease: "linear" }}
          style={{ pointerEvents: "none", filter: "drop-shadow(0 0 8px white)", opacity: 0.85, transformOrigin: `${center}px ${center}px` }} />
      </motion.g>

      {/* 14. Structural Energy Circuit */}
      <motion.circle cx={center} cy={center} r={outerRadius + 29} fill="none"
        stroke={hexToRgba(glowColor, 0.4)} strokeWidth="1.5" style={{ pointerEvents: "none" }} />

      {/* 15. Particle Chase Relay (Alpha + Beta) — synced to ENERGY_CYCLE */}
      <motion.circle cx={center} cy={center} r={outerRadius + 29} fill="none"
        stroke="white" strokeWidth="3" strokeLinecap="round" pathLength="1"
        initial={{ strokeDasharray: "0.08 0.92", strokeDashoffset: 0.75, opacity: 0.35 }}
        animate={{ strokeDashoffset: [0.75, -0.25], opacity: [0.35, 0.95, 0.95, 0.35] }}
        transition={{
          strokeDashoffset: { duration: ENERGY_CYCLE.duration / 4, repeat: Infinity, ease: "linear" },
          opacity: { duration: ENERGY_CYCLE.duration, repeat: Infinity, ease: "linear",
            times: [0, ENERGY_CYCLE.segments.s2Wheel.start, ENERGY_CYCLE.segments.s2Wheel.end, 1.0] }
        }}
        style={{ pointerEvents: "none", filter: `blur(0.5px) drop-shadow(0 0 15px ${glowColor}) drop-shadow(0 0 6px white)` }} />
      <motion.circle cx={center} cy={center} r={outerRadius + 29} fill="none"
        stroke="white" strokeWidth="3" strokeLinecap="round" pathLength="1"
        initial={{ strokeDasharray: "0.08 0.92", strokeDashoffset: 0.25, opacity: 0.35 }}
        animate={{ strokeDashoffset: [0.25, -0.75], opacity: [0.35, 0.95, 0.95, 0.35] }}
        transition={{
          strokeDashoffset: { duration: ENERGY_CYCLE.duration / 4, repeat: Infinity, ease: "linear" },
          opacity: { duration: ENERGY_CYCLE.duration, repeat: Infinity, ease: "linear",
            times: [0, ENERGY_CYCLE.segments.s2Wheel.start, ENERGY_CYCLE.segments.s2Wheel.end, 1.0] }
        }}
        style={{ pointerEvents: "none", filter: `blur(0.5px) drop-shadow(0 0 15px ${glowColor}) drop-shadow(0 0 6px white)` }} />

      {/* CRITICAL: Local <style jsx> — 3x SLOWER than globals.css (production speeds) */}
      <style jsx>{`
        .ring-outer-anim { animation: rotate-slow 60s linear infinite; transform-origin: center; }
        .ring-middle-anim { animation: rotate-slow 45s linear infinite reverse; transform-origin: center; }
        .ring-inner-anim { animation: rotate-slow 30s linear infinite; transform-origin: center; }
        @keyframes rotate-slow { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
      `}</style>
    </svg>
  )
}
