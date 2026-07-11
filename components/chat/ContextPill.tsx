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

/**
 * ContextPill — compact context-window usage + phase indicator in the chat
 * header. Dark glass, brand-color accents, monospace token count. When the
 * agent reports a live `currentAction` (e.g. while crawling), it is shown
 * instead of the raw phase so the user sees what the assistant is doing.
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
  const phaseLabel = PHASE_LABELS[(phase || "idle").toString()] || (phase || "idle").toString().toUpperCase()
  const actionText = currentAction ? currentAction : phaseLabel

  return (
    <div
      className="flex items-center gap-2 px-2 py-1 rounded-lg"
      style={{
        background: "rgba(10,11,22,0.55)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        border: `1px solid ${glowColor}20`,
      }}
      title={currentAction ? `Context: ${usedTokens} / ${maxTokens} tokens — ${currentAction}` : `Context: ${usedTokens} / ${maxTokens} tokens`}
    >
      <span
        className="text-[9px] font-mono tabular-nums tracking-wide"
        style={{ color: "rgba(255,255,255,0.7)" }}
      >
        {formatTokens(usedTokens)} / {formatTokens(maxTokens)}
      </span>
      <div
        className="w-12 h-[3px] rounded-full overflow-hidden"
        style={{ background: "rgba(255,255,255,0.1)" }}
      >
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{ width: `${pct * 100}%`, background: color }}
        />
      </div>
      <span
        className="text-[9px] font-mono uppercase tracking-wide max-w-[160px] truncate"
        style={{ color: glowColor }}
      >
        {actionText}
      </span>
    </div>
  )
}
