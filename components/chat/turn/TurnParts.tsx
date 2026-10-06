"use client"

/**
 * TurnParts — the parts of a turn that had no view before Phase 3.
 *
 * The execution audit found two event kinds with no listener at all: live
 * reasoning and backend errors ("you never see them"). With the turn
 * protocol both arrive as numbered parts of their turn, so they render HERE,
 * inside the turn they belong to:
 *
 *   reasoning  -> one quiet line while the turn runs (latest sentence only;
 *                 it never takes over the view). Developer: `THK :`.
 *   notice     -> a muted line (validation failed, budget, recovery...).
 *   error      -> a visible red line in the turn, with Retry when offered.
 *   cancelled  -> "Stopped." so a stopped turn never looks finished.
 *
 * Tool calls, task steps, cards and permission/question prompts still render
 * through their existing views (task card, RichDocument, Permission/Question
 * cards); Phase 4 / reply-surface Phase B move them onto turn parts.
 * No visual redesign here (Phase 3 NOT THIS): sizes and colours follow the
 * bubbles around them.
 */
import React from "react"
import type { TurnRecord } from "@/lib/turns/turnStore"
import { partsOf } from "@/lib/turns/turnStore"

export interface TurnPartsProps {
  turn: TurnRecord
  isDeveloper: boolean
  glowColor: string
  /** Re-send the prompt of an errored turn. Omitted -> no Retry button. */
  onRetry?: () => void
}

/** The last sentence of the streamed reasoning (what the model thinks NOW). */
export function latestSentence(text: string): string {
  const t = text.trim()
  if (!t) return ""
  const parts = t.split(/(?<=[.!?])\s+/)
  return parts[parts.length - 1] || t
}

const ERROR_RED = "#ef4444"

export function ReasoningLine({ turn, isDeveloper }: { turn: TurnRecord; isDeveloper: boolean }) {
  if (turn.status !== "running" || !turn.reasoning.trim()) return null
  const line = latestSentence(turn.reasoning)
  return isDeveloper ? (
    <div className="font-mono text-[11px] flex gap-2 min-w-0" style={{ lineHeight: 1.5 }} data-part="reasoning">
      <span className="flex-none font-bold" style={{ color: "#f2c14e" }}>THK :</span>
      <span className="truncate italic text-white/55">{line}</span>
    </div>
  ) : (
    <div className="text-[11px] leading-snug italic text-white/50 truncate" data-part="reasoning">
      Thinking: {line}
    </div>
  )
}

export function TurnParts({ turn, isDeveloper, glowColor, onRetry }: TurnPartsProps) {
  const notices = partsOf(turn, "notice")
  const errors = partsOf(turn, "error")
  // An errored turn whose backend sent no error part still shows why.
  const endOnlyError = turn.status === "error" && errors.length === 0 ? turn.error || "The turn failed." : null
  const mono = isDeveloper ? "font-mono" : ""
  return (
    <div className="flex flex-col gap-1 mt-1" data-turn-parts={turn.id}>
      <ReasoningLine turn={turn} isDeveloper={isDeveloper} />
      {notices.map((n, i) => (
        <div key={`n${i}`} className={`${mono} text-[11px] leading-snug text-white/45`} data-part="notice">
          {n.message}
        </div>
      ))}
      {errors.map((e, i) => (
        <div
          key={`e${i}`}
          role="alert"
          data-part="error"
          className={`${mono} text-[11.5px] leading-snug rounded px-2 py-1.5 flex items-start gap-2`}
          style={{ color: "#fca5a5", background: "rgba(239,68,68,0.08)", border: `1px solid rgba(239,68,68,0.3)` }}
        >
          <span className="flex-none font-bold" style={{ color: ERROR_RED }}>✕</span>
          <span className="flex-1 min-w-0 break-words">
            {e.recoverable ? "A step failed and IRIS tried again: " : ""}
            {e.message}
          </span>
          {!e.recoverable && onRetry && i === errors.length - 1 && (
            <button
              onClick={onRetry}
              className="flex-none text-[10px] font-medium px-1.5 py-0.5 rounded"
              style={{ color: glowColor, border: `1px solid ${glowColor}40` }}
            >
              Retry
            </button>
          )}
        </div>
      ))}
      {endOnlyError && (
        <div
          role="alert"
          data-part="error"
          className={`${mono} text-[11.5px] leading-snug rounded px-2 py-1.5`}
          style={{ color: "#fca5a5", background: "rgba(239,68,68,0.08)", border: `1px solid rgba(239,68,68,0.3)` }}
        >
          <span className="font-bold mr-2" style={{ color: ERROR_RED }}>✕</span>
          {endOnlyError}
        </div>
      )}
      {turn.status === "cancelled" && (
        <div className={`${mono} text-[11px] text-white/45`} data-part="cancelled">
          ■ Stopped. IRIS kept what it finished.
        </div>
      )}
    </div>
  )
}

export default TurnParts
