"use client"

import React, { useState, useEffect, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ChevronDown, Sparkles } from "lucide-react"
import { Xur } from "@/components/Xur"
import { TaskCardProps } from "../TaskListCard.v2"

/**
 * VARIANT: LIQUID INK
 * Fluid dark ink surface with a single warm accent vein that pulses
 * through the left edge. Step nodes use ink-dot markers with
 * expanding ripple rings on active state.
 */
export function VariantLiquidInk({
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

  const veinColor = isCrystallized ? "#34d399" : isThinking ? "#fbbf24" : "#f97316"

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.22 }}
      className="my-2 w-full select-none antialiased"
    >
      <div
        className="relative rounded-lg overflow-hidden transition-all duration-300"
        style={{
          background: "linear-gradient(135deg, rgba(8, 8, 16, 0.97) 0%, rgba(14, 12, 20, 0.98) 50%, rgba(8, 8, 16, 0.97) 100%)",
          border: "1px solid rgba(255, 255, 255, 0.07)",
          boxShadow: "0 12px 40px rgba(0, 0, 0, 0.7), 0 0 1px rgba(255, 255, 255, 0.1)",
        }}
      >
        {/* Warm Ink Vein — Animated Left Edge */}
        <div
          className="absolute top-0 left-0 bottom-0 w-[3px] pointer-events-none"
          style={{
            background: `linear-gradient(180deg, transparent 0%, ${veinColor} 30%, ${veinColor} 70%, transparent 100%)`,
            opacity: isWorking ? 1 : 0.5,
            transition: "opacity 0.5s ease",
          }}
        />
        {/* Vein Glow Halo */}
        <div
          className="absolute top-0 left-0 bottom-0 w-8 pointer-events-none"
          style={{
            background: `linear-gradient(90deg, ${veinColor}15, transparent)`,
          }}
        />

        <div className="p-4 pl-5">
          {/* Header */}
          <div className="flex items-center justify-between gap-2.5">
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <Xur size={14} color={veinColor} speed={isWorking ? 1.8 : 0.6} />
              <span className="text-[12px] font-mono font-semibold text-white/95 truncate tracking-tight">
                {objective}
              </span>
              {isCrystallized && (
                <span
                  className="text-[8px] font-mono uppercase px-1.5 py-0.5 rounded-md flex items-center gap-1 shrink-0 font-bold"
                  style={{
                    color: veinColor,
                    background: `${veinColor}15`,
                    border: `1px solid ${veinColor}35`,
                  }}
                >
                  <Sparkles size={8} /> done
                </span>
              )}
            </div>

            <div className="flex items-center gap-2 shrink-0">
              {totalCount > 0 && (
                <span
                  className="text-[9.5px] font-mono font-bold px-2 py-0.5 rounded-md tabular-nums"
                  style={{ color: veinColor, background: `${veinColor}12`, border: `1px solid ${veinColor}25` }}
                >
                  [{doneCount}/{totalCount}]
                </span>
              )}
              <button
                onClick={() => setIsCollapsed(!isCollapsed)}
                className="p-1 rounded text-white/30 hover:text-white hover:bg-white/10 transition-colors"
              >
                <ChevronDown size={12} style={{ transform: isCollapsed ? "rotate(-90deg)" : "rotate(0deg)", transition: "transform 0.16s ease" }} />
              </button>
            </div>
          </div>

          {/* Thinking Whisper */}
          {(isThinking || currentThought) && (
            <div className="mt-2.5 pt-2 border-t border-white/5 flex items-center gap-2 text-[10px] font-mono min-w-0">
              <span
                className="text-[9px] font-bold uppercase shrink-0 px-1.5 py-0.5 rounded-md"
                style={{ color: "#fbbf24", background: "rgba(251, 191, 36, 0.1)", border: "1px solid rgba(251, 191, 36, 0.2)" }}
              >THK</span>
              <span className="truncate text-amber-200/70 italic">{currentThought || "Reflecting..."}</span>
            </div>
          )}

          {/* Steps — Ink Dot Markers with Ripple Rings */}
          <AnimatePresence initial={false}>
            {!isCollapsed && steps.length > 0 && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="mt-2.5 space-y-0.5"
              >
                {steps.map((step, idx) => {
                  const isExpanded = expandedStepId === step.id
                  return (
                    <div key={step.id || idx} className={`${step.branchLabel ? "pl-4" : ""}`}>
                      <div
                        onClick={() => step.summary && setExpandedStepId(isExpanded ? null : step.id)}
                        className={`flex items-center gap-2 px-1.5 py-1.5 rounded-md transition-colors ${
                          step.summary ? "cursor-pointer hover:bg-white/[0.03]" : ""
                        }`}
                      >
                        {/* Ink Dot with Ripple */}
                        <div className="w-4 h-4 shrink-0 flex items-center justify-center relative">
                          {step.status === "running" ? (
                            <>
                              <div className="absolute w-4 h-4 rounded-full border border-amber-400/40 animate-ping" style={{ animationDuration: "2s" }} />
                              <div className="w-2.5 h-2.5 rounded-full border border-amber-400 flex items-center justify-center bg-amber-500/20">
                                <Xur size={7} color="#fbbf24" speed={2.5} />
                              </div>
                            </>
                          ) : step.status === "crystallized" ? (
                            <div className="w-2.5 h-2.5 rounded-full bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.8)]" />
                          ) : step.status === "done" ? (
                            <div className="w-2 h-2 rounded-full" style={{ background: veinColor, boxShadow: `0 0 6px ${veinColor}80` }} />
                          ) : (
                            <div className="w-1.5 h-1.5 rounded-full bg-white/20 border border-white/15" />
                          )}
                        </div>

                        <span className="w-12 text-left text-[10px] font-mono font-bold uppercase tracking-wider shrink-0" style={{ color: veinColor }}>
                          {step.verb}
                        </span>

                        {step.branchLabel && (
                          <span className="text-[8px] font-mono font-medium text-purple-300/80 bg-purple-500/10 border border-purple-500/20 px-1.5 py-0.5 rounded-md shrink-0">
                            ↳ {step.branchLabel}
                          </span>
                        )}

                        <span className="text-[10.5px] font-mono text-white/85 truncate leading-tight flex-1 min-w-0">
                          {step.target}
                        </span>

                        {step.summary && !isExpanded && (
                          <span className="text-[9px] font-mono text-white/25 truncate max-w-[170px] shrink-0">
                            · {step.summary}
                          </span>
                        )}
                      </div>

                      {isExpanded && step.summary && (
                        <div className="ml-6 mt-1 p-2 rounded-md bg-black/50 border border-white/6 text-[9px] font-mono text-white/50 leading-relaxed break-words">
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
          <div className="mt-2.5 pt-1.5 border-t border-white/5 flex items-center justify-between text-[9px] font-mono text-white/35 min-w-0">
            <div className="flex items-center gap-1.5 truncate min-w-0 flex-1">
              {latestMemory ? (
                <>
                  <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: veinColor, boxShadow: `0 0 4px ${veinColor}` }} />
                  <span className="truncate">{latestMemory.detail}</span>
                </>
              ) : (
                <span className="text-white/20 truncate">Active Execution</span>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0 ml-2">
              {isWorking && (
                <span className="text-[9px] font-mono tabular-nums px-1.5 py-0.5 rounded-md" style={{ color: `${veinColor}cc`, background: `${veinColor}10`, border: `1px solid ${veinColor}20` }}>
                  ⏱ {timerLabel}
                </span>
              )}
              <span className="text-[8px] uppercase tracking-wider text-white/20">data/memory.db</span>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  )
}
