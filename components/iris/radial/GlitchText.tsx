"use client"

import React, { useEffect, useRef, useState, useCallback } from "react"

const CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789→↑←"

interface GlitchTextProps {
  text: string
  visible: boolean
  color: string
  fontSize?: number
  className?: string
}

/**
 * GlitchText — scramble animation label for the XurOrb.
 *
 * Renders uppercase monospace text with a glow text-shadow. On mount
 * (and whenever `text` changes) the characters scramble from random
 * glyphs to their final value, matching the aesthetic from
 * PrototypeOrbShellsRotating's label animation.
 *
 * Used for MENU / VOICE / CHAT labels around the orb. These are
 * ALWAYS visible at level 1 idle and disappear when navigating
 * to level 2+ or when chat-wings open (controlled by `visible`).
 */
export function GlitchText({
  text,
  visible,
  color,
  fontSize = 11,
  className,
}: GlitchTextProps) {
  const [displayText, setDisplayText] = useState(text)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const scramble = useCallback((finalText: string) => {
    const len = finalText.length
    if (len === 0) {
      setDisplayText("")
      return
    }
    let frame = 0
    const totalFrames = 24

    if (timerRef.current) clearInterval(timerRef.current)

    const timer = setInterval(() => {
      frame++
      let out = ""
      for (let i = 0; i < len; i++) {
        if (frame / totalFrames > i / len) {
          out += finalText[i]
        } else {
          out += CHARS[Math.floor(Math.random() * CHARS.length)]
        }
      }
      setDisplayText(out)
      if (frame >= totalFrames) {
        clearInterval(timer)
        setDisplayText(finalText)
      }
    }, 30)
    timerRef.current = timer
  }, [])

  useEffect(() => {
    scramble(text)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [text, scramble])

  return (
    <span
      className={className}
      style={{
        display: "block",
        fontSize: `${fontSize}px`,
        fontWeight: 700,
        letterSpacing: "0.12em",
        textTransform: "uppercase" as const,
        color,
        textShadow: `0 0 16px ${color}55, 0 0 4px ${color}88`,
        whiteSpace: "nowrap",
        fontFamily: "'Courier New', Courier, monospace",
        opacity: visible ? 1 : 0,
        transition: "opacity 0.3s ease",
        pointerEvents: "auto",
        cursor: "pointer",
        userSelect: "none",
      }}
    >
      {displayText}
    </span>
  )
}
