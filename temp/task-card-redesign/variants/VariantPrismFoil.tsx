"use client"

import React, { useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ChevronDown, Sparkles } from "lucide-react"
import { Xur } from "@/components/Xur"
import { TaskCardProps } from "../TaskListCard.v2"

/**
 * VARIANT 4: FLOATING PRISM FOIL
 * Aesthetics:
 * - Asymmetric Geometric Chamfer (rounded-tl-xl rounded-br-xl rounded-tr-sm rounded-bl-sm).
 * - Multi-Stop Chromatic Glass Gradient: linear-gradient(160deg, rgba(16, 24, 42, 0.95) 0%, rgba(8, 12, 20, 0.98) 40%, rgba(24, 18, 36, 0.92) 100%).
 * - Luminous edge refraction and smooth typography.
 */
export function VariantPrismFoil({
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
      className="my-2.5 w-full select-none"
    >
      <div
        className="relative overflow-hidden p-3.5 transition-all duration-300 rounded-tl-xl rounded-br-xl rounded-tr-sm rounded-bl-sm"
        style={{
          background: "linear-gradient(160deg, rgba(16, 24, 42, 0.95) 0%, rgba(8, 12, 20, 0.98) 40%, rgba(24, 18, 36, 0.92) 100%)",
          border: "1px solid rgba(255, 255, 255, 0.09)",
          borderLeft: `2.5px solid ${accentColor}`,
          boxShadow: "0 8px 26px rgba(0, 0, 0, 0.52), inset 0 1px 0 rgba(255, 255, 255, 0.08)",
        }}
      >
        {/* Subtle top-left prism refraction */}
        <div
          className="absolute top-0 left-0 w-32 h-[1px] pointer-events-none"
          style={{ background: `linear-gradient(90deg, ${accentColor}, transparent)` }}
        />

        {/* Header */}
        <div className="flex items-center justify-between gap-2.5">
          <div className="flex items-center gap-2.5 min-w-0 flex-1">
            <Xur size={16} color={accentColor} speed={isWorking ? 1.7 : 0.8} />
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <span className="text-[12.5px] font-semibold text-white/95 truncate tracking-tight">
                {objective}
              </span>
              {isCrystallized && (
                <span className="text-[8.5px] font-mono text-emerald-400 bg-emerald-950/60 border border-emerald-500/30 px-1.5 py-0.5 rounded flex items-center gap-1 shrink-0">
                  <Sparkles size={9} /> crystallized
                </span>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {totalCount > 0 && (
              <span className="text-[10px] font-mono text-white/45 tabular-nums">
                {doneCount}/{totalCount}
              </span>
            )}
            <button
              onClick={() => setIsCollapsed(!isCollapsed)}
              className="p-1 rounded text-white/30 hover:text-white/80 hover:bg-white/5 transition-colors"
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
          <div className="mt-2.5 pt-2 border-t border-white/6 flex items-center justify-between gap-2 text-[10px] font-mono min-w-0">
            <div className="flex items-center gap-1.5 text-amber-300/90 min-w-0 flex-1 truncate">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse shrink-0" />
              <span className="truncate italic">{currentThought || "Synthesizing trajectory..."}</span>
            </div>
            {thoughtHistory && (
              <button
                onClick={() => setShowThoughtTrace(!showThoughtTrace)}
                className="text-[9px] text-white/40 hover:text-white/80 shrink-0 px-1.5 py-0.5 rounded bg-white/5"
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
              className="mt-2 p-2 rounded bg-black/40 text-[9.5px] font-mono text-white/70 leading-relaxed max-h-32 overflow-y-auto whitespace-pre-wrap"
            >
              {thoughtHistory}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Step Nodes */}
        <AnimatePresence initial={false}>
          {!isCollapsed && steps.length > 0 && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="mt-2.5 space-y-1 relative"
            >
              <div
                className="absolute left-[5.5px] top-2 bottom-2 w-[1px] pointer-events-none"
                style={{ background: `linear-gradient(to bottom, ${accentColor}40, rgba(255,255,255,0.06))` }}
              />

              {steps.map((step, idx) => (
                <div key={step.id || idx} className={`relative ${step.branchLabel ? "pl-5" : "pl-4"}`}>
                  <div className="absolute left-0 top-1 shrink-0 flex items-center justify-center">
                    {step.status === "running" ? (
                      <div className="w-3 h-3 rounded-full flex items-center justify-center bg-black border border-amber-400">
                        <Xur size={8} color="#fbbf24" speed={2.0} />
                      </div>
                    ) : step.status === "crystallized" ? (
                      <div className="w-2.5 h-2.5 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(34,197,94,0.6)]" />
                    ) : step.status === "done" ? (
                      <div className="w-2 h-2 rounded-full bg-cyan-400 shadow-[0_0_4px_rgba(0,212,255,0.5)] mt-0.5 ml-0.5" />
                    ) : (
                      <div className="w-1.5 h-1.5 rounded-full bg-white/20 mt-1 ml-1" />
                    )}
                  </div>

                  <div className="flex items-baseline justify-between gap-2 p-0.5">
                    <div className="flex items-baseline gap-1.5 min-w-0 flex-1">
                      <span className="text-[10px] font-mono font-medium text-cyan-300/90 shrink-0">
                        {step.verb}
                      </span>
                      {step.branchLabel && (
                        <span className="text-[8.5px] font-mono text-purple-300/80 bg-purple-950/40 px-1 py-0.2 rounded border border-purple-500/20 shrink-0">
                          ↳ [{step.branchLabel}]
                        </span>
                      )}
                      <span className="text-[11px] truncate text-white/85 flex-1 min-w-0">
                        {step.target}
                      </span>
                      {step.summary && (
                        <span className="text-[9.5px] font-mono text-white/35 truncate max-w-[200px] shrink-0">
                          · {step.summary}
                        </span>
                      )}
                    </div>
                    {step.durationMs != null && (
                      <span className="text-[8.5px] font-mono text-white/30 shrink-0 tabular-nums">
                        {step.durationMs > 1000 ? `${(step.durationMs / 1000).toFixed(1)}s` : `${step.durationMs}ms`}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Memory Indicator */}
        {latestMemory && (
          <div className="mt-2.5 pt-1.5 border-t border-white/6 flex items-center justify-between text-[9px] font-mono text-white/45">
            <span className="flex items-center gap-1.5 truncate">
              <span className={`w-1.5 h-1.5 rounded-full ${latestMemory.direction === "crystallize" ? "bg-emerald-400" : "bg-cyan-400"}`} />
              <span className="truncate">{latestMemory.detail}</span>
            </span>
            <span className="text-[8px] uppercase tracking-wider text-white/25 shrink-0">
              {latestMemory.engine === "episodic" ? "episodic" : "coordinates"}
            </span>
          </div>
        )}
      </div>
    </motion.div>
  )
}
