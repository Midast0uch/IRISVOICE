"use client"

import { motion } from "framer-motion"

export interface OrbBadgeProps {
  isVisible: boolean
  variant: "working" | "question"
  currentStep?: number
  totalSteps?: number
  glowColor: string
}

/**
 * OrbBadge — background-task indicator on the orb (orb-only view).
 *
 * Design language (must match OrbCanvas / XurOrb, NOT the glass cards):
 *  - Particle pip: radial-gradient dot in glowColor with `lighter` blend
 *    (additive glow, like OrbCanvas particles). No flat Material chip.
 *  - Counter / "?" in the orb's monospace label font with glow textShadow.
 *  - Top-right of the 120px orb (only label-free corner: Chat=bottom,
 *    Menu=top, Voice=left at idle).
 *  - pointer-events: none — never intercepts the orb's drag/click.
 *
 * Visibility is computed by the parent (XurOrb): only when wings are closed
 * AND (task working OR pending question).
 */
export default function OrbBadge({
  isVisible,
  variant,
  currentStep,
  totalSteps,
  glowColor,
}: OrbBadgeProps) {
  if (!isVisible) return null

  const showCounter =
    variant === "working" &&
    typeof currentStep === "number" &&
    typeof totalSteps === "number" &&
    totalSteps > 0

  const label = variant === "question" ? "?" : showCounter ? `${currentStep}/${totalSteps}` : ""

  const pulseDuration = variant === "question" ? 1.4 : 0.8

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.6 }}
      animate={{
        opacity: [0.65, 1, 0.65],
        scale: [1, 1.18, 1],
      }}
      transition={{
        duration: pulseDuration,
        repeat: Infinity,
        ease: "easeInOut",
      }}
      style={{
        position: "absolute",
        top: 8,
        right: 8,
        display: "flex",
        alignItems: "center",
        gap: 4,
        pointerEvents: "none",
        zIndex: 20,
      }}
    >
      {/* Particle pip — additive glow, matches OrbCanvas particles */}
      <span
        style={{
          width: 10,
          height: 10,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${glowColor} 0%, ${glowColor}55 45%, transparent 72%)`,
          boxShadow: `0 0 10px ${glowColor}, 0 0 4px ${glowColor}`,
          mixBlendMode: "lighter",
          flexShrink: 0,
        }}
      />
      {label ? (
        <span
          style={{
            fontFamily: "'Courier New', Courier, monospace",
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: glowColor,
            textShadow: `0 0 16px ${glowColor}55, 0 0 4px ${glowColor}88`,
            lineHeight: 1,
          }}
        >
          {label}
        </span>
      ) : null}
    </motion.div>
  )
}
