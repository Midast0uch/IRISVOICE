/**
 * EMITTER CONTRACT for the task-card event stream.
 *
 * specs/der-ground-truth/ REQ-19 (T27).
 *
 * WHY THIS EXISTS
 * ---------------
 * `__tests__/hooks/useTaskProgress.card-contract.test.tsx` replays REAL captured
 * WS traces through the reducer and asserts what the CARD exhibits. That is good
 * practice and it caught a real bug when it was written (pin_c456f10e048a).
 *
 * But it asserts the FRONTEND's handling of whatever the backend sent. If the
 * backend emitted a malformed stream, the replay reproduces it faithfully and
 * the assertions — written against what was observed — encode the defect as
 * correct. Nothing anywhere pinned what the backend is PERMITTED to emit.
 *
 * This module is that missing half. It is deliberately:
 *
 *   - RENDERER-INDEPENDENT. It imports no React, no hook, no component. It reads
 *     wire frames and judges them on their own terms. A frame stream is either
 *     well-formed or it is not, regardless of how gracefully some consumer
 *     copes with it.
 *   - PURE and SYNCHRONOUS. No app, no dev server, no developer-mode session
 *     (specs/der-ground-truth/ Decisions Locked 2).
 *
 * WHAT IT DOES NOT DO
 * -------------------
 * It does not fix anything and it does not judge rendering. A violation here
 * means the RECORD is wrong — per REQ-19 AC6 the fix belongs in the emitter, and
 * adjusting a reducer to accommodate a malformed stream is explicitly forbidden.
 */

/** One frame as it arrives on the wire (`iris:task_update` detail payload). */
export interface CardFrame {
  type?: string
  card_id?: string | null
  conversation_id?: string | null
  task_id?: string | null
  card_relation?: string | null
  origin?: string | null
  steps?: Array<Record<string, unknown>> | null
  total_steps?: number | null
  step_number?: number | null
  step_id?: string | null
  step_done?: boolean | null
  phase?: string | null
  phase_sequence?: number | null
  update_step?: boolean | null
  [k: string]: unknown
}

export type Severity = "violation" | "warning"

export interface ContractFinding {
  /** Stable rule id — E1..E5. */
  rule: string
  severity: Severity
  /** Which card (or conversation, when the frame is card-less) it applies to. */
  scope: string
  /** Index of the offending frame in the input stream, or -1 for whole-stream. */
  frameIndex: number
  message: string
}

export interface ContractReport {
  traceName: string
  frameCount: number
  findings: ContractFinding[]
  get violations(): number
}

/** Frame types that carry planner rows. */
const START = "task:start"
const TERMINAL = new Set(["task:done", "task:fail"])

/**
 * Frames that produce or address a ROW and must therefore be orderable.
 * A `task:progress` frame is row-producing when it opens a phase; per-page
 * detail updates (`update_step` without a new phase) address an existing row
 * and are not themselves rows.
 */
function opensPhase(f: CardFrame): boolean {
  return f.type === "task:progress" && f.phase != null
}

/** Resolve the scope a frame belongs to; card_id when present, else conversation. */
function scopeOf(f: CardFrame): string {
  if (f.card_id) return String(f.card_id)
  if (f.conversation_id) return `conv:${String(f.conversation_id)}`
  return "<unattributed>"
}

/**
 * Validate one trace against the emitter contract.
 *
 * Rules (specs/der-ground-truth/ REQ-19 AC1):
 *   E1  every planner row carries an ordering key
 *   E2  ordering keys are unique within a card
 *   E3  exactly one terminal frame per started card
 *   E4  a phase frame carries BOTH `phase` and `phase_sequence`
 *   E5  a phase-opening row carries an ordering key relative to planner rows
 *
 * E5 is separated from E1 because they fail for different reasons and need
 * different fixes: E1 is a payload-completeness gap in the planner, E5 is a
 * missing concept in the phase emitter.
 */
export function validateTrace(traceName: string, frames: CardFrame[]): ContractReport {
  const findings: ContractFinding[] = []
  const add = (rule: string, severity: Severity, scope: string, frameIndex: number, message: string) =>
    findings.push({ rule, severity, scope, frameIndex, message })

  // stepNumber -> the row ids seen carrying it, per card (E2)
  const keysByScope = new Map<string, Map<number, Set<string>>>()
  const startedScopes = new Set<string>()
  const terminalCounts = new Map<string, number>()
  const lastPhaseSeq = new Map<string, number>()

  frames.forEach((f, idx) => {
    const scope = scopeOf(f)

    if (f.type === START) {
      startedScopes.add(scope)
      const steps = Array.isArray(f.steps) ? f.steps : []
      steps.forEach((raw) => {
        const id = raw?.id == null ? "<no-id>" : String(raw.id)
        const key = raw?.stepNumber
        if (key == null) {
          add(
            "E1",
            "violation",
            scope,
            idx,
            `task:start row "${id}" carries no ordering key (stepNumber). ` +
              `Unkeyed rows cannot be placed in sequence; any consumer must guess.`,
          )
          return
        }
        const n = Number(key)
        if (!Number.isFinite(n)) {
          add("E1", "violation", scope, idx, `task:start row "${id}" has a non-numeric ordering key (${String(key)}).`)
          return
        }
        let byKey = keysByScope.get(scope)
        if (!byKey) { byKey = new Map(); keysByScope.set(scope, byKey) }
        let ids = byKey.get(n)
        if (!ids) { ids = new Set(); byKey.set(n, ids) }
        ids.add(id)
        if (ids.size > 1) {
          add(
            "E2",
            "violation",
            scope,
            idx,
            `ordering key ${n} is shared by ${ids.size} distinct rows [${[...ids].join(", ")}]. ` +
              `A collision makes render order depend on insertion accident, not on the record.`,
          )
        }
      })
    }

    if (TERMINAL.has(String(f.type))) {
      terminalCounts.set(scope, (terminalCounts.get(scope) ?? 0) + 1)
    }

    // E4 — phase and phase_sequence travel together, in both directions.
    if (f.phase != null && f.phase_sequence == null) {
      add("E4", "violation", scope, idx, `phase "${String(f.phase)}" arrives without phase_sequence.`)
    }
    if (f.phase_sequence != null && f.phase == null) {
      add("E4", "violation", scope, idx, `phase_sequence ${String(f.phase_sequence)} arrives without a phase.`)
    }

    // E5 — a phase-opening frame produces a ROW, so it needs an ordering key
    // relative to the planner rows it will render beside.
    if (opensPhase(f)) {
      const seq = Number(f.phase_sequence)
      const prev = lastPhaseSeq.get(scope)
      if (prev != null && Number.isFinite(seq) && seq < prev) {
        add("E5", "warning", scope, idx, `phase_sequence went backwards (${prev} -> ${seq}).`)
      }
      if (Number.isFinite(seq)) lastPhaseSeq.set(scope, seq)

      if (f.step_number == null) {
        add(
          "E5",
          "violation",
          scope,
          idx,
          `phase "${String(f.phase)}" opens a row but carries no ordering key relative to planner rows. ` +
            `phase_sequence orders phases among THEMSELVES only — it cannot interleave them with planner steps.`,
        )
      }
    }
  })

  // E3 — exactly one terminal per started card.
  for (const scope of startedScopes) {
    const n = terminalCounts.get(scope) ?? 0
    if (n === 0) {
      add("E3", "violation", scope, -1, `card was started but never reached a terminal frame.`)
    } else if (n > 1) {
      add("E3", "violation", scope, -1, `card reached ${n} terminal frames; exactly one is permitted.`)
    }
  }
  // A terminal for a card that was never started is equally a break.
  for (const [scope, n] of terminalCounts) {
    if (!startedScopes.has(scope) && n > 0) {
      add("E3", "warning", scope, -1, `terminal frame(s) for a scope with no task:start in this trace.`)
    }
  }

  return {
    traceName,
    frameCount: frames.length,
    findings,
    get violations() {
      return findings.filter((f) => f.severity === "violation").length
    },
  }
}

/** Human-readable report, for the record REQ-19 AC3 asks to be kept. */
export function formatReport(r: ContractReport): string {
  const lines: string[] = []
  const v = r.findings.filter((f) => f.severity === "violation").length
  const w = r.findings.length - v
  lines.push(`TRACE ${r.traceName} — ${r.frameCount} frames — ${v} violation(s), ${w} warning(s)`)
  if (!r.findings.length) {
    lines.push("  (conformant)")
    return lines.join("\n")
  }
  const byRule = new Map<string, ContractFinding[]>()
  for (const f of r.findings) {
    const arr = byRule.get(f.rule) ?? []
    arr.push(f)
    byRule.set(f.rule, arr)
  }
  for (const [rule, fs] of [...byRule.entries()].sort()) {
    lines.push(`  ${rule} — ${fs.length} finding(s)`)
    for (const f of fs) {
      const where = f.frameIndex >= 0 ? `frame ${f.frameIndex}` : "whole-trace"
      lines.push(`    [${f.severity}] ${where} ${f.scope}: ${f.message}`)
    }
  }
  return lines.join("\n")
}
