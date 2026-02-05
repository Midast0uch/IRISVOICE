"use client"

import React from "react"
import { motion } from "framer-motion"

interface VoiceActivityOverlayProps {
  state: "idle" | "listening" | "processing" | "speaking" | "error"
  glowColor: string
}

export function VoiceActivityOverlay({ state, glowColor }: VoiceActivityOverlayProps) {
  if (state === "idle") return null

  const stateLabel =
    state === "listening"
      ? "Listening..."
      : state === "processing"
        ? "Thinking..."
        : state === "speaking"
          ? "Speaking..."
          : "Error"

  return (
    <div className="absolute left-1/2 top-1/2 flex flex-col items-center gap-4 pointer-events-none" style={{ marginTop: 120 }}>
      <div className="flex items-end gap-1">
        {Array.from({ length: 12 }).map((_, idx) => (
          <motion.div
            key={idx}
            className="w-1.5 rounded-full"
            style={{ backgroundColor: glowColor, height: 10 }}
            animate={{ scaleY: [0.6, 1.8, 0.8] }}
            transition={{ duration: 0.8, repeat: Infinity, delay: idx * 0.05, ease: "easeInOut" }}
          />
        ))}
      </div>
      <div className="text-xs uppercase tracking-[0.3em] text-white/70">{stateLabel}</div>
      <div className="text-xs text-white/50">Transcript preview will appear here.</div>
    </div>
  )
}
