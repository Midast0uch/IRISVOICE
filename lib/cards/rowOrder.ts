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

/**
 * Statuses that mean the row is finished, whatever vocabulary produced it.
 * Session 312 (user-directed 2026-09-09): the frontend settles rows as
 * "fail"/"error" while the backend records "failed" — both spellings count,
 * otherwise failed rows could never advance the counter (live conv-98 where
 * three red rows settled but counted for nothing). "vetoed" stays out:
 * rejected work is not settled progress.
 */
const TERMINAL = new Set([
  "done",
  "crystallized",
  "rerouted",
  "failed",
  "fail",
  "error",
  "skipped",
])

/**
 * The progress pair — numerator and denominator from the SAME row collection,
 * computed TOGETHER (REQ-18 AC1/AC2).
 *
 * They used to be computed apart: the phase-progress branch advanced
 * `totalSteps` and never recomputed `currentStep`, so the denominator grew
 * alone. Because that same value drives the XurOrb ring, the counter and the
 * ring drifted from the list together.
 *
 * The numerator is SETTLED rows, always (Session 312, user-directed
 * 2026-09-09): every verb-row is a step and the counter advances only when a
 * row settles. The previous reading — the working row's position while
 * anything was in flight — is gone; WHERE work is shows on the glowing
 * working row + timer, while the counter shows what SETTLED.
 *
 * `floor` carries a previously-seen denominator so it can never SHRINK as work
 * is discovered (REQ-18 AC6).
 */
export function deriveProgress(
  rows: readonly OrderableRow[],
  floor = 0,
): { currentStep: number; totalSteps: number } {
  const totalSteps = Math.max(floor, rows.length)
  const raw = rows.filter((r) => TERMINAL.has(String(r.status))).length
  // REQ-18 AC4: the numerator can never exceed the denominator.
  return { currentStep: Math.min(raw, totalSteps), totalSteps }
}
