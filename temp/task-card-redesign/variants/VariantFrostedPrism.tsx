"use client"

import React, { useState, useEffect, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ChevronDown, Sparkles } from "lucide-react"
import { Xur } from "@/components/Xur"
import { TaskCardProps } from "../TaskListCard.v2"

/**
 * VARIANT: FROSTED PRISM
 * Frosted glass panel with luminous edge glow, diffused background blur,
 * and soft gradient accent border that shifts with task state.
 * Step nodes use soft frosted pills instead of hard dots.
 */
export function VariantFrostedPrism({
  objective,
  steps = [],
  isThinking = false,
  currentThought = "",
  thoughtHistory = "",
  isCrystallized = false,
  memoryEvents = [],
}: TaskCardProps) {
  const [isCollapsed, setIsCollapsed] = useState(false)
  const [expandedStepId, setExpandedStepId] = useState<string | null>(null)

  const doneCount = steps.filter((s) => s.status === "done" || s.status === "crystallized").length
  const totalCount = steps.length
  const isWorking = isThinking || steps.some((s) => s.status === "running")

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

  const accentFrom = isCrystallized ? "#22c55e" : isThinking ? "#f59e0b" : "#06b6d4"
  const accentTo = isCrystallized ? "#10b981" : isThinking ? "#eab308" : "#8b5cf6"

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.25 }}
      className="my-2 w-full select-none antialiased"
    >
      <div
        className="relative rounded-xl overflow-hidden p-4 transition-all duration-500"
        style={{
          background: "rgba(15, 18, 30, 0.65)",
          backdropFilter: "blur(20px) saturate(1.4)",
          WebkitBackdropFilter: "blur(20px) saturate(1.4)",
          border: "1px solid rgba(255, 255, 255, 0.1)",
          boxShadow: `0 0 40px -8px ${accentFrom}30, 0 16px 32px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.12)`,
        }}
      >
        {/* Luminous Gradient Top Edge */}
        <div
          className="absolute top-0 left-0 right-0 h-[2px] pointer-events-none"
          style={{ background: `linear-gradient(90deg, ${accentFrom}, ${accentTo}, transparent)` }}
        />

        {/* Header */}
        <div className="flex items-center justify-between gap-2.5">
          <div className="flex items-center gap-2.5 min-w-0 flex-1">
            <div
              className="w-6 h-6 rounded-lg flex items-center justify-center shrink-0"
              style={{
                background: `linear-gradient(135deg, ${accentFrom}30, ${accentTo}20)`,
                border: `1px solid ${accentFrom}50`,
              }}
            >
              <Xur size={12} color={accentFrom} speed={isWorking ? 2 : 0.6} />
            </div>
            <span className="text-[12px] font-mono font-semibold text-white truncate tracking-tight leading-tight">
              {objective}
            </span>
            {isCrystallized && (
              <span className="text-[8px] font-mono uppercase text-emerald-300 bg-emerald-500/15 border border-emerald-500/30 px-1.5 py-0.5 rounded-md flex items-center gap-1 shrink-0 font-bold backdrop-blur-sm">
                <Sparkles size={8} /> done
              </span>
            )}
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {totalCount > 0 && (
              <span
                className="text-[9.5px] font-mono font-bold px-2 py-0.5 rounded-md tabular-nums"
                style={{
                  color: accentFrom,
                  background: `${accentFrom}15`,
                  border: `1px solid ${accentFrom}30`,
                }}
              >
                {doneCount}/{totalCount}
              </span>
            )}
            <button
              onClick={() => setIsCollapsed(!isCollapsed)}
              className="p-1 rounded-md text-white/40 hover:text-white hover:bg-white/10 transition-colors"
            >
              <ChevronDown size={12} style={{ transform: isCollapsed ? "rotate(-90deg)" : "rotate(0deg)", transition: "transform 0.16s ease" }} />
            </button>
          </div>
        </div>

        {/* Thinking Stream */}
        {(isThinking || currentThought) && (
          <div className="mt-2.5 pt-2 border-t border-white/6 flex items-center gap-2 text-[10px] font-mono min-w-0">
            <span className="text-[9px] font-bold uppercase text-amber-300 shrink-0 bg-amber-500/15 border border-amber-500/25 px-1.5 py-0.5 rounded-md backdrop-blur-sm">THK</span>
            <span className="truncate text-amber-200/80">{currentThought || "Resolving execution dependencies..."}</span>
          </div>
        )}

        {/* Steps */}
        <AnimatePresence initial={false}>
          {!isCollapsed && steps.length > 0 && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="mt-2.5 space-y-1"
            >
              {steps.map((step, idx) => {
                const isExpanded = expandedStepId === step.id
                return (
                  <div key={step.id || idx} className={`${step.branchLabel ? "pl-4" : ""}`}>
                    <div
                      onClick={() => step.summary && setExpandedStepId(isExpanded ? null : step.id)}
                      className={`flex items-center gap-2 px-2 py-1.5 rounded-lg transition-all ${
                        step.summary ? "cursor-pointer hover:bg-white/[0.04]" : ""
                      } ${step.status === "running" ? "bg-amber-500/[0.06]" : ""}`}
                    >
                      {/* Frosted Pill Indicator */}
                      <div className="w-4 h-4 shrink-0 flex items-center justify-center">
                        {step.status === "running" ? (
                          <div className="w-3.5 h-3.5 rounded-md bg-amber-500/20 border border-amber-400/60 flex items-center justify-center backdrop-blur-sm">
                            <Xur size={8} color="#fbbf24" speed={2.5} />
                          </div>
                        ) : step.status === "crystallized" ? (
                          <div className="w-3 h-3 rounded-md bg-emerald-500/25 border border-emerald-400/50 flex items-center justify-center">
                            <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                          </div>
                        ) : step.status === "done" ? (
                          <div className="w-3 h-3 rounded-md bg-cyan-500/15 border border-cyan-400/40 flex items-center justify-center">
                            <div className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                          </div>
                        ) : (
                          <div className="w-2.5 h-2.5 rounded-md border border-white/20 flex items-center justify-center">
                            <div className="w-1 h-1 rounded-full bg-white/30" />
                          </div>
                        )}
                      </div>

                      <span className="w-12 text-left text-[10px] font-mono font-bold uppercase tracking-wider shrink-0" style={{ color: accentFrom }}>
                        {step.verb}
                      </span>

                      {step.branchLabel && (
                        <span className="text-[8px] font-mono font-medium text-purple-300 bg-purple-500/15 border border-purple-500/25 px-1.5 py-0.5 rounded-md shrink-0 backdrop-blur-sm">
                          ↳ {step.branchLabel}
                        </span>
                      )}

                      <span className="text-[10.5px] font-mono text-white/90 truncate leading-tight flex-1 min-w-0">
                        {step.target}
                      </span>

                      {step.summary && !isExpanded && (
                        <span className="text-[9px] font-mono text-white/30 truncate max-w-[170px] shrink-0">
                          · {step.summary}
                        </span>
                      )}
                    </div>

                    {isExpanded && step.summary && (
                      <div className="ml-6 mt-1 p-2 rounded-lg bg-white/[0.03] border border-white/8 text-[9px] font-mono text-white/60 leading-relaxed break-words backdrop-blur-sm">
                        {step.summary}
                      </div>
                    )}
                  </div>
                )
              })}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Footnote */}
        <div className="mt-2.5 pt-1.5 border-t border-white/6 flex items-center justify-between text-[9px] font-mono text-white/40 min-w-0">
          <div className="flex items-center gap-1.5 truncate min-w-0 flex-1">
            {latestMemory ? (
              <>
                <span className={`w-1.5 h-1.5 rounded-full shrink-0`} style={{ background: accentFrom, boxShadow: `0 0 6px ${accentFrom}` }} />
                <span className="truncate">{latestMemory.detail}</span>
              </>
            ) : (
              <span className="text-white/25 truncate">Active Execution</span>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0 ml-2">
            {isWorking && (
              <span className="text-[9px] font-mono text-amber-300/80 tabular-nums bg-amber-500/10 border border-amber-500/20 px-1.5 py-0.5 rounded-md">
                ⏱ {timerLabel}
              </span>
            )}
            <span className="text-[8px] uppercase tracking-wider text-white/25">data/memory.db</span>
          </div>
        </div>
      </div>
    </motion.div>
  )
}
