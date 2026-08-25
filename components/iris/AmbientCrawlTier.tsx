"use client"

/**
 * AmbientCrawlTier — REQ-6 (T11) and REQ-16 (T18, the OrbBadge retirement).
 *
 * The visual framework used to live ONLY inside the browser sub-app of the
 * DashboardWing — invisible whenever the wing was closed or chat-spotlighted.
 * This tier carries the crawl/vision grammar on a wing-independent surface so
 * the agent's work is visible WHEREVER the user is.
 *
 * REQ-16: THIS TIER REPLACES OrbBadge EVERYWHERE. There is now ONE working
 * indicator with ONE grammar, instead of a badge stuck to the orb for tasks
 * and a separate tier for crawls. The badge could only ever show a step
 * counter; the tier shows steps AND crawl pages on the same footing (AC5),
 * which is what the user actually needs to read: "how much work is left",
 * not "how many of one particular KIND of work is left".
 *
 * COUNTER FORM (AC1) — no mini orb thumbnail. An earlier draft put a small
 * orb to the left of the counter; the user rejected it. The tier IS the
 * counter: a radial progress ring around a CardChassis-grammar `[done/total]`
 * bubble, with the OrbCanvas particles BEHIND it rather than beside it.
 *
 * Contract:
 *  - Consumes CrawlProvider + useTaskProgress directly (single source of
 *    truth — NO duplicate window listeners, AC4).
 *  - Panel open & visible -> MINIMAL (a dot); the full shutter stays primary.
 *  - Panel closed/obscured -> ACTIVE counter form.
 *  - prefers-reduced-motion -> static, no particles, no ring animation (AC7).
 *
 * OPT GATE (T11/T18): returns NULL when idle — no rAF, no timers while
 * nothing is working; reuses OrbCanvas rather than importing a second
 * particle engine; the ring is one SVG circle, not a per-frame canvas.
 */

import React, { useState } from "react"
import { useCrawlContext } from "@/hooks/CrawlProvider"
import { useReducedMotion } from "@/hooks/useReducedMotion"
import { useTaskProgress } from "@/hooks/useTaskProgress"
import { useAgentQuestion } from "@/hooks/useAgentQuestion"
import { OrbCanvas } from "@/components/iris/orb/OrbCanvas"

export interface AmbientCrawlTierProps {
  glowColor: string
  /** True when the browser panel is actually on screen and unobscured. */
  panelVisible: boolean
  /**
   * True when ChatView is on screen. A pending question is answerable INLINE
   * here only when it is NOT — otherwise QuestionCard already owns it and two
   * answer surfaces for one question is how double-submits happen.
   */
  chatVisible?: boolean
  /** Live orb diameter in px, so the tier can sit beside it without overlap. */
  orbDiameter?: number
  /** Same signature ChatView uses: sendMessage("question_response", {...}). */
  sendMessage?: (type: string, payload: Record<string, unknown>) => void
}

const RING = 44 // px — matches the tier's original w-11/h-11 orb footprint
const R = 19 // ring radius inside the 44x44 viewBox
const CIRC = 2 * Math.PI * R

/**
 * Unified done/total across BOTH kinds of work (REQ-16 AC5).
 *
 * Steps and crawl pages are summed rather than shown as two counters: the
 * user is reading one number for "work remaining", and a crawl that runs
 * inside a task would otherwise present two competing progress readings.
 *
 * NEVER returns [0/0] — a total of 0 means there is nothing countable to
 * show, and the caller renders the form without a counter rather than an
 * empty well (same rule as CardChassis' zero-step case).
 */
export function unifiedProgress(
  steps: { current: number; total: number },
  pages: { done: number; total: number | null },
): { done: number; total: number } {
  const stepTotal = steps.total > 0 ? steps.total : 0
  const pageTotal = pages.total && pages.total > 0 ? pages.total : 0
  const total = stepTotal + pageTotal
  if (total <= 0) return { done: 0, total: 0 }
  // Clamp each side to its own total so a late-arriving event cannot push the
  // reading past 100% (crawl page events can outrun the announced total).
  const done = Math.min(steps.current, stepTotal) + Math.min(pages.done, pageTotal)
  return { done: Math.min(done, total), total }
}

export function AmbientCrawlTier({
  glowColor,
  panelVisible,
  chatVisible = false,
  orbDiameter = 175,
  sendMessage,
}: AmbientCrawlTierProps) {
  const { state: crawl } = useCrawlContext()
  const taskProgress = useTaskProgress()
  const agentQuestion = useAgentQuestion()
  const reducedMotion = useReducedMotion()
  // Per-question, because AskUserQuestion emits a SET: each question resolves
  // independently through its own question_id (ask_user_tool.py REQ-6), so one
  // answered question must not close or block the others.
  const [answered, setAnswered] = useState<Record<string, true>>({})
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [picks, setPicks] = useState<Record<string, string[]>>({})

  const pendingQuestion = agentQuestion.hasPendingQuestion
  // REQ-16: the tier now answers for background TASKS too, not just crawls —
  // that is what lets OrbBadge be retired rather than merely duplicated.
  const active = crawl.active || taskProgress.isWorking || pendingQuestion
  if (!active) return null

  const lastAction =
    crawl.visionActions.length > 0
      ? crawl.visionActions[crawl.visionActions.length - 1]
      : null
  const actionWord = lastAction?.kind ? `${lastAction.kind}ing` : ""

  const { done, total } = unifiedProgress(
    { current: taskProgress.currentStep, total: taskProgress.totalSteps },
    { done: crawl.pages.length, total: crawl.total ?? null },
  )
  const hasCounter = total > 0
  const pct = hasCounter ? done / total : 0

  // ── Answerable question (REQ-16, user-directed 2026-08-25) ──────────────
  // A "?" glyph only told the user a question existed SOMEWHERE. When
  // ChatView is not on screen there is nowhere to go and answer it, so the
  // tier carries the question itself plus its options or a free-text input.
  //
  // Gated on !chatVisible deliberately: when ChatView IS up, QuestionCard
  // owns the question. Two live answer surfaces for one question_id is how
  // double-submits happen.
  const openQuestions = agentQuestion.questions.filter((q) => !answered[q.questionId])
  const askInline = pendingQuestion && !chatVisible && openQuestions.length > 0

  function submitAnswer(
    questionId: string,
    answer: string | string[],
    source: "click" | "text",
  ) {
    const value = Array.isArray(answer) ? answer.filter(Boolean) : answer.trim()
    if (!questionId || value.length === 0) return
    // The SAME call ChatView's QuestionCard makes — not a new message shape.
    sendMessage?.("question_response", { question_id: questionId, answer: value, source })
    // Latch locally so this question closes immediately; the authoritative
    // clear still arrives via iris:question_answered.
    setAnswered((prev) => ({ ...prev, [questionId]: true }))
    setDrafts((prev) => ({ ...prev, [questionId]: "" }))
  }

  function togglePick(questionId: string, opt: string) {
    setPicks((prev) => {
      const cur = prev[questionId] || []
      return {
        ...prev,
        [questionId]: cur.includes(opt) ? cur.filter((o) => o !== opt) : [...cur, opt],
      }
    })
  }

  const statusLine = [
    crawl.query,
    lastAction ? `vision ${actionWord}` : "",
  ]
    .filter(Boolean)
    .join(" · ")

  // Minimal tier: the panel is the primary surface — just a presence dot.
  if (panelVisible) {
    return (
      <div
        className="fixed bottom-4 left-1/2 -translate-x-1/2 z-40 flex items-center gap-1.5 px-2 h-5 rounded-full pointer-events-none"
        style={{ background: "rgba(4,8,12,0.55)", border: `1px solid ${glowColor}22` }}
        role="status"
        aria-live="polite"
      >
        <span className="w-1 h-1 rounded-full" style={{ background: glowColor }} />
        <span className="text-[8px] font-mono tracking-wider" style={{ color: `${glowColor}aa` }}>
          {pendingQuestion ? "ASKING" : "READING"}
        </span>
      </div>
    )
  }

  // ── COUNTER FORM (REQ-16 AC1) ────────────────────────────────────────────
  //
  // ANCHORED BESIDE THE ORB, not parked at the bottom of the screen. The orb
  // is the thing the user is looking at, so the working indicator belongs next
  // to it. Offset is computed from the LIVE orb diameter (it ranges 60-400px
  // with wing state), so the gap is constant and overlap is impossible by
  // construction rather than by a hardcoded guess that only holds at one size.
  //
  // Right side specifically: the orb's own labels occupy bottom (Chat), top
  // (Menu) and left (Voice) — right is the only free edge, which is also why
  // the retired badge lived at top-right.
  const anchorOffset = orbDiameter / 2 + 18
  return (
    <div
      className="fixed top-1/2 left-1/2 z-40 flex items-center gap-3 pl-1 pr-4 py-1 rounded-full"
      style={{
        transform: `translate(${anchorOffset}px, -50%)`,
        background: "rgba(4,8,12,0.72)",
        border: `1px solid ${glowColor}33`,
        boxShadow: `0 0 18px ${glowColor}22`,
        // The counter itself never intercepts the orb's drag/click; only the
        // question surface below opts back in.
        pointerEvents: "none",
      }}
      role="status"
      aria-live="polite"
      data-testid="ambient-crawl-tier"
    >
      <div className="relative shrink-0" style={{ width: RING, height: RING }}>
        {/* Particles BEHIND the counter, not beside it. */}
        {!reducedMotion && (
          <div className="absolute inset-0">
            <OrbCanvas
              glowColor={glowColor}
              breathMode={lastAction ? "D" : "A"}
              breathLevel={0.45}
              isBreathing
              glowActive
              animationMode={null}
              animActive={false}
              size={RING}
            />
          </div>
        )}

        {/* Radial progress ring. One SVG, no per-frame work: the dash offset
            is derived from the counter the WS path already delivers. */}
        <svg
          className="absolute inset-0 -rotate-90"
          width={RING}
          height={RING}
          viewBox={`0 0 ${RING} ${RING}`}
          aria-hidden="true"
        >
          <circle
            cx={RING / 2}
            cy={RING / 2}
            r={R}
            fill="none"
            stroke={`${glowColor}22`}
            strokeWidth={2}
          />
          {hasCounter && (
            <circle
              cx={RING / 2}
              cy={RING / 2}
              r={R}
              fill="none"
              stroke={glowColor}
              strokeWidth={2}
              strokeLinecap="round"
              strokeDasharray={CIRC}
              strokeDashoffset={CIRC * (1 - pct)}
              style={
                reducedMotion
                  ? undefined
                  : { transition: "stroke-dashoffset 400ms ease-out" }
              }
            />
          )}
        </svg>

        {/* CardChassis counter grammar, centred in the ring. A pending
            question outranks the count: it is the one state that needs the
            user, so it takes the glyph. */}
        <div className="absolute inset-0 flex items-center justify-center">
          {pendingQuestion ? (
            <span
              data-testid="tier-question-glyph"
              className="text-[13px] font-mono font-bold leading-none"
              style={{
                color: glowColor,
                textShadow: `0 0 16px ${glowColor}55, 0 0 4px ${glowColor}88`,
              }}
            >
              ?
            </span>
          ) : hasCounter ? (
            <span
              data-testid="tier-counter"
              className="text-[9.5px] font-mono font-bold px-1 py-0.5 rounded-md tabular-nums leading-none"
              style={{
                color: glowColor,
                background: `${glowColor}12`,
                border: `1px solid ${glowColor}25`,
              }}
            >
              [{done}/{total}]
            </span>
          ) : null}
        </div>
      </div>

      {askInline ? (
        <div
          className="flex flex-col gap-2 py-1"
          style={{ pointerEvents: "auto", maxWidth: "min(52vw, 420px)" }}
          data-testid="tier-question"
        >
          {openQuestions.map((q) => {
            const sel = picks[q.questionId] || []
            const hasOptions = !!q.options && q.options.length > 0
            return (
              <div key={q.questionId} className="flex flex-col gap-1.5">
                {q.header ? (
                  <span
                    className="text-[8px] font-mono tracking-widest uppercase"
                    style={{ color: `${glowColor}aa` }}
                  >
                    {q.header}
                  </span>
                ) : null}
                <span
                  className="text-[11px] font-mono leading-snug"
                  style={{ color: "rgba(255,255,255,0.92)" }}
                >
                  {q.text}
                </span>

                {hasOptions ? (
                  <div className="flex flex-wrap gap-1.5">
                    {q.options!.map((opt) => {
                      const picked = sel.includes(opt)
                      return (
                        <button
                          key={opt}
                          type="button"
                          aria-pressed={q.multiSelect ? picked : undefined}
                          onClick={() =>
                            q.multiSelect
                              ? togglePick(q.questionId, opt)
                              : submitAnswer(q.questionId, opt, "click")
                          }
                          className="text-[10px] font-mono px-2 py-1 rounded-md transition-colors"
                          style={{
                            color: glowColor,
                            background: picked ? `${glowColor}30` : `${glowColor}12`,
                            border: `1px solid ${glowColor}${picked ? "70" : "35"}`,
                          }}
                        >
                          {opt}
                        </button>
                      )
                    })}
                    {/* Multi-select needs an explicit commit — clicking an
                        option toggles rather than answers. */}
                    {q.multiSelect ? (
                      <button
                        type="button"
                        disabled={sel.length === 0}
                        onClick={() => submitAnswer(q.questionId, sel, "click")}
                        className="text-[10px] font-mono px-2 py-1 rounded-md transition-colors disabled:opacity-40"
                        style={{
                          color: glowColor,
                          background: `${glowColor}20`,
                          border: `1px solid ${glowColor}55`,
                        }}
                      >
                        SEND
                      </button>
                    ) : null}
                  </div>
                ) : null}

                {/* Free text when the asker allows it, or when there are no
                    options at all — otherwise an open question would be
                    unanswerable from here. */}
                {q.allowOther || !hasOptions ? (
                  <input
                    value={drafts[q.questionId] || ""}
                    onChange={(e) =>
                      setDrafts((prev) => ({ ...prev, [q.questionId]: e.target.value }))
                    }
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        submitAnswer(q.questionId, drafts[q.questionId] || "", "text")
                      }
                    }}
                    placeholder="Answer…"
                    aria-label={q.text}
                    className="text-[10px] font-mono px-2 py-1 rounded-md bg-transparent outline-none"
                    style={{
                      color: "rgba(255,255,255,0.92)",
                      border: `1px solid ${glowColor}35`,
                    }}
                  />
                ) : null}
              </div>
            )
          })}
        </div>
      ) : statusLine ? (
        <span
          className="text-[10px] font-mono tracking-wide whitespace-nowrap truncate"
          style={{ color: "rgba(255,255,255,0.82)", maxWidth: "40vw" }}
        >
          {statusLine}
        </span>
      ) : null}
    </div>
  )
}

export default AmbientCrawlTier
