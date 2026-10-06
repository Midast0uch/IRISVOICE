/**
 * Live execution matrix — the pure model (execution audit Phase 4).
 *
 * The developer turn's matrix is the DER graph drawn on screen. It renders from
 * the SAME props as the ANSI export (`TaskCardProps`, built by
 * `taskCardToMatrixProps` from the task card store), so the GUI matrix and
 * `renderBlueprintCellMatrixCLI` can never disagree on what ran, in what order,
 * with which verb (parity guard: __tests__/matrix/matrixParity.test.ts).
 *
 * Plain words (owner, 2026-10-06): no "sub-loop", "converged", "crystallized"
 * or landmarks on screen. A split child is "looked closer", a settled run is
 * "done", a fold-back is "found it".
 */
import { resolveVerb } from "@/lib/cards/verbRegistry"
import type { TaskCardProps, TaskStepItem } from "@/lib/cli/CLITaskProgressRenderer"
import type { EditDiff } from "@/lib/diffs/api"

export type RowState = "pending" | "running" | "done" | "failed" | "rerouted"

export interface RowDetailData {
  history?: string[]
  url?: string
  preview?: string
}

export interface MatrixRowModel {
  id: string
  verb: string
  target: string
  state: RowState
  summary?: string
  detail?: RowDetailData
  /** Edits this row made: the row shows a ± (opens the review). */
  diffs?: EditDiff[]
}

export interface ChamberModel {
  /** The parent row whose result made the agent look closer. */
  parentId: string
  rows: MatrixRowModel[]
  /** Every child settled: the chamber folds to one line. */
  settled: boolean
}

export type MatrixItem =
  | { kind: "row"; row: MatrixRowModel }
  | { kind: "chamber"; chamber: ChamberModel }

export interface MatrixModel {
  objective: string
  items: MatrixItem[]
  /** Rows in render order, flattened (parity with the ANSI export). */
  flat: MatrixRowModel[]
  current: number
  total: number
  running: number
  failed: number
}

function rowState(s: TaskStepItem["status"]): RowState {
  switch (s) {
    case "running":
      return "running"
    case "done":
    case "crystallized":
      return "done"
    case "failed":
      return "failed"
    case "rerouted":
      return "rerouted"
    default:
      return "pending"
  }
}

/** A split child carries the id `<parentId>_s<n>` (DER split; useTaskProgress F3). */
export function parentOf(id: string): string | null {
  const m = /^(.+)_s\d+$/.exec(id)
  return m ? m[1] : null
}

export function buildMatrix(
  props: TaskCardProps,
  details: Record<string, RowDetailData> = {},
): MatrixModel {
  const flat: MatrixRowModel[] = props.steps.map((s) => ({
    id: s.id,
    verb: resolveVerb(s.verb),
    target: s.target,
    state: rowState(s.status),
    summary: s.summary,
    detail: details[s.id],
    diffs: s.diffs,
  }))
  const ids = new Set(flat.map((r) => r.id))
  const items: MatrixItem[] = []
  const chamberOf = new Map<string, ChamberModel>()
  for (const row of flat) {
    const parent = parentOf(row.id)
    if (parent && ids.has(parent)) {
      let ch = chamberOf.get(parent)
      if (!ch) {
        ch = { parentId: parent, rows: [], settled: false }
        chamberOf.set(parent, ch)
        // The chamber sits right after its parent row (or after the
        // previous chamber child when the parent is already placed).
        const at = items.findIndex((it) => it.kind === "row" && it.row.id === parent)
        if (at >= 0) items.splice(at + 1, 0, { kind: "chamber", chamber: ch })
        else items.push({ kind: "chamber", chamber: ch })
      }
      ch.rows.push(row)
      continue
    }
    items.push({ kind: "row", row })
  }
  for (const ch of chamberOf.values()) {
    ch.settled = ch.rows.length > 0 && ch.rows.every((r) => r.state !== "running" && r.state !== "pending")
  }
  return {
    objective: props.objective,
    items,
    flat,
    current: props.currentStep ?? flat.filter((r) => r.state !== "pending" && r.state !== "running").length,
    total: props.totalSteps ?? flat.length,
    running: flat.filter((r) => r.state === "running").length,
    failed: flat.filter((r) => r.state === "failed").length,
  }
}

/** A row opens by default only when it failed or is running (audit: "rows are
 *  closed by default, except a failure and the running row"). */
export function rowOpenByDefault(row: MatrixRowModel): boolean {
  return (row.state === "failed" || row.state === "running") && !!(row.detail?.history?.length || row.detail?.preview)
}

/** The one-line fold of a finished run, in plain words. */
export function foldLine(m: MatrixModel, stopped: boolean, elapsed: string): { mark: string; word: string; rest: string } {
  const steps = `${m.flat.length} step${m.flat.length === 1 ? "" : "s"}`
  if (stopped) return { mark: "■", word: "STOPPED", rest: `${m.objective} · ${steps} · ${elapsed}` }
  if (m.failed > 0 && m.flat.every((r) => r.state !== "done")) {
    return { mark: "✕", word: "FAILED", rest: `${m.objective} · ${steps} · ${elapsed}` }
  }
  const retried = m.failed > 0 ? ` · ${m.failed} tried again` : ""
  return { mark: "✓", word: "DONE", rest: `${m.objective} · ${steps}${retried} · ${elapsed}` }
}

export function formatElapsed(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`
}

/** Memory activity in plain words; learning/crystallize events are not shown. */
export function memoryLine(props: TaskCardProps): string | null {
  const events = (props.memoryEvents || []).filter((e) => e.direction !== "crystallize")
  const last = events[events.length - 1]
  if (!last) return null
  return last.direction === "retrieve" ? `remembered: ${last.detail}` : `saved: ${last.detail}`
}
