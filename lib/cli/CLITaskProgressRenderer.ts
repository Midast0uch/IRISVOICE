import stringWidth from "string-width"
import { resolveVerb } from "../cards/verbRegistry"

/**
 * CLI TASK PROGRESS RENDERER — Blueprint Matrix (REQ-8, REQ-9)
 *
 * Promoted out of `temp/task-card-redesign/CLITaskProgressRenderer.ts` (T12).
 * That file held four candidate variants; the user chose Blueprint Matrix
 * (`renderBlueprintCellMatrixCLI`), so ONLY that variant is promoted here —
 * Cyber Double Rail, Architectural Grid and Double Track Pipeline are
 * dropped, not carried forward.
 *
 * Three defects fixed on promotion (see design.md "Blueprint Matrix tokens
 * as built" and requirements.md REQ-8/REQ-9):
 *   1. `CLITaskProgressRenderer.render()` delegated to the unselected Flow
 *      Pipeline variant (`renderCyberDoubleRailCLI`). Now points at
 *      `renderBlueprintCellMatrixCLI`.
 *   2. Content lines opened a left wall and never closed a right wall or
 *      padded to width — only the frame rows did. Every content row now
 *      goes through `closeRow()`, which pads to `INNER_WIDTH` and closes
 *      the right wall.
 *   3. `String.length` counts ANSI escape codes, so naive `padEnd` misaligned
 *      every coloured line. All layout math goes through `visibleWidth()`
 *      (escape-stripped, display-width aware) — never `String.length`.
 */

/**
 * ANSI Color Codes for Terminal Rendering
 */
export const ANSI = {
  reset: "\x1b[0m",
  bold: "\x1b[1m",
  dim: "\x1b[2m",
  italic: "\x1b[3m",
  underline: "\x1b[4m",

  cyan: "\x1b[36m",
  green: "\x1b[32m",
  yellow: "\x1b[33m",
  magenta: "\x1b[35m",
  red: "\x1b[31m",
  white: "\x1b[37m",
  blue: "\x1b[34m",
  gray: "\x1b[90m",

  brightCyan: "\x1b[96m",
  brightGreen: "\x1b[92m",
  brightYellow: "\x1b[93m",
  brightMagenta: "\x1b[95m",
  brightWhite: "\x1b[97m",
}

const c = (code: string, text: string, useColor = true) => (useColor ? `${code}${text}${ANSI.reset}` : text)

export interface MemoryEvent {
  direction: "retrieve" | "store" | "crystallize"
  engine: "episodic" | "coordinates"
  detail: string
  timestamp?: number
}

export interface TaskStepItem {
  id: string
  /**
   * GROUND TRUTH REQ-20 AC1: the backend-owned ordering key, carried through
   * from the GUI card so the CLI renders the SAME sequence rather than
   * inheriting whatever array order it was handed.
   *
   * Without it the CLI could not detect a bad order, let alone correct one —
   * it had no key at all, so `taskCardToMatrixProps` silently dropped the
   * only thing that encodes when the work happened.
   */
  seq?: number
  /**
   * Backend tool name (or a short verb already in that vocabulary, e.g.
   * "read", "exec") passed to `resolveVerb()` from `lib/cards/verbRegistry`
   * to get the displayed verb. Never re-mapped locally — T8a exists so the
   * GUI card and this renderer share one mapping.
   */
  verb: string
  target: string // e.g. "src-tauri/src/ws_client.rs"
  status: "pending" | "running" | "done" | "crystallized" | "rerouted" | "failed"
  durationMs?: number
  summary?: string // Compact 1-line output summary
  branchLabel?: string // If spawned as sub-loop or parallel worker
  memoryEffect?: "recalled" | "stored" | "crystallized"
}

export interface TaskCardProps {
  objective: string
  steps: TaskStepItem[]
  /**
   * GROUND TRUTH REQ-20 AC3: the progress pair, from the SAME single
   * derivation the GUI counter and the XurOrb ring read (REQ-18 AC1/AC3).
   * Optional so existing callers and the width/Unicode baseline tests are
   * untouched.
   */
  currentStep?: number
  totalSteps?: number
  isThinking?: boolean
  currentThought?: string
  thoughtHistory?: string
  isCrystallized?: boolean
  memoryEvents?: MemoryEvent[]
}

/** Fixed inner width of the Blueprint Matrix frame (design.md: "inner width
 *  66, total 68"). Every content row is padded/truncated to exactly this
 *  many VISIBLE columns before the right wall closes it. */
const INNER_WIDTH = 66

/** Header icon (REQ-9 AC1) — schematic square, sits immediately left of the
 *  `TASK :` label. Its display width is measured, never assumed, so AC4
 *  ("account for the icon's display width when aligning the label") holds
 *  even if a future icon is multi-column. */
const ICON = "▤"

/**
 * Visible column width of a string for terminal layout. ANSI escape codes
 * contribute zero width, combining marks contribute zero columns, and wide
 * glyphs (CJK / fullwidth) count as two columns — `String.length` counts
 * none of that correctly (it counts UTF-16 code units, including the escape
 * bytes), which is exactly the defect this promotion fixes (REQ-8 AC2).
 * Delegates to `string-width` (already a project dependency, and itself
 * built from `strip-ansi` + `is-fullwidth-code-point`) rather than
 * reimplementing Unicode width tables.
 */
export function visibleWidth(text: string): number {
  return stringWidth(text)
}

/**
 * Truncate free text (never structural glyphs) to fit `maxWidth` VISIBLE
 * columns, appending a single-column ellipsis marker when truncation
 * happens. Walks by code point (never splits a surrogate pair or a wide
 * glyph) and measures each with `visibleWidth`, so combining marks and CJK
 * are handled the same way the final row measurement is.
 */
export function truncateToWidth(text: string, maxWidth: number): string {
  if (maxWidth <= 0) return ""
  if (visibleWidth(text) <= maxWidth) return text

  const ELLIPSIS = "…"
  const ellipsisWidth = visibleWidth(ELLIPSIS)
  if (maxWidth <= ellipsisWidth) return ELLIPSIS.slice(0, maxWidth)

  const budget = maxWidth - ellipsisWidth
  let out = ""
  let width = 0
  for (const ch of text) {
    const chWidth = visibleWidth(ch)
    if (width + chWidth > budget) break
    out += ch
    width += chWidth
  }
  return `${out}${ELLIPSIS}`
}

/** Fit free text into the remaining budget around fixed (already-coloured)
 *  decoration, so a long field (objective, target, branchLabel, summary,
 *  thought) truncates instead of pushing the row past `INNER_WIDTH`. */
function fitWidth(prefix: string, text: string, suffix = ""): string {
  const budget = Math.max(0, INNER_WIDTH - visibleWidth(prefix) - visibleWidth(suffix))
  return truncateToWidth(text, budget)
}

/** Pad `content` to `INNER_WIDTH` visible columns (never `String.length`)
 *  and close the right wall — the fix for REQ-8 AC1/AC2. If `content`
 *  already reached `INNER_WIDTH` (callers pre-truncate free text via
 *  `fitWidth`) no padding is added and the wall closes flush. */
function closeRow(wall: string, content: string): string {
  const pad = " ".repeat(Math.max(0, INNER_WIDTH - visibleWidth(content)))
  return `${wall}${content}${pad}${wall}`
}

/** Build footer lines that stack inside the container. Every line now
 *  closes its right wall (REQ-8 AC4 — containment applies to header, body,
 *  sub-chambers AND footer alike); the memory detail is free text and is
 *  truncated the same way any other field is. */
function buildFooter(task: TaskCardProps, wall: string, closeLine: string, useColor: boolean): string[] {
  const lines: string[] = []
  const lastMem = task.memoryEvents && task.memoryEvents.length > 0
    ? task.memoryEvents[task.memoryEvents.length - 1]
    : null

  const pushLine = (text: string, colorCode: string) => {
    const prefix = " "
    const fit = fitWidth(prefix, text)
    lines.push(closeRow(wall, `${prefix}${c(colorCode, fit, useColor)}`))
  }

  if (task.isCrystallized) {
    pushLine("✦ CONVERGED", ANSI.brightGreen + ANSI.bold)
    pushLine("Skill crystallized into data/memory.db (skills)", ANSI.brightGreen)
    if (lastMem) pushLine(lastMem.detail, ANSI.dim)
  } else if (lastMem) {
    pushLine(`MEM: ${lastMem.detail}`, ANSI.dim)
    pushLine("data/memory.db", ANSI.dim)
  } else {
    pushLine("Active Task Execution", ANSI.dim)
    pushLine("data/memory.db", ANSI.dim)
  }

  lines.push(closeLine)
  return lines
}

/**
 * ════════════════════════════════════════════════════════════════════════════
 * BLUEPRINT CELL MATRIX (┌──┐ outer + ┊ dotted rail hierarchy)
 * Dotted vertical guides (┊) and hairline sub-chambers (┄) for a
 * blueprint/schematic aesthetic. This is the variant the user chose.
 * ════════════════════════════════════════════════════════════════════════════
 */
export function renderBlueprintCellMatrixCLI(task: TaskCardProps, useColor = true): string {
  const lines: string[] = []
  const border = "─".repeat(INNER_WIDTH)
  const wall = c(ANSI.cyan, "│", useColor)

  lines.push(`${c(ANSI.cyan, "┌", useColor)}${c(ANSI.cyan, border, useColor)}${c(ANSI.cyan, "┐", useColor)}`)

  // Header — icon immediately left of TASK (REQ-9 AC1), objective truncates
  // to whatever room is left (REQ-8 AC3).
  {
    const taskLabel = c(ANSI.brightCyan + ANSI.bold, "TASK :", useColor)
    const prefix = ` ${ICON} ${taskLabel} `
    const objective = fitWidth(prefix, task.objective)
    lines.push(closeRow(wall, `${prefix}${c(ANSI.brightWhite + ANSI.bold, objective, useColor)}`))
  }

  if (task.isThinking || task.currentThought) {
    // Blank the width of the icon so "THK  :" stays in the same column as
    // "TASK :" (design.md: "label padded to align with TASK :").
    const iconBlank = " ".repeat(visibleWidth(ICON))
    const thkLabel = c(ANSI.brightYellow + ANSI.bold, "THK  :", useColor)
    const prefix = ` ${iconBlank} ${thkLabel} `
    const thought = fitWidth(prefix, task.currentThought || "Resolving plan...")
    lines.push(closeRow(wall, `${prefix}${c(ANSI.dim + ANSI.italic, thought, useColor)}`))
  }

  lines.push(`${c(ANSI.cyan, "├", useColor)}${c(ANSI.cyan, border, useColor)}${c(ANSI.cyan, "┤", useColor)}`)

  task.steps.forEach((s, idx) => {
    const isLast = idx === task.steps.length - 1
    const rail = isLast ? " " : c(ANSI.dim, "┊", useColor)

    let orb = c(ANSI.dim, "○", useColor)
    let verbColor = ANSI.white

    if (s.status === "running") {
      orb = c(ANSI.brightYellow + ANSI.bold, "◎", useColor)
      verbColor = ANSI.brightYellow + ANSI.bold
    } else if (s.status === "crystallized") {
      orb = c(ANSI.brightGreen + ANSI.bold, "✦", useColor)
      verbColor = ANSI.brightGreen + ANSI.bold
    } else if (s.status === "done") {
      orb = c(ANSI.brightCyan + ANSI.bold, "●", useColor)
      verbColor = ANSI.brightCyan + ANSI.bold
    }

    // Decision 12: the verb column stays padEnd(6) exactly as the variant
    // chose it — resolveVerb() is the new part (T8a), never a local remap.
    const verb = c(verbColor, resolveVerb(s.verb).padEnd(6), useColor)

    if (s.branchLabel) {
      // "Diving Deeper" chamber (Decision 13). The label is free text from
      // the backend and may be any length — the filler dash run is computed
      // from the width actually left after the label, never hardcoded, so a
      // long label truncates instead of pushing the corner "┐" past the
      // frame (the live trap this promotion exists to fix).
      const prefixPlain = "  ┊ ┌┄┄ ↳ ["
      const suffixPlain = "] "
      const cornerPlain = "┐"
      const fixedWidth = visibleWidth(prefixPlain) + visibleWidth(suffixPlain) + visibleWidth(cornerPlain)
      const MIN_FILLER = 1
      const maxLabelWidth = Math.max(0, INNER_WIDTH - fixedWidth - MIN_FILLER)
      const label = truncateToWidth(s.branchLabel, maxLabelWidth)
      const fillerWidth = Math.max(MIN_FILLER, INNER_WIDTH - fixedWidth - visibleWidth(label))
      const filler = "┄".repeat(fillerWidth)

      const railGuide = c(ANSI.dim, "┊", useColor)
      const chamberOpen = c(ANSI.cyan, "┌┄┄", useColor)
      const labelUnit = c(ANSI.brightMagenta, `↳ [${label}]`, useColor)
      const dashClose = c(ANSI.dim, `${filler}${cornerPlain}`, useColor)
      lines.push(closeRow(wall, `  ${railGuide} ${chamberOpen} ${labelUnit} ${dashClose}`))

      const nestedPrefix = `  ${railGuide} ${c(ANSI.dim, "┊", useColor)}   ${orb}  ${verb} `
      const target = fitWidth(nestedPrefix, s.target)
      lines.push(closeRow(wall, `${nestedPrefix}${target}`))

      if (s.summary) {
        const summaryOuterPrefix = `  ${railGuide} ${c(ANSI.dim, "┊", useColor)}   `
        const summaryInnerFixed = "└─ "
        const summary = fitWidth(summaryOuterPrefix + summaryInnerFixed, s.summary)
        lines.push(closeRow(wall, `${summaryOuterPrefix}${c(ANSI.dim, `${summaryInnerFixed}${summary}`, useColor)}`))
      }

      // Chamber bottom border matches the same box width as the top row
      // (INNER_WIDTH minus the shared 4-column lead-in "  ┊ "), so it never
      // depends on the label and the box stays rectangular.
      const leadIn = `  ${railGuide} `
      const bottomDashWidth = Math.max(0, INNER_WIDTH - visibleWidth(leadIn) - 2)
      const bottomBorder = c(ANSI.dim, `└${"┄".repeat(bottomDashWidth)}┘`, useColor)
      lines.push(closeRow(wall, `${leadIn}${bottomBorder}`))
    } else {
      const prefix = `  ${c(ANSI.dim, "┊", useColor)} ${orb}  ${verb} `
      const target = fitWidth(prefix, s.target)
      lines.push(closeRow(wall, `${prefix}${target}`))

      if (s.summary) {
        const outerPrefix = `  ${rail}    `
        const innerFixed = "└─ "
        const summary = fitWidth(outerPrefix + innerFixed, s.summary)
        lines.push(closeRow(wall, `${outerPrefix}${c(ANSI.dim, `${innerFixed}${summary}`, useColor)}`))
      }
    }

    if (!isLast) {
      lines.push(closeRow(wall, `  ${c(ANSI.dim, "┊", useColor)}`))
    }
  })

  if (task.steps.length === 0) {
    lines.push(closeRow(wall, `  ${c(ANSI.dim, "┊ ○  Awaiting execution...", useColor)}`))
  }

  lines.push(`${c(ANSI.cyan, "├", useColor)}${c(ANSI.cyan, border, useColor)}${c(ANSI.cyan, "┤", useColor)}`)

  const close = `${c(ANSI.cyan, "└", useColor)}${c(ANSI.cyan, border, useColor)}${c(ANSI.cyan, "┘", useColor)}`
  lines.push(...buildFooter(task, wall, close, useColor))

  return lines.join("\n")
}

export class CLITaskProgressRenderer {
  public static render(task: TaskCardProps, useColor: boolean = true): string {
    return renderBlueprintCellMatrixCLI(task, useColor)
  }
}
