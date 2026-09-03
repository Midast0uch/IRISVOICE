"use client"

import React, { useState, useMemo, useCallback } from "react"
import { motion } from "framer-motion"

// ── Shared helpers (same as DualRingMechanism) ────────────────────────

function hexToRgba(color: string, alpha: number): string {
  if (color.startsWith("hsl")) {
    return color.replace("hsl(", "hsla(").replace(")", `, ${alpha})`)
  }
  const hex = color.replace("#", "")
  const r = parseInt(hex.substring(0, 2), 16)
  const g = parseInt(hex.substring(2, 4), 16)
  const b = parseInt(hex.substring(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = ((angleDeg - 90) * Math.PI) / 180
  // Round to 2 decimal places to prevent SSR/CSR hydration mismatch
  // (floating-point precision differs between server and client)
  return {
    x: Math.round((cx + r * Math.cos(rad)) * 100) / 100,
    y: Math.round((cy + r * Math.sin(rad)) * 100) / 100,
  }
}

const SAMPLE_ITEMS = [
  { id: "voice", label: "Voice" },
  { id: "agent", label: "Agent" },
  { id: "automate", label: "Automate" },
  { id: "system", label: "System" },
  { id: "customize", label: "Customize" },
  { id: "monitor", label: "Monitor" },
]

// ── Ring surface style variants ───────────────────────────────────────
// Each variant changes ONLY the interactive segment rendering:
//   - segment body stroke (the main surface)
//   - segment glow background
//   - micro edge highlight
// Everything else (decorative rings, ticks, energy beams, base plate) stays identical.

type RingVariant = "glassmorphic" | "hex-pattern" | "neon-glass" | "neon-hex"

interface RingSegmentProps {
  path: string
  glowPath: string
  isSelected: boolean
  glowColor: string
  strokeWidth: number
  variant: RingVariant
  gradientId: string
  onClick: () => void
}

function RingSegment({ path, glowPath, isSelected, glowColor, strokeWidth, variant, gradientId, onClick }: RingSegmentProps) {
  switch (variant) {
    // ── Variant 1: Glassmorphic ────────────────────────────────────────
    // Matches the hex node's glassmorphic base: dark linear gradient with
    // glow color tint, inner shadow feel, active state gets radial glow.
    case "glassmorphic":
      return (
        <g>
          {/* Glow background */}
          <path
            d={path}
            fill="none"
            stroke={isSelected ? hexToRgba(glowColor, 0.15) : "rgba(255,255,255,0.02)"}
            strokeWidth={strokeWidth}
            style={{ filter: isSelected ? `blur(8px)` : "none" }}
          />
          {/* Glassmorphic body */}
          <path
            d={path}
            fill="none"
            stroke={isSelected ? `url(#${gradientId}-glass-active)` : `url(#${gradientId}-glass-idle)`}
            strokeWidth={strokeWidth}
            style={{ cursor: "pointer", pointerEvents: "auto", opacity: 0.95 }}
            onMouseDown={(e) => e.stopPropagation()}
            onClick={onClick}
          />
          {/* Inner highlight (top edge) */}
          <path
            d={glowPath}
            fill="none"
            stroke={isSelected ? "rgba(255,255,255,0.5)" : "rgba(255,255,255,0.08)"}
            strokeWidth={0.5}
            style={{ opacity: 0.7 }}
          />
          {/* Active radial glow fill on top */}
          {isSelected && (
            <path
              d={path}
              fill="none"
              stroke={hexToRgba(glowColor, 0.2)}
              strokeWidth={strokeWidth - 4}
              style={{ filter: `blur(4px)`, pointerEvents: "none" }}
            />
          )}
        </g>
      )

    // ── Variant 2: Hex Pattern ─────────────────────────────────────────
    // Overlays a honeycomb SVG pattern on the segment surface, giving the
    // ring a textured hex feel while keeping the arc shape.
    case "hex-pattern":
      return (
        <g>
          {/* Glow background */}
          <path
            d={path}
            fill="none"
            stroke={isSelected ? hexToRgba(glowColor, 0.12) : "rgba(255,255,255,0.02)"}
            strokeWidth={strokeWidth}
            style={{ filter: isSelected ? `blur(8px)` : "none" }}
          />
          {/* Base metal body */}
          <path
            d={path}
            fill="none"
            stroke={isSelected ? `url(#${gradientId}-hex-active)` : `url(#${gradientId}-hex-idle)`}
            strokeWidth={strokeWidth}
            style={{ cursor: "pointer", pointerEvents: "auto", opacity: 0.95 }}
            onMouseDown={(e) => e.stopPropagation()}
            onClick={onClick}
          />
          {/* Hex pattern texture overlay */}
          <path
            d={path}
            fill="none"
            stroke={`url(#${gradientId}-hex-pattern)`}
            strokeWidth={strokeWidth}
            style={{ cursor: "pointer", pointerEvents: "auto", opacity: isSelected ? 0.4 : 0.22 }}
            onMouseDown={(e) => e.stopPropagation()}
            onClick={onClick}
          />
          {/* Neon edge outline (the bright line) */}
          <path
            d={path}
            fill="none"
            stroke={isSelected ? glowColor : hexToRgba(glowColor, 0.2)}
            strokeWidth={isSelected ? 1.5 : 0.75}
            style={{
              pointerEvents: "none",
              filter: isSelected ? `drop-shadow(0 0 6px ${glowColor}) drop-shadow(0 0 12px ${glowColor})` : "none",
            }}
          />
        </g>
      )

    // ── Variant 3: Neon Hex ───────────────────────────────────────────
    // Combines neon-glass surface with hex pattern texture overlay.
    // Selected segments glow with neon edge + hex pattern brightens.
    case "neon-hex":
      return (
        <g>
          {/* Outer glow (matches hex node outer glow) */}
          <path
            d={path}
            fill="none"
            stroke={isSelected ? hexToRgba(glowColor, 0.4) : "rgba(255,255,255,0.02)"}
            strokeWidth={strokeWidth + 6}
            style={{ filter: isSelected ? `blur(8px)` : "none", pointerEvents: "none" }}
          />
          {/* Glassmorphic body */}
          <path
            d={path}
            fill="none"
            stroke={isSelected ? `url(#${gradientId}-neon-active)` : `url(#${gradientId}-neon-idle)`}
            strokeWidth={strokeWidth}
            style={{ cursor: "pointer", pointerEvents: "auto", opacity: 0.9 }}
            onMouseDown={(e) => e.stopPropagation()}
            onClick={onClick}
          />
          {/* Hex pattern texture overlay */}
          <path
            d={path}
            fill="none"
            stroke={`url(#${gradientId}-hex-pattern)`}
            strokeWidth={strokeWidth}
            style={{ cursor: "pointer", pointerEvents: "auto", opacity: isSelected ? 0.4 : 0.22 }}
            onMouseDown={(e) => e.stopPropagation()}
            onClick={onClick}
          />
          {/* Neon edge outline (the bright line) */}
          <path
            d={path}
            fill="none"
            stroke={isSelected ? glowColor : hexToRgba(glowColor, 0.2)}
            strokeWidth={isSelected ? 1.5 : 0.75}
            style={{
              pointerEvents: "none",
              filter: isSelected ? `drop-shadow(0 0 6px ${glowColor}) drop-shadow(0 0 12px ${glowColor})` : "none",
            }}
          />
          {/* Inner shadow (depth) */}
          <path
            d={path}
            fill="none"
            stroke="rgba(0,0,0,0.3)"
            strokeWidth={strokeWidth - 8}
            style={{ pointerEvents: "none" }}
          />
          {/* Active radial glow fill */}
          {isSelected && (
            <path
              d={path}
              fill="none"
              stroke={hexToRgba(glowColor, 0.15)}
              strokeWidth={strokeWidth - 10}
              style={{ filter: `blur(2px)`, pointerEvents: "none" }}
            />
          )}
        </g>
      )

    // ── Variant 4: Neon Glass ──────────────────────────────────────────
    // Combines the hex node's outer glow + glassmorphic base with a neon
    // edge outline. The most "alive" variant — selected segments have a
    // bright neon outline that matches the hex node's active glow.
    case "neon-glass":
      return (
        <g>
          {/* Outer glow (matches hex node outer glow) */}
          <path
            d={path}
            fill="none"
            stroke={isSelected ? hexToRgba(glowColor, 0.4) : "rgba(255,255,255,0.02)"}
            strokeWidth={strokeWidth + 6}
            style={{ filter: isSelected ? `blur(8px)` : "none", pointerEvents: "none" }}
          />
          {/* Glassmorphic body */}
          <path
            d={path}
            fill="none"
            stroke={isSelected ? `url(#${gradientId}-neon-active)` : `url(#${gradientId}-neon-idle)`}
            strokeWidth={strokeWidth}
            style={{ cursor: "pointer", pointerEvents: "auto", opacity: 0.9 }}
            onMouseDown={(e) => e.stopPropagation()}
            onClick={onClick}
          />
          {/* Neon edge outline (the bright line) */}
          <path
            d={path}
            fill="none"
            stroke={isSelected ? glowColor : hexToRgba(glowColor, 0.2)}
            strokeWidth={isSelected ? 1.5 : 0.75}
            style={{
              pointerEvents: "none",
              filter: isSelected ? `drop-shadow(0 0 6px ${glowColor}) drop-shadow(0 0 12px ${glowColor})` : "none",
            }}
          />
          {/* Inner shadow (depth) */}
          <path
            d={path}
            fill="none"
            stroke="rgba(0,0,0,0.3)"
            strokeWidth={strokeWidth - 8}
            style={{ pointerEvents: "none" }}
          />
          {/* Active radial glow fill */}
          {isSelected && (
            <path
              d={path}
              fill="none"
              stroke={hexToRgba(glowColor, 0.15)}
              strokeWidth={strokeWidth - 10}
              style={{ filter: `blur(2px)`, pointerEvents: "none" }}
            />
          )}
        </g>
      )
  }
}

// ── SVG gradient defs for each variant ───────────────────────────────

function VariantDefs({ glowColor, gradientId, variant }: { glowColor: string; gradientId: string; variant: RingVariant }) {
  if (variant === "glassmorphic") {
    return (
      <defs>
        <linearGradient id={`${gradientId}-glass-active`} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor={hexToRgba(glowColor, 0.3)} />
          <stop offset="50%" stopColor="rgba(10,10,12,0.8)" />
          <stop offset="100%" stopColor={hexToRgba(glowColor, 0.15)} />
        </linearGradient>
        <linearGradient id={`${gradientId}-glass-idle`} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="rgba(30,32,40,0.6)" />
          <stop offset="100%" stopColor={hexToRgba(glowColor, 0.05)} />
        </linearGradient>
      </defs>
    )
  }
  if (variant === "hex-pattern" || variant === "neon-hex") {
    return (
      <defs>
        <linearGradient id={`${gradientId}-hex-active`} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor={hexToRgba(glowColor, 0.25)} />
          <stop offset="50%" stopColor="rgba(10,10,12,0.7)" />
          <stop offset="100%" stopColor={hexToRgba(glowColor, 0.1)} />
        </linearGradient>
        <linearGradient id={`${gradientId}-hex-idle`} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="rgba(30,32,40,0.5)" />
          <stop offset="100%" stopColor={hexToRgba(glowColor, 0.03)} />
        </linearGradient>
        {/* Honeycomb pattern */}
        <pattern id={`${gradientId}-hex-pattern`} x="0" y="0" width="8" height="9.24" patternUnits="userSpaceOnUse">
          <polygon
            points="4,0 8,2.31 8,6.93 4,9.24 0,6.93 0,2.31"
            fill="none"
            stroke={hexToRgba(glowColor, 0.4)}
            strokeWidth="0.4"
          />
        </pattern>
        {/* Neon glass defs (used by neon-hex variant) */}
        {variant === "neon-hex" && (
          <>
            <linearGradient id={`${gradientId}-neon-active`} x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor={hexToRgba(glowColor, 0.2)} />
              <stop offset="40%" stopColor="rgba(10,10,12,0.85)" />
              <stop offset="100%" stopColor={hexToRgba(glowColor, 0.1)} />
            </linearGradient>
            <linearGradient id={`${gradientId}-neon-idle`} x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor="rgba(20,22,28,0.6)" />
              <stop offset="100%" stopColor="rgba(10,10,12,0.4)" />
            </linearGradient>
          </>
        )}
      </defs>
    )
  }
  // neon-glass
  return (
    <defs>
      <linearGradient id={`${gradientId}-neon-active`} x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%" stopColor={hexToRgba(glowColor, 0.2)} />
        <stop offset="40%" stopColor="rgba(10,10,12,0.85)" />
        <stop offset="100%" stopColor={hexToRgba(glowColor, 0.1)} />
      </linearGradient>
      <linearGradient id={`${gradientId}-neon-idle`} x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%" stopColor="rgba(20,22,28,0.6)" />
        <stop offset="100%" stopColor="rgba(10,10,12,0.4)" />
      </linearGradient>
    </defs>
  )
}

// ── Mini wheel renderer (same structure as DualRingMechanism, only surface changes) ──

function MiniWheel({ glowColor, variant }: { glowColor: string; variant: RingVariant }) {
  const [selected, setSelected] = useState(0)
  const orbSize = 200
  const buffer = 120
  const center = (orbSize + buffer) / 2
  const outerRadius = orbSize * 0.39
  const innerRadius = orbSize * 0.2575
  const splitPoint = Math.ceil(SAMPLE_ITEMS.length / 2)
  const outerItems = SAMPLE_ITEMS.slice(0, splitPoint)
  const innerItems = SAMPLE_ITEMS.slice(splitPoint)
  const outerSegmentAngle = 360 / outerItems.length
  const innerSegmentAngle = 360 / innerItems.length

  const isOuterSelected = selected < splitPoint
  const outerSelectedIndex = isOuterSelected ? selected : -1
  const outerRotation = outerSelectedIndex >= 0 ? -(outerSelectedIndex * outerSegmentAngle) : 0
  const innerSelectedIndex = !isOuterSelected ? selected - splitPoint : -1
  const innerRotation = innerSelectedIndex >= 0 ? -(innerSelectedIndex * innerSegmentAngle) : 0

  const gradientId = `wheel-${variant}`

  const generateArcPath = useCallback(
    (radius: number, startAngle: number, endAngle: number): string => {
      const start = polarToCartesian(center, center, radius, endAngle)
      const end = polarToCartesian(center, center, radius, startAngle)
      const largeArcFlag = endAngle - startAngle <= 180 ? "0" : "1"
      return ["M", start.x, start.y, "A", radius, radius, 0, largeArcFlag, 0, end.x, end.y].join(" ")
    },
    [center]
  )

  const renderSegmentText = (radius: number, startAngle: number, endAngle: number, id: string, label: string, isSelected: boolean, fontSize: number) => {
    const textPathId = `${gradientId}-text-${id}`
    const path = generateArcPath(radius, startAngle, endAngle)
    return (
      <g key={`text-${id}`}>
        <defs>
          <path id={textPathId} d={path} fill="none" />
        </defs>
        <text
          fill={isSelected ? "rgba(255,255,255,0.95)" : "rgba(255,255,255,0.4)"}
          fontSize={fontSize}
          fontWeight="600"
          textAnchor="middle"
          style={{ pointerEvents: "none", textTransform: "uppercase", letterSpacing: "0.05em" }}
        >
          <textPath href={`#${textPathId}`} startOffset="50%">
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
      style={{ overflow: "visible", pointerEvents: "none" }}
    >
      <VariantDefs glowColor={glowColor} gradientId={gradientId} variant={variant} />

      {/* Base plate (same as original) */}
      <circle cx={center} cy={center} r={orbSize * 0.49} fill="rgba(10,11,22,0.6)" style={{ opacity: 0.8 }} />
      <circle cx={center} cy={center} r={orbSize * 0.46} fill="none" stroke="rgba(0,0,0,0.4)" strokeWidth="8" style={{ filter: "blur(4px)", opacity: 0.6 }} />

      {/* Decorative outer frame (same as original) */}
      <circle cx={center} cy={center} r={outerRadius + 30} fill="none" stroke={hexToRgba(glowColor, 0.3)} strokeWidth="5" style={{ opacity: 0.9 }} />
      <circle cx={center} cy={center} r={outerRadius + 32.5} fill="none" stroke={glowColor} strokeWidth="0.75" style={{ opacity: 0.8, filter: `drop-shadow(0 0 4px ${glowColor})` }} />

      {/* ═══ STRUCTURAL BEAMS — 4 beams: 2 CCW + 2 CW counter-rotating pairs ═══ */}
      {/* CCW pair (slower) */}
      <motion.circle
        cx={center} cy={center} r={outerRadius + 30}
        fill="none" stroke="white" strokeWidth="1.8"
        pathLength={1} strokeDasharray="0.02 0.48"
        animate={{ rotate: -360 }}
        transition={{ duration: 6, repeat: Infinity, ease: "linear" }}
        style={{ filter: `drop-shadow(0 0 8px white)`, opacity: 0.9, transformOrigin: `${center}px ${center}px` }}
      />
      {/* CCW pair (faster) */}
      <motion.circle
        cx={center} cy={center} r={outerRadius + 28}
        fill="none" stroke="white" strokeWidth="1.4"
        pathLength={1} strokeDasharray="0.015 0.485"
        animate={{ rotate: -360 }}
        transition={{ duration: 4.5, repeat: Infinity, ease: "linear" }}
        style={{ filter: `drop-shadow(0 0 6px white)`, opacity: 0.7, transformOrigin: `${center}px ${center}px` }}
      />
      {/* CW pair (slower) */}
      <motion.circle
        cx={center} cy={center} r={outerRadius + 30}
        fill="none" stroke="white" strokeWidth="1.8"
        pathLength={1} strokeDasharray="0.018 0.482"
        animate={{ rotate: 360 }}
        transition={{ duration: 7, repeat: Infinity, ease: "linear" }}
        style={{ filter: `drop-shadow(0 0 8px white)`, opacity: 0.9, transformOrigin: `${center}px ${center}px` }}
      />
      {/* CW pair (faster) */}
      <motion.circle
        cx={center} cy={center} r={outerRadius + 28}
        fill="none" stroke="white" strokeWidth="1.4"
        pathLength={1} strokeDasharray="0.012 0.488"
        animate={{ rotate: 360 }}
        transition={{ duration: 5, repeat: Infinity, ease: "linear" }}
        style={{ filter: `drop-shadow(0 0 6px white)`, opacity: 0.7, transformOrigin: `${center}px ${center}px` }}
      />

      {/* ═══ BARRIER KINETIC GLIDER — faster than ticks (gear teeth moving off) ═══ */}
      {/* Barrier dashed ring — faster CW rotation */}
      <motion.circle
        cx={center}
        cy={center}
        r={outerRadius + 23}
        fill="none"
        stroke="white"
        strokeWidth="2.7"
        strokeDasharray="18.57 4"
        animate={{ rotate: 360 }}
        transition={{ duration: 8, repeat: Infinity, ease: "linear" }}
        style={{ opacity: 0.6, filter: `drop-shadow(0 0 4px white)`, transformOrigin: `${center}px ${center}px` }}
      />

      {/* ═══ ORBITAL TICKS — slower rotation (gear teeth left behind) ═══ */}
      <g className="ring-outer-anim">
        {Array.from({ length: 12 }).map((_, i) => {
          const angle = (i * 360) / 12
          const tickRadius = outerRadius + 18
          const inner = polarToCartesian(center, center, tickRadius - 5, angle)
          const outer = polarToCartesian(center, center, tickRadius + 5, angle)
          const isWhite = i % 2 === 0
          return (
            <g key={`tick-${i}`}>
              {/* Bloom layer */}
              <line
                x1={inner.x} y1={inner.y} x2={outer.x} y2={outer.y}
                stroke={isWhite ? "white" : glowColor}
                strokeWidth={isWhite ? 6.5 : 5.2}
                style={{ opacity: isWhite ? 0.3 : 0.2, filter: isWhite ? "drop-shadow(0 0 5px white)" : `drop-shadow(0 0 4px ${glowColor})` }}
              />
              {/* Core layer — bright neon line */}
              <line
                x1={inner.x} y1={inner.y} x2={outer.x} y2={outer.y}
                stroke={isWhite ? "white" : glowColor}
                strokeWidth={isWhite ? 2.8 : 2.2}
                style={{
                  opacity: isWhite ? 0.75 : 0.6,
                  filter: isWhite
                    ? `drop-shadow(0 0 6px white) drop-shadow(0 0 12px ${glowColor})`
                    : `drop-shadow(0 0 4px ${glowColor})`,
                }}
              />
            </g>
          )
        })}
      </g>

      {/* ═══ GAP KINETIC GLIDER — counter-clockwise, with space between outer and inner rings ═══ */}
      <g>
        {/* Dashed gap ring — neon glow color, counter-rotating via CSS */}
        <circle
          cx={center}
          cy={center}
          r={(outerRadius + innerRadius) / 2}
          fill="none"
          stroke={hexToRgba(glowColor, 0.4)}
          strokeWidth="2.7"
          strokeDasharray="45 15"
          className="ring-middle-anim"
          style={{ pointerEvents: "none" }}
        />
        {/* Counter-rotating white beam (CCW) — matches original DualRingMechanism */}
        <motion.circle
          cx={center}
          cy={center}
          r={(outerRadius + innerRadius) / 2}
          fill="none"
          stroke="white"
          strokeWidth="2.2"
          pathLength={1}
          strokeDasharray="0.02 0.48"
          animate={{ rotate: -360 }}
          transition={{ duration: 3.5, repeat: Infinity, ease: "linear" }}
          style={{
            pointerEvents: "none",
            filter: `drop-shadow(0 0 8px white)`,
            opacity: 0.85,
            transformOrigin: `${center}px ${center}px`,
          }}
        />
      </g>

      {/* ═══ CORE KINETIC GLIDER — clockwise, envelops the core halo ═══ */}
      <g>
        {/* Dashed core ring — neon glow color, clockwise-rotating via CSS */}
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
        {/* Clockwise-rotating white beam (CW) — matches original DualRingMechanism */}
        <motion.circle
          cx={center}
          cy={center}
          r={orbSize * 0.185}
          fill="none"
          stroke="white"
          strokeWidth="2.2"
          pathLength={1}
          strokeDasharray="0.02 0.98"
          animate={{ rotate: 360 }}
          transition={{ duration: 4, repeat: Infinity, ease: "linear" }}
          style={{
            pointerEvents: "none",
            filter: `drop-shadow(0 0 8px white)`,
            opacity: 0.85,
            transformOrigin: `${center}px ${center}px`,
          }}
        />
      </g>

      {/* Core shimmer (same as original) */}
      <motion.circle
        cx={center} cy={center} r={orbSize * 0.11}
        fill="none" stroke="white" strokeWidth="6"
        animate={{ opacity: [0.1, 0.35, 0.1], scale: [1, 1.1, 1] }}
        transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
        style={{ filter: "blur(12px)", transformOrigin: `${center}px ${center}px` }}
      />
      <circle cx={center} cy={center} r={orbSize * 0.11} fill="none" stroke="white" strokeWidth="2" style={{ opacity: 0.9, filter: `drop-shadow(0 0 10px white)` }} />

      {/* ═══ OUTER INTERACTIVE RING — surface variant applied here ═══ */}
      <motion.g
        animate={{ rotate: outerRotation }}
        transition={{ type: "spring", stiffness: 80, damping: 16 }}
        style={{ transformOrigin: "center center", transformBox: "view-box" }}
      >
        {outerItems.map((item, index) => {
          const startAngle = index * outerSegmentAngle
          const endAngle = (index + 1) * outerSegmentAngle
          const isSelected = selected === index
          const path = generateArcPath(outerRadius, startAngle + 1, endAngle - 1)
          const glowPath = generateArcPath(outerRadius + 14.5, startAngle + 1, endAngle - 1)
          return (
            <g key={`outer-${item.id}`}>
              <RingSegment
                path={path}
                glowPath={glowPath}
                isSelected={isSelected}
                glowColor={glowColor}
                strokeWidth={28}
                variant={variant}
                gradientId={gradientId}
                onClick={() => setSelected(index)}
              />
              {renderSegmentText(outerRadius, startAngle, endAngle, item.id, item.label, isSelected, 10.5)}
            </g>
          )
        })}
      </motion.g>

      {/* ═══ INNER INTERACTIVE RING — surface variant applied here ═══ */}
      <motion.g
        animate={{ rotate: innerRotation }}
        transition={{ type: "spring", stiffness: 80, damping: 16 }}
        style={{ transformOrigin: "center center", transformBox: "view-box" }}
      >
        {innerItems.map((item, index) => {
          const startAngle = index * innerSegmentAngle
          const endAngle = (index + 1) * innerSegmentAngle
          const isSelected = selected === splitPoint + index
          const globalIndex = splitPoint + index
          const path = generateArcPath(innerRadius, startAngle + 1, endAngle - 1)
          const glowPath = generateArcPath(innerRadius + 11.5, startAngle + 1, endAngle - 1)
          return (
            <g key={`inner-${item.id}-${index}`}>
              <RingSegment
                path={path}
                glowPath={glowPath}
                isSelected={isSelected}
                glowColor={glowColor}
                strokeWidth={22}
                variant={variant}
                gradientId={gradientId}
                onClick={() => setSelected(globalIndex)}
              />
              {renderSegmentText(innerRadius, startAngle, endAngle, item.id, item.label, isSelected, 9.5)}
            </g>
          )
        })}
      </motion.g>
    </svg>
  )
}

// ── Main export: 4 variants in a vertical list ────────────────────────

const VARIANTS: { key: RingVariant; badge: string; title: string; description: string }[] = [
  {
    key: "glassmorphic",
    badge: "1",
    title: "Glassmorphic Surface",
    description:
      "Matches the hex node's glassmorphic base: dark linear gradient with glow color tint, inner shadow depth, active state gets a radial glow fill. Subtle and clean.",
  },
  {
    key: "hex-pattern",
    badge: "2",
    title: "Hex Pattern Surface",
    description:
      "Overlays a honeycomb SVG pattern texture on the segment surface, giving the ring a hex feel while keeping the arc shape. The pattern is subtle when idle and brightens on selection.",
  },
  {
    key: "neon-hex",
    badge: "3",
    title: "Neon Hex Surface",
    description:
      "Combines the neon-glass surface (bright neon edge outline + outer glow) with the hex pattern texture overlay. Selected segments glow with neon edge while the honeycomb pattern brightens. The most layered variant.",
  },
  {
    key: "neon-glass",
    badge: "4",
    title: "Neon Glass Surface",
    description:
      "Combines the hex node's outer glow + glassmorphic base with a bright neon edge outline. Selected segments have a glowing neon line that matches the hex node's active glow. The most 'alive' variant.",
  },
]

export function WheelRingStyles({ glowColor }: { glowColor: string }) {
  return (
    <div className="flex flex-col gap-8 w-full max-w-2xl mx-auto">
      {VARIANTS.map((v) => {
        const isWinner = v.key === "hex-pattern"
        return (
          <div
            key={v.key}
            className="flex flex-col items-center gap-4 p-6 rounded-2xl"
            style={isWinner ? {
              background: "linear-gradient(180deg, rgba(251, 191, 36, 0.06) 0%, rgba(255, 255, 255, 0.02) 100%)",
              border: "1px solid rgba(251, 191, 36, 0.35)",
              boxShadow: "0 0 32px rgba(251, 191, 36, 0.08)",
            } : { background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)" }}
          >
            <div className="flex items-center gap-2">
              <span
                className="px-2 py-0.5 rounded text-xs font-bold tracking-wider"
                style={isWinner ? {
                  background: "linear-gradient(135deg, #fde68a 0%, #fbbf24 50%, #f59e0b 100%)",
                  color: "#0a0a0e",
                  boxShadow: "0 0 14px rgba(251, 191, 36, 0.5)",
                } : { background: glowColor, color: "#0a0a0e" }}
              >
                {isWinner ? "★ WINNER" : v.badge}
              </span>
              <h3 className="text-sm font-semibold text-white tracking-wide">{v.title}</h3>
            </div>

            <div className="relative flex items-center justify-center" style={{ width: 320, height: 320 }}>
              <MiniWheel glowColor={glowColor} variant={v.key} />
            </div>

            <p className="text-xs text-slate-400 text-center leading-relaxed max-w-sm">{v.description}</p>
          </div>
        )
      })}
    </div>
  )
}
