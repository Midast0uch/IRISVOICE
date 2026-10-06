"use client"

/**
 * The live execution matrix (execution audit Phase 4; look: owner-approved
 * concept 2, docs/design/chatview-2026-10-06/iris-strands.html).
 *
 * Built from components, not a printed string: rows are BORN as nodes start,
 * RUN (scan shimmer, breathing orb, live chip), and FOLD; a split child opens a
 * "looked closer" chamber that shrinks to one line when it settles; a finished
 * run folds to one line. The agent's Xur rides the rail to the running row.
 * It fits any wing width (ellipsis, no sideways scroll) at a readable 12.5 px.
 *
 *   MatrixFrame   header (TASK, progress, time, fold), THK line, rail, rows, memory line
 *   MatrixRow     orb · verb · target · result chip (+ chevron to its detail)
 *   SubLoopChamber  ↳ looked closer — the split children of a row
 *   RowDetail     the row's recent actions / output preview / page
 *
 * Data: the SAME TaskCardProps the ANSI export renders (renderBlueprintCellMatrixCLI
 * stays for terminal export and logs); per-row details come from the task card.
 */
import React, { useLayoutEffect, useMemo, useRef, useState } from "react"
import { Xur } from "@/components/Xur"
import type { TaskCardProps } from "@/lib/cli/CLITaskProgressRenderer"
import {
  buildMatrix,
  foldLine,
  formatElapsed,
  memoryLine,
  rowOpenByDefault,
  type ChamberModel,
  type MatrixRowModel,
  type RowDetailData,
} from "./matrixModel"

const RUN = "#f2c14e"
const BAD = "#ff7a6e"
const OK = "#5fcf98"

const ORB: Record<MatrixRowModel["state"], string> = {
  pending: "○",
  running: "◎",
  done: "●",
  failed: "✕",
  rerouted: "↷",
}

function stateColor(state: MatrixRowModel["state"], glow: string): string {
  if (state === "running") return RUN
  if (state === "failed") return BAD
  if (state === "done") return glow
  return "rgba(255,255,255,0.32)"
}

export function RowDetail({ detail }: { detail: RowDetailData }) {
  const lines = detail.history?.slice(-6) ?? []
  return (
    <div
      className="mb-1 pl-2 text-[11.5px] whitespace-pre-wrap break-words min-w-0"
      style={{ marginLeft: 26, lineHeight: 1.5, borderLeft: "1px solid rgba(255,255,255,0.12)", color: "rgba(196,202,214,0.95)" }}
      data-matrix-detail
    >
      {lines.map((l, i) => (
        <div key={i} className="truncate">{l}</div>
      ))}
      {detail.preview && <div className="text-white/60">{detail.preview}</div>}
      {detail.url && <div className="truncate text-white/40">{detail.url}</div>}
    </div>
  )
}

export function MatrixRow({
  row,
  glowColor,
  live,
}: {
  row: MatrixRowModel
  glowColor: string
  /** Live chip text for the running row (current action, elapsed). */
  live?: string
}) {
  const hasDetail = !!(row.detail?.history?.length || row.detail?.preview || row.detail?.url)
  const [open, setOpen] = useState(() => rowOpenByDefault(row))
  const color = stateColor(row.state, glowColor)
  const chip = row.state === "running" ? live || "…" : row.summary || ""
  return (
    <>
      <div
        className={`iris-mx-row relative flex items-center gap-2 min-w-0 px-1 rounded ${row.state === "running" ? "iris-mx-scan" : ""}`}
        style={{ minHeight: 22 }}
        data-state={row.state}
        data-row-id={row.id}
      >
        <span className={`flex-none w-3 text-center ${row.state === "running" ? "iris-mx-breathe" : ""}`} style={{ color }}>
          {ORB[row.state]}
        </span>
        <span className="flex-none font-bold" style={{ color, width: "7ch" }}>{row.verb}</span>
        <span className="flex-1 min-w-0 truncate text-white/80" title={row.target}>{row.target}</span>
        {chip && (
          <span className="flex-none truncate text-[11px]" style={{ maxWidth: "42%", color: row.state === "failed" ? BAD : "rgba(255,255,255,0.45)" }}>
            {chip}
          </span>
        )}
        {hasDetail && (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="flex-none px-1 text-[12px] leading-none"
            style={{ color: glowColor }}
            aria-expanded={open}
            aria-label={open ? "Hide output" : "Show output"}
          >
            {open ? "⌃" : "⌄"}
          </button>
        )}
      </div>
      {hasDetail && open && row.detail && <RowDetail detail={row.detail} />}
    </>
  )
}

export function SubLoopChamber({
  chamber,
  glowColor,
  live,
}: {
  chamber: ChamberModel
  glowColor: string
  live?: string
}) {
  const [open, setOpen] = useState(false)
  const showRows = !chamber.settled || open
  return (
    <div
      className="ml-4 my-0.5 pl-2 overflow-hidden"
      style={{ borderLeft: "1px dashed color-mix(in oklab, #8ea6ff 60%, transparent)" }}
      data-matrix-chamber={chamber.parentId}
      data-settled={chamber.settled}
    >
      <button
        type="button"
        onClick={() => chamber.settled && setOpen((o) => !o)}
        className="block w-full text-left text-[11px] truncate"
        style={{ color: "#8ea6ff", cursor: chamber.settled ? "pointer" : "default" }}
        aria-expanded={showRows}
      >
        ↳ looked closer{chamber.settled ? " · found it" : ""}
        {chamber.settled && <span className="ml-1">{open ? "⌃" : "⌄"}</span>}
      </button>
      {showRows && chamber.rows.map((r) => <MatrixRow key={r.id} row={r} glowColor={glowColor} live={live} />)}
    </div>
  )
}

export interface MatrixFrameProps {
  matrix: TaskCardProps
  details?: Record<string, RowDetailData>
  glowColor: string
  /** The card is still working. */
  working: boolean
  /** The user stopped the turn. */
  stopped?: boolean
  elapsedSec: number
  /** Latest reasoning (turn reasoning, else the card's current action). */
  thought?: string
  /** Live action of the running row(s), e.g. "reading router.py · 0:07". */
  liveAction?: string
  /** Fold a finished run to one line (default). A one-node shell run keeps
   *  its row: its output is the point. */
  foldWhenDone?: boolean
}

export function MatrixFrame({
  matrix,
  details,
  glowColor,
  working,
  stopped = false,
  elapsedSec,
  thought,
  liveAction,
  foldWhenDone = true,
}: MatrixFrameProps) {
  const m = useMemo(() => buildMatrix(matrix, details), [matrix, details])
  const [unfolded, setUnfolded] = useState(false)
  const folded = foldWhenDone && !working && !unfolded && m.flat.length > 0
  const elapsed = formatElapsed(elapsedSec)
  const mem = memoryLine(matrix)

  // The agent's Xur rides the rail to the running row(s).
  const bodyRef = useRef<HTMLDivElement>(null)
  const [xurTop, setXurTop] = useState<number | null>(null)
  useLayoutEffect(() => {
    const body = bodyRef.current
    if (!body || folded || !working) {
      setXurTop(null)
      return
    }
    const running = Array.from(body.querySelectorAll<HTMLElement>('[data-state="running"]'))
    if (!running.length) {
      setXurTop(null)
      return
    }
    const avg = running.reduce((a, el) => a + el.offsetTop + el.offsetHeight / 2, 0) / running.length
    setXurTop(avg - 9)
  })

  if (folded) {
    const f = foldLine(m, stopped, elapsed)
    const color = f.word === "DONE" ? OK : f.word === "FAILED" ? BAD : "rgba(255,255,255,0.5)"
    return (
      <div
        className="font-mono text-[12.5px] rounded-md px-2 py-1.5 min-w-0"
        style={{ lineHeight: 1.55, border: `1px solid ${glowColor}38`, background: "rgba(7,8,20,0.9)" }}
        data-matrix="folded"
      >
        <button type="button" onClick={() => setUnfolded(true)} className="flex w-full items-center gap-2 min-w-0 text-left" aria-expanded={false}>
          <span className="flex-none font-bold" style={{ color }}>{f.mark} {f.word}</span>
          <span className="flex-1 min-w-0 truncate text-white/55">{f.rest}</span>
          <span className="flex-none" style={{ color: glowColor }}>⌄</span>
        </button>
      </div>
    )
  }

  return (
    <div
      className="font-mono text-[12.5px] rounded-md px-2 py-1.5 min-w-0 overflow-hidden"
      style={{ lineHeight: 1.55, border: `1px solid ${glowColor}38`, background: "rgba(7,8,20,0.9)" }}
      data-matrix={working ? "live" : "open"}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span className="flex-none" style={{ color: glowColor }}>▤</span>
        <span className="flex-none font-bold" style={{ color: glowColor }}>TASK :</span>
        <span className="flex-1 min-w-0 truncate font-semibold text-white" title={m.objective}>{m.objective}</span>
        <span className="flex-none text-[11px] text-white/45 tabular-nums">
          {m.current}/{m.total} · {elapsed}
        </span>
        {!working && (
          <button type="button" onClick={() => setUnfolded(false)} className="flex-none px-1" style={{ color: glowColor }} aria-label="Fold">
            ⌃
          </button>
        )}
      </div>
      {working && thought && (
        <div className="flex gap-2 min-w-0 text-[11.5px] text-white/50" data-matrix-thk>
          <span className="flex-none font-bold" style={{ color: RUN }}>THK</span>
          <span className="flex-1 min-w-0 truncate italic">{thought}</span>
        </div>
      )}
      <div ref={bodyRef} className="relative mt-0.5 pt-1 pl-5" style={{ borderTop: `1px solid ${glowColor}1f` }} data-matrix-body>
        {/* The rail: a quiet line the rows hang from; the Xur rides it. */}
        <span aria-hidden className="absolute w-px" style={{ left: 7, top: 4, bottom: 4, background: `linear-gradient(${glowColor}55, ${glowColor}10)` }} />
        {xurTop !== null && (
          <span aria-hidden className="absolute" style={{ left: -2, top: xurTop, transition: "top 0.5s ease-out" }} data-matrix-xur>
            <Xur size={18} color={glowColor} speed={m.running > 1 ? 2.4 : 1.6} />
          </span>
        )}
        {m.items.map((it) =>
          it.kind === "row" ? (
            <MatrixRow key={it.row.id} row={it.row} glowColor={glowColor} live={liveAction} />
          ) : (
            <SubLoopChamber key={`ch-${it.chamber.parentId}`} chamber={it.chamber} glowColor={glowColor} live={liveAction} />
          ),
        )}
        {m.flat.length === 0 && <div className="text-white/35 text-[11.5px]">○ getting ready…</div>}
      </div>
      {mem && <div className="mt-1 text-[11px] text-white/40 truncate">◈ {mem}</div>}
    </div>
  )
}

export default MatrixFrame
