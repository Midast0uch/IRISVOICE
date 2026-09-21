"use client"

import React, { useState, useEffect, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ChevronDown, Sparkles } from "lucide-react"
import { Xur } from "@/components/Xur"
import { TaskCardProps } from "../TaskListCard.v2"

/**
 * VARIANT 4: THE SYNTHESIS (FLAGSHIP)
 * Combines the user's top choices:
 * - Chassis: Precision Monolith micro-radius (rounded-md / 6px) & layered obsidian-slate gradient.
 * - Header Accents: Quantum HUD top-right angled notch and crisp rail telemetry.
 * - Action Words & Nodes: Bioluminescent glowing typography (read, patch, search, exec) with luminous spore dots.
 * - Footnote: Single running timer & memory store attribution.
 */
export function VariantSynthesis({
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

  // Single card-level elapsed timer in footnote
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
        className="relative rounded-md overflow-hidden p-3 transition-all duration-300"
        style={{
          background: "linear-gradient(145deg, rgba(14, 18, 30, 0.96) 0%, rgba(8, 10, 18, 0.98) 55%, rgba(12, 16, 28, 0.94) 100%)",
          border: "1px solid rgba(255, 255, 255, 0.09)",
          borderLeft: `2.5px solid ${accentColor}`,
          boxShadow: `0 8px 26px rgba(0, 0, 0, 0.55), 0 0 16px ${accentColor}12, inset 0 1px 0 rgba(255, 255, 255, 0.06)`,
        }}
      >
        {/* Top-Right HUD Angled Notch Rail */}
        <div
          className="absolute top-0 right-0 w-20 h-[1.5px] pointer-events-none"
          style={{ background: `linear-gradient(90deg, transparent, ${accentColor}99)` }}
        />

        {/* ── Header ── */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <Xur size={15} color={accentColor} speed={isWorking ? 1.8 : 0.8} />
            <div className="flex items-center gap-1.5 min-w-0 flex-1">
              <span className="text-[12px] font-semibold text-white/95 truncate tracking-tight">
                {objective}
              </span>
              {isCrystallized && (
                <span className="text-[8px] font-mono text-emerald-400 bg-emerald-950/60 border border-emerald-500/30 px-1 py-0.2 rounded flex items-center gap-0.5 shrink-0 shadow-[0_0_8px_rgba(34,197,94,0.3)]">
                  <Sparkles size={8} /> crystallized
                </span>
              )}
            </div>
          </div>

          {/* Right Header Counter */}
          <div className="flex items-center gap-1.5 shrink-0">
            {totalCount > 0 && (
              <span className="text-[9.5px] font-mono font-medium text-cyan-300/80 bg-cyan-950/40 border border-cyan-500/20 px-1.5 py-0.5 rounded tabular-nums">
                {doneCount}/{totalCount}
              </span>
            )}
            <button
              onClick={() => setIsCollapsed(!isCollapsed)}
              className="p-0.5 rounded text-white/30 hover:text-white/80 hover:bg-white/5 transition-colors"
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

        {/* ── Live Thought & Reflection Stream ── */}
        {(isThinking || currentThought || thoughtHistory) && (
          <div className="mt-2 pt-1.5 border-t border-white/6 flex items-center justify-between gap-2 text-[10px] font-mono min-w-0">
            <div className="flex items-center gap-1.5 text-amber-300/90 min-w-0 flex-1 truncate">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse shrink-0 shadow-[0_0_6px_rgba(251,191,36,0.8)]" />
              <span className="truncate italic">{currentThought || "Reflecting on memory coordinates..."}</span>
            </div>
            {thoughtHistory && (
              <button
                onClick={() => setShowThoughtTrace(!showThoughtTrace)}
                className="text-[8.5px] text-white/40 hover:text-white/80 shrink-0 px-1 py-0.2 rounded bg-white/5"
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
              className="mt-1.5 p-2 rounded bg-black/40 border border-white/6 text-[9px] font-mono text-white/70 leading-relaxed max-h-28 overflow-y-auto whitespace-pre-wrap"
            >
              {thoughtHistory}
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Step Nodes (Non-overlapping Inline Flex Layout) ── */}
        <AnimatePresence initial={false}>
          {!isCollapsed && steps.length > 0 && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="mt-2 space-y-1"
            >
              {steps.map((step, idx) => {
                const isExpanded = expandedStepId === step.id
                return (
                  <div key={step.id || idx} className={`${step.branchLabel ? "pl-3.5" : ""}`}>
                    <div
                      onClick={() => step.summary && setExpandedStepId(isExpanded ? null : step.id)}
                      className={`flex items-center gap-2 p-0.5 rounded transition-colors ${
                        step.summary ? "cursor-pointer hover:bg-white/[0.03]" : ""
                      }`}
                    >
                      {/* Non-overlapping Flowing Spore Dot */}
                      <div className="w-3 h-3 shrink-0 flex items-center justify-center">
                        {step.status === "running" ? (
                          <div className="w-3 h-3 rounded-full flex items-center justify-center bg-black border border-amber-400 shadow-[0_0_6px_rgba(251,191,36,0.7)]">
                            <Xur size={7} color="#fbbf24" speed={2.0} />
                          </div>
                        ) : step.status === "crystallized" ? (
                          <div className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(34,197,94,0.8)]" />
                        ) : step.status === "done" ? (
                          <div className="w-1.5 h-1.5 rounded-full bg-cyan-400 shadow-[0_0_4px_rgba(0,212,255,0.7)]" />
                        ) : step.status === "rerouted" ? (
                          <div className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                        ) : (
                          <div className="w-1.5 h-1.5 rounded-full bg-white/20" />
                        )}
                      </div>

                      {/* Action Verb */}
                      <span className="text-[9.5px] font-mono font-bold text-cyan-300 shadow-sm shrink-0 drop-shadow-[0_0_6px_rgba(0,212,255,0.4)]">
                        {step.verb}
                      </span>

                      {/* Branch Label if any */}
                      {step.branchLabel && (
                        <span className="text-[8px] font-mono text-purple-300 bg-purple-950/40 border border-purple-500/20 px-1 py-0.2 rounded-full shrink-0">
                          ↳ [{step.branchLabel}]
                        </span>
                      )}

                      {/* Target Entity */}
                      <span
                        className={`text-[10.5px] truncate leading-tight flex-1 min-w-0 ${
                          step.status === "running"
                            ? "text-white font-medium"
                            : step.status === "done" || step.status === "crystallized"
                            ? "text-white/85"
                            : "text-white/40"
                        }`}
                      >
                        {step.target}
                      </span>

                      {/* Truncated Summary */}
                      {step.summary && !isExpanded && (
                        <span className="text-[9px] font-mono text-white/35 truncate max-w-[170px] shrink-0">
                          · {step.summary}
                        </span>
                      )}
                    </div>

                    {/* Expanded Detail (if tapped) */}
                    {isExpanded && step.summary && (
                      <div className="ml-5 mt-0.5 p-1.5 rounded bg-black/40 border border-white/6 text-[9px] font-mono text-white/70 leading-relaxed break-words">
                        {step.summary}
                      </div>
                    )}
                  </div>
                )
              })}
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Footnote Area: Running Timer + Memory Store ── */}
        <div className="mt-2.5 pt-1.5 border-t border-white/6 flex items-center justify-between text-[9px] font-mono text-white/45 min-w-0">
          <div className="flex items-center gap-1.5 truncate min-w-0 flex-1">
            {latestMemory ? (
              <>
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${latestMemory.direction === "crystallize" ? "bg-emerald-400 shadow-[0_0_6px_rgba(34,197,94,0.8)]" : "bg-cyan-400 shadow-[0_0_6px_rgba(0,212,255,0.8)]"}`} />
                <span className="truncate">{latestMemory.detail}</span>
              </>
            ) : (
              <span className="text-white/30 truncate">Live Task Execution</span>
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
