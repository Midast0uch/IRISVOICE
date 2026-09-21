import { TaskCardProps, TaskStepItem, MemoryEvent } from "./TaskListCard.v2"

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

/** Helper: build footer lines that stack inside the container */
function buildFooter(
  task: TaskCardProps,
  wall: string,
  closeLine: string,
  useColor: boolean,
): string[] {
  const lines: string[] = []
  const lastMem = task.memoryEvents && task.memoryEvents.length > 0
    ? task.memoryEvents[task.memoryEvents.length - 1]
    : null

  if (task.isCrystallized) {
    lines.push(`${wall} ${c(ANSI.brightGreen + ANSI.bold, "✦ CONVERGED", useColor)}`)
    lines.push(`${wall} ${c(ANSI.brightGreen, "Skill crystallized into data/memory.db (skills)", useColor)}`)
    if (lastMem) {
      lines.push(`${wall} ${c(ANSI.dim, lastMem.detail, useColor)}`)
    }
  } else if (lastMem) {
    lines.push(`${wall} ${c(ANSI.dim, `MEM: ${lastMem.detail}`, useColor)}`)
    lines.push(`${wall} ${c(ANSI.dim, "data/memory.db", useColor)}`)
  } else {
    lines.push(`${wall} ${c(ANSI.dim, "Active Task Execution", useColor)}`)
    lines.push(`${wall} ${c(ANSI.dim, "data/memory.db", useColor)}`)
  }

  lines.push(closeLine)
  return lines
}

/**
 * ════════════════════════════════════════════════════════════════════════════
 * CLI VARIANT 1: CYBER DOUBLE RAIL (╔══╗, ╠══╣, ╚══╝)
 * Double outer border + curved tendril connectors (╭─, ├─, ╰─▶)
 * ════════════════════════════════════════════════════════════════════════════
 */
export function renderCyberDoubleRailCLI(task: TaskCardProps, useColor = true): string {
  const lines: string[] = []
  const border = "═".repeat(66)

  lines.push(`${c(ANSI.cyan, "╔", useColor)}${c(ANSI.cyan, border, useColor)}${c(ANSI.cyan, "╗", useColor)}`)
  lines.push(`${c(ANSI.cyan, "║", useColor)} ${c(ANSI.brightCyan + ANSI.bold, "◈ TASK:", useColor)} ${c(ANSI.brightWhite + ANSI.bold, task.objective, useColor)}`)

  if (task.isThinking || task.currentThought) {
    lines.push(`${c(ANSI.cyan, "║", useColor)}   ${c(ANSI.brightYellow + ANSI.bold, "THK :", useColor)} ${c(ANSI.dim + ANSI.italic, task.currentThought || "Resolving plan...", useColor)}`)
  }

  lines.push(`${c(ANSI.cyan, "╠", useColor)}${c(ANSI.cyan, border, useColor)}${c(ANSI.cyan, "╣", useColor)}`)

  task.steps.forEach((s, idx) => {
    const isFirst = idx === 0
    const isLast = idx === task.steps.length - 1
    const stem = isFirst ? "╭─" : isLast ? "╰─" : "├─"
    const pipe = isLast ? "  " : "│ "

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

    const verb = c(verbColor, s.verb.toUpperCase().padEnd(6), useColor)

    if (s.branchLabel) {
      lines.push(`${c(ANSI.cyan, "║", useColor)}  ${c(ANSI.cyan, "├─ ┌──", useColor)} ${c(ANSI.brightMagenta, `↳ [${s.branchLabel}]`, useColor)} ${c(ANSI.dim, "────────────────────────────┐", useColor)}`)
      lines.push(`${c(ANSI.cyan, "║", useColor)}  ${c(ANSI.cyan, "│  │", useColor)}   ${orb}  ${verb} ${s.target}`)
      if (s.summary) {
        lines.push(`${c(ANSI.cyan, "║", useColor)}  ${c(ANSI.cyan, "│  │", useColor)}   ${c(ANSI.dim, `╰─▶ ${s.summary}`, useColor)}`)
      }
      lines.push(`${c(ANSI.cyan, "║", useColor)}  ${c(ANSI.cyan, "│  └──────────────────────────────────────────────┘", useColor)}`)
    } else {
      lines.push(`${c(ANSI.cyan, "║", useColor)}  ${c(ANSI.cyan, stem, useColor)} ${orb}  ${verb} ${s.target}`)
      if (s.summary) {
        lines.push(`${c(ANSI.cyan, "║", useColor)}  ${c(ANSI.cyan, pipe, useColor)}  ${c(ANSI.dim, `╰─▶ ${s.summary}`, useColor)}`)
      }
      if (!isLast) {
        lines.push(`${c(ANSI.cyan, "║", useColor)}  ${c(ANSI.cyan, "│", useColor)}`)
      }
    }
  })

  if (task.steps.length === 0) {
    lines.push(`${c(ANSI.cyan, "║", useColor)}   ${c(ANSI.dim, "○  Awaiting execution...", useColor)}`)
  }

  lines.push(`${c(ANSI.cyan, "╠", useColor)}${c(ANSI.cyan, border, useColor)}${c(ANSI.cyan, "╣", useColor)}`)

  const wall = c(ANSI.cyan, "║", useColor)
  const close = `${c(ANSI.cyan, "╚", useColor)}${c(ANSI.cyan, border, useColor)}${c(ANSI.cyan, "╝", useColor)}`
  lines.push(...buildFooter(task, wall, close, useColor))

  return lines.join("\n")
}

/**
 * ════════════════════════════════════════════════════════════════════════════
 * CLI VARIANT 2: ARCHITECTURAL GRID (┌──┐, ├──┤, └──┘)
 * Structured cell dividers + nested sub-card chambers + └─ summary tails
 * ════════════════════════════════════════════════════════════════════════════
 */
export function renderArchitecturalGridCLI(task: TaskCardProps, useColor = true): string {
  const lines: string[] = []
  const border = "─".repeat(66)

  lines.push(`${c(ANSI.cyan, "┌", useColor)}${c(ANSI.cyan, border, useColor)}${c(ANSI.cyan, "┐", useColor)}`)
  lines.push(`${c(ANSI.cyan, "│", useColor)} ${c(ANSI.brightCyan + ANSI.bold, "TASK :", useColor)} ${c(ANSI.brightWhite + ANSI.bold, task.objective, useColor)}`)

  if (task.isThinking || task.currentThought) {
    lines.push(`${c(ANSI.cyan, "│", useColor)} ${c(ANSI.brightYellow + ANSI.bold, "THK  :", useColor)} ${c(ANSI.dim + ANSI.italic, task.currentThought || "Resolving plan...", useColor)}`)
  }

  lines.push(`${c(ANSI.cyan, "├", useColor)}${c(ANSI.cyan, border, useColor)}${c(ANSI.cyan, "┤", useColor)}`)

  task.steps.forEach((s, idx) => {
    const isLast = idx === task.steps.length - 1
    const stem = isLast ? "└──" : "├──"
    const pipe = isLast ? "   " : "│  "

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

    const verb = c(verbColor, s.verb.toUpperCase().padEnd(6), useColor)

    if (s.branchLabel) {
      lines.push(`${c(ANSI.cyan, "│", useColor)}  ${c(ANSI.cyan, "├── ┌─", useColor)} ${c(ANSI.brightMagenta, `↳ [${s.branchLabel}]`, useColor)} ${c(ANSI.dim, "────────────────────────────┐", useColor)}`)
      lines.push(`${c(ANSI.cyan, "│", useColor)}  ${c(ANSI.cyan, "│   │", useColor)}  ${orb}  ${verb} ${s.target}`)
      if (s.summary) {
        lines.push(`${c(ANSI.cyan, "│", useColor)}  ${c(ANSI.cyan, "│   │", useColor)}  ${c(ANSI.dim, `└─ ${s.summary}`, useColor)}`)
      }
      lines.push(`${c(ANSI.cyan, "│", useColor)}  ${c(ANSI.cyan, "│   └─────────────────────────────────────────────┘", useColor)}`)
    } else {
      lines.push(`${c(ANSI.cyan, "│", useColor)}  ${c(ANSI.cyan, stem, useColor)} ${orb}  ${verb} ${s.target}`)
      if (s.summary) {
        lines.push(`${c(ANSI.cyan, "│", useColor)}  ${c(ANSI.cyan, pipe, useColor)} ${c(ANSI.dim, `└─ ${s.summary}`, useColor)}`)
      }
    }
  })

  if (task.steps.length === 0) {
    lines.push(`${c(ANSI.cyan, "│", useColor)}  ${c(ANSI.dim, "└── ○  Awaiting execution...", useColor)}`)
  }

  lines.push(`${c(ANSI.cyan, "├", useColor)}${c(ANSI.cyan, border, useColor)}${c(ANSI.cyan, "┤", useColor)}`)

  const wall = c(ANSI.cyan, "│", useColor)
  const close = `${c(ANSI.cyan, "└", useColor)}${c(ANSI.cyan, border, useColor)}${c(ANSI.cyan, "┘", useColor)}`
  lines.push(...buildFooter(task, wall, close, useColor))

  return lines.join("\n")
}

/**
 * ════════════════════════════════════════════════════════════════════════════
 * CLI VARIANT 3: DOUBLE TRACK PIPELINE (╔══╗ outer + ╠═▶ directional arrows)
 * Like Cyber Double Rail but with directional flow arrows (▶, ═▶, ◆═▶)
 * showing task execution direction explicitly
 * ════════════════════════════════════════════════════════════════════════════
 */
export function renderDoubleTrackPipelineCLI(task: TaskCardProps, useColor = true): string {
  const lines: string[] = []
  const border = "═".repeat(66)

  lines.push(`${c(ANSI.cyan, "╔", useColor)}${c(ANSI.cyan, border, useColor)}${c(ANSI.cyan, "╗", useColor)}`)
  lines.push(`${c(ANSI.cyan, "║", useColor)} ${c(ANSI.brightCyan + ANSI.bold, "▶ TASK:", useColor)} ${c(ANSI.brightWhite + ANSI.bold, task.objective, useColor)}`)

  if (task.isThinking || task.currentThought) {
    lines.push(`${c(ANSI.cyan, "║", useColor)}   ${c(ANSI.brightYellow + ANSI.bold, "▶ THK:", useColor)} ${c(ANSI.dim + ANSI.italic, task.currentThought || "Resolving plan...", useColor)}`)
  }

  lines.push(`${c(ANSI.cyan, "╠", useColor)}${c(ANSI.cyan, border, useColor)}${c(ANSI.cyan, "╣", useColor)}`)

  task.steps.forEach((s, idx) => {
    let orb = c(ANSI.dim, "○", useColor)
    let verbColor = ANSI.white
    let arrow = c(ANSI.dim, "═─▷", useColor)

    if (s.status === "running") {
      orb = c(ANSI.brightYellow + ANSI.bold, "◎", useColor)
      verbColor = ANSI.brightYellow + ANSI.bold
      arrow = c(ANSI.brightYellow + ANSI.bold, "══▶", useColor)
    } else if (s.status === "crystallized") {
      orb = c(ANSI.brightGreen + ANSI.bold, "✦", useColor)
      verbColor = ANSI.brightGreen + ANSI.bold
      arrow = c(ANSI.brightGreen + ANSI.bold, "◆═▶", useColor)
    } else if (s.status === "done") {
      orb = c(ANSI.brightCyan + ANSI.bold, "●", useColor)
      verbColor = ANSI.brightCyan + ANSI.bold
      arrow = c(ANSI.brightCyan + ANSI.bold, "●═▶", useColor)
    }

    const verb = c(verbColor, s.verb.toUpperCase().padEnd(6), useColor)

    if (s.branchLabel) {
      lines.push(`${c(ANSI.cyan, "║", useColor)}  ${arrow} ${c(ANSI.cyan, "╔══", useColor)} ${c(ANSI.brightMagenta, `↳ [${s.branchLabel}]`, useColor)} ${c(ANSI.dim, "══════════════════════════╗", useColor)}`)
      lines.push(`${c(ANSI.cyan, "║", useColor)}  ${c(ANSI.cyan, "    ║", useColor)}   ${orb}  ${verb} ${s.target}`)
      if (s.summary) {
        lines.push(`${c(ANSI.cyan, "║", useColor)}  ${c(ANSI.cyan, "    ║", useColor)}   ${c(ANSI.dim, `└─▶ ${s.summary}`, useColor)}`)
      }
      lines.push(`${c(ANSI.cyan, "║", useColor)}  ${c(ANSI.cyan, "    ╚══════════════════════════════════════════════╝", useColor)}`)
    } else {
      lines.push(`${c(ANSI.cyan, "║", useColor)}  ${arrow} ${orb}  ${verb} ${s.target}`)
      if (s.summary) {
        lines.push(`${c(ANSI.cyan, "║", useColor)}        ${c(ANSI.dim, `└─▶ ${s.summary}`, useColor)}`)
      }
    }

    if (idx < task.steps.length - 1) {
      lines.push(`${c(ANSI.cyan, "║", useColor)}  ${c(ANSI.dim, "  │", useColor)}`)
    }
  })

  if (task.steps.length === 0) {
    lines.push(`${c(ANSI.cyan, "║", useColor)}  ${c(ANSI.dim, "═─▷ ○  Awaiting execution...", useColor)}`)
  }

  lines.push(`${c(ANSI.cyan, "╠", useColor)}${c(ANSI.cyan, border, useColor)}${c(ANSI.cyan, "╣", useColor)}`)

  const wall = c(ANSI.cyan, "║", useColor)
  const close = `${c(ANSI.cyan, "╚", useColor)}${c(ANSI.cyan, border, useColor)}${c(ANSI.cyan, "╝", useColor)}`
  lines.push(...buildFooter(task, wall, close, useColor))

  return lines.join("\n")
}

/**
 * ════════════════════════════════════════════════════════════════════════════
 * CLI VARIANT 4: BLUEPRINT CELL MATRIX (┌──┐ outer + ┊ dotted rail hierarchy)
 * Like Architectural Grid but with dotted vertical guides (┊) and
 * hairline sub-chambers (┄) for a blueprint/schematic aesthetic
 * ════════════════════════════════════════════════════════════════════════════
 */
export function renderBlueprintCellMatrixCLI(task: TaskCardProps, useColor = true): string {
  const lines: string[] = []
  const border = "─".repeat(66)

  lines.push(`${c(ANSI.cyan, "┌", useColor)}${c(ANSI.cyan, border, useColor)}${c(ANSI.cyan, "┐", useColor)}`)
  lines.push(`${c(ANSI.cyan, "│", useColor)} ${c(ANSI.brightCyan + ANSI.bold, "TASK :", useColor)} ${c(ANSI.brightWhite + ANSI.bold, task.objective, useColor)}`)

  if (task.isThinking || task.currentThought) {
    lines.push(`${c(ANSI.cyan, "│", useColor)} ${c(ANSI.brightYellow + ANSI.bold, "THK  :", useColor)} ${c(ANSI.dim + ANSI.italic, task.currentThought || "Resolving plan...", useColor)}`)
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

    const verb = c(verbColor, s.verb.toUpperCase().padEnd(6), useColor)

    if (s.branchLabel) {
      lines.push(`${c(ANSI.cyan, "│", useColor)}  ${c(ANSI.dim, "┊", useColor)} ${c(ANSI.cyan, "┌┄┄", useColor)} ${c(ANSI.brightMagenta, `↳ [${s.branchLabel}]`, useColor)} ${c(ANSI.dim, "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┐", useColor)}`)
      lines.push(`${c(ANSI.cyan, "│", useColor)}  ${c(ANSI.dim, "┊", useColor)} ${c(ANSI.dim, "┊", useColor)}   ${orb}  ${verb} ${s.target}`)
      if (s.summary) {
        lines.push(`${c(ANSI.cyan, "│", useColor)}  ${c(ANSI.dim, "┊", useColor)} ${c(ANSI.dim, "┊", useColor)}   ${c(ANSI.dim, `└─ ${s.summary}`, useColor)}`)
      }
      lines.push(`${c(ANSI.cyan, "│", useColor)}  ${c(ANSI.dim, "┊", useColor)} ${c(ANSI.dim, "└┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┘", useColor)}`)
    } else {
      lines.push(`${c(ANSI.cyan, "│", useColor)}  ${c(ANSI.dim, "┊", useColor)} ${orb}  ${verb} ${s.target}`)
      if (s.summary) {
        lines.push(`${c(ANSI.cyan, "│", useColor)}  ${rail}    ${c(ANSI.dim, `└─ ${s.summary}`, useColor)}`)
      }
    }

    if (!isLast) {
      lines.push(`${c(ANSI.cyan, "│", useColor)}  ${c(ANSI.dim, "┊", useColor)}`)
    }
  })

  if (task.steps.length === 0) {
    lines.push(`${c(ANSI.cyan, "│", useColor)}  ${c(ANSI.dim, "┊ ○  Awaiting execution...", useColor)}`)
  }

  lines.push(`${c(ANSI.cyan, "├", useColor)}${c(ANSI.cyan, border, useColor)}${c(ANSI.cyan, "┤", useColor)}`)

  const wall = c(ANSI.cyan, "│", useColor)
  const close = `${c(ANSI.cyan, "└", useColor)}${c(ANSI.cyan, border, useColor)}${c(ANSI.cyan, "┘", useColor)}`
  lines.push(...buildFooter(task, wall, close, useColor))

  return lines.join("\n")
}

export class CLITaskProgressRenderer {
  public static render(task: TaskCardProps, useColor: boolean = true): string {
    return renderCyberDoubleRailCLI(task, useColor)
  }
}
