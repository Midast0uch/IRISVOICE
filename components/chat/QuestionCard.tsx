"use client"

import React, { useState, useEffect, useCallback } from "react"
import { motion } from "framer-motion"
import { HelpCircle, Send, Clock, Mic } from "lucide-react"
import { useBrandColor } from "@/contexts/BrandColorContext"

export interface QuestionCardProps {
  questionId: string
  text: string
  options?: string[]
  allowOther?: boolean
  timeoutSeconds?: number
  onAnswer: (questionId: string, answer: string) => void
}

export function QuestionCard({
  questionId,
  text,
  options = [],
  allowOther = false,
  timeoutSeconds = 120,
  onAnswer,
}: QuestionCardProps) {
  const { getThemeConfig } = useBrandColor()
  const brandTheme = getThemeConfig()
  const glowColor = brandTheme.glow.color || "#00d4ff"
  const shimmerPrimary = brandTheme.shimmer.primary || glowColor
  const glassBlur = brandTheme.glass.blur || 20
  const glassOpacity = brandTheme.glass.opacity || 0.18

  const [selected, setSelected] = useState<string | null>(null)
  const [customInput, setCustomInput] = useState("")
  const [timeLeft, setTimeLeft] = useState(timeoutSeconds)
  const [expired, setExpired] = useState(false)
  const [submitted, setSubmitted] = useState(false)

  // Countdown
  useEffect(() => {
    if (submitted || expired) return
    if (timeLeft <= 0) {
      setExpired(true)
      onAnswer(questionId, "")
      return
    }
    const id = setTimeout(() => setTimeLeft((t) => t - 1), 1000)
    return () => clearTimeout(id)
  }, [timeLeft, submitted, expired, questionId, onAnswer])

  const handleSubmit = useCallback(() => {
    const answer = selected || customInput.trim()
    if (!answer && !expired) return
    if (submitted) return
    setSubmitted(true)
    onAnswer(questionId, answer)
  }, [selected, customInput, expired, submitted, questionId, onAnswer])

  const minutes = Math.floor(timeLeft / 60)
  const seconds = timeLeft % 60

  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
      className="my-3 w-full"
    >
      <div
        className="rounded-lg overflow-hidden relative"
        style={{
          background: `linear-gradient(135deg, rgba(10,11,22,${0.6 + glassOpacity * 2}) 0%, rgba(15,16,28,${0.65 + glassOpacity * 2}) 100%)`,
          backdropFilter: `blur(${glassBlur}px)`,
          WebkitBackdropFilter: `blur(${glassBlur}px)`,
          borderLeft: `2px solid ${glowColor}`,
          border: `1px solid ${glowColor}20`,
          boxShadow: `
            inset 0 1px 1px rgba(255,255,255,0.04),
            inset 0 -1px 1px rgba(0,0,0,0.5),
            0 0 0 1px rgba(0,0,0,0.6),
            0 4px 20px rgba(0,0,0,0.4)
          `,
        }}
      >
        {/* Edge fresnel */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background: `
              linear-gradient(90deg, ${shimmerPrimary}06 0%, transparent 20%, transparent 80%, ${shimmerPrimary}06 100%),
              linear-gradient(0deg, ${shimmerPrimary}04 0%, transparent 20%, transparent 80%, ${shimmerPrimary}04 100%)
            `,
            borderRadius: "10px",
          }}
        />

        <div className="relative p-3">
          {/* Header */}
          <div className="flex items-center gap-2 mb-2.5">
            <HelpCircle size={12} style={{ color: glowColor }} />
            <span className="text-[10px] font-semibold tracking-wide uppercase" style={{ color: glowColor }}>
              Question
            </span>
            <div className="ml-auto flex items-center gap-1 text-[9px] tabular-nums"
              style={{ color: timeLeft <= 10 ? "rgba(239,68,68,0.8)" : "rgba(255,255,255,0.3)" }}>
              <Clock size={9} />
              {minutes}:{seconds.toString().padStart(2, "0")}
            </div>
          </div>

          {/* Question text */}
          <p className="text-[11px] leading-relaxed mb-2.5 font-medium"
            style={{ color: "rgba(255,255,255,0.7)" }}>
            {text}
          </p>

          {/* Options */}
          {options.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-2.5">
              {options.map((opt) => {
                const isSelected = selected === opt
                return (
                  <button
                    key={opt}
                    onClick={() => { setSelected(opt); setCustomInput("") }}
                    disabled={submitted && !isSelected}
                    className="px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all duration-150 hover:brightness-125"
                    style={{
                      color: isSelected ? glowColor : "rgba(255,255,255,0.5)",
                      backgroundColor: isSelected ? `${glowColor}15` : "rgba(255,255,255,0.04)",
                      border: isSelected ? `1px solid ${glowColor}40` : "1px solid rgba(255,255,255,0.08)",
                    }}
                  >
                    {opt}
                  </button>
                )
              })}
            </div>
          )}

          {/* Custom input (allow_other) */}
          {allowOther && (
            <div className="mb-2.5 flex gap-1.5">
              <input
                type="text"
                value={customInput}
                onChange={(e) => { setCustomInput(e.target.value); setSelected(null) }}
                placeholder="Type your answer..."
                disabled={submitted}
                className="flex-1 px-2.5 py-1 rounded-lg text-[11px] outline-none transition-all duration-150"
                style={{
                  color: "rgba(255,255,255,0.6)",
                  backgroundColor: "rgba(255,255,255,0.04)",
                  border: `1px solid rgba(255,255,255,0.08)`,
                }}
                onFocus={(e) => {
                  e.currentTarget.style.borderColor = `${glowColor}40`
                  e.currentTarget.style.boxShadow = `0 0 0 2px ${glowColor}10`
                }}
                onBlur={(e) => {
                  e.currentTarget.style.borderColor = "rgba(255,255,255,0.08)"
                  e.currentTarget.style.boxShadow = "none"
                }}
              />
            </div>
          )}

          {/* Submit */}
          {!submitted && !expired && (
            <div className="flex gap-1.5 pt-1.5 border-t items-center"
              style={{ borderColor: "rgba(255,255,255,0.06)" }}>
              <button
                onClick={handleSubmit}
                disabled={!selected && !customInput.trim()}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium tracking-wide transition-all duration-150 hover:brightness-125 disabled:opacity-30"
                style={{
                  color: glowColor,
                  backgroundColor: `${glowColor}12`,
                  border: `1px solid ${glowColor}30`,
                }}
              >
                <Send size={10} />
                Submit Answer
              </button>
              <span className="flex items-center text-[9px] ml-1"
                style={{ color: "rgba(255,255,255,0.2)" }}>
                <Mic size={9} className="mr-1" />
                or speak
              </span>
            </div>
          )}

          {/* Submitted state */}
          {submitted && (
            <div className="flex items-center gap-1.5 py-1.5 text-[11px] font-medium"
              style={{ color: "#22c55e" }}>
              <Send size={12} />
              Answer submitted
            </div>
          )}

          {/* Expired state */}
          {expired && !submitted && (
            <div className="flex items-center gap-1.5 py-1.5 text-[11px] font-medium"
              style={{ color: "rgba(239,68,68,0.8)" }}>
              Timed out
            </div>
          )}
        </div>
      </div>
    </motion.div>
  )
}