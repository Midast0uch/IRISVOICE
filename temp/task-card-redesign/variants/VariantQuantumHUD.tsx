"use client"

import React, { useState, useEffect, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ChevronDown, Sparkles, GitBranch, GitCommit } from "lucide-react"
import { Xur } from "@/components/Xur"
import { TaskCardProps } from "../TaskListCard.v2"

/**
 * VARIANT 3: SYNAPTIC GIT-GRAPH (Neural Cortex & Branch Stems)
 * Unique Concept:
 * - Visual git-branch graph semantics (* | |\ |/) for parallel steps.
 * - Angular chamfered precision frame.
 * - Monospace developer telemetry.
 */
export function VariantQuantumHUD({
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
        className="relative rounded-sm overflow-hidden p-3 transition-all duration-300"
        style={{
          background: "linear-gradient(155deg, rgba(16, 20, 32, 0.97) 0%, rgba(10, 12, 20, 0.98) 50%, rgba(6, 8, 14, 0.96) 100%)",
          border: "1px solid rgba(255, 255, 255, 0.1)",
          borderLeft: `2px solid ${accentColor}`,
          boxShadow: "0 6px 22px rgba(0, 0, 0, 0.6), inset 0 1px 0 rgba(255, 255, 255, 0.05)",
        }}
      >
        {/* Top-right subtle angled accent line */}
        <div
          className="absolute top-0 right-0 w-16 h-[1.5px] pointer-events-none"
          style={{ background: `linear-gradient(90deg, transparent, ${accentColor})` }}
        />

        {/* Header */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <Xur size={14} color={accentColor} speed={isWorking ? 1.8 : 0.8} />
            <div className="flex items-center gap-1.5 min-w-0 flex-1">
              <span className="text-[11.5px] font-mono font-semibold text-white/95 truncate tracking-tight flex items-center gap-1">
                <GitBranch size={11} className="text-cyan-400 shrink-0" />
                {objective}
              </span>
              {isCrystallized && (
                <span className="text-[7.5px] font-mono uppercase text-emerald-400 bg-emerald-950/60 border border-emerald-500/30 px-1 py-0.2 rounded shrink-0">
                  ✦ crystallized
                </span>
              )}
            </div>
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            {totalCount > 0 && (
              <span className="text-[9px] font-mono text-white/40 tabular-nums">
                [{doneCount}/{totalCount}]
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

        {/* Thinking stream */}
        {(isThinking || currentThought || thoughtHistory) && (
          <div className="mt-2 pt-1.5 border-t border-white/6 flex items-center justify-between gap-2 text-[9.5px] font-mono min-w-0">
            <div className="flex items-center gap-1.5 text-amber-300/90 min-w-0 flex-1 truncate">
              <span className="text-[9px] text-amber-400 font-bold shrink-0">~ think:</span>
              <span className="truncate">{currentThought || "Tracing branch trajectory..."}</span>
            </div>
            {thoughtHistory && (
              <button
                onClick={() => setShowThoughtTrace(!showThoughtTrace)}
                className="text-[8px] text-white/40 hover:text-white/80 shrink-0 px-1 py-0.2 rounded bg-white/5"
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
              className="mt-1.5 p-2 rounded bg-black/50 text-[8.5px] font-mono text-white/70 leading-relaxed max-h-28 overflow-y-auto whitespace-pre-wrap"
            >
              {thoughtHistory}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Step Nodes (Git-Graph Branch Node Flow) */}
        <AnimatePresence initial={false}>
          {!isCollapsed && steps.length > 0 && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="mt-2 space-y-1 font-mono"
            >
              {steps.map((step, idx) => (
                <div key={step.id || idx} className={`flex items-center gap-2 p-0.5 ${step.branchLabel ? "pl-3" : ""}`}>
                  {/* Git commit dot icon */}
                  <div className="w-2.5 h-2.5 shrink-0 flex items-center justify-center">
                    {step.status === "running" ? (
                      <span className="text-amber-400 text-[11px] font-bold animate-pulse">*</span>
                    ) : step.status === "crystallized" ? (
                      <span className="text-emerald-400 text-[11px] font-bold">✦</span>
                    ) : step.status === "done" ? (
                      <span className="text-cyan-400 text-[11px] font-bold">*</span>
                    ) : (
                      <span className="text-white/30 text-[10px]">o</span>
                    )}
                  </div>

                  <span className="text-[9px] uppercase font-bold text-cyan-300/90 shrink-0">
                    {step.verb}
                  </span>
                  {step.branchLabel && (
                    <span className="text-[7.5px] text-purple-300 bg-purple-950/40 px-1 py-0.2 rounded border border-purple-500/20 shrink-0">
                      | \__ {step.branchLabel}
                    </span>
                  )}
                  <span className="text-[10px] truncate text-white/85 flex-1 min-w-0">
                    {step.target}
                  </span>
                  {step.summary && (
                    <span className="text-[8.5px] text-white/35 truncate max-w-[160px] shrink-0">
                      · {step.summary}
                    </span>
                  )}
                </div>
              ))}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Footnote with Running Timer */}
        <div className="mt-2 pt-1 border-t border-white/6 flex items-center justify-between text-[8.5px] font-mono text-white/40 min-w-0">
          <span className="flex items-center gap-1.5 truncate min-w-0 flex-1">
            <span className="text-cyan-400 font-bold">~ mem:</span>
            <span className="truncate">{latestMemory?.detail || "Git-memory graph synced"}</span>
          </span>

          <div className="flex items-center gap-2 shrink-0 ml-2">
            {isWorking && (
              <span className="text-[8.5px] font-mono text-amber-300/90 tabular-nums bg-amber-950/40 border border-amber-500/25 px-1 py-0.2 rounded">
                ⏱ {timerLabel}
              </span>
            )}
            <span className="text-[7.5px] uppercase tracking-wider text-white/25">
              data/memory.db
            </span>
          </div>
        </div>
      </div>
    </motion.div>
  )
}
