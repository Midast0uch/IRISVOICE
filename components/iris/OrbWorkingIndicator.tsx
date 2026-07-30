"use client"

import { motion, AnimatePresence } from "framer-motion"
import { useReducedMotion } from "@/hooks/useReducedMotion"

export interface OrbWorkingIndicatorProps {
  isActive: boolean
  variant: "working" | "question"
  glowColor: string
  shimmerPrimary?: string
}

const ORBIT_RADIUS = 55 // px from orb center — just outside the 120px shell edge (60px radius)
const PARTICLE_COUNT = 5
const PARTICLE_SIZE = 5 // px

/**
 * Compose a colour with an alpha channel as VALID CSS.
 *
 * This replaces string concatenation of the form `${activeColor}55`, which only
 * yields legal CSS when the colour happens to be a 6-digit hex. Callers pass
 * hsl() — `shimmerPrimary="hsl(190, 100%, 60%)"` — and
 * `"hsl(190, 100%, 60%)55"` is syntactically invalid, so the browser discards
 * the ENTIRE declaration rather than just the alpha. On the particle background
 * that meant no gradient at all: invisible particles in real browsers, not only
 * in jsdom. Alpha values below preserve the previous hex behaviour (0x55 ≈ 0.33,
 * 0x40 ≈ 0.25, 0x30 ≈ 0.19, 0x20 ≈ 0.13).
 */
function withAlpha(color: string, alpha: number): string {
  const a = Math.max(0, Math.min(1, alpha))
  const c = (color || "").trim()
  // #rgb / #rrggbb -> 8-digit hex
  if (/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(c)) {
    const body =
      c.length === 4
        ? c.slice(1).split("").map((ch) => ch + ch).join("")
        : c.slice(1)
    return `#${body}${Math.round(a * 255).toString(16).padStart(2, "0")}`
  }
  // rgb()/hsl() (and their -a forms) -> rgba()/hsla()
  const fn = c.match(/^(rgb|hsl)a?\(([^)]*)\)$/i)
  if (fn) {
    const parts = fn[2]
      .split(/[,/]/)
      .map((p) => p.trim())
      .filter(Boolean)
      .slice(0, 3)
    return `${fn[1].toLowerCase()}a(${parts.join(", ")}, ${a})`
  }
  // Named colour or unrecognised form: return it unchanged. Losing the alpha is
  // a cosmetic regression; emitting invalid CSS drops the whole declaration.
  return c
}

// Each particle has a different orbital speed + starting angle for a dynamic, non-mechanical feel
const PARTICLE_CONFIGS = [
  { duration: 2.5, startAngle: 0, delay: 0 },
  { duration: 3.0, startAngle: 72, delay: 0.1 },
  { duration: 3.5, startAngle: 144, delay: 0.2 },
  { duration: 4.0, startAngle: 216, delay: 0.15 },
  { duration: 4.5, startAngle: 288, delay: 0.05 },
]

/**
 * OrbWorkingIndicator — orbiting particle ring shown while the agent is
 * thinking/executing tools. Replaces the old flat CSS border ring (XurOrb
 * lines 468-498) which clashed with the orb's particle aesthetic.
 *
 * Design language (matches OrbCanvas / OrbBadge, NOT the glass cards):
 *  - Particles: radial-gradient dots in glowColor with `lighter` blend
 *    (additive glow, like OrbCanvas particles). No flat Material border.
 *  - Orbit the orb at radius 55px (just outside the 120px shell edge).
 *  - No text label — OrbBadge already shows the step counter / "?" glyph.
 *  - pointer-events: none — never intercepts the orb's drag/click.
 */
export function OrbWorkingIndicator({
  isActive,
  variant,
  glowColor,
  shimmerPrimary,
}: OrbWorkingIndicatorProps) {
  const prefersReducedMotion = useReducedMotion()
  const activeColor = shimmerPrimary || glowColor

  // Question variant: slower, unified pulse
  const orbitDurationMultiplier = variant === "question" ? 1.8 : 1.0
  const pulseDuration = variant === "question" ? 1.4 : 0.8

  return (
    <AnimatePresence>
      {isActive && (
        <motion.div
          initial={{ opacity: 0, scale: 0.5 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.5 }}
          transition={{ duration: 0.3, ease: "easeOut" }}
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            pointerEvents: "none",
            zIndex: 15,
          }}
        >
          {prefersReducedMotion ? (
            // Reduced motion: static glow ring (no orbit)
            <div
              style={{
                position: "absolute",
                width: ORBIT_RADIUS * 2,
                height: ORBIT_RADIUS * 2,
                borderRadius: "50%",
                border: `1px solid ${withAlpha(activeColor, 0.25)}`,
                boxShadow: `0 0 12px ${withAlpha(activeColor, 0.19)}, inset 0 0 8px ${withAlpha(activeColor, 0.13)}`,
              }}
            />
          ) : (
            // Orbiting particles — each motion.div rotates around orb center
            PARTICLE_CONFIGS.map((cfg, i) => (
              <motion.div
                key={i}
                style={{
                  position: "absolute",
                  left: "50%",
                  top: "50%",
                  width: 0,
                  height: 0,
                  transformOrigin: "center center",
                }}
                animate={{ rotate: 360 }}
                transition={{
                  duration: cfg.duration * orbitDurationMultiplier,
                  repeat: Infinity,
                  ease: "linear",
                  delay: cfg.delay,
                }}
              >
                <div
                  style={{
                    position: "absolute",
                    left: ORBIT_RADIUS - PARTICLE_SIZE / 2,
                    top: -PARTICLE_SIZE / 2,
                    width: PARTICLE_SIZE,
                    height: PARTICLE_SIZE,
                    borderRadius: "50%",
                    background: `radial-gradient(circle, ${activeColor} 0%, ${withAlpha(activeColor, 0.33)} 45%, transparent 72%)`,
                    boxShadow: `0 0 8px ${activeColor}, 0 0 3px ${activeColor}`,
                    mixBlendMode: "lighter",
                    transform: `rotate(${cfg.startAngle}deg)`,
                    transformOrigin: `${-ORBIT_RADIUS + PARTICLE_SIZE / 2}px center`,
                    opacity: 0.7,
                  }}
                />
              </motion.div>
            ))
          )}
        </motion.div>
      )}
    </AnimatePresence>
  )
}
