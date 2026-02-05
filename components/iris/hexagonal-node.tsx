"use client"

import React, { type ElementType } from "react"
import { motion } from "framer-motion"

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
  glowColor: string
  spinConfig: { staggerDelay: number; ease: readonly number[] }
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
  glowColor,
  spinConfig,
}: HexagonalNodeProps) {
  const Icon = node.icon
  const pos = getSpiralPosition(angle, radius, spinRotations)
  const counterRotation = -pos.rotation

  const spiralVariants = {
    collapsed: { x: 0, y: 0, scale: 0.5, opacity: 0, rotate: 0 },
    expanded: {
      x: pos.x,
      y: pos.y,
      scale: 1,
      opacity: 1,
      rotate: pos.rotation,
      transition: {
        duration: spinDuration / 1000,
        delay: staggerIndex * (spinConfig.staggerDelay / 1000),
        ease: spinConfig.ease as any,
      },
    },
    exit: {
      x: 0,
      y: 0,
      scale: 0.5,
      opacity: 0,
      rotate: -360,
      transition: {
        duration: spinDuration / 1000,
        delay: staggerIndex * (spinConfig.staggerDelay / 1000),
        ease: spinConfig.ease as any,
      },
    },
  }

  const contentVariants = {
    collapsed: { rotate: 0 },
    expanded: {
      rotate: counterRotation,
      transition: {
        duration: spinDuration / 1000,
        delay: staggerIndex * (spinConfig.staggerDelay / 1000),
        ease: spinConfig.ease as any,
      },
    },
    exit: {
      rotate: 360,
      transition: {
        duration: spinDuration / 1000,
        delay: staggerIndex * (spinConfig.staggerDelay / 1000),
        ease: spinConfig.ease as any,
      },
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
            background: `radial-gradient(circle, ${glowColor}33 0%, transparent 70%)`,
            filter: "blur(8px)",
          }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        />
      )}

      <div
        className="relative w-full h-full flex flex-col items-center justify-center pointer-events-auto"
        style={{
          borderRadius: "24px",
          background: "rgba(255, 255, 255, 0.06)",
          backdropFilter: "blur(12px)",
          border: "1px solid rgba(255, 255, 255, 0.08)",
        }}
      >
        <motion.div
          className="flex flex-col items-center justify-center gap-1 pointer-events-none"
          variants={contentVariants}
          initial="collapsed"
          animate={isCollapsing ? "exit" : "expanded"}
        >
          <Icon className="w-6 h-6 text-silver" strokeWidth={1.5} />
          <span className="text-[10px] font-medium tracking-wider text-muted-foreground">
            {node.label}
          </span>
        </motion.div>
      </div>
    </motion.button>
  )
}
