/**
 * Shell runs for the developer timeline (execution audit Phase 4: "a >cmd
 * command shows as an EXEC row").
 *
 * A `>cmd` typed in developer mode goes to the shell (terminal_input) and its
 * output streams back as terminal_output lines into the terminal scrollback
 * store. Before Phase 4 nothing in the chat drew them, so the command looked as
 * if it did nothing. This groups the scrollback into runs — one per shell
 * command, with the output lines that followed it — so the timeline can draw
 * each run as a one-node matrix with an EXEC row. Pure: no React, no store.
 *
 * Outcome markers come from backend/dev/terminal_handler.py: a command that
 * ran and failed prints `[exit N]`; a handler failure prints `Terminal error:`;
 * Ctrl-C prints `^C aborted`.
 */
import type { TerminalLine } from "@/components/terminal/terminalScrollback"

export type ShellRunState = "running" | "done" | "failed"

export interface ShellRun {
  /** The command line's id in the scrollback (stable React key). */
  id: string
  /** The conversation it was typed in (undefined for untagged, older lines). */
  conversationId?: string
  /** What the user typed after `>`. */
  command: string
  ts: number
  output: string[]
  state: ShellRunState
  /** Time of the last output line (or the command when none). */
  lastTs: number
}

const FAIL_RE = /^(\[exit \d+\]|Terminal error:|\^C aborted)/

/** `appendCommand(">ls")` stores "$ >ls". Only `>` shell commands are runs
 *  (`/run` becomes a DER task card; question answers are not commands). */
function shellCommandOf(line: TerminalLine): string | null {
  if (line.kind !== "command") return null
  const m = /^\$ >(.*)$/.exec(line.text)
  if (!m) return null
  const cmd = m[1].trim()
  return cmd || null
}

/** The shell prints no marker on success, so the newest run counts as running
 *  until its output has been quiet this long. */
export const SHELL_QUIET_MS = 2500

export function buildShellRuns(lines: readonly TerminalLine[], now: number = Date.now()): ShellRun[] {
  const runs: ShellRun[] = []
  let cur: ShellRun | null = null
  for (const line of lines) {
    const cmd = shellCommandOf(line)
    if (cmd !== null) {
      cur = { id: `shell-${line.id}`, conversationId: line.conversationId, command: cmd, ts: line.ts, output: [], state: "running", lastTs: line.ts }
      runs.push(cur)
      continue
    }
    if (!cur) continue
    if (line.kind === "command") {
      // Another kind of command (/run, an answer) ends the current run's output.
      cur = null
      continue
    }
    if (line.source === "chat" || line.kind === "system") continue
    cur.output.push(line.text)
    cur.lastTs = line.ts
    if (line.kind === "error" || FAIL_RE.test(line.text)) cur.state = "failed"
  }
  // A run is finished once a later command started; the newest run is still
  // running until its output has been quiet for SHELL_QUIET_MS.
  runs.forEach((r, i) => {
    if (r.state === "failed") return
    const newest = i === runs.length - 1
    r.state = newest && now - r.lastTs < SHELL_QUIET_MS ? "running" : "done"
  })
  return runs
}
