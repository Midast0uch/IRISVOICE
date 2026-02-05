"use client"

import React from "react"
import { motion } from "framer-motion"
import * as LucideIcons from "lucide-react"
import type { ConfirmedNode } from "@/types/navigation"

interface OrbitNodeProps {
  node: {
    id: string
    label: string
    icon: string
    orbitAngle: number
    values?: Record<string, string | number | boolean>
  }
  orbitRadius: number
  onRecall: (nodeId: string) => void
  glowColor?: string
}

export function OrbitNode({
  node,
  orbitRadius,
  onRecall,
  glowColor = "#00D4FF",
}: OrbitNodeProps) {
  // Use orbitAngle from node data (matches LiquidMetalLine positioning)
  const angleRad = (node.orbitAngle * Math.PI) / 180
  const x = Math.cos(angleRad) * orbitRadius
  const y = Math.sin(angleRad) * orbitRadius

  // Get icon component with proper typing
  const IconComponent = ((LucideIcons as unknown as Record<string, React.ComponentType<{ className?: string }>>)[node.icon]) || LucideIcons.Circle

  return (
    <motion.div
      className="absolute flex items-center justify-center pointer-events-auto cursor-pointer"
      style={{
        width: 90,
        height: 90,
        left: "50%",
        top: "50%",
        marginLeft: -45,
        marginTop: -45,
      }}
      initial={{ scale: 0, opacity: 0, x: 0, y: 0 }}
      animate={{
        scale: 1,
        opacity: 1,
        x,
        y,
      }}
      exit={{ scale: 0, opacity: 0 }}
      transition={{ type: "spring", stiffness: 100, damping: 15 }}
      onClick={() => onRecall(node.id)}
      whileHover={{ scale: 1.1 }}
      whileTap={{ scale: 0.95 }}
    >
      {/* Glow effect */}
      <motion.div
        className="absolute inset-0 rounded-2xl pointer-events-none"
        style={{
          background: `radial-gradient(circle, ${glowColor}40 0%, transparent 70%)`,
          filter: "blur(8px)",
        }}
        animate={{ opacity: [0.5, 1, 0.5] }}
        transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
      />
      
      {/* Node content */}
      <div
        className="relative w-full h-full flex flex-col items-center justify-center gap-1 rounded-2xl"
        style={{
          background: "rgba(255, 255, 255, 0.08)",
          backdropFilter: "blur(12px)",
          border: `1px solid ${glowColor}40`,
        }}
      >
        <div style={{ color: glowColor }}>
          <IconComponent className="w-5 h-5" />
        </div>
        <span className="text-[8px] font-medium tracking-wider text-white/70">
          {node.label}
        </span>
      </div>
    </motion.div>
  )
}
