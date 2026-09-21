"use client"

import React, { useState, useEffect, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ChevronDown, Sparkles } from "lucide-react"
import { Xur } from "@/components/Xur"
import { TaskCardProps } from "../TaskListCard.v2"

/**
 * VARIANT 1: INDUSTRIAL PRECISION (Winning GUI Design)
 * Aesthetics:
 * - High-precision dark carbon plate with razor-sharp anti-aliased typography.
 * - Uniform fixed-width verb columns (w-12) for razor-sharp vertical grid alignment.
 * - Custom XurOrb orbital step indicators (active Xur particle / converged photon core).
 * - Subtle inline summary & footnote font scale matching Flagship.
 */
export function VariantMonolith({
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
  const [expandedStepId, setExpandedStepId] = useState<string | null>(null)

  const doneCount = steps.filter((s) => s.status === "done" || s.status === "crystallized").length
  const totalCount = steps.length
  const isWorking = isThinking || steps.some((s) => s.status === "running")

  // Footnote running timer
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
      className="my-2 w-full select-none antialiased"
      style={{ WebkitFontSmoothing: "antialiased", MozOsxFontSmoothing: "grayscale", textRendering: "optimizeLegibility" }}
    >
      <div
        className="relative rounded-md overflow-hidden p-3.5 transition-all duration-300"
        style={{
          background: "linear-gradient(180deg, rgba(16, 20, 32, 0.98) 0%, rgba(10, 12, 20, 0.99) 100%)",
          border: "1px solid rgba(255, 255, 255, 0.12)",
          borderLeft: `3px solid ${accentColor}`,
          boxShadow: "0 8px 24px rgba(0, 0, 0, 0.6), inset 0 1px 0 rgba(255, 255, 255, 0.08)",
        }}
      >
        {/* Top precision notch */}
        <div
          className="absolute top-0 left-0 right-0 h-[1.5px] pointer-events-none"
          style={{ background: `linear-gradient(90deg, ${accentColor}99 0%, transparent 60%)` }}
        />

        {/* Header */}
        <div className="flex items-center justify-between gap-2.5">
          <div className="flex items-center gap-2.5 min-w-0 flex-1">
            <Xur size={15} color={accentColor} speed={isWorking ? 1.7 : 0.8} />
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <span className="text-[12px] font-mono font-semibold text-white truncate tracking-tight">
                {objective}
              </span>
              {isCrystallized && (
                <span className="text-[8.5px] font-mono uppercase text-emerald-400 bg-emerald-950/70 border border-emerald-500/40 px-1.5 py-0.2 rounded flex items-center gap-1 shrink-0 font-bold">
                  <Sparkles size={8} /> done
                </span>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {totalCount > 0 && (
              <span className="text-[9.5px] font-mono font-bold text-cyan-300 bg-cyan-950/60 border border-cyan-500/30 px-1.5 py-0.5 rounded tabular-nums">
                [{doneCount}/{totalCount}]
              </span>
            )}
            <button
              onClick={() => setIsCollapsed(!isCollapsed)}
              className="p-1 rounded text-white/40 hover:text-white hover:bg-white/10 transition-colors"
            >
              <ChevronDown
                size={12}
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
          <div className="mt-2.5 pt-2 border-t border-white/8 flex items-center justify-between gap-2 text-[10px] font-mono min-w-0">
            <div className="flex items-center gap-2 text-amber-300 min-w-0 flex-1 truncate">
              <span className="text-[9px] font-bold uppercase text-amber-400 shrink-0 bg-amber-950/60 border border-amber-500/30 px-1 rounded">THK</span>
              <span className="truncate text-amber-200/90">{currentThought || "Resolving execution dependencies..."}</span>
            </div>
            {thoughtHistory && (
              <button
                onClick={() => setShowThoughtTrace(!showThoughtTrace)}
                className="text-[8.5px] text-white/50 hover:text-white shrink-0 px-1.5 py-0.2 rounded bg-white/10 font-bold"
              >
                {showThoughtTrace ? "hide trace" : "trace"}
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
              className="mt-2 p-2 rounded bg-black/60 border border-white/10 text-[9px] font-mono text-slate-300 leading-relaxed max-h-28 overflow-y-auto whitespace-pre-wrap"
            >
              {thoughtHistory}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Step Nodes (Uniform Grid with Fixed-Width Verbs) */}
        <AnimatePresence initial={false}>
          {!isCollapsed && steps.length > 0 && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="mt-2.5 space-y-1.5"
            >
              {steps.map((step, idx) => {
                const isExpanded = expandedStepId === step.id
                return (
                  <div key={step.id || idx} className={`${step.branchLabel ? "pl-3.5" : ""}`}>
                    <div
                      onClick={() => step.summary && setExpandedStepId(isExpanded ? null : step.id)}
                      className={`flex items-center gap-2 p-1 rounded transition-colors ${
                        step.summary ? "cursor-pointer hover:bg-white/[0.04]" : ""
                      }`}
                    >
                      {/* Unique XurOrb Loading & State Indicator */}
                      <div className="w-4 h-4 shrink-0 flex items-center justify-center">
                        {step.status === "running" ? (
                          <div className="w-4 h-4 rounded-full flex items-center justify-center bg-black border border-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.7)]">
                            <Xur size={9} color="#fbbf24" speed={2.5} />
                          </div>
                        ) : step.status === "crystallized" ? (
                          <div className="relative flex items-center justify-center">
                            <div className="w-3 h-3 rounded-full border border-emerald-400 animate-ping absolute opacity-30" />
                            <div className="w-2.5 h-2.5 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(34,197,94,0.9)]" />
                          </div>
                        ) : step.status === "done" ? (
                          <div className="w-3 h-3 rounded-full border border-cyan-400/60 flex items-center justify-center bg-cyan-950/30 shadow-[0_0_6px_rgba(0,212,255,0.4)]">
                            <div className="w-1.5 h-1.5 rounded-full bg-cyan-400 shadow-[0_0_4px_rgba(0,212,255,0.8)]" />
                          </div>
                        ) : step.status === "rerouted" ? (
                          <div className="w-3 h-3 rounded-full border border-amber-400/50 flex items-center justify-center">
                            <div className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                          </div>
                        ) : (
                          <div className="w-2.5 h-2.5 rounded-full border border-white/30 flex items-center justify-center">
                            <div className="w-1 h-1 rounded-full bg-white/40" />
                          </div>
                        )}
                      </div>

                      {/* Uniform Fixed-Width Verb Column */}
                      <span className="w-12 text-left text-[10px] font-mono font-bold uppercase tracking-wider text-cyan-300 shrink-0">
                        {step.verb}
                      </span>

                      {/* Branch Tag if any */}
                      {step.branchLabel && (
                        <span className="text-[8px] font-mono font-medium text-purple-300 bg-purple-950/60 border border-purple-500/30 px-1.5 py-0.2 rounded-full shrink-0">
                          ↳ [{step.branchLabel}]
                        </span>
                      )}

                      {/* Target Entity */}
                      <span className="text-[10.5px] font-mono text-slate-100 truncate flex-1 min-w-0 font-medium">
                        {step.target}
                      </span>

                      {/* Flagship-Matched Subtle Inline Summary */}
                      {step.summary && !isExpanded && (
                        <span className="text-[9px] font-mono text-white/35 truncate max-w-[170px] shrink-0">
                          · {step.summary}
                        </span>
                      )}
                    </div>

                    {isExpanded && step.summary && (
                      <div className="ml-6 mt-1 p-2 rounded bg-black/60 border border-white/10 text-[9px] font-mono text-slate-300 leading-relaxed break-words">
                        {step.summary}
                      </div>
                    )}
                  </div>
                )
              })}
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Footnote Area: Running Timer + Memory Store (Flagship Scale) ── */}
        <div className="mt-2.5 pt-1.5 border-t border-white/6 flex items-center justify-between text-[9px] font-mono text-white/45 min-w-0">
          <div className="flex items-center gap-1.5 truncate min-w-0 flex-1">
            {latestMemory ? (
              <>
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${latestMemory.direction === "crystallize" ? "bg-emerald-400 shadow-[0_0_6px_rgba(34,197,94,0.8)]" : "bg-cyan-400 shadow-[0_0_6px_rgba(0,212,255,0.8)]"}`} />
                <span className="truncate">{latestMemory.detail}</span>
              </>
            ) : (
              <span className="text-white/30 truncate">Active Execution</span>
            )}
          </div>

          <div className="flex items-center gap-2 shrink-0 ml-2">
            {isWorking && (
              <span className="text-[9px] font-mono text-amber-300/90 tabular-nums bg-amber-950/40 border border-amber-500/25 px-1.5 py-0.2 rounded flex items-center gap-1">
                ⏱ {timerLabel}
              </span>
            )}
            <span className="text-[8px] uppercase tracking-wider text-white/30">
              {latestMemory?.engine === "episodic" ? "data/memory.db" : "data/memory.db (skills)"}
            </span>
          </div>
        </div>
      </div>
    </motion.div>
  )
}
