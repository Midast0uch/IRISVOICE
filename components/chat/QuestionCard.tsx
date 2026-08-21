"use client"

import React, { useState, useEffect, useCallback, useMemo } from "react"
import { Clock, Send, Check } from "lucide-react"
import { useBrandColor } from "@/contexts/BrandColorContext"
import { CardChassis, ChassisBadge } from "@/components/chat/CardChassis"

/**
 * One question in a set (REQ-5). Mirrors the wire shape `ask_set()` emits
 * (`backend/agent/tools/ask_user_tool.py:188-211`), translated to the
 * camelCase this card already used for its legacy single-question props —
 * `question_id` -> `questionId`, `allow_other` -> `allowOther`, `multi_select`
 * -> `multiSelect`.
 */
export interface QuestionSetItem {
  questionId: string
  text: string
  options?: string[]
  allowOther?: boolean
  /** REQ-5 AC3: only this question allows more than one selection. */
  multiSelect?: boolean
  /** REQ-5 AC4: per-question label so questions in a set are distinguishable. */
  header?: string
  /** Backend-reported status, when known ("pending" | "answered" | "timed_out"). */
  status?: string
}

export interface QuestionCardProps {
  // Legacy single-question shape (REQ-5 AC6 back-compat) — the shape
  // chat-view.tsx has always passed. Used whenever `questions` is absent, so
  // an unmodified caller keeps working unchanged.
  questionId?: string
  text?: string
  options?: string[]
  allowOther?: boolean
  // REQ-5 AC1/AC2: a question SET, rendered INSTEAD of the legacy props
  // above when present. `setId` carries through for the aria-label only —
  // each question still resolves independently through the same funnel
  // (REQ-6 edge case: "a multi-question set -> each question resolves
  // independently"), never as one set-level answer.
  setId?: string
  questions?: QuestionSetItem[]
  timeoutSeconds?: number
  /** `answer` is a plain string for a single-select question and a list of
   *  option strings for a `multiSelect` one (REQ-5 AC3). */
  onAnswer: (questionId: string, answer: string | string[], source?: string) => void
}

/**
 * QuestionCard — inline agent question(s) in the chat stream.
 * T10 (REQ-2, REQ-5): renders through the shared `CardChassis` (T8) rather
 * than its own bespoke orbital surface, and renders EVERY question in a set
 * (AC2) — each with its own header, prompt, options and answer control. A
 * per-question `multiSelect` allows more than one selection only where the
 * backend actually set it (AC3); an answered question locks in place while
 * the rest of the set stays live (AC5, edge case). REQ-5 AC6: falls back to
 * the legacy single-question props when no `questions` array is given.
 */
export function QuestionCard({
  questionId,
  text,
  options,
  allowOther,
  setId,
  questions,
  timeoutSeconds = 30,
  onAnswer,
}: QuestionCardProps) {
  const { getThemeConfig } = useBrandColor()
  const brandTheme = getThemeConfig()
  const glowColor = brandTheme.glow.color || "#00d4ff"

  // REQ-5 AC6: render from `questions` when present; otherwise fall back to
  // the legacy top-level single-question props so nothing breaks for a
  // caller that hasn't been updated to pass a set.
  const resolvedQuestions: QuestionSetItem[] = useMemo(() => {
    if (questions && questions.length > 0) return questions
    if (questionId && text) {
      return [{ questionId, text, options: options ?? [], allowOther: !!allowOther }]
    }
    return []
  }, [questions, questionId, text, options, allowOther])

  const [timeLeft, setTimeLeft] = useState(timeoutSeconds)
  // Locally-resolved answers — REQ-5 edge case: "one question answered,
  // others pending -> answered ones lock, pending stay live." The card owns
  // this itself rather than waiting for a prop update, since answering
  // doesn't remove the card until the WHOLE set resolves.
  const [locallyAnswered, setLocallyAnswered] = useState<Record<string, string | string[]>>({})
  const [selections, setSelections] = useState<Record<string, string[]>>({})
  const [customAnswers, setCustomAnswers] = useState<Record<string, string>>({})

  useEffect(() => {
    if (timeLeft <= 0) return
    const timer = setInterval(() => setTimeLeft((t) => Math.max(0, t - 1)), 1000)
    return () => clearInterval(timer)
  }, [timeLeft])

  // A question is locked once WE resolved it locally, or the backend already
  // reports it as non-pending (e.g. a rehydrated set with one question
  // already answered before the card mounted).
  const isAnswered = useCallback(
    (q: QuestionSetItem) => q.questionId in locallyAnswered || (!!q.status && q.status !== "pending"),
    [locallyAnswered]
  )

  const submitAnswer = useCallback(
    (q: QuestionSetItem, answer: string | string[], source?: string) => {
      const cleaned = Array.isArray(answer) ? answer.map((a) => a.trim()).filter(Boolean) : answer.trim()
      if (Array.isArray(cleaned) ? cleaned.length === 0 : !cleaned) return
      setLocallyAnswered((prev) => ({ ...prev, [q.questionId]: cleaned }))
      onAnswer(q.questionId, cleaned, source)
    },
    [onAnswer]
  )

  const toggleSelection = (q: QuestionSetItem, opt: string) => {
    setSelections((prev) => {
      const current = prev[q.questionId] ?? []
      const next = current.includes(opt) ? current.filter((o) => o !== opt) : [...current, opt]
      return { ...prev, [q.questionId]: next }
    })
  }

  const answeredCount = resolvedQuestions.filter(isAnswered).length
  const allAnswered = resolvedQuestions.length > 0 && answeredCount === resolvedQuestions.length

  const minutes = Math.floor(timeLeft / 60)
  const seconds = timeLeft % 60

  return (
    <CardChassis
      veinColor={glowColor}
      isActive={!allAnswered}
      collapsible={false}
      // REQ-5 AC5: bracketed [answered/total] only earns its keep once
      // there's more than one question — a single-question card doesn't need
      // to announce "0/1 answered" for what is obviously one question.
      counter={resolvedQuestions.length > 1 ? { done: answeredCount, total: resolvedQuestions.length } : undefined}
      aria-label={setId ? `Question set ${setId}` : "Question"}
      header={
        <>
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
          <ChassisBadge color={glowColor}>Asking You</ChassisBadge>
          <div
            className="ml-auto flex items-center gap-1 text-[9px] tabular-nums"
            style={{ color: timeLeft <= 10 ? "rgba(239,68,68,0.8)" : "rgba(255,255,255,0.3)" }}
          >
            <Clock size={9} />
            {minutes}:{seconds.toString().padStart(2, "0")}
          </div>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {resolvedQuestions.map((q, idx) => {
          const answered = isAnswered(q)
          const answerValue = locallyAnswered[q.questionId]
          const qOptions = q.options ?? []
          const selected = selections[q.questionId] ?? []
          const customValue = customAnswers[q.questionId] ?? ""

          return (
            <div
              key={q.questionId}
              className="flex flex-col gap-1.5"
              style={{
                paddingTop: idx > 0 ? 8 : 0,
                borderTop: idx > 0 ? "1px solid rgba(255,255,255,0.05)" : "none",
                opacity: answered ? 0.6 : 1,
              }}
            >
              {/* REQ-5 AC4: per-question header, so questions in a set read
                  as distinguishable rather than a single wall of text. */}
              {q.header && <ChassisBadge color={glowColor}>{q.header}</ChassisBadge>}

              <p className="text-[11px] leading-snug" style={{ color: "rgba(255,255,255,0.9)" }}>
                {q.text}
              </p>

              {answered ? (
                // REQ-5 edge case: an answered question locks — no more
                // controls, just confirmation of what was sent (REQ-6 AC4:
                // "confirm resolution in the card, so the user can see the
                // answer landed").
                <div
                  className="flex items-center gap-1.5 text-[10px]"
                  style={{ color: "rgba(255,255,255,0.5)" }}
                >
                  <Check size={11} style={{ color: glowColor }} />
                  {Array.isArray(answerValue) ? answerValue.join(", ") : answerValue || "Answered"}
                </div>
              ) : (
                <>
                  {qOptions.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {qOptions.map((opt, i) => {
                        const isSelected = selected.includes(opt)
                        return (
                          <button
                            key={i}
                            type="button"
                            onClick={() =>
                              q.multiSelect ? toggleSelection(q, opt) : submitAnswer(q, opt, "click")
                            }
                            className="px-2.5 py-1 rounded text-[10px] transition-colors"
                            style={{
                              color: isSelected ? "#05060c" : "rgba(255,255,255,0.85)",
                              border: `1px solid ${glowColor}30`,
                              backgroundColor: isSelected ? glowColor : "rgba(255,255,255,0.04)",
                            }}
                          >
                            {opt}
                          </button>
                        )
                      })}
                      {/* REQ-5 AC3: multi-select needs an explicit submit —
                          a click can't both toggle a checkbox AND commit. */}
                      {q.multiSelect && (
                        <button
                          type="button"
                          onClick={() => submitAnswer(q, selected, "click")}
                          disabled={selected.length === 0}
                          className="flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-semibold disabled:opacity-40"
                          style={{ color: "#05060c", backgroundColor: glowColor }}
                        >
                          <Send size={10} />
                          Submit ({selected.length})
                        </button>
                      )}
                    </div>
                  )}

                  {/* Edge case: empty options + allowOther -> free-text only,
                      still a valid way to answer. */}
                  {q.allowOther && (
                    <div className="flex items-center gap-1.5">
                      <input
                        type="text"
                        value={customValue}
                        onChange={(e) =>
                          setCustomAnswers((prev) => ({ ...prev, [q.questionId]: e.target.value }))
                        }
                        onKeyDown={(e) => {
                          if (e.key === "Enter") submitAnswer(q, customValue, "text")
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
                        onClick={() => submitAnswer(q, customValue, "text")}
                        className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-semibold"
                        style={{ color: "#05060c", backgroundColor: glowColor }}
                      >
                        <Send size={11} />
                        Send
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          )
        })}
      </div>
    </CardChassis>
  )
}
