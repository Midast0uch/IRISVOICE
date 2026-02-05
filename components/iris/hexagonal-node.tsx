"use client"

import React, { type ElementType } from "react"
import { motion } from "framer-motion"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { useTransitionVariants } from "@/hooks/useTransitionVariants"

type ThemeIntensity = 'subtle' | 'medium' | 'strong'

interface HexagonalNodeProps {
  node: { id: string; label: string; icon: ElementType; fields?: any[] }
  angle: number
  radius: number
  nodeSize: number
  onClick: () => void
  spinRotations: number
  spinDuration: number
  staggerIndex: number
  isCollapsing: boolean
  isActive: boolean
  spinConfig: { staggerDelay: number; ease: readonly number[] }
  themeIntensity?: ThemeIntensity
}

function getSpiralPosition(baseAngle: number, radius: number, spinRotations: number) {
  const finalAngleRad = (baseAngle * Math.PI) / 180
  return {
    x: Math.cos(finalAngleRad) * radius,
    y: Math.sin(finalAngleRad) * radius,
    rotation: spinRotations * 360,
  }
}

export function HexagonalNode({
  node,
  angle,
  radius,
  nodeSize,
  onClick,
  spinRotations,
  spinDuration,
  staggerIndex,
  isCollapsing,
  isActive,
  spinConfig,
  themeIntensity = 'medium',
}: HexagonalNodeProps) {
  const Icon = node.icon
  const pos = getSpiralPosition(angle, radius, spinRotations)
  const counterRotation = -pos.rotation
  const { brandColor, getHSLString } = useBrandColor()
  const { variants, transitionName } = useTransitionVariants()
  
  // Derive glowColor from brandColor (updates with ThemeTestSwitcher)
  const glowColor = getHSLString()

  // DEBUG: Log which transition is being used
  console.log(`[HexagonalNode:${node.id}] Transition:`, transitionName, 'Variant keys:', Object.keys(variants))

  // Theme calculations per PRD spec - increased lightness for visible background colors
  const intensity = {
    subtle: { bgSat: 0.25, bgLight: 20, glowOp: 0.15, iconMix: 0.4 },
    medium: { bgSat: 0.35, bgLight: 25, glowOp: 0.25, iconMix: 0.7 },
    strong: { bgSat: 0.5, bgLight: 30, glowOp: 0.4, iconMix: 1.0 },
  }[themeIntensity]

  const bgColor = `hsl(${brandColor.hue}, ${brandColor.saturation * intensity.bgSat}%, ${intensity.bgLight}%)`
  const iconColor = intensity.iconMix === 1
    ? glowColor
    : `color-mix(in hsl, ${glowColor} ${intensity.iconMix * 100}%, #c0c0c0)`
  const labelColor = `hsl(${brandColor.hue}, 10%, 70%)`
  const glowHex = Math.round(intensity.glowOp * 255).toString(16).padStart(2, '0')

  // Merge transition variants with position/rotation animations
  const baseTransition = {
    duration: spinDuration / 1000,
    delay: staggerIndex * (spinConfig.staggerDelay / 1000),
    ease: spinConfig.ease as any,
  }

  const spiralVariants = {
    collapsed: { 
      ...variants.hidden,
      x: 0, y: 0, 
    },
    expanded: {
      ...variants.visible,
      x: pos.x,
      y: pos.y,
      rotate: pos.rotation,
      transition: {
        ...baseTransition,
        ...(variants.visible as any)?.transition,
      },
    },
    exit: {
      ...variants.exit,
      x: 0,
      y: 0,
      transition: {
        ...baseTransition,
        ...(variants.exit as any)?.transition,
      },
    },
  }

  const contentVariants = {
    collapsed: { rotate: 0 },
    expanded: {
      rotate: counterRotation,
      transition: baseTransition,
    },
    exit: {
      rotate: 360,
      transition: baseTransition,
    },
  }

  return (
    <motion.button
      className="absolute flex flex-col items-center justify-center cursor-pointer z-10 pointer-events-auto"
      style={{
        left: "50%",
        top: "50%",
        marginLeft: -nodeSize / 2,
        marginTop: -nodeSize / 2,
        width: nodeSize,
        height: nodeSize,
      }}
      variants={spiralVariants}
      initial="collapsed"
      animate={isCollapsing ? "exit" : "expanded"}
      exit="exit"
      onClick={onClick}
      whileHover={{ scale: 1.05 }}
      whileTap={{ scale: 0.95 }}
    >
      {/* Ambient glow - NEW per PRD */}
      <div 
        className="absolute -inset-2 rounded-2xl -z-10 pointer-events-none"
        style={{
          background: `radial-gradient(circle, ${glowColor}${glowHex} 0%, transparent 70%)`,
          filter: "blur(8px)",
        }}
      />

      <motion.div
        className="absolute -inset-0.5 pointer-events-none"
        style={{
          borderRadius: "24px",
          padding: "2px",
          background: `conic-gradient(from 0deg, transparent 0deg, ${glowColor}1a 60deg, ${isActive ? glowColor : `${glowColor}e6`} 180deg, ${glowColor}1a 300deg, transparent 360deg)`,
          WebkitMask: "linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)",
          WebkitMaskComposite: "xor",
        }}
        animate={{ rotate: 360 }}
        transition={{ duration: 8, repeat: Infinity, ease: "linear" }}
      />

      {isActive && (
        <motion.div
          className="absolute -inset-2 pointer-events-none"
          style={{
            borderRadius: "28px",
            background: `radial-gradient(circle, ${glowColor}40 0%, transparent 60%)`,
            filter: "blur(12px)",
          }}
          animate={{ opacity: [0.5, 1, 0.5] }}
          transition={{ duration: 2, repeat: Infinity }}
        />
      )}

      <div
        className="relative w-full h-full flex flex-col items-center justify-center pointer-events-auto"
        style={{
          borderRadius: "24px",
          background: bgColor,
          backdropFilter: "blur(12px)",
          border: `1px solid ${isActive ? glowColor : 'rgba(255, 255, 255, 0.08)'}`,
          // High opacity dark inner shadow with theme color
          boxShadow: `inset 0 0 20px ${glowColor}40, inset 0 0 40px ${glowColor}20`,
        }}
      >
        <motion.div
          className="flex flex-col items-center justify-center gap-1 pointer-events-none"
          variants={contentVariants}
          initial="collapsed"
          animate={isCollapsing ? "exit" : "expanded"}
        >
          <Icon 
            className="w-6 h-6" 
            style={{ color: iconColor }} 
            strokeWidth={1.5} 
          />
          <span 
            className="text-[10px] font-medium tracking-wider"
            style={{ color: labelColor }}
          >
            {node.label}
          </span>
        </motion.div>
      </div>
    </motion.button>
  )
}
