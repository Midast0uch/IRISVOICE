"use client"

import React, { useState, useEffect, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ChevronDown, Sparkles, Activity } from "lucide-react"
import { Xur } from "@/components/Xur"
import { TaskCardProps } from "../TaskListCard.v2"

/**
 * VARIANT 2: ACOUSTIC WAVEFORM (Voice & Soundwave Resonance)
 * Unique Concept:
 * - Dynamic voice-frequency rail with subtle waveform ripple.
 * - Soft pill geometry with rich harmonic gradient.
 * - Audio-stream telemetry suited for a voice assistant.
 */
export function VariantBioluminescent({
  objective,
  steps = [],
  isThinking = false,
  currentThought = "",
  thoughtHistory = "",
  isCrystallized = false,
  memoryEvents = [],
}: TaskCardProps) {
  const [isCollapsed, setIsCollapsed] = useState(false)
  const [showThoughtTrace, setShowThoughtTrace] = useState(false)

  const doneCount = steps.filter((s) => s.status === "done" || s.status === "crystallized").length
  const totalCount = steps.length
  const isWorking = isThinking || steps.some((s) => s.status === "running")

  // Footnote timer
  const [elapsed, setElapsed] = useState(0)
  const startRef = useRef<number | null>(null)
  useEffect(() => {
    if (!isWorking) { startRef.current = null; return }
    if (!startRef.current) startRef.current = Date.now()
    const t0 = startRef.current
    const iv = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000)
    return () => clearInterval(iv)
  }, [isWorking])
  const timerLabel = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}`

  const latestMemory = memoryEvents[memoryEvents.length - 1]
  const accentColor = 
    isCrystallized || latestMemory?.direction === "crystallize" ? "#22c55e" :
    latestMemory?.direction === "retrieve" ? "#38bdf8" :
    isThinking ? "#fbbf24" : "#00d4ff"

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.2 }}
      className="my-2 w-full select-none"
    >
      <div
        className="relative rounded-xl overflow-hidden p-3 transition-all duration-300"
        style={{
          background: "linear-gradient(135deg, rgba(12, 22, 38, 0.95) 0%, rgba(8, 12, 22, 0.98) 45%, rgba(18, 14, 30, 0.92) 100%)",
          border: "1px solid rgba(56, 189, 248, 0.15)",
          borderLeft: `3px solid ${accentColor}`,
          boxShadow: `0 8px 28px rgba(0, 0, 0, 0.55), 0 0 16px ${accentColor}15, inset 0 1px 0 rgba(255, 255, 255, 0.08)`,
        }}
      >
        {/* Top acoustic waveform shimmer */}
        <div
          className="absolute top-0 left-0 right-0 h-[1.5px] pointer-events-none"
          style={{
            background: `linear-gradient(90deg, transparent, ${accentColor}80 30%, ${accentColor}20 80%, transparent)`,
          }}
        />

        {/* Header */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <Xur size={15} color={accentColor} speed={isWorking ? 1.8 : 0.8} />
            <div className="flex items-center gap-1.5 min-w-0 flex-1">
              <span className="text-[12px] font-semibold text-white/95 truncate tracking-tight">
                {objective}
              </span>
              {isCrystallized && (
                <span className="text-[8px] font-mono text-emerald-400 bg-emerald-950/50 border border-emerald-500/30 px-1.5 py-0.2 rounded-full flex items-center gap-0.5 shrink-0">
                  <Sparkles size={8} /> crystallized
                </span>
              )}
            </div>
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            {totalCount > 0 && (
              <span className="text-[9.5px] font-mono text-cyan-300/80 bg-cyan-950/30 px-1.5 py-0.5 rounded-full border border-cyan-500/20 tabular-nums">
                {doneCount}/{totalCount}
              </span>
            )}
            <button
              onClick={() => setIsCollapsed(!isCollapsed)}
              className="p-0.5 rounded text-white/30 hover:text-white/80 transition-colors"
            >
              <ChevronDown
                size={11}
                style={{
                  transform: isCollapsed ? "rotate(-90deg)" : "rotate(0deg)",
                  transition: "transform 0.16s ease",
                }}
              />
            </button>
          </div>
        </div>

        {/* Live Acoustic Thought Stream */}
        {(isThinking || currentThought || thoughtHistory) && (
          <div className="mt-2 pt-1.5 border-t border-white/6 flex items-center justify-between gap-2 text-[10px] font-mono min-w-0">
            <div className="flex items-center gap-1.5 text-amber-300/90 min-w-0 flex-1 truncate">
              <Activity size={10} className="text-amber-400 shrink-0 animate-pulse" />
              <span className="truncate italic">{currentThought || "Synthesizing voice harmonic trajectory..."}</span>
            </div>
            {thoughtHistory && (
              <button
                onClick={() => setShowThoughtTrace(!showThoughtTrace)}
                className="text-[8.5px] text-white/40 hover:text-white/80 shrink-0 px-1 py-0.2 rounded bg-white/5"
              >
                {showThoughtTrace ? "hide" : "trace"}
              </button>
            )}
          </div>
        )}

        {/* Thought trace */}
        <AnimatePresence>
          {showThoughtTrace && thoughtHistory && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="mt-1.5 p-2 rounded bg-black/40 text-[9px] font-mono text-white/70 leading-relaxed max-h-28 overflow-y-auto whitespace-pre-wrap"
            >
              {thoughtHistory}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Step Nodes (Harmonic Soundwave Dots) */}
        <AnimatePresence initial={false}>
          {!isCollapsed && steps.length > 0 && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="mt-2 space-y-1"
            >
              {steps.map((step, idx) => (
                <div key={step.id || idx} className={`flex items-center gap-2 p-0.5 ${step.branchLabel ? "pl-3.5" : ""}`}>
                  <div className="w-3 h-3 shrink-0 flex items-center justify-center">
                    {step.status === "running" ? (
                      <div className="w-3 h-3 rounded-full flex items-center justify-center bg-black border border-amber-400 shadow-[0_0_6px_rgba(251,191,36,0.6)]">
                        <Xur size={7} color="#fbbf24" speed={2.0} />
                      </div>
                    ) : step.status === "crystallized" ? (
                      <div className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(34,197,94,0.7)]" />
                    ) : step.status === "done" ? (
                      <div className="w-1.5 h-1.5 rounded-full bg-cyan-400 shadow-[0_0_4px_rgba(0,212,255,0.6)]" />
                    ) : (
                      <div className="w-1.5 h-1.5 rounded-full bg-white/20" />
                    )}
                  </div>

                  <span className="text-[9.5px] font-mono font-medium text-cyan-300 shrink-0">
                    {step.verb}
                  </span>
                  {step.branchLabel && (
                    <span className="text-[8px] font-mono text-pink-300/80 bg-pink-950/40 px-1.5 py-0.2 rounded-full border border-pink-500/20 shrink-0">
                      ↳ ({step.branchLabel})
                    </span>
                  )}
                  <span className="text-[10.5px] truncate text-white/85 flex-1 min-w-0">
                    {step.target}
                  </span>
                  {step.summary && (
                    <span className="text-[9px] font-mono text-white/35 truncate max-w-[170px] shrink-0">
                      · {step.summary}
                    </span>
                  )}
                </div>
              ))}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Footnote */}
        <div className="mt-2.5 pt-1.5 border-t border-white/6 flex items-center justify-between text-[9px] font-mono text-white/45 min-w-0">
          <span className="flex items-center gap-1.5 truncate min-w-0 flex-1">
            <span className="text-cyan-300/80">∿ voice-mem:</span>
            <span className="truncate">{latestMemory?.detail || "Audio memory stream synced"}</span>
          </span>

          <div className="flex items-center gap-2 shrink-0 ml-2">
            {isWorking && (
              <span className="text-[9px] font-mono text-amber-300/90 tabular-nums bg-amber-950/40 border border-amber-500/25 px-1.5 py-0.2 rounded">
                ⏱ {timerLabel}
              </span>
            )}
            <span className="text-[8px] uppercase tracking-wider text-white/25">
              data/memory.db
            </span>
          </div>
        </div>
      </div>
    </motion.div>
  )
}
