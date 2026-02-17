"use client"

import { motion, AnimatePresence } from "framer-motion"
import { useState } from "react"
import { useBrandColor } from "@/contexts/BrandColorContext"

interface IrisOrbThemedProps {
  isExpanded: boolean
  onClick: () => void
  centerLabel: string
  size: number
  glowColor: string
}

export function IrisOrbThemed({ isExpanded, onClick, centerLabel, size, glowColor }: IrisOrbThemedProps) {
  const [isWaking, setIsWaking] = useState(false)
  const { theme } = useBrandColor()

  // Theme-specific personality per PRD Phase 4
  const themeConfig = {
    aether: { outerDuration: 5, innerDuration: 3, layerCount: 2, shimmerDuration: 10 },
    ember: { outerDuration: 4, innerDuration: 2.5, layerCount: 3, shimmerDuration: 8 },
    aurum: { outerDuration: 6, innerDuration: 4, layerCount: 1, shimmerDuration: 12 },
    verdant: { outerDuration: 5, innerDuration: 3, layerCount: 2, shimmerDuration: 10 },
    nebula: { outerDuration: 4, innerDuration: 2.5, layerCount: 3, shimmerDuration: 8 },
    crimson: { outerDuration: 4, innerDuration: 2, layerCount: 2, shimmerDuration: 6 },
  }[theme]

  return (
    <motion.div
      className="relative flex items-center justify-center rounded-full cursor-grab active:cursor-grabbing z-50 pointer-events-auto"
      style={{ width: size, height: size }}
      onMouseDown={(e) => {
        // Handle drag logic here or pass through
        onClick()
      }}
    >
      {/* Extra layer for ember theme (layerCount: 3) */}
      {themeConfig.layerCount > 2 && (
        <motion.div
          className="absolute rounded-full pointer-events-none"
          style={{
            inset: -40,
            background: `radial-gradient(circle, ${glowColor}40 0%, transparent 60%)`,
            filter: "blur(20px)",
          }}
          animate={{ scale: [1, 1.3, 1], opacity: [0.4, 0.7, 0.4] }}
          transition={{ duration: themeConfig.outerDuration * 0.8, repeat: Infinity, ease: "easeInOut" }}
        />
      )}

      {/* Outer breathe glow - theme-specific duration */}
      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{
          inset: -60,
          background: `radial-gradient(circle, ${glowColor}80 0%, ${glowColor}40 30%, transparent 70%)`,
          filter: "blur(30px)",
        }}
        animate={{ scale: [1, 1.6, 1], opacity: [0.6, 1, 0.6] }}
        transition={{ duration: themeConfig.outerDuration, repeat: Infinity, ease: "easeInOut" }}
      />

      {/* Inner core pulse - theme-specific duration */}
      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{
          inset: -8,
          background: `radial-gradient(circle, ${glowColor}cc 0%, ${glowColor}60 30%, ${glowColor}20 60%, transparent 80%)`,
          filter: "blur(8px)",
        }}
        animate={{ scale: [0.8, 1.4, 0.8], opacity: [0.7, 1, 0.7] }}
        transition={{ duration: themeConfig.innerDuration, repeat: Infinity, ease: "easeInOut" }}
      />

      {/* Wake flash */}
      <AnimatePresence>
        {isWaking && centerLabel !== "IRIS" && (
          <motion.div
            className="absolute rounded-full pointer-events-none"
            style={{ inset: -20, backgroundColor: `${glowColor}99` }}
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1.5 }}
            exit={{ opacity: 0, scale: 2 }}
            transition={{ duration: 0.3 }}
          />
        )}
      </AnimatePresence>

      {/* Rotating shimmer - theme-specific duration */}
      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{
          inset: -3,
          borderRadius: "50%",
          padding: "3px",
          background: `conic-gradient(from 0deg, transparent 0deg, ${glowColor}4d 90deg, ${glowColor}cc 180deg, ${glowColor}4d 270deg, transparent 360deg)`,
          WebkitMask: "linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)",
          WebkitMaskComposite: "xor",
        }}
        animate={{ rotate: 360 }}
        transition={{ duration: themeConfig.shimmerDuration, repeat: Infinity, ease: "linear" }}
      />

      {/* Orb body */}
      <div
        className="relative w-full h-full flex items-center justify-center rounded-full pointer-events-none"
        style={{
          background: "rgba(255, 255, 255, 0.05)",
          backdropFilter: "blur(20px)",
          border: "1px solid rgba(255, 255, 255, 0.1)",
        }}
      >
        <div
          className="absolute inset-0 rounded-full pointer-events-none"
          style={{ background: `radial-gradient(circle at 30% 30%, ${glowColor}14, transparent 70%)` }}
        />

        <AnimatePresence mode="wait">
          <motion.span
            key={centerLabel}
            className="text-lg font-light tracking-[0.2em] select-none pointer-events-none"
            style={{ color: "rgba(255, 255, 255, 0.95)" }}
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0, opacity: 0 }}
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
          >
            <motion.span
              animate={{ textShadow: [`0 0 10px ${glowColor}4d`, `0 0 20px ${glowColor}99`, `0 0 10px ${glowColor}4d`] }}
              transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
            >
              {centerLabel}
            </motion.span>
          </motion.span>
        </AnimatePresence>
      </div>
    </motion.div>
  )
}
