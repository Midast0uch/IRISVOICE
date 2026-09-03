/**
 * THE single ordering + progress derivation, shared by the GUI card and the CLI.
 *
 * specs/der-ground-truth/ REQ-17 / REQ-18 / REQ-20 AC4.
 *
 * Follows the `verbRegistry` precedent exactly: the GUI card and the CLI
 * Blueprint Matrix already share ONE verb mapping rather than each keeping its
 * own, because two implementations of one mapping drift. Order and progress are
 * the same kind of thing, and they drifted for the same reason — the GUI derived
 * position three separate ways and the CLI inherited array order with no key at
 * all.
 *
 * Everything here is pure, so it runs in a node test with no app, no dev server,
 * and no developer-mode session (REQ-20 AC6).
 */

/** The minimum a row must expose to be ordered. Both card models satisfy it. */
export interface OrderableRow {
  /** Backend-owned ordering key (REQ-17). The authority. */
  seq?: number
  /** Planner's own numbering. A DISPLAY concern, and a legacy-frame fallback. */
  stepNumber?: number
  status?: string
}

/**
 * The ordering key for one row.
 *
 * `seq` wins. `stepNumber` is consulted only for legacy frames emitted before
 * the backend stamped a key. A row with neither is a contract violation the
 * emitter contract (rule E1) surfaces — it sorts last so rendering still works,
 * but that placement is a symptom, never the intent.
 */
export function orderKey(row: OrderableRow): number {
  return row.seq ?? row.stepNumber ?? Number.MAX_SAFE_INTEGER
}

/** Rows in the order the work actually happened. Never mutates the input. */
export function sortRows<T extends OrderableRow>(rows: readonly T[]): T[] {
  return [...rows].sort((a, b) => orderKey(a) - orderKey(b))
}

/** True when every row carries a real key — i.e. the emitter held up its end. */
export function allRowsKeyed(rows: readonly OrderableRow[]): boolean {
  return rows.every((r) => orderKey(r) !== Number.MAX_SAFE_INTEGER)
}

/** Statuses that mean the row is finished, whatever vocabulary produced it. */
const TERMINAL = new Set(["done", "crystallized", "rerouted", "failed", "skipped"])
const WORKING = new Set(["working", "running"])

/**
 * The progress pair — numerator and denominator from the SAME row collection,
 * computed TOGETHER (REQ-18 AC1/AC2).
 *
 * They used to be computed apart: the phase-progress branch advanced
 * `totalSteps` and never recomputed `currentStep`, so the denominator grew
 * alone. Because that same value drives the XurOrb ring, the counter and the
 * ring drifted from the list together.
 *
 * `floor` carries a previously-seen denominator so it can never SHRINK as work
 * is discovered (REQ-18 AC6).
 */
export function deriveProgress(
  rows: readonly OrderableRow[],
  floor = 0,
): { currentStep: number; totalSteps: number } {
  const totalSteps = Math.max(floor, rows.length)
  const workingIdx = rows.findIndex((r) => WORKING.has(String(r.status)))
  const raw =
    workingIdx >= 0
      ? workingIdx + 1
      : rows.filter((r) => TERMINAL.has(String(r.status))).length
  // REQ-18 AC4: the numerator can never exceed the denominator.
  return { currentStep: Math.min(raw, totalSteps), totalSteps }
}
