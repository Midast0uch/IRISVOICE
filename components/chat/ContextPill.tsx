"use client"

import { useBrandColor } from "@/contexts/BrandColorContext"

export interface ContextPillProps {
  usedTokens: number
  maxTokens: number
  phase: string
  /** Live action text from the agent (e.g. "Reading example.com (2/5)"). */
  currentAction?: string
}

function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return `${n}`
}

function usageColor(pct: number): string {
  if (pct < 0.6) return "#34d399" // green
  if (pct < 0.85) return "#fbbf24" // amber
  return "#f87171" // red
}

// Friendly phase labels — the raw VoiceState enum ("processing_conversation")
// reads as "processing my STT" to users; map it to what's actually happening.
const PHASE_LABELS: Record<string, string> = {
  idle: "IDLE",
  listening: "LISTENING",
  processing_conversation: "WORKING",
  processing_tool: "SEARCHING",
  speaking: "SPEAKING",
  error: "ERROR",
}

// REQ-11 (Wave 8) AC2: compact 2-3 letter phase code for the VISIBLE pill
// label. Full words (WORKING/SEARCHING) overflow the max-w-[160px] pill at
// text-[9px]; the code stays legible. Full phase name stays in `title` only.
const PHASE_CODES: Record<string, string> = {
  idle: "IDL",
  listening: "LSN",
  processing_conversation: "WRK",
  processing_tool: "SRH",
  speaking: "SPK",
  error: "ERR",
}

// REQ-11 AC3: cap the live action text so a long "Reading example.com (2/5)"
// string can NEVER render as a full sentence in the pill. Full text stays in
// `title` only.
const ACTION_CAP = 24

/**
 * ContextPill — compact context-window usage + phase indicator in the chat
 * header. Dark glass, brand-color accents, monospace token count. When the
 * agent reports a live `currentAction` (e.g. while crawling), it is shown
 * (truncated) instead of the phase code so the user sees what the assistant
 * is doing.
 *
 * The denominator is the REAL max_tokens reported by the backend
 * (resolve_context_window of the model in use) via the iris:context_usage
 * event — NOT a hardcoded 128k. The 128000 fallback below is only the
 * cold-start placeholder before the first event arrives.
 */
export default function ContextPill({
  usedTokens,
  maxTokens,
  phase,
  currentAction,
}: ContextPillProps) {
  const { getThemeConfig } = useBrandColor()
  const glowColor = getThemeConfig().glow.color
  const safeMax = maxTokens > 0 ? maxTokens : 1
  const pct = Math.min(1, usedTokens / safeMax)
  const color = usageColor(pct)
  const phaseKey = (phase || "idle").toString()
  const phaseCode = PHASE_CODES[phaseKey] || phaseKey.toUpperCase().slice(0, 3)
  const fullPhase = PHASE_LABELS[phaseKey] || phaseKey.toUpperCase()
  const truncatedAction =
    currentAction && currentAction.length > ACTION_CAP
      ? currentAction.slice(0, ACTION_CAP) + "…"
      : currentAction || ""
  // Visible label = truncated live action if present, else the phase code.
  const actionText = truncatedAction || phaseCode

  return (
      <div
        /* Grows to fill its wrapper, but only to 220px. Uncapped it stretched
           across the whole footer at 680px wing width and dwarfed everything
           else; the wing is 360 / 510 / 680 depending on spotlight state, so
           the row's leftover width is absorbed by ml-auto on the conversation
           chips instead (see chat-view). The pill grows a little, the right
           group slides right, and neither has to swallow the entire band. */
        className="flex items-center justify-end gap-1.5 px-1.5 py-1 pr-2.5 -ml-2 rounded-full max-w-[190px]"
        style={{
        background: "rgba(10,11,22,0.55)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        border: `1px solid ${glowColor}20`,
      }}
      title={
        currentAction
          ? `Context: ${usedTokens} / ${maxTokens} tokens — ${fullPhase}\n${currentAction}`
          : `Context: ${usedTokens} / ${maxTokens} tokens — ${fullPhase}`
      }
    >
      <div
        /* 40px. The meter carries one number; the phase label carries the word
           that says what IRIS is doing, so the meter must not out-measure it.
           At 40px the two read as comparable rather than a long rule beside a
           three-letter tag. */
        className="w-10 shrink-0 h-[3px] rounded-full overflow-hidden"
        style={{ background: "rgba(255,255,255,0.1)" }}
      >
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{ width: `${pct * 100}%`, background: color }}
        />
      </div>
      <span
        className="text-[9px] font-mono tabular-nums tracking-wide whitespace-nowrap"
        style={{ color: "rgba(255,255,255,0.7)" }}
      >
        {formatTokens(usedTokens)} / {formatTokens(maxTokens)}
      </span>
      <span
        /* Sized to its content, NOT flex-1. Stretching it made the pill hold a
           wide empty band between the token count and a three-letter phase,
           which is the disproportion it was meant to fix. The pill now sizes to
           what it actually contains and the row's slack lives outside it. */
        className="text-[9px] font-mono uppercase tracking-wide truncate"
        style={{ color: glowColor }}
      >
        {actionText}
      </span>
    </div>
  )
}
