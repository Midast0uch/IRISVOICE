"use client"

import { useEffect, useRef } from "react"
import { animate, motion, useMotionValue, useReducedMotion, useSpring, useTransform } from "framer-motion"
import { useBrandColor } from "@/contexts/BrandColorContext"

/** CLM's live view (docs/architecture/CLM.md 1.3; backend kernel/context.py
 *  `_context_band`). While nodes run it is the fullest node's view against that
 *  node's own model; at rest it is what the last call put in the window. */
export interface ContextBand {
  now: number
  window: number
  /** Where CLM sets results aside. 0 = it does not (offload off, or at rest). */
  limit: number
  /** The furthest it stretched. */
  peak: number
  /** Results set aside (kept by reference, not lost). */
  aside: number
  asideTokens: number
  /** Nodes running side by side. 0 = at rest. */
  views: number
}

/** The band in a `context:usage` payload; undefined from a backend without one. */
export function bandOf(d: Record<string, unknown>): ContextBand | undefined {
  if (typeof d.now_tokens !== "number") return undefined
  const n = (k: string) => (typeof d[k] === "number" ? (d[k] as number) : 0)
  return {
    now: n("now_tokens"), window: n("now_window"), limit: n("limit_tokens"), peak: n("peak_tokens"),
    aside: n("aside"), asideTokens: n("aside_tokens"), views: n("views"),
  }
}

export interface ContextPillProps {
  usedTokens: number
  maxTokens: number
  phase: string
  /** Live action text from the agent (e.g. "Reading example.com (2/5)"). */
  currentAction?: string
  /** Absent = the plain meter (usedTokens / maxTokens). */
  band?: ContextBand
}

function formatTokens(n: number): string {
  // A 1M window (mercury-3) read "1000.0k"; millions get their own unit.
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
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

const BAND_W = 46
const BAND_H = 12
const REST = 3.4 // the loop's half-height when nothing pulls it
// The pill is fused to ModelSwitcher (both overlap by 8px): x = 2 is the switcher's
// right rim, so the band hangs on the model whose window it fills.
const PEG = 2
const SPAN = BAND_W - PEG - REST

/** Share of the window -> share of the meter. A square root, because real views
 *  live in the first tenth of a 128k window and must still be seen to move; the
 *  exact numbers are the text beside it. */
const reach = (share: number) => Math.sqrt(Math.min(1, Math.max(0, share)))

/** One closed loop held by two pegs, `x` px apart. Pulled out it gets flatter and
 *  thinner (rubber keeps its volume); `pluck` bows both strands the same way. */
function loopPath(x: number, pluck: number): string {
  const len = Math.max(0, x)
  const t = Math.min(1, len / SPAN)
  const r = REST - 1.5 * t
  const waist = r * (1.5 * t - 0.4) // slack bellies out, taut pinches in at the middle
  const l = PEG
  const e = PEG + len
  const m = (l + e) / 2
  const y = BAND_H / 2
  return (
    `M${l} ${y - r}Q${m} ${y - r + waist + pluck} ${e} ${y - r}` +
    `A${r} ${r} 0 0 1 ${e} ${y + r}Q${m} ${y + r - waist + pluck} ${l} ${y + r}` +
    `A${r} ${r} 0 0 1 ${l} ${y - r}Z`
  )
}

/**
 * The band itself. Slack = a small ring on the switcher's rim; a node that reads pulls
 * it long and thin; when CLM sets results aside (or a step ends) it lets go,
 * overshoots and wobbles. Dashes = how far it has been stretched; the bright post
 * = where CLM lets go (drawn only when CLM does).
 */
function RubberBand({
  share, peak, limit, aside, color, glow,
}: { share: number; peak: number; limit: number; aside: number; color: string; glow: string }) {
  const still = useReducedMotion()
  const span = SPAN
  const target = reach(share) * span
  const spring = useSpring(target, { stiffness: 190, damping: 11, mass: 0.7 })
  const pluck = useMotionValue(0)
  const d = useTransform([spring, pluck], ([x, p]: number[]) => loopPath(x, p))
  const width = useTransform(spring, (x: number) => 1.7 - 0.7 * Math.min(1, Math.max(0, x) / span))
  const tip = useTransform(spring, (x: number) => PEG + Math.max(0, x))
  const last = useRef({ target, aside })
  useEffect(() => {
    const was = last.current
    last.current = { target, aside }
    if (still) {
      spring.jump(target)
      return
    }
    spring.set(target)
    // Let go: the strands ring, harder for a longer fall.
    const fell = was.target - target
    if (fell > 1 || aside > was.aside) pluck.set(Math.min(4, 1.6 + fell * 0.12))
    const ring = animate(pluck, 0, { type: "spring", stiffness: 520, damping: 6, mass: 0.5 })
    return () => ring.stop()
  }, [target, aside, still, spring, pluck])
  const at = (n: number) => PEG + reach(n) * span
  const y = BAND_H / 2
  return (
    <svg width={BAND_W} height={BAND_H} viewBox={`0 0 ${BAND_W} ${BAND_H}`} className="relative block overflow-visible" aria-hidden>
      {at(peak) - at(share) > REST + 1 && (
        <line
          data-testid="band-peak" data-at={reach(peak).toFixed(3)}
          x1={at(share) + REST} x2={at(peak)} y1={y} y2={y}
          stroke="rgba(255,255,255,0.28)" strokeWidth={1} strokeDasharray="1.5 2"
        />
      )}
      {limit > 0 && (
        <line
          data-testid="band-limit" data-at={reach(limit).toFixed(3)}
          x1={at(limit)} x2={at(limit)} y1={1.5} y2={BAND_H - 1.5} stroke={glow} strokeWidth={1} strokeLinecap="round"
        />
      )}
      <circle cx={PEG} cy={y} r={1.2} fill={glow} />
      <motion.circle cx={tip} cy={y} r={0.9} fill="rgba(255,255,255,0.8)" />
      <motion.path
        data-testid="band-loop" data-reach={reach(share).toFixed(3)}
        d={d} fill={`${color}14`} stroke={color} style={{ strokeWidth: width, filter: `drop-shadow(0 0 2px ${color}66)` }}
      />
    </svg>
  )
}

/**
 * ContextPill — compact context-window usage + phase indicator in the chat
 * header. Dark glass, brand-color accents, monospace token count. When the
 * agent reports a live `currentAction` (e.g. while crawling), it is shown
 * (truncated) instead of the phase code so the user sees what the assistant
 * is doing.
 *
 * THE METER IS A RUBBER BAND (2026-11-23), see RubberBand: it stretches as a node
 * reads, and springs back when CLM sets results aside or a new node starts small.
 *
 * The denominator is the REAL max_tokens reported by the backend
 * (resolve_context_window of the model in use) via the iris:context_usage
 * event — NOT a hardcoded 128k. Before the first event arrives maxTokens is
 * 0, meaning "unknown", and the denominator renders as "—" rather than a
 * number the backend never sent.
 */
export default function ContextPill({
  usedTokens,
  maxTokens,
  phase,
  currentAction,
  band,
}: ContextPillProps) {
  const { getThemeConfig } = useBrandColor()
  const glowColor = getThemeConfig().glow.color
  const now = band ? band.now : usedTokens
  const max = band ? band.window || maxTokens : maxTokens
  const safeMax = max > 0 ? max : 1
  const share = (n: number) => Math.min(1, Math.max(0, n / safeMax))
  const pct = share(now)
  // How near it is to letting go: against CLM's own limit when there is one, else the
  // window. Red is kept for the window itself, where the router would have to cut.
  const tension = band && band.limit > 0 ? Math.min(0.84, now / band.limit) : pct
  const color = usageColor(Math.max(pct, tension))
  const plain = `Context: ${now} / ${max} tokens`
  const fullTitle = !band
    ? plain
    : [
        band.views > 0
          ? `${plain} — ${band.views > 1 ? `the fullest of ${band.views} steps running` : "the step running now"}`
          : `${plain} — at rest: the last call`,
        band.peak > now ? `Furthest it stretched: ${band.peak}` : "",
        band.limit > 0 ? `It lets go at ${band.limit}: older results are set aside, kept by reference` : "",
        band.aside > 0 ? `${band.aside} set aside (${band.asideTokens} tokens), each can come back` : "",
      ].filter(Boolean).join("\n")
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
          ? `${fullTitle} — ${fullPhase}\n${currentAction}`
          : `${fullTitle} — ${fullPhase}`
      }
    >
      <div
        /* 46x12: the loop needs height to read as a band, and no more than the 9px
           text line has, so the footer keeps its height. */
        className="relative shrink-0"
        style={{ width: BAND_W, height: BAND_H }}
      >
        {/* The window, as a hairline the band is pulled along; the covered part is tinted. */}
        <div className="absolute inset-y-[5.5px] left-0 right-0 rounded-full" style={{ background: "rgba(255,255,255,0.12)" }}>
          <div
            className="h-full rounded-full motion-reduce:transition-none"
            style={{ width: `${reach(pct) * 100}%`, background: color, opacity: 0.3, transition: "width 500ms ease-out" }}
          />
        </div>
        <RubberBand
          share={pct}
          peak={band ? share(Math.max(band.peak, now)) : pct}
          limit={band ? share(band.limit) : 0}
          aside={band?.aside ?? 0}
          color={color}
          glow={glowColor}
        />
      </div>
      <span
        className="text-[9px] font-mono tabular-nums tracking-wide whitespace-nowrap"
        style={{ color: "rgba(255,255,255,0.7)" }}
      >
        {/* 0 = no call measured yet in this thread, not an empty window */}
        {now > 0 ? formatTokens(now) : "—"} / {max > 0 ? formatTokens(max) : "—"}
      </span>
      {band && band.aside > 0 && (
        /* Set aside, not lost: a loose ring and how many. */
        <span
          data-testid="band-aside"
          className="flex items-center gap-[2px] text-[9px] font-mono tabular-nums whitespace-nowrap"
          style={{ color: glowColor, opacity: 0.75 }}
        >
          <i className="inline-block w-[5px] h-[5px] rounded-full border" style={{ borderColor: glowColor }} />
          {band.aside}
        </span>
      )}
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
