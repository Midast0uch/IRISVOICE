"use client"

import React, { useState, useEffect, useCallback } from "react"
import { motion } from "framer-motion"
import { Clock, Send } from "lucide-react"
import { useBrandColor } from "@/contexts/BrandColorContext"

export interface QuestionCardProps {
  questionId: string
  text: string
  options?: string[]
  allowOther?: boolean
  timeoutSeconds?: number
  onAnswer: (id: string, answer: string) => void
}

/**
 * QuestionCard — inline agent question in the chat stream.
 * Orbital (borderless) treatment: glowing action core + "Asking You" action
 * badge. Option pills render the agent-provided choices verbatim (never
 * hardcoded) — short and task-relevant by construction. Glow tracks the brand
 * color (XurOrb).
 */
export function QuestionCard({
  questionId,
  text,
  options = [],
  allowOther = false,
  timeoutSeconds = 30,
  onAnswer,
}: QuestionCardProps) {
  const { getThemeConfig } = useBrandColor()
  const brandTheme = getThemeConfig()
  const glowColor = brandTheme.glow.color || "#00d4ff"

  const [timeLeft, setTimeLeft] = useState(timeoutSeconds)
  const [customAnswer, setCustomAnswer] = useState("")

  useEffect(() => {
    if (timeLeft <= 0) return
    const timer = setInterval(() => {
      setTimeLeft((t) => Math.max(0, t - 1))
    }, 1000)
    return () => clearInterval(timer)
  }, [timeLeft])

  const handleAnswer = useCallback(
    (answer: string) => {
      if (answer.trim()) onAnswer(questionId, answer.trim())
    },
    [onAnswer, questionId]
  )

  const minutes = Math.floor(timeLeft / 60)
  const seconds = timeLeft % 60

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
      className="my-2 w-full"
    >
      {/* Header: action core + action badge + timer */}
      <div className="flex items-center gap-2.5 mb-2.5">
        <span
          className="relative shrink-0"
          style={{
            width: 10,
            height: 10,
            borderRadius: "50%",
            background: `radial-gradient(circle at 35% 30%, #aef3ff, ${glowColor} 60%, #006b8a)`,
            boxShadow: `0 0 10px ${glowColor}, inset 0 0 4px rgba(255,255,255,0.6)`,
          }}
        />
        <span
          className="px-1.5 py-0.5 rounded text-[9px] font-semibold tracking-wide uppercase"
          style={{
            color: glowColor,
            backgroundColor: `${glowColor}1a`,
            border: `1px solid ${glowColor}30`,
          }}
        >
          Asking You
        </span>
        <div
          className="ml-auto flex items-center gap-1 text-[9px] tabular-nums"
          style={{
            color:
              timeLeft <= 10 ? "rgba(239,68,68,0.8)" : "rgba(255,255,255,0.3)",
          }}
        >
          <Clock size={9} />
          {minutes}:{seconds.toString().padStart(2, "0")}
        </div>
      </div>

      <p className="text-[11px] leading-snug mb-2" style={{ color: "rgba(255,255,255,0.9)" }}>
        {text}
      </p>

      {options.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {options.map((opt, i) => (
            <button
              key={i}
              type="button"
              onClick={() => handleAnswer(opt)}
              className="px-2.5 py-1 rounded text-[10px] transition-colors"
              style={{
                color: "rgba(255,255,255,0.85)",
                border: `1px solid ${glowColor}30`,
                backgroundColor: "rgba(255,255,255,0.04)",
              }}
            >
              {opt}
            </button>
          ))}
        </div>
      )}

      {allowOther && (
        <div className="flex items-center gap-1.5">
          <input
            type="text"
            value={customAnswer}
            onChange={(e) => setCustomAnswer(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleAnswer(customAnswer)
            }}
            placeholder="Type your answer…"
            className="flex-1 px-2 py-1 rounded text-[10px] outline-none"
            style={{
              color: "rgba(255,255,255,0.9)",
              backgroundColor: "rgba(0,0,0,0.3)",
              border: `1px solid ${glowColor}30`,
            }}
          />
          <button
            type="button"
            onClick={() => handleAnswer(customAnswer)}
            className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-semibold"
            style={{ color: "#05060c", backgroundColor: glowColor }}
          >
            <Send size={11} />
            Send
          </button>
        </div>
      )}
    </motion.div>
  )
}
