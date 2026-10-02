/**
 * agentCommandStore — the agent's shell commands, live, for the workspace.
 *
 * Fed by two window events (useIRISWebSocket):
 *   - `iris:agent_command`   { id, command, status, elapsed_s, exit_code?, idle_s? }
 *                            one per status change: running → waiting →
 *                            done | failed | timed_out | stopped
 *   - `iris:terminal_output` { line, cmd_id } one per output line
 *
 * The listeners are installed once at module load, so a command that runs
 * while the workspace is not on screen is still there when it opens.
 * Bounded: the newest MAX_COMMANDS commands, MAX_LINES lines each.
 */
import { create } from 'zustand'

export type AgentCommandStatus = 'running' | 'waiting' | 'done' | 'failed' | 'timed_out' | 'stopped'

export interface AgentCommand {
  id: string
  command: string
  status: AgentCommandStatus
  /** client clock (ms) when the command started (event time minus elapsed) */
  startedAt: number
  /** client clock (ms) when it reached a final status */
  endedAt?: number
  exitCode?: number | null
  /** seconds without output or CPU when it was handed back to the agent */
  idleS?: number
  lines: string[]
}

const MAX_COMMANDS = 30
const MAX_LINES = 200
const FINAL: AgentCommandStatus[] = ['done', 'failed', 'timed_out', 'stopped']

export const isFinal = (s: AgentCommandStatus) => FINAL.includes(s)

interface AgentCommandState {
  commands: Record<string, AgentCommand>
  /** newest first */
  order: string[]
  upsert: (ev: { id?: string; command?: string; status?: string; elapsed_s?: number; exit_code?: number | null; idle_s?: number }) => void
  appendLine: (id: string, line: string) => void
  clearFinished: () => void
}

export const useAgentCommandStore = create<AgentCommandState>((set) => ({
  commands: {},
  order: [],
  upsert: (ev) =>
    set((state) => {
      const id = ev.id
      if (!id || !ev.status) return state
      const now = Date.now()
      const status = ev.status as AgentCommandStatus
      const prev = state.commands[id]
      const next: AgentCommand = {
        id,
        command: ev.command ?? prev?.command ?? '',
        status,
        // The backend's elapsed is the truth: re-anchor on every event, so a
        // timer never counts from when the browser first heard of it.
        startedAt: typeof ev.elapsed_s === 'number'
          ? now - Math.max(0, ev.elapsed_s * 1000)
          : prev?.startedAt ?? now,
        endedAt: isFinal(status) ? now : undefined,
        exitCode: ev.exit_code ?? prev?.exitCode,
        idleS: ev.idle_s ?? prev?.idleS,
        lines: prev?.lines ?? [],
      }
      const order = prev ? state.order : [id, ...state.order]
      const commands = { ...state.commands, [id]: next }
      for (const old of order.slice(MAX_COMMANDS)) delete commands[old]
      return { commands, order: order.slice(0, MAX_COMMANDS) }
    }),
  appendLine: (id, line) =>
    set((state) => {
      const cmd = state.commands[id]
      if (!cmd) return state
      return {
        commands: { ...state.commands, [id]: { ...cmd, lines: [...cmd.lines, line].slice(-MAX_LINES) } },
      }
    }),
  clearFinished: () =>
    set((state) => {
      const order = state.order.filter((id) => !isFinal(state.commands[id]?.status ?? 'done'))
      const commands: Record<string, AgentCommand> = {}
      for (const id of order) commands[id] = state.commands[id]
      return { commands, order }
    }),
}))

let installed = false
if (typeof window !== 'undefined' && !installed) {
  installed = true
  window.addEventListener('iris:agent_command', (e: Event) => {
    const d = (e as CustomEvent).detail
    if (d && typeof d === 'object') useAgentCommandStore.getState().upsert(d)
  })
  window.addEventListener('iris:terminal_output', (e: Event) => {
    const d = (e as CustomEvent<{ line?: string; cmd_id?: string }>).detail
    if (d?.cmd_id && typeof d.line === 'string') useAgentCommandStore.getState().appendLine(d.cmd_id, d.line)
  })
}
