"use client"

import React, { useState, useEffect, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ChevronDown, Sparkles } from "lucide-react"
import { Xur } from "@/components/Xur"
import { TaskCardProps } from "../TaskListCard.v2"

/**
 * VARIANT: ETCHED TITANIUM
 * Machined metal plate aesthetic — hairline etched borders,
 * recessed inset shadow, brushed surface texture.
 * Step indicators use precision cross-hair marks.
 */
export function VariantEtchedTitanium({
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

  const stateColor = isCrystallized ? "#22c55e" : isThinking ? "#f59e0b" : "#94a3b8"

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.2 }}
      className="my-2 w-full select-none antialiased"
    >
      <div
        className="relative rounded-sm overflow-hidden p-4 transition-all duration-300"
        style={{
          background: "linear-gradient(180deg, rgba(22, 25, 35, 0.98) 0%, rgba(16, 18, 26, 0.99) 100%)",
          border: "1px solid rgba(148, 163, 184, 0.15)",
          boxShadow: "inset 0 2px 4px rgba(0, 0, 0, 0.4), inset 0 -1px 0 rgba(255, 255, 255, 0.05), 0 4px 16px rgba(0, 0, 0, 0.5)",
        }}
      >
        {/* Etched Top Hairline — full width thin line */}
        <div
          className="absolute top-0 left-0 right-0 h-[1px] pointer-events-none"
          style={{ background: `linear-gradient(90deg, transparent, ${stateColor}60, transparent)` }}
        />
        {/* Etched Bottom Hairline */}
        <div
          className="absolute bottom-0 left-0 right-0 h-[1px] pointer-events-none"
          style={{ background: `linear-gradient(90deg, transparent, rgba(148, 163, 184, 0.1), transparent)` }}
        />

        {/* Header — Machined Label */}
        <div className="flex items-center justify-between gap-2.5">
          <div className="flex items-center gap-2.5 min-w-0 flex-1">
            <Xur size={14} color={stateColor} speed={isWorking ? 1.5 : 0.5} />
            <span className="text-[12px] font-mono font-semibold text-slate-200 truncate tracking-wide uppercase">
              {objective}
            </span>
            {isCrystallized && (
              <span className="text-[8px] font-mono uppercase text-emerald-400 border border-emerald-500/40 px-1.5 py-0.5 rounded-sm flex items-center gap-1 shrink-0 font-bold tracking-widest">
                <Sparkles size={8} /> VERIFIED
              </span>
            )}
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {totalCount > 0 && (
              <span className="text-[9.5px] font-mono font-bold text-slate-400 border border-slate-500/30 px-2 py-0.5 rounded-sm tabular-nums tracking-wider">
                {doneCount} / {totalCount}
              </span>
            )}
            <button
              onClick={() => setIsCollapsed(!isCollapsed)}
              className="p-1 rounded-sm text-slate-500 hover:text-slate-200 hover:bg-slate-700/40 transition-colors"
            >
              <ChevronDown size={12} style={{ transform: isCollapsed ? "rotate(-90deg)" : "rotate(0deg)", transition: "transform 0.16s ease" }} />
            </button>
          </div>
        </div>

        {/* Thinking — Etched Status Strip */}
        {(isThinking || currentThought) && (
          <div className="mt-2.5 pt-2 border-t border-slate-600/20 flex items-center gap-2 text-[10px] font-mono min-w-0">
            <span className="text-[9px] font-bold uppercase text-amber-400 shrink-0 border border-amber-500/30 px-1.5 py-0.5 rounded-sm tracking-widest">THK</span>
            <span className="truncate text-amber-200/70">{currentThought || "Processing..."}</span>
          </div>
        )}

        {/* Etched Divider */}
        {!isCollapsed && steps.length > 0 && (
          <div className="mt-2.5 mb-1 h-[1px]" style={{ background: "linear-gradient(90deg, transparent, rgba(148, 163, 184, 0.12), transparent)" }} />
        )}

        {/* Steps — Precision Cross-Hair Nodes */}
        <AnimatePresence initial={false}>
          {!isCollapsed && steps.length > 0 && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="space-y-0.5"
            >
              {steps.map((step, idx) => {
                const isExpanded = expandedStepId === step.id
                return (
                  <div key={step.id || idx} className={`${step.branchLabel ? "pl-4" : ""}`}>
                    <div
                      onClick={() => step.summary && setExpandedStepId(isExpanded ? null : step.id)}
                      className={`flex items-center gap-2 px-1 py-1.5 rounded-sm transition-colors ${
                        step.summary ? "cursor-pointer hover:bg-white/[0.03]" : ""
                      }`}
                    >
                      {/* Cross-Hair Indicator */}
                      <div className="w-4 h-4 shrink-0 flex items-center justify-center">
                        {step.status === "running" ? (
                          <div className="w-3.5 h-3.5 rounded-sm border border-amber-400/80 flex items-center justify-center" style={{ boxShadow: `0 0 6px rgba(251, 191, 36, 0.4)` }}>
                            <Xur size={8} color="#fbbf24" speed={2.5} />
                          </div>
                        ) : step.status === "crystallized" || step.status === "done" ? (
                          <div className="w-3 h-3 rounded-sm border border-slate-400/40 flex items-center justify-center bg-slate-800/60">
                            <div className={`w-1.5 h-1.5 rounded-full ${step.status === "crystallized" ? "bg-emerald-400" : "bg-cyan-400/80"}`} />
                          </div>
                        ) : (
                          <div className="w-2.5 h-2.5 rounded-sm border border-slate-500/30 flex items-center justify-center">
                            <div className="w-1 h-1 rounded-full bg-slate-500/50" />
                          </div>
                        )}
                      </div>

                      <span className="w-12 text-left text-[10px] font-mono font-bold uppercase tracking-[0.15em] text-slate-400 shrink-0">
                        {step.verb}
                      </span>

                      {step.branchLabel && (
                        <span className="text-[8px] font-mono font-medium text-purple-300/80 border border-purple-500/25 px-1.5 py-0.5 rounded-sm shrink-0 tracking-wider">
                          ↳ {step.branchLabel}
                        </span>
                      )}

                      <span className="text-[10.5px] font-mono text-slate-200 truncate leading-tight flex-1 min-w-0">
                        {step.target}
                      </span>

                      {step.summary && !isExpanded && (
                        <span className="text-[9px] font-mono text-slate-500 truncate max-w-[170px] shrink-0">
                          — {step.summary}
                        </span>
                      )}
                    </div>

                    {isExpanded && step.summary && (
                      <div className="ml-6 mt-1 p-2 rounded-sm bg-black/40 border border-slate-600/20 text-[9px] font-mono text-slate-400 leading-relaxed break-words">
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
        <div className="mt-2.5 pt-1.5 border-t border-slate-600/15 flex items-center justify-between text-[9px] font-mono text-slate-500 min-w-0">
          <div className="flex items-center gap-1.5 truncate min-w-0 flex-1">
            {latestMemory ? (
              <>
                <span className="w-1 h-1 rounded-full shrink-0 bg-slate-400" />
                <span className="truncate">{latestMemory.detail}</span>
              </>
            ) : (
              <span className="text-slate-600 truncate">Active Execution</span>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0 ml-2">
            {isWorking && (
              <span className="text-[9px] font-mono text-amber-300/70 tabular-nums border border-amber-500/20 px-1.5 py-0.5 rounded-sm">
                ⏱ {timerLabel}
              </span>
            )}
            <span className="text-[8px] uppercase tracking-[0.2em] text-slate-600">data/memory.db</span>
          </div>
        </div>
      </div>
    </motion.div>
  )
}
