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
import { AnimatePresence, motion } from "framer-motion"
import { useCrawlContext } from "@/hooks/CrawlProvider"
import { useReducedMotion } from "@/hooks/useReducedMotion"
import { useTaskProgress } from "@/hooks/useTaskProgress"
import { useAgentQuestion } from "@/hooks/useAgentQuestion"
import { OrbCanvas } from "@/components/iris/orb/OrbCanvas"
import {
  setSwallowTarget,
  setTierDismissed,
  useTierDismissed,
} from "@/components/iris/swallowTarget"

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
  /**
   * Horizontal offset from the viewport centre for the SWALLOWED card. The
   * orb's spot is not free when one wing is open and maximised — the wing is
   * on it — so the card is placed in the centre of the remaining band instead.
   */
  centerOffsetX?: number
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
// The logo mark sits INSIDE the ring, so it must clear the stroke: the ring's
// usable inner diameter is 2R - strokeWidth = 36px.
const MINI_ORB = 32
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
  centerOffsetX = 0,
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
  // T20's inline-ask state. MUST live here with the other hooks, not down
  // beside submitAsk where it reads more naturally: three early returns sit
  // between there and here, so declaring it below them made the hook COUNT
  // depend on whether the tier had anything to show — 5 hooks idle, 7 active.
  // React crashes on that transition ("Rendered more hooks than during the
  // previous render"), and it only fires when the tier goes idle -> active,
  // which is exactly the transition a component test that always renders one
  // state never performs.
  // The particle field spans the WHOLE card, so it needs the card's live width.
  // A callback ref rather than useRef: the tier returns null while idle, so a
  // ref captured on mount would be null forever and the observer would never
  // attach. This re-runs whenever the node actually appears.
  const [pillEl, setPillEl] = useState<HTMLDivElement | null>(null)
  const [pillW, setPillW] = useState(0)
  useEffect(() => {
    if (!pillEl) return
    const measure = () => setPillW(pillEl.getBoundingClientRect().width)
    measure()
    // ResizeObserver is not universal (absent in jsdom, and in older
    // WebViews). The measurement above already covers the common case — the
    // card's width is stable for a given state — so a missing observer costs
    // live re-measurement, not the particle field.
    if (typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver(measure)
    ro.observe(pillEl)
    return () => ro.disconnect()
  }, [pillEl])

  // Publish the logo slot so XurOrb can fly INTO it (T19). Measured, not
  // guessed: the slot's x depends on the card's width, which depends on the
  // status text. Cleared whenever the tier is not standing in for the orb, so
  // a stale point can never drag the orb somewhere meaningless.
  const [slotEl, setSlotEl] = useState<HTMLDivElement | null>(null)
  useEffect(() => {
    if (!slotEl) {
      setSwallowTarget(null)
      return
    }
    const publish = () => {
      const r = slotEl.getBoundingClientRect()
      setSwallowTarget({ x: r.left + r.width / 2, y: r.top + r.height / 2 })
    }
    publish()
    if (typeof ResizeObserver !== "undefined") {
      const ro = new ResizeObserver(publish)
      ro.observe(slotEl)
      return () => {
        ro.disconnect()
        setSwallowTarget(null)
      }
    }
    return () => setSwallowTarget(null)
  }, [slotEl])

  const dismissed = useTierDismissed()
  const [asking, setAsking] = useState(false)
  const [askDraft, setAskDraft] = useState("")
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

  // A dismissal applies to the run the user dismissed, not to every run after
  // it. Clearing on the idle -> active edge means the next task gets its card
  // back without the user having to undo anything.
  useEffect(() => {
    if (active) return
    setTierDismissed(false)
  }, [active])


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

  // ── THE TWO FORMS ────────────────────────────────────────────────────────
  //
  // Which form shows is decided by ONE fact: is XurOrb on screen?
  //
  // SWALLOWED (a wing is open) — XurOrb is hidden and the tier stands in for
  // it. It therefore CARRIES THE MINI ORB: the orb is the application's logo,
  // and with the real one gone the tier is the only place that identity lives.
  // Dropping it here (an earlier build did) leaves the app with no brand mark
  // at all for the whole time a wing is open.
  //
  // BESIDE (no wings) — XurOrb is right there, so a second orb would be
  // redundant. The tier takes the retired badge's position at the orb's
  // top-right and shows the counter alone, with the particles as the BACKGROUND
  // of its surface rather than as a separate thumbnail.
  //
  // This is also the only state where orb and tier are both visible, and that
  // is deliberate: XurOrb is a movable desktop widget, so the pair has to let
  // the user see progress and speak or type to the agent WITHOUT opening the
  // full interface. That is the whole point of the widget.
  const swallowed = wingOpen

  // Minimal presence dot — only when NOT standing in for the orb. Swallowed,
  // the tier must still render as the orb even with nothing to count.
  const minimalDot = !swallowed && panelVisible && !hasCounter && !askInline
  if (active && minimalDot) {
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
  // RELEASE (REQ-16 AC3). The card used to vanish the instant work finished
  // while the orb animated back — half a gesture. `show` gates the CONTENT, and
  // AnimatePresence plays it out, so the card recedes toward the orb as the orb
  // returns. Both halves on the same 450ms curve, mirroring the swallow.
  const show =
    active && !dismissed && (swallowed || hasCounter || askInline || !!statusLine)

  // ── POSITION ─────────────────────────────────────────────────────────────
  //
  // BESIDE: the retired badge's spot — the orb's top-right, on the 45 degree
  // diagonal just clear of its edge. Top-right specifically because the orb's
  // own labels occupy bottom (Chat), top (Menu) and left (Voice); it is the
  // only free corner, which is why the badge lived there too. Derived from the
  // LIVE diameter (60-400px with wing state) so it cannot overlap at any size.
  //
  // SWALLOWED: centred on the orb's old position, because the tier IS the orb
  // now. The travel between the two is the swallow (T19).
  const r = orbDiameter / 2
  const besideX = r * 0.75 + 22
  const besideY = -(r * 0.75) - 4
  // Mid-swallow the tier sits where the orb was; settled, it rests centred.
  // Reduced motion skips the travel entirely (AC7).
  // The reading (count, or "?" when a question is pending) and the tail
  // (question surface / ask input / status line) are hoisted so the swallowed
  // form can stack them without duplicating either branch.
  const counterNode =
    pendingQuestion ? (
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
        className="text-[10px] font-mono font-bold tabular-nums leading-none"
        style={{
          // NO CHIP. A tinted pill with its own border sat a second bordered
          // shape inside an already-bordered card and muddied both. On the dark
          // ground the numerals can simply BE the reading.
          // Brackets in the accent, numbers in near-white: the accent is the
          // card's rim colour, so using it for everything flattened the reading
          // into the chrome. Splitting them gives the count its own weight and
          // lets the accent do what it is good at — framing.
          color: "rgba(255,255,255,0.97)",
          textShadow: "0 1px 4px rgba(0,0,0,0.85)",
          letterSpacing: "0.02em",
        }}
      >
        <span style={{ color: `${glowColor}cc` }}>[</span>
        {done}
        <span style={{ color: "rgba(255,255,255,0.45)" }}>/</span>
        {total}
        <span style={{ color: `${glowColor}cc` }}>]</span>
      </span>
    ) : null

  const tailNode = askInline ? (
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
          style={{
            color: "rgba(255,255,255,0.95)",
            textShadow: "0 1px 3px rgba(0,0,0,0.6)",
            maxWidth: "40vw",
          }}
        >
          {statusLine}
        </span>
      ) : null

  const tx = swallowed ? (settled || reducedMotion ? centerOffsetX : besideX) : besideX
  const ty = swallowed ? (settled || reducedMotion ? 0 : besideY) : besideY
  return (
    // ZERO-SIZE ANCHOR. The card used to centre itself with
    // `translate(-50% + Xpx)`, which made its own WIDTH part of the transform
    // — and the width changes at the same instant as the swallow (mini orb in,
    // ring out, layout becomes a column). The percentage therefore resolved to
    // a different number mid-transition and the card jumped instead of
    // travelling: the snap.
    // A 0x0 grid centred on the point holds the card centred at ANY size, so
    // the animated transform is pure pixels and `layout` can tween the size
    // change independently.
    <div
      className="fixed top-1/2 left-1/2 z-40"
      style={{ width: 0, height: 0, display: "grid", placeItems: "center" }}
    >
    <AnimatePresence>
    {show && (
    <motion.div
      layout
      initial={{ x: tx, y: ty, opacity: 0, scale: 0.86 }}
      animate={{ x: tx, y: ty, opacity: 1, scale: 1 }}
      exit={{
        // Recede toward the orb's resting point rather than fading in place.
        x: besideX,
        y: besideY,
        opacity: 0,
        scale: 0.86,
      }}
      transition={
        reducedMotion
          ? { duration: 0 }
          : { type: "tween", duration: 0.45, ease: [0.4, 0, 0.2, 1] }
      }
      className={`flex rounded-full ${
        // Swallowed: items-center keeps the two-line block optically centred
        // against the orb, and a tighter gap binds text to mark instead of
        // letting it drift toward the pill's far edge.
        swallowed ? "items-center gap-2.5 pl-1.5 pr-4 py-1.5" : "items-center gap-2 pl-1 pr-2 py-1"
      }`}
      ref={setPillEl}
      data-swallowed={swallowed ? "true" : "false"}
      data-testid="ambient-crawl-tier"
      style={{
        position: "relative",
        // NOTE: no overflow:hidden here. It was clipping the dismiss control,
        // because on a fully-rounded pill the top-right "corner" is a curve
        // that has already fallen away by the time you reach it. The clip
        // belongs to the particle field, which is the only thing that needs
        // it — moved to that layer instead.
        transition: reducedMotion
          ? "opacity 200ms linear"
          : "transform 450ms cubic-bezier(0.4, 0, 0.2, 1), opacity 450ms ease-in-out",
        // GLASS, not a flat scrim. The previous fill was an opaque slab that
        // sat the text on dead ground: nothing behind it showed through, so
        // the pill read as a grey rectangle with the glow only on its rim.
        // Blur + saturate lifts whatever is behind it, the gradient gives the
        // surface a direction, and the inset top highlight is the lit edge
        // that makes it read as glass rather than paint.
        // THE WHOLE CARD IS THE WELL. The well drawn behind the logo turned out
        // to be the right treatment for the entire surface: a deep, nearly
        // opaque ground is what made the mark legible and the type pop, where
        // the translucent glass let the background bleed through and washed
        // both out. Same recipe at card scale — dark radial ground, hard inner
        // shadow, glow rim.
        background:
          "radial-gradient(120% 160% at 50% 0%, rgba(6,12,18,0.97) 0%, rgba(2,5,9,0.985) 70%, rgba(1,3,6,0.99) 100%)",
        // Blur stays, but it is now a subtle lift under an opaque ground rather
        // than the thing the card relies on to be visible.
        backdropFilter: "blur(10px) saturate(1.35)",
        WebkitBackdropFilter: "blur(10px) saturate(1.35)",
        border: `1px solid ${glowColor}88`,
        boxShadow: [
          `0 0 0 1px rgba(0,0,0,0.7)`,
          `0 0 26px ${glowColor}3d`,
          `0 10px 30px rgba(0,0,0,0.7)`,
          `inset 0 1px 0 ${glowColor}4a`,
          `inset 0 0 26px rgba(0,0,0,0.95)`,
        ].join(", "),
        // The counter itself never intercepts the orb's drag/click; only the
        // question surface below opts back in.
        pointerEvents: "none",
      }}
      role="status"
      aria-live="polite"
    >
      {/* MANUAL RELEASE. The widget is draggable and the card can simply be in
          the way, so the user gets an explicit way back to the orb without
          waiting for work to finish. Small and quiet until hovered — this is an
          escape hatch, not a primary action, and it must not compete with the
          reading. Only offered while the card is standing in for the orb;
          beside it the orb is already right there. */}
      {swallowed && (
        <button
          type="button"
          data-testid="tier-dismiss"
          aria-label="Return to the orb"
          title="Return to the orb"
          onClick={(e) => {
            e.stopPropagation()
            setTierDismissed(true)
          }}
          className="flex items-center justify-center rounded-full transition-colors"
          style={{
            // INLINE, not Tailwind classes. As `absolute top-0.5 right-0.5`
            // this landed at the START of the flex row — next to the logo —
            // whenever the utility classes were not applied, because the
            // fallback for a failed `absolute` is normal flex flow. Inline
            // positioning cannot silently degrade that way.
            position: "absolute",
            // Clear of the rounded edge: on a pill the corner is a curve, so a
            // control at (2,2) sits outside the shape entirely. Pulled inward
            // and sized up so it is reachable as well as visible.
            top: 4,
            right: 10,
            width: 16,
            height: 16,
            pointerEvents: "auto",
            zIndex: 2,
            color: "rgba(255,255,255,0.35)",
            background: "rgba(0,0,0,0.35)",
            fontSize: 9,
            lineHeight: 1,
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = "rgba(255,255,255,0.95)"
            e.currentTarget.style.background = `${glowColor}33`
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = "rgba(255,255,255,0.35)"
            e.currentTarget.style.background = "rgba(0,0,0,0.35)"
          }}
        >
          ✕
        </button>
      )}

      {/* AMBIENT PARTICLE FIELD — BESIDE FORM ONLY.
          This is the beside form's share of the orb identity, standing in for
          the mini orb rather than accompanying it: swallowed, the logo inside
          the ring already carries the particles, and running a second field
          behind it would both double the canvases and clutter the mark it is
          meant to showcase.
          Spanning the whole card matters — confined to the 44px ring the
          shells were a dense speck; at card scale they drift the full width
          and the pill reads as a lit surface with something alive behind the
          glass. Sized from the measured card, clipped by the pill's own
          overflow, never interactive. */}
      {!swallowed && !reducedMotion && pillW > 0 && (
        <div
          className="absolute inset-0"
          style={{
            pointerEvents: "none",
            opacity: 0.5,
            // The clip that used to live on the pill. Only the field needs it.
            overflow: "hidden",
            borderRadius: 9999,
          }}
          aria-hidden="true"
          data-testid="tier-particle-field"
        >
          <div
            style={{
              position: "absolute",
              left: "50%",
              top: "50%",
              transform: "translate(-50%, -50%)",
              width: Math.max(pillW, RING),
              height: Math.max(pillW, RING),
            }}
          >
            <OrbCanvas
              glowColor={glowColor}
              breathMode={lastAction ? "D" : "A"}
              breathLevel={0.4}
              isBreathing
              glowActive={false}
              animationMode={null}
              animActive={false}
              size={Math.max(pillW, RING)}
            />
          </div>
        </div>
      )}

      <div
        className="relative shrink-0"
        style={{ width: RING, height: RING, pointerEvents: canAsk ? "auto" : "none" }}
        onClick={canAsk ? () => setAsking((v) => !v) : undefined}
        role={canAsk ? "button" : undefined}
        tabIndex={canAsk ? 0 : undefined}
        aria-label={canAsk ? "Ask the agent" : undefined}
        data-testid="tier-counter-form"
      >
        {/* ── ONE CIRCULAR INSTRUMENT, TWO FILLINGS ──────────────────────
            The ring is the ORB'S OWN HALO, not a second dial parked beside it.
            An earlier build set a 40px logo next to a 44px ring: the same
            shape twice, neither reading as belonging to the other, and the
            ring meaning nothing in particular.
            Wrapping the orb makes the ring's meaning literal — it is the
            orb's progress — and keeps the instrument IDENTICAL across both
            forms. The only thing that changes is what sits inside it. */}
        {swallowed ? (
          <div
            className="absolute"
            style={{
              top: (RING - MINI_ORB) / 2,
              left: (RING - MINI_ORB) / 2,
              width: MINI_ORB,
              height: MINI_ORB,
            }}
            data-testid="tier-mini-orb"
            aria-hidden="true"
            ref={setSlotEl}
          >
            {/* A WELL BEHIND THE MARK. The logo was drawn straight onto the
                glass, so its particles competed with whatever the blur pulled
                through and it read as faint smudge rather than an object. A
                dark recessed disc gives it its own ground, and the outer halo
                separates that ground from the card — contrast on both sides of
                the edge, which is what actually makes a small mark legible. */}
            {/* The card itself is now the dark ground, so the mark needs a LIFT
                against it rather than another well: a faint glow disc so it
                reads as raised, not recessed into an already-black surface. */}
            <div
              style={{
                position: "absolute",
                inset: -5,
                borderRadius: "50%",
                background: `radial-gradient(circle, ${glowColor}1f 0%, ${glowColor}0d 55%, transparent 100%)`,
                boxShadow: `0 0 16px ${glowColor}44`,
              }}
            />
            <div
              style={{
                position: "absolute",
                inset: -2,
                borderRadius: "50%",
                border: `1px solid ${glowColor}55`,
              }}
            />
            <div style={{ position: "relative" }}>
            {reducedMotion ? (
              /* Reduced motion suppresses MOVEMENT, not identity. Gating the
                 mark on it left reduced-motion users with no logo at all for
                 as long as a wing was open. Static mark, same glow grammar. */
              <div
                style={{
                  width: MINI_ORB,
                  height: MINI_ORB,
                  borderRadius: "50%",
                  background: `radial-gradient(circle at 38% 34%, ${glowColor}26 0%, ${glowColor}0f 60%, transparent 100%)`,
                  border: `1px solid ${glowColor}3a`,
                }}
              />
            ) : (
              /* Brightened deliberately. At 32px the shells render far fewer
                 pixels per particle than they do at the orb's 90px, so the same
                 alpha reads much fainter — the mark needs lifting to match its
                 own full-size appearance, not to exceed it. */
              <div style={{ filter: `brightness(1.55) saturate(1.25) drop-shadow(0 0 6px ${glowColor}77)` }}>
                <OrbCanvas
                  glowColor={glowColor}
                  breathMode={lastAction ? "D" : "A"}
                  breathLevel={0.72}
                  isBreathing
                  glowActive
                  animationMode={null}
                  animActive={false}
                  size={MINI_ORB}
                />
              </div>
            )}
            </div>
          </div>
        ) : (
          /* Nothing ring-local here any more: the card-wide field above is
             the surface the counter sits on. A second canvas confined to the
             ring would just be a denser copy of it in the same place. */
          null
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
          {/* Track and progress arc are BESIDE-ONLY. Ringing the logo drowned
              it out — a 2px stroke at 44px sits right on the mark's edge and
              competes with it for the same silhouette. The reading is already
              stacked on the pill when swallowed, so the arc has nothing left
              to say there. */}
          {!swallowed && (
          <circle
            cx={RING / 2}
            cy={RING / 2}
            r={R}
            fill="none"
            stroke={`${glowColor}22`}
            strokeWidth={2}
          />
          )}
          {swallowed ? null : hasCounter ? (
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
          ) : null}
        </svg>

        {/* The counter is centred in the ring ONLY when the ring is empty.
            Swallowed, the orb occupies that centre and the reading moves out
            onto the pill (rendered just below) — stacking text over the logo
            would obscure the mark and make both harder to read. */}
        {!swallowed && (
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
              className="text-[9.5px] font-mono font-bold tabular-nums leading-none"
              style={{
                color: "rgba(255,255,255,0.97)",
                textShadow: "0 1px 4px rgba(0,0,0,0.9)",
              }}
            >
              <span style={{ color: `${glowColor}cc` }}>[</span>
              {done}
              <span style={{ color: "rgba(255,255,255,0.45)" }}>/</span>
              {total}
              <span style={{ color: `${glowColor}cc` }}>]</span>
            </span>
          ) : null}
        </div>
        )}
      </div>

      {swallowed ? (
        /* SWALLOWED LAYOUT — the reading stacks ABOVE the status text and both
           sit tight against the ringed orb. Laid out as one two-line block
           rather than three loose items strung across the pill: a counter
           floating between the orb and the text had nothing to align to and
           read as debris. Top-aligned so the count sits at the container's
           upper edge, mirroring where the retired badge used to sit. */
        <div className="flex flex-col items-start justify-center gap-1 min-w-0">
          {counterNode}
          {tailNode}
        </div>
      ) : (
        tailNode
      )}
    </motion.div>
    )}
    </AnimatePresence>
    </div>
  )
}

export default AmbientCrawlTier
