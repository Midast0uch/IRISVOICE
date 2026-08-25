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

import React, { useEffect, useState } from "react"
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
  /**
   * True when ANY wing is open. During an active run the orb is swallowed into
   * the tier (REQ-16 AC2) and the tier becomes the sole working indicator —
   * orb and tier are never both visible while a wing is open.
   */
  wingOpen?: boolean
  /** Same signature ChatView uses: sendMessage("question_response", {...}). */
  sendMessage?: (type: string, payload: Record<string, unknown>) => void
  /**
   * THE SOCKET'S authoritative thread id (NavigationContext.currentConversationId,
   * which is localStorage-backed and re-synced on reconnect). REQ-16 AC4's
   * inline ask must send this and nothing else — see the note at submitAsk.
   */
  conversationId?: string
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
  wingOpen = false,
  sendMessage,
  conversationId,
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
  // Swallow travel (T19): false for one frame after a wing opens so the tier
  // starts AT the orb's centre and transitions out to its anchor. Without the
  // frame gap the browser coalesces both positions into one style and there is
  // no animation to see.
  const [settled, setSettled] = useState(false)
  useEffect(() => {
    if (!wingOpen) {
      setSettled(false)
      return
    }
    const id = requestAnimationFrame(() => setSettled(true))
    return () => cancelAnimationFrame(id)
  }, [wingOpen])

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

  // ── WHO OWNS THE PROGRESS DISPLAY RIGHT NOW ─────────────────────────────
  //
  // One rule: THE TIER SHOWS ONLY WHAT NO VISIBLE SURFACE IS ALREADY SHOWING.
  //
  // Retiring OrbBadge removed one duplicate indicator; naively always showing
  // the unified counter here would immediately introduce another. With ChatView
  // open on a live TaskListCard reading [3/7], a tier beside the orb also
  // reading [3/7] is the same debt in a new place.
  //
  //   browser panel visible  -> the shutter shows the crawl -> tier drops pages
  //   ChatView + live card   -> the card shows the steps    -> tier drops steps
  //   both                   -> nothing left to add         -> minimal dot
  //   neither                -> the tier is the ONLY indicator -> show both
  //
  // "Live card" reuses chat-view's own predicate (chat-view.tsx:590,
  // `taskProgressStillRunning`): the card drives its indicator only while a
  // step is still unresolved. Once every step is done the card goes static and
  // the tier legitimately speaks again for the synthesis phase — the same gap
  // that measured 79s of silent UI in chat-view's note.
  const cardLive =
    taskProgress.steps.length > 0 &&
    taskProgress.steps.some(
      (st) => st.status === "working" || st.status === "pending" || st.status === "unknown",
    )
  const cardOwnsSteps = chatVisible && cardLive
  const panelOwnsPages = panelVisible

  const { done, total } = unifiedProgress(
    cardOwnsSteps
      ? { current: 0, total: 0 }
      : { current: taskProgress.currentStep, total: taskProgress.totalSteps },
    panelOwnsPages
      ? { done: 0, total: null }
      : { done: crawl.pages.length, total: crawl.total ?? null },
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

  // ── INLINE ASK (REQ-16 AC4, T20) ────────────────────────────────────────
  //
  // THREAD IDENTITY IS THE WHOLE RISK HERE, not the input box.
  //
  // `text_message` is deliberately EXCLUDED from the socket's SUPPLY_IF_MISSING
  // set (useIRISWebSocket.ts:1754): sending it without a conversation_id lets
  // the backend fall back to session_id, and sending it with a STALE one files
  // the message into the wrong thread. Both have already happened here — the
  // hook's own comment records four kernels constructed for a single question,
  // and chat-view.tsx:1828 records every new conversation collapsing into one
  // session-keyed thread.
  //
  // So this does NOT re-derive an id, and does NOT fall back to a stored one.
  // It sends ONLY the socket's authoritative `currentConversationId`, and when
  // there is none it refuses to send at all. A missing id is a visible
  // failure; a wrong-but-plausible one silently corrupts thread history.
  const canAsk = !!sendMessage && !!conversationId
  const [asking, setAsking] = useState(false)
  const [askDraft, setAskDraft] = useState("")

  function submitAsk() {
    const text = askDraft.trim()
    if (!text || !conversationId) return
    sendMessage?.("text_message", { text, conversation_id: conversationId })
    setAskDraft("")
    setAsking(false)
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

  // Minimal tier: every reading the tier could contribute is already on screen
  // somewhere else, so it degrades to a presence dot rather than repeating it.
  // Still shown (not nulled) because "the agent is working" is itself
  // information the other surfaces do not carry once they go static.
  if (panelVisible && !hasCounter && !askInline) {
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

  // Nothing left to say and no panel dot to fall back on — render nothing
  // rather than an empty pill beside the orb. Reachable when ChatView owns the
  // steps and there is no crawl, which is the common case for a plain chat turn.
  if (!hasCounter && !askInline && !statusLine) return null

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

  // ── SWALLOW / RELEASE (REQ-16 AC2/AC3, T19) ─────────────────────────────
  //
  // While a wing is open during an active run the orb is hidden and the tier
  // is the sole working indicator (`swallowed`). The tier slides from the
  // orb's centre out to its anchor, so the orb reads as having been ABSORBED
  // rather than simply vanishing while a separate pill appears.
  //
  // The mutual exclusivity is a HARD contract and is enforced at the ORB, not
  // here — a component cannot guarantee something about a sibling it does not
  // render. XurOrb hides itself on the same predicate; this only animates.
  //
  // Reduced motion (AC7): opacity only, no travel.
  const swallowed = wingOpen
  // Mid-swallow the tier sits on the orb's centre; settled, it rests at the
  // anchor. Reduced motion skips the travel entirely (AC7).
  const x = swallowed && !settled && !reducedMotion ? 0 : anchorOffset
  return (
    <div
      className="fixed top-1/2 left-1/2 z-40 flex items-center gap-3 pl-1 pr-4 py-1 rounded-full"
      data-swallowed={swallowed ? "true" : "false"}
      style={{
        transform: `translate(${x}px, -50%)`,
        opacity: swallowed && !settled && !reducedMotion ? 0.4 : 1,
        transition: reducedMotion
          ? "opacity 200ms linear"
          : "transform 450ms cubic-bezier(0.4, 0, 0.2, 1), opacity 450ms ease-in-out",
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
      <div
        className="relative shrink-0"
        style={{ width: RING, height: RING, pointerEvents: canAsk ? "auto" : "none" }}
        onClick={canAsk ? () => setAsking((v) => !v) : undefined}
        role={canAsk ? "button" : undefined}
        tabIndex={canAsk ? 0 : undefined}
        aria-label={canAsk ? "Ask the agent" : undefined}
        data-testid="tier-counter-form"
      >
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
        <style>{`
          @keyframes iris-tier-sweep {
            from { transform: rotate(0deg); }
            to   { transform: rotate(360deg); }
          }
        `}</style>
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
          {hasCounter ? (
            /* DETERMINATE. Eased on the SAME curve and duration as the swallow
               (450ms cubic-bezier) so a wing opening mid-run does not produce
               two competing tempos on one element — the ring settling and the
               tier travelling read as one gesture. */
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
                  : { transition: "stroke-dashoffset 450ms cubic-bezier(0.4, 0, 0.2, 1)" }
              }
            />
          ) : (
            /* INDETERMINATE. Work is happening but nothing is countable yet —
               a crawl before its total arrives, or a task with no plan. An
               empty ring here reads as "0% done", which is wrong and worrying;
               a slow sweep reads as "working, extent unknown". Same stroke and
               colour, so it is the same instrument in a different mode rather
               than a second spinner idiom. */
            !reducedMotion && (
              <circle
                data-testid="tier-ring-indeterminate"
                cx={RING / 2}
                cy={RING / 2}
                r={R}
                fill="none"
                stroke={glowColor}
                strokeWidth={2}
                strokeLinecap="round"
                strokeDasharray={`${CIRC * 0.22} ${CIRC}`}
                style={{
                  transformOrigin: "50% 50%",
                  animation: "iris-tier-sweep 1.6s linear infinite",
                  opacity: 0.75,
                }}
              />
            )
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
      ) : asking && canAsk ? (
        <input
          autoFocus
          value={askDraft}
          onChange={(e) => setAskDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submitAsk()
            if (e.key === "Escape") setAsking(false)
          }}
          placeholder="Ask…"
          aria-label="Ask the agent"
          data-testid="tier-ask-input"
          className="text-[10px] font-mono px-2 py-1 rounded-md bg-transparent outline-none"
          style={{
            pointerEvents: "auto",
            color: "rgba(255,255,255,0.92)",
            border: `1px solid ${glowColor}35`,
            minWidth: 180,
          }}
        />
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
