"use client"

import React, { type ElementType } from "react"
import { motion } from "framer-motion"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { useTransitionVariants } from "@/hooks/useTransitionVariants"
import { useReducedMotion } from "@/hooks/useReducedMotion"

type ThemeIntensity = 'subtle' | 'medium' | 'strong'

interface PrismNodeProps {
  node: { id: string; label: string; icon: ElementType; fields?: any[] }
  angle: number
  radius: number
  nodeSize: number
  onClick: (e?: React.MouseEvent) => void
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

export function PrismNode({
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
}: PrismNodeProps) {
  const Icon = node.icon
  const pos = getSpiralPosition(angle, radius, spinRotations)
  const counterRotation = -pos.rotation
  const { getThemeConfig } = useBrandColor()
  const { variants } = useTransitionVariants()
  const prefersReducedMotion = useReducedMotion()
  
  // Get complete theme configuration
  const theme = getThemeConfig()

  // Check if theme should have clean look (no rotating effects)
  const isCleanTheme = theme.name === 'Verdant' || theme.name === 'Aurum'

  // Icon color: always white for maximum contrast across all themes
  const iconColor = 'rgba(255, 255, 255, 0.95)'

  // Intensity adjustments for glass effect
  const intensityMultipliers = {
    subtle: { glassOpacity: 0.7, glowOpacity: 0.6, shimmerOpacity: 0.5 },
    medium: { glassOpacity: 1.0, glowOpacity: 1.0, shimmerOpacity: 1.0 },
    strong: { glassOpacity: 1.3, glowOpacity: 1.4, shimmerOpacity: 1.2 },
  }[themeIntensity]

  // Merge transition variants with position/rotation animations
  const baseTransition = {
    duration: prefersReducedMotion ? 0 : spinDuration / 1000,
    delay: prefersReducedMotion ? 0 : staggerIndex * (spinConfig.staggerDelay / 1000),
    ease: spinConfig.ease as any,
  }

  const spiralVariants = {
    collapsed: { 
      ...variants.hidden,
      x: 0, y: 0, 
    },
    expanded: {
      ...variants.visible,
      x: prefersReducedMotion ? pos.x : pos.x,
      y: prefersReducedMotion ? pos.y : pos.y,
      rotate: prefersReducedMotion ? 0 : pos.rotation,
      transition: {
        ...baseTransition,
        ...(variants.visible as any)?.transition,
      },
    },
    exit: {
      ...variants.exit,
      x: 0,
      y: 0,
      rotate: prefersReducedMotion ? 0 : undefined,
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

  // Calculate adjusted values based on intensity
  const glassOpacity = Math.min(theme.glass.opacity * intensityMultipliers.glassOpacity, 0.35)
  const glowOpacity = Math.min(theme.glow.opacity * intensityMultipliers.glowOpacity * 1.5, 0.75)
  const shimmerOpacity = Math.min(1 * intensityMultipliers.shimmerOpacity, 1)

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
      onClick={(e) => {
        e.stopPropagation()
        onClick(e)
      }}
      onMouseDown={(e) => e.stopPropagation()}
      onPointerDown={(e) => e.stopPropagation()}
      whileHover={{ scale: 1.05 }}
      whileTap={{ scale: 0.95 }}
    >
      {/* 1. Outer glow - soft radial gradient */}
      <div 
        className="absolute -inset-4 rounded-[2.5rem] pointer-events-none"
        style={{
          background: `radial-gradient(circle, ${theme.glow.color}${Math.round(glowOpacity * 255).toString(16).padStart(2, '0')} 0%, transparent 70%)`,
          filter: `blur(${theme.glow.blur * 1.5}px)`,
          opacity: isActive ? 1 : 0.6,
        }}
      />

      {/* 2. Active state additional glow */}
      {isActive && (
        <motion.div
          className="absolute -inset-3 rounded-[2.5rem] pointer-events-none"
          style={{
            background: `radial-gradient(circle, ${theme.shimmer.primary}50 0%, transparent 60%)`,
            filter: "blur(16px)",
          }}
          animate={{ opacity: [0.4, 0.8, 0.4] }}
          transition={{ duration: 2, repeat: Infinity }}
        />
      )}

      {/* 3. Main glass card container */}
      <div
        className="relative w-full h-full flex flex-col items-center justify-center overflow-hidden"
        style={{
          borderRadius: "2.5rem",
          background: `linear-gradient(${theme.gradient.angle}deg, ${theme.gradient.from}${Math.round(glassOpacity * 255).toString(16).padStart(2, '0')}, ${theme.gradient.to}${Math.round(glassOpacity * 255).toString(16).padStart(2, '0')})`,
          backdropFilter: `blur(${theme.glass.blur}px)`,
          border: `1px solid rgba(255,255,255,${theme.glass.borderOpacity})`,
          boxShadow: `inset 0 1px 1px rgba(255,255,255,0.1), 0 4px 24px rgba(0,0,0,0.2)`,
        }}
      >
        {/* 6. Gradient overlay for depth */}
        <div 
          className="absolute inset-0 rounded-[2.5rem] pointer-events-none"
          style={{
            background: `linear-gradient(135deg, ${theme.gradient.from}30 0%, transparent 50%, ${theme.gradient.to}15 100%)`,
          }}
        />

        {/* 7. Floating orbs (conditional - NOT for clean themes) */}
        {theme.orbs && theme.orbs.map((orb, i) => (
          <motion.div
            key={i}
            className="absolute rounded-full pointer-events-none"
            style={{
              width: orb.size * (isActive ? 1.2 : 1),
              height: orb.size * (isActive ? 1.2 : 1),
              left: `calc(50% + ${orb.x}px)`,
              top: `calc(50% + ${orb.y}px)`,
              marginLeft: -orb.size / 2,
              marginTop: -orb.size / 2,
              background: orb.color,
              filter: `blur(${orb.blur}px)`,
              opacity: 0.5 * intensityMultipliers.glowOpacity,
            }}
            animate={{
              x: [0, 15, -10, 0],
              y: [0, -12, 8, 0],
              scale: [1, 1.15, 0.95, 1],
            }}
            transition={{ 
              duration: 8 + i * 2, 
              repeat: Infinity, 
              ease: "easeInOut",
              delay: i * 0.5
            }}
          />
        ))}

        {/* 7. Verdant liquid glass effect - DISABLED, using liquid metal border instead */}
        {/* {!theme.orbs && (
          <motion.div
            className="absolute inset-0 rounded-[2.5rem] pointer-events-none"
            style={{
              background: `linear-gradient(90deg, transparent 0%, ${theme.shimmer.primary}10 50%, transparent 100%)`,
            }}
            animate={{
              x: ["-100%", "100%"],
            }}
            transition={{
              duration: 6,
              repeat: Infinity,
              ease: "easeInOut",
            }}
          />
        )} */}

        {/* 8. Content: Icon + Label */}
        <motion.div
          className="relative z-10 flex flex-col items-center justify-center gap-2 pointer-events-none"
          variants={contentVariants}
          initial="collapsed"
          animate={isCollapsing ? "exit" : "expanded"}
        >
          <Icon 
            className="w-6 h-6" 
            style={{ 
              color: '#ffffff',
              filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.7))'
            }} 
            strokeWidth={1.5}
          />
          <span 
            className="text-[10px] font-semibold tracking-wider uppercase"
            style={{ 
              color: '#ffffff',
              textShadow: '0 1px 2px rgba(0,0,0,0.7), 0 0 2px rgba(0,0,0,0.5)',
              letterSpacing: '0.1em'
            }}
          >
            {node.label}
          </span>
        </motion.div>
      </div>
    </motion.button>
  )
}

// Backwards compatibility alias
export const HexagonalNode = PrismNode
