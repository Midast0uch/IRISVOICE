"use client"

import React, { useMemo, useCallback } from "react"
import { motion } from "framer-motion"
import type { MiniNode } from "@/types/navigation"

interface DualRingMechanismProps {
  items: MiniNode[]
  selectedIndex: number
  onSelect: (index: number) => void
  glowColor: string
  orbSize: number
  confirmSpinning: boolean
}

/**
 * Helper function to convert hex color to rgba with alpha
 * Validates: Property 36 - HexToRgba Color Conversion
 */
function hexToRgba(hex: string, alpha: number): string {
  // Remove # if present
  hex = hex.replace("#", "")
  
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
  orbSize,
  confirmSpinning,
}) => {
  // Task 5.1: Ring distribution logic (Property 6)
  const { outerItems, innerItems, splitPoint } = useMemo(() => {
    const split = Math.ceil(items.length / 2)
    return {
      outerItems: items.slice(0, split),
      innerItems: items.slice(split),
      splitPoint: split,
    }
  }, [items])

  // Calculate radii
  const outerRadius = orbSize * 0.42
  const innerRadius = orbSize * 0.18
  const center = orbSize / 2

  // Task 5.2: Outer ring calculations (memoized for performance - Requirement 12.2)
  const outerSegmentAngle = useMemo(() => 360 / outerItems.length, [outerItems.length])
  const outerSelectedIndex = selectedIndex < splitPoint ? selectedIndex : -1

  // Task 5.4: Outer ring rotation logic (memoized for performance - Requirement 12.2)
  const outerBaseRotation = useMemo(() => 
    outerSelectedIndex >= 0 ? -(outerSelectedIndex * outerSegmentAngle) : 0,
    [outerSelectedIndex, outerSegmentAngle]
  )

  // Task 5.3: Inner ring calculations (memoized for performance - Requirement 12.2)
  const innerSegmentAngle = useMemo(() => 
    innerItems.length > 0 ? 360 / innerItems.length : 0,
    [innerItems.length]
  )
  const innerSelectedIndex = selectedIndex >= splitPoint 
    ? selectedIndex - splitPoint 
    : -1

  // Task 5.5: Inner ring rotation logic (memoized for performance - Requirement 12.2)
  const innerBaseRotation = useMemo(() =>
    innerSelectedIndex >= 0 ? -(innerSelectedIndex * innerSegmentAngle) : 0,
    [innerSelectedIndex, innerSegmentAngle]
  )

  // Task 5.8: Counter-spin animation
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
   * Generate curved text path for labels
   */
  const generateTextPath = (
    radius: number,
    startAngle: number,
    endAngle: number,
    id: string
  ): JSX.Element => {
    const midAngle = (startAngle + endAngle) / 2
    const textRadius = radius
    const path = generateArcPath(textRadius, startAngle, endAngle)

    return (
      <defs key={`textpath-${id}`}>
        <path id={`textpath-${id}`} d={path} fill="none" />
      </defs>
    )
  }

  return (
    <svg
      width={orbSize}
      height={orbSize}
      viewBox={`0 0 ${orbSize} ${orbSize}`}
      className="absolute inset-0"
      style={{ pointerEvents: "none" }}
    >
      {/* Task 5.6: Decorative rings */}
      <g style={{ pointerEvents: "none" }}>
        {/* Ring 1 (innermost) */}
        <motion.circle
          cx={center}
          cy={center}
          r={innerRadius - 6}
          fill="none"
          stroke={hexToRgba(glowColor, 0.15)}
          strokeWidth="1"
          strokeDasharray="4 4"
          className="ring-inner-anim"
          style={{ pointerEvents: "none" }}
        />

        {/* Ring 2 (middle) */}
        <motion.circle
          cx={center}
          cy={center}
          r={orbSize * 0.30 + 6}
          fill="none"
          stroke={hexToRgba(glowColor, 0.12)}
          strokeWidth="1"
          strokeDasharray="6 6"
          className="ring-middle-anim"
          style={{ pointerEvents: "none" }}
        />

        {/* Ring 3 (outermost) with tick marks */}
        <g className="ring-outer-anim">
          {Array.from({ length: 24 }).map((_, i) => {
            const angle = (i * 360) / 24
            const tickRadius = outerRadius + 14
            const innerPoint = polarToCartesian(center, center, tickRadius - 3, angle)
            const outerPoint = polarToCartesian(center, center, tickRadius + 3, angle)
            
            return (
              <line
                key={`tick-${i}`}
                x1={innerPoint.x}
                y1={innerPoint.y}
                x2={outerPoint.x}
                y2={outerPoint.y}
                stroke={hexToRgba(glowColor, 0.2)}
                strokeWidth="1"
                style={{ pointerEvents: "none" }}
              />
            )
          })}
        </g>
      </g>

      {/* Task 5.7: Groove separator */}
      <g style={{ pointerEvents: "none" }}>
        <circle
          cx={center}
          cy={center}
          r={orbSize * 0.30}
          fill="none"
          stroke="rgba(0, 0, 0, 0.6)"
          strokeWidth="2"
        />
        <circle
          cx={center}
          cy={center}
          r={orbSize * 0.30}
          fill="none"
          stroke={hexToRgba(glowColor, 0.1)}
          strokeWidth="1"
        />
      </g>

      {/* Task 5.2: Outer ring rendering */}
      <motion.g
        animate={{ rotate: outerRotation }}
        transition={confirmSpinning ? confirmSpinConfig : springConfig}
        style={{ originX: "50%", originY: "50%" }}
      >
        {outerItems.map((item, index) => {
          const startAngle = index * outerSegmentAngle
          const endAngle = (index + 1) * outerSegmentAngle
          const isSelected = index === outerSelectedIndex
          const globalIndex = index

          return (
            <g key={item.id}>
              {/* Segment path */}
              <path
                d={generateArcPath(outerRadius, startAngle, endAngle)}
                fill="none"
                stroke={hexToRgba(glowColor, isSelected ? 0.6 : 0.3)}
                strokeWidth="28"
                style={{ 
                  cursor: "pointer",
                  pointerEvents: "auto",
                }}
                onClick={() => onSelect(globalIndex)}
                aria-label={item.label}
              />

              {/* Diamond marker at segment start */}
              {(() => {
                const markerPos = polarToCartesian(center, center, outerRadius, startAngle)
                return (
                  <g transform={`translate(${markerPos.x}, ${markerPos.y}) rotate(${startAngle})`}>
                    <polygon
                      points="0,-3 2,0 0,3 -2,0"
                      fill={hexToRgba(glowColor, 0.8)}
                      style={{ pointerEvents: "none" }}
                    />
                  </g>
                )
              })()}
            </g>
          )
        })}

        {/* Curved text labels for outer ring */}
        {outerItems.map((item, index) => {
          const startAngle = index * outerSegmentAngle
          const endAngle = (index + 1) * outerSegmentAngle
          const isSelected = index === outerSelectedIndex
          const textPathId = `outer-text-${item.id}`
          const path = generateArcPath(outerRadius, startAngle, endAngle)

          return (
            <g key={`text-${item.id}`}>
              <defs>
                <path id={textPathId} d={path} fill="none" />
              </defs>
              <text
                fill={hexToRgba(glowColor, isSelected ? 0.9 : 0.5)}
                fontSize="9"
                fontWeight="600"
                textAnchor="middle"
                style={{ pointerEvents: "none" }}
              >
                <textPath
                  href={`#${textPathId}`}
                  startOffset="50%"
                >
                  {item.label}
                </textPath>
              </text>
            </g>
          )
        })}
      </motion.g>

      {/* Task 5.3: Inner ring rendering */}
      {innerItems.length > 0 && (
        <motion.g
          animate={{ rotate: innerRotation }}
          transition={confirmSpinning ? confirmSpinConfig : springConfig}
          style={{ originX: "50%", originY: "50%" }}
        >
          {/* Task 5.3: Inner ring depth styling with drop shadows */}
          <defs>
            <filter id="inner-ring-shadow">
              <feDropShadow
                dx="0"
                dy="2"
                stdDeviation="3"
                floodColor={glowColor}
                floodOpacity="0.4"
              />
            </filter>
            <filter id="inner-ring-glow">
              <feGaussianBlur stdDeviation="2" result="blur" />
              <feFlood floodColor={glowColor} floodOpacity="0.3" />
              <feComposite in2="blur" operator="in" />
              <feMerge>
                <feMergeNode />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {innerItems.map((item, index) => {
            const startAngle = index * innerSegmentAngle
            const endAngle = (index + 1) * innerSegmentAngle
            const isSelected = index === innerSelectedIndex
            const globalIndex = splitPoint + index

            return (
              <g key={item.id}>
                {/* Segment path with depth styling */}
                <path
                  d={generateArcPath(innerRadius, startAngle, endAngle)}
                  fill="none"
                  stroke={hexToRgba(glowColor, isSelected ? 0.7 : 0.35)}
                  strokeWidth="22"
                  filter="url(#inner-ring-shadow)"
                  style={{ 
                    cursor: "pointer",
                    pointerEvents: "auto",
                  }}
                  onClick={() => onSelect(globalIndex)}
                  aria-label={item.label}
                />

                {/* Circle marker at segment start */}
                {(() => {
                  const markerPos = polarToCartesian(center, center, innerRadius, startAngle)
                  return (
                    <circle
                      cx={markerPos.x}
                      cy={markerPos.y}
                      r="2"
                      fill={hexToRgba(glowColor, 0.9)}
                      filter="url(#inner-ring-glow)"
                      style={{ pointerEvents: "none" }}
                    />
                  )
                })()}
              </g>
            )
          })}

          {/* Task 5.3: Curved text labels for inner ring (radius + 14) */}
          {innerItems.map((item, index) => {
            const startAngle = index * innerSegmentAngle
            const endAngle = (index + 1) * innerSegmentAngle
            const isSelected = index === innerSelectedIndex
            const textPathId = `inner-text-${item.id}`
            const textRadius = innerRadius + 14
            const path = generateArcPath(textRadius, startAngle, endAngle)

            return (
              <g key={`text-${item.id}`}>
                <defs>
                  <path id={textPathId} d={path} fill="none" />
                </defs>
                <text
                  fill={hexToRgba(glowColor, isSelected ? 0.9 : 0.5)}
                  fontSize="8"
                  fontWeight="600"
                  textAnchor="middle"
                  style={{ pointerEvents: "none" }}
                >
                  <textPath
                    href={`#${textPathId}`}
                    startOffset="50%"
                  >
                    {item.label}
                  </textPath>
                </text>
              </g>
            )
          })}
        </motion.g>
      )}

      {/* CSS animations for decorative rings */}
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
    </svg>
  )
}
