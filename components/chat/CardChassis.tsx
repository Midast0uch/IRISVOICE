"use client"

import React, { useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ChevronDown } from "lucide-react"
import { Xur } from "@/components/Xur"

/**
 * CardChassis — the ONE Liquid Ink chassis shared by every inline chat card
 * (T8, REQ-1, REQ-2 AC3). Promoted from `temp/task-card-redesign/variants/
 * VariantLiquidInk.tsx` — the exact variant the user chose (Decision 3). The
 * tokens below reproduce it, not an approximation; see design.md "Liquid Ink
 * tokens as built".
 *
 * WHAT LIVES HERE (chassis-level, REQ-2 AC3) vs WHAT DOESN'T:
 *   - the ink surface, the accent vein, the header slot, the bracketed
 *     [done/total] counter and the collapse affordance ARE the chassis.
 *   - REQ-1 AC5 padding is applied HERE, once, so every card inherits it —
 *     a card only ever gets `header` / `subheader` / `children` / `footer`
 *     slots, never the outer element, so it cannot render outside the
 *     padding or omit the vein.
 *   - step lists, question options, permission approve/deny, document body —
 *     those are PER-CARD content and stay in TaskListCard / QuestionCard /
 *     PermissionCard / RichDocument / DocumentPanel (T9-T11a). This file
 *     does not know about any of them.
 *
 * Two deliberate departures from the variant, both required:
 *   1. Decision 15 (type floor) — nothing below 9px; anything carrying
 *      meaning is >=10px. `ChassisBadge` and `ChassisBranchBadge` are fixed
 *      at 10px; `ChassisChromeLabel` and the counter stay at 9-9.5px as
 *      de-emphasized chrome (design.md: "the inline summary and the counter
 *      stay at 9-9.5px").
 *   2. Decision 13 (revised 2026-08-19) — the branch row reads "Diving
 *      Deeper", never "Sub-Loop", never "Detour". `branchLabel` is FREE TEXT
 *      supplied by the caller; `ChassisBranchBadge` never hardcodes a word,
 *      it only renders `↳ {branchLabel}`. The purple treatment is unchanged.
 */

// ── Vein colour (REQ-1 AC2) ─────────────────────────────────────────────────
// Task-card execution states, exported so T9 doesn't invent a second copy.
// Other card types (question/permission/document) derive their own vein
// colour from their own role (REQ-2 AC2) and pass it straight into
// `veinColor` — the chassis never assumes a task-shaped state machine.
export type ChassisVeinState = "idle" | "thinking" | "crystallized"

export const VEIN_COLOR_BY_STATE: Record<ChassisVeinState, string> = {
  idle: "#f97316",
  thinking: "#fbbf24",
  crystallized: "#34d399",
}

// ── Type floor (Decision 15 / REQ-1 AC7) ────────────────────────────────────
export const CHASSIS_TYPE_FLOOR_PX = 9
export const CHASSIS_MEANING_FLOOR_PX = 10

export interface CardChassisCounter {
  done: number
  total: number
}

export interface CardChassisProps {
  /** Left-edge accent vein colour — always rendered, never optional. */
  veinColor: string
  /** Pulses the vein + halo to full opacity while true; settles to 0.5 idle
   *  (REQ-1 AC3). */
  isActive?: boolean
  /** Header row content — identity marker, objective/title, role badges.
   *  Rendered left of the counter and collapse button. */
  header: React.ReactNode
  /** Bracketed `[done/total]` counter (REQ-1 AC1/AC6). Omitted entirely
   *  when `total` is 0 — a card with nothing to count doesn't get an empty
   *  counter (REQ-1 Edge Case: zero steps -> no empty step well). */
  counter?: CardChassisCounter
  /** Secondary header row — e.g. the THK thinking whisper. Rendered under a
   *  hairline divider, above the collapsible body. */
  subheader?: React.ReactNode
  /** Collapsible body content (REQ-1 AC4). */
  children?: React.ReactNode
  /** Footer row — e.g. the memory slot + elapsed timer. Rendered under a
   *  hairline divider, below the body. */
  footer?: React.ReactNode
  /** Whether the collapse chevron is shown at all. Defaults to true, but
   *  only renders when there is `children` to collapse. */
  collapsible?: boolean
  /** Controlled collapse state. When omitted, the chassis manages its own. */
  collapsed?: boolean
  onCollapsedChange?: (collapsed: boolean) => void
  defaultCollapsed?: boolean
  className?: string
  /**
   * Fill mode (T11a) — makes the chassis occupy its parent's full height as a
   * flex column (surface `h-full flex flex-col`, body `flex-1 overflow-y-auto`),
   * so the EXPANDED document panel (`DocumentPanel`) renders on the SAME Liquid
   * Ink surface as the inline `RichDocument` card it expands from (REQ-2 AC6) —
   * expanding must not change the surface mid-interaction. Off by default, so
   * the inline card tests (T8/T9/T10/T11) are untouched.
   */
  fill?: boolean
  "aria-label"?: string
}

export function CardChassis({
  veinColor,
  isActive = false,
  header,
  counter,
  subheader,
  children,
  footer,
  collapsible = true,
  collapsed: collapsedProp,
  onCollapsedChange,
  defaultCollapsed = false,
  className = "",
  fill = false,
  ...rest
}: CardChassisProps) {
  const [internalCollapsed, setInternalCollapsed] = useState(defaultCollapsed)
  const isControlled = collapsedProp !== undefined
  const isCollapsed = isControlled ? collapsedProp : internalCollapsed
  const canCollapse = collapsible && Boolean(children)

  const toggleCollapsed = () => {
    const next = !isCollapsed
    if (!isControlled) setInternalCollapsed(next)
    onCollapsedChange?.(next)
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.22 }}
      className={`w-full select-none antialiased ${fill ? "h-full my-0" : "my-2"} ${className}`}
      aria-label={rest["aria-label"]}
    >
      <div
        data-testid="chassis-surface"
        className={`relative rounded-lg overflow-hidden transition-all duration-300 ${
          fill ? "h-full flex flex-col" : ""
        }`}
        style={{
          background:
            "linear-gradient(135deg, rgba(8, 8, 16, 0.97) 0%, rgba(14, 12, 20, 0.98) 50%, rgba(8, 8, 16, 0.97) 100%)",
          border: "1px solid rgba(255, 255, 255, 0.07)",
          boxShadow: "0 12px 40px rgba(0, 0, 0, 0.7), 0 0 1px rgba(255, 255, 255, 0.1)",
        }}
      >
        {/* Accent vein — REQ-1 AC1/AC2/AC3. Not gated by any prop: every
            card that renders through the chassis gets it, unconditionally. */}
        <div
          data-testid="chassis-vein"
          className="absolute top-0 left-0 bottom-0 w-[3px] pointer-events-none"
          style={{
            background: `linear-gradient(180deg, transparent 0%, ${veinColor} 30%, ${veinColor} 70%, transparent 100%)`,
            opacity: isActive ? 1 : 0.5,
            transition: "opacity 0.5s ease",
          }}
        />
        {/* Vein glow halo */}
        <div
          className="absolute top-0 left-0 bottom-0 w-8 pointer-events-none"
          style={{ background: `linear-gradient(90deg, ${veinColor}15, transparent)` }}
        />

        {/* REQ-1 AC5 padding — the ONLY place it is applied. Cards receive
            slots inside this element and have no way to render a sibling
            that sits outside it, so padding cannot be accidentally skipped. */}
        <div
          className={`relative p-4 pl-5 ${
            fill ? "flex-1 flex flex-col min-h-0" : ""
          }`}
          data-testid="chassis-padding"
        >
          {/* Header row */}
          <div className={`flex items-center justify-between gap-2.5 ${fill ? "shrink-0" : ""}`}>
            <div className="flex items-center gap-2 min-w-0 flex-1">{header}</div>

            <div className="flex items-center gap-2 shrink-0">
              {counter && counter.total > 0 && (
                <span
                  data-testid="chassis-counter"
                  className="text-[9.5px] font-mono font-bold px-2 py-0.5 rounded-md tabular-nums"
                  style={{
                    color: veinColor,
                    background: `${veinColor}12`,
                    border: `1px solid ${veinColor}25`,
                  }}
                >
                  [{counter.done}/{counter.total}]
                </span>
              )}
              {canCollapse && (
                <button
                  type="button"
                  onClick={toggleCollapsed}
                  aria-label={isCollapsed ? "Expand card" : "Collapse card"}
                  className="p-1 rounded text-white/30 hover:text-white hover:bg-white/10 transition-colors"
                >
                  <ChevronDown
                    size={12}
                    style={{
                      transform: isCollapsed ? "rotate(-90deg)" : "rotate(0deg)",
                      transition: "transform 0.16s ease",
                    }}
                  />
                </button>
              )}
            </div>
          </div>

          {/* Secondary header row (e.g. THK whisper) */}
          {subheader && <div className="mt-2.5 pt-2 border-t border-white/5">{subheader}</div>}

          {/* Collapsible body */}
          <AnimatePresence initial={false}>
            {children && (!canCollapse || !isCollapsed) && (
               <motion.div
                 initial={{ height: 0, opacity: 0 }}
                 animate={{ height: "auto", opacity: 1 }}
                 exit={{ height: 0, opacity: 0 }}
                 className={`mt-2.5 ${fill ? "flex-1 overflow-y-auto min-h-0" : ""}`}
               >
                {children}
              </motion.div>
            )}
          </AnimatePresence>

          {/* Footer row (e.g. memory slot + timer) */}
          {footer && <div className="mt-2.5 pt-1.5 border-t border-white/5">{footer}</div>}
        </div>
      </div>
    </motion.div>
  )
}

// ── Reusable, floor-compliant primitives ────────────────────────────────────
// Not required by any card, but available so T9-T11a don't each reinvent the
// same 8px-eliminated badge/node markup from the variant.

/** A meaning-carrying pill badge, fixed at the 10px meaning floor (Decision
 *  15) — e.g. a "crystallized" / "done" header badge, a THK label, a tier
 *  label. The variant used 8px here in one instance (the header "done"
 *  badge); this primitive makes 8px structurally unreachable. */
export function ChassisBadge({
  children,
  color,
  background,
  border,
  icon,
  className = "",
}: {
  children: React.ReactNode
  color: string
  background?: string
  border?: string
  icon?: React.ReactNode
  className?: string
}) {
  return (
    <span
      className={`text-[10px] font-mono uppercase px-1.5 py-0.5 rounded-md flex items-center gap-1 shrink-0 font-bold ${className}`}
      style={{
        color,
        background: background ?? `${color}15`,
        border: border ?? `1px solid ${color}35`,
      }}
    >
      {icon}
      {children}
    </span>
  )
}

/** De-emphasized chrome text (counter, timer, footnote labels) — held at the
 *  9px legibility floor, deliberately NOT bumped to the 10px meaning floor
 *  because design.md treats this class of text as chrome, not content the
 *  user must read to understand what happened. The variant's footnote
 *  "data/memory.db" label was 8px; this primitive makes that unreachable
 *  too, without over-promoting chrome to the same weight as meaning. */
export function ChassisChromeLabel({
  children,
  className = "",
}: {
  children: React.ReactNode
  className?: string
}) {
  return <span className={`text-[9px] uppercase tracking-wider text-white/20 ${className}`}>{children}</span>
}

/**
 * Diving Deeper badge (Decision 13, revised 2026-08-19; Decision 15 type
 * floor). `branchLabel` is FREE TEXT the backend populates — this component
 * NEVER hardcodes "Sub-Loop" or "Detour" and never invents its own copy; it
 * only renders `↳ {branchLabel}`. The purple treatment is byte-for-byte the
 * variant's, moved from 8px to the 10px meaning floor — this is the exact
 * element the user singled out as wanting to be readable (REQ-1 AC7).
 */
export function ChassisBranchBadge({ branchLabel }: { branchLabel: string }) {
  return (
    <span
      data-testid="chassis-branch-badge"
      className="text-[10px] font-mono font-medium text-purple-300/80 bg-purple-500/10 border border-purple-500/20 px-1.5 py-0.5 rounded-md shrink-0"
    >
      ↳ {branchLabel}
    </span>
  )
}

/** Step node states from the variant (pending / running / done /
 *  crystallized), reproduced verbatim including the running state's
 *  `animate-ping` ripple ring, so a future card doesn't fork this markup. */
export type ChassisStepNodeStatus = "pending" | "running" | "done" | "crystallized"

export function ChassisStepNode({
  status,
  color,
}: {
  status: ChassisStepNodeStatus
  color: string
}) {
  if (status === "running") {
    return (
      <div className="w-4 h-4 shrink-0 flex items-center justify-center relative" data-testid="chassis-node-running">
        <div
          className="absolute w-4 h-4 rounded-full border border-amber-400/40 animate-ping"
          style={{ animationDuration: "2s" }}
        />
        <div className="w-2.5 h-2.5 rounded-full border border-amber-400 flex items-center justify-center bg-amber-500/20">
          <Xur size={7} color="#fbbf24" speed={2.5} />
        </div>
      </div>
    )
  }
  if (status === "crystallized") {
    return (
      <div className="w-4 h-4 shrink-0 flex items-center justify-center" data-testid="chassis-node-crystallized">
        <div className="w-2.5 h-2.5 rounded-full bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.8)]" />
      </div>
    )
  }
  if (status === "done") {
    return (
      <div className="w-4 h-4 shrink-0 flex items-center justify-center" data-testid="chassis-node-done">
        <div className="w-2 h-2 rounded-full" style={{ background: color, boxShadow: `0 0 6px ${color}80` }} />
      </div>
    )
  }
  return (
    <div className="w-4 h-4 shrink-0 flex items-center justify-center" data-testid="chassis-node-pending">
      <div className="w-1.5 h-1.5 rounded-full bg-white/20 border border-white/15" />
    </div>
  )
}

export default CardChassis
