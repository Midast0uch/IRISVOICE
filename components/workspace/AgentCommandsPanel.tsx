'use client'

/**
 * AgentCommandsPanel — the agent's shell commands, live, in the workspace.
 *
 * Owner 2026-10-02: the user should feel part of what is happening while the
 * agent works. Each command shows its state as it changes (running → waiting
 * → done / failed / timed out / stopped), a live timer, the newest output
 * lines, the exit code, and a Stop button while it runs. "Waiting" means the
 * backend saw no output and no CPU for 30 s and handed control back to the
 * agent (backend/dev/subprocess_manager.py run_isolated).
 */
import React from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Check, X, Clock, Square, ChevronRight, Terminal, Hourglass } from 'lucide-react'
import { useBrandColor } from '@/contexts/BrandColorContext'
import { useTerminal } from '@/contexts/TerminalContext'
import { useAgentCommandStore, isFinal, type AgentCommand, type AgentCommandStatus } from '@/stores/agentCommandStore'

const VISIBLE = 6
const AMBER = '#f59e0b'
const GREEN = '#34d399'
const ROSE = '#fb7185'
const ORANGE = '#fb923c'
const SLATE = 'rgba(255,255,255,0.35)'

const STATUS_LABEL: Record<AgentCommandStatus, string> = {
  running: 'running',
  waiting: 'waiting',
  done: 'done',
  failed: 'failed',
  timed_out: 'timed out',
  stopped: 'stopped',
}

function statusColor(s: AgentCommandStatus, glow: string): string {
  return s === 'running' ? glow : s === 'waiting' ? AMBER : s === 'done' ? GREEN
    : s === 'failed' ? ROSE : s === 'timed_out' ? ORANGE : SLATE
}

function fmtElapsed(ms: number): string {
  const s = Math.max(0, ms) / 1000
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)}s`
  const m = Math.floor(s / 60)
  return `${m}m ${Math.floor(s % 60).toString().padStart(2, '0')}s`
}

/** Re-render every second while something is live, so timers tick. */
function useTick(active: boolean) {
  const [, setT] = React.useState(0)
  React.useEffect(() => {
    if (!active) return
    const h = setInterval(() => setT((t) => t + 1), 1000)
    return () => clearInterval(h)
  }, [active])
}

function StatusOrb({ status, glow }: { status: AgentCommandStatus; glow: string }) {
  const c = statusColor(status, glow)
  const live = status === 'running' || status === 'waiting'
  return (
    <span className="relative inline-flex items-center justify-center w-4 h-4 shrink-0">
      {live && (
        <motion.span
          className="absolute inset-0 rounded-full"
          style={{ border: `1px solid ${c}` }}
          animate={{ scale: [1, 1.7], opacity: [0.7, 0] }}
          transition={{ duration: status === 'running' ? 1.2 : 2.4, repeat: Infinity, ease: 'easeOut' }}
        />
      )}
      <span
        className="relative inline-flex items-center justify-center w-3 h-3 rounded-full"
        style={{ background: `${c}22`, border: `1px solid ${c}`, boxShadow: live ? `0 0 8px ${c}80` : 'none' }}
      >
        {status === 'done' && <Check size={8} style={{ color: c }} strokeWidth={3} />}
        {status === 'failed' && <X size={8} style={{ color: c }} strokeWidth={3} />}
        {status === 'timed_out' && <Clock size={8} style={{ color: c }} strokeWidth={3} />}
        {status === 'stopped' && <Square size={6} style={{ color: c, fill: c }} />}
        {status === 'waiting' && <Hourglass size={7} style={{ color: c }} strokeWidth={3} />}
        {status === 'running' && <span className="w-1 h-1 rounded-full" style={{ background: c }} />}
      </span>
    </span>
  )
}

function CommandRow({ cmd, glow, now, onStop }: { cmd: AgentCommand; glow: string; now: number; onStop: (id: string) => void }) {
  const [open, setOpen] = React.useState(false)
  const live = !isFinal(cmd.status)
  const c = statusColor(cmd.status, glow)
  const elapsed = (cmd.endedAt ?? now) - cmd.startedAt
  const tail = cmd.lines.slice(live ? -3 : -40)

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
      className="relative rounded-md overflow-hidden"
      style={{
        background: live ? `linear-gradient(90deg, ${c}10, rgba(255,255,255,0.015) 40%)` : 'rgba(255,255,255,0.015)',
        border: `1px solid ${live ? `${c}35` : 'rgba(255,255,255,0.05)'}`,
      }}
    >
      <div className="flex items-center gap-2 px-2 py-1.5 cursor-pointer select-none" onClick={() => setOpen((v) => !v)}>
        <StatusOrb status={cmd.status} glow={glow} />
        <span className="text-[11px] font-mono shrink-0" style={{ color: GREEN, textShadow: `0 0 6px ${GREEN}40` }}>$</span>
        <span className="flex-1 min-w-0 truncate text-[11px] font-mono" style={{ color: 'rgba(226,232,240,0.85)' }} title={cmd.command}>
          {cmd.command.split('\n')[0]}
        </span>
        <span className="text-[9px] uppercase tracking-wider shrink-0" style={{ color: c }}>{STATUS_LABEL[cmd.status]}</span>
        {cmd.exitCode !== undefined && cmd.exitCode !== null && isFinal(cmd.status) && (
          <span className="text-[9px] font-mono px-1.5 py-0.5 rounded shrink-0"
            style={{ background: `${cmd.exitCode === 0 ? GREEN : ROSE}15`, color: cmd.exitCode === 0 ? GREEN : ROSE }}>
            exit {cmd.exitCode}
          </span>
        )}
        <span className="text-[10px] font-mono tabular-nums shrink-0 w-12 text-right" style={{ color: 'rgba(255,255,255,0.45)' }}>
          {fmtElapsed(elapsed)}
        </span>
        {live && (
          <button
            onClick={(e) => { e.stopPropagation(); onStop(cmd.id) }}
            title="Stop this command (the agent is told you stopped it)"
            className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] shrink-0 transition-colors"
            style={{ color: ROSE, border: `1px solid ${ROSE}40`, background: `${ROSE}10` }}
            onMouseEnter={(e) => { e.currentTarget.style.background = `${ROSE}25` }}
            onMouseLeave={(e) => { e.currentTarget.style.background = `${ROSE}10` }}
          >
            <Square size={7} style={{ fill: ROSE }} /> Stop
          </button>
        )}
        <ChevronRight size={11} className="shrink-0 transition-transform" style={{ color: 'rgba(255,255,255,0.3)', transform: open ? 'rotate(90deg)' : 'none' }} />
      </div>

      {cmd.status === 'waiting' && (
        <div className="px-8 pb-1 text-[10px]" style={{ color: `${AMBER}cc` }}>
          No output and no CPU for {cmd.idleS ?? 30}s: it waits on something, or it is a server. The agent got control back and decides.
        </div>
      )}

      {(live || open) && tail.length > 0 && (
        <div
          className={`mx-2 mb-1.5 px-2 py-1 rounded font-mono text-[10px] leading-[1.45] ${open ? 'max-h-40 overflow-y-auto' : ''}`}
          style={{ background: 'rgba(0,0,0,0.25)', color: 'rgba(226,232,240,0.6)', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}
        >
          {tail.map((l, i) => <div key={i}>{l || ' '}</div>)}
        </div>
      )}

      {cmd.status === 'running' && (
        <div className="absolute left-0 right-0 bottom-0 h-px overflow-hidden">
          <motion.div
            className="h-px w-1/3"
            style={{ background: `linear-gradient(90deg, transparent, ${c}, transparent)` }}
            animate={{ x: ['-100%', '300%'] }}
            transition={{ duration: 1.6, repeat: Infinity, ease: 'linear' }}
          />
        </div>
      )}
    </motion.div>
  )
}

export function AgentCommandsPanel() {
  const { getThemeConfig } = useBrandColor()
  const glow = getThemeConfig().glow?.color || '#60a5fa'
  const { sendMessage } = useTerminal()
  const commands = useAgentCommandStore((s) => s.commands)
  const order = useAgentCommandStore((s) => s.order)
  const clearFinished = useAgentCommandStore((s) => s.clearFinished)
  const [collapsed, setCollapsed] = React.useState(false)

  const list = order.map((id) => commands[id]).filter(Boolean)
  const running = list.filter((c) => c.status === 'running').length
  const waiting = list.filter((c) => c.status === 'waiting').length
  useTick(running + waiting > 0)
  const now = Date.now()

  const onStop = React.useCallback((id: string) => {
    sendMessage('agent_command_stop', { id })
  }, [sendMessage])

  if (list.length === 0) return null

  return (
    <div className="shrink-0 px-3 pt-2">
      <div
        className="rounded-lg overflow-hidden"
        style={{
          background: 'linear-gradient(180deg, rgba(10,11,22,0.7) 0%, rgba(6,7,14,0.5) 100%)',
          border: `1px solid ${glow}18`,
          boxShadow: 'inset 0 1px 1px rgba(255,255,255,0.04), 0 2px 8px rgba(0,0,0,0.3)',
        }}
      >
        <div className="flex items-center gap-2 px-3 py-1.5" style={{ borderBottom: collapsed ? 'none' : `1px solid ${glow}12` }}>
          <button onClick={() => setCollapsed((v) => !v)} className="flex items-center gap-2 flex-1 min-w-0 text-left">
            <Terminal size={12} style={{ color: `${glow}90` }} />
            <span className="text-[11px] font-medium tracking-wide" style={{ color: `${glow}b0` }}>Live commands</span>
            {running > 0 && (
              <span className="text-[9px] px-1.5 py-0.5 rounded-full flex items-center gap-1"
                style={{ background: `${glow}15`, color: glow, border: `1px solid ${glow}30` }}>
                <motion.span className="w-1.5 h-1.5 rounded-full" style={{ background: glow }}
                  animate={{ opacity: [1, 0.3, 1] }} transition={{ duration: 1.2, repeat: Infinity }} />
                {running} running
              </span>
            )}
            {waiting > 0 && (
              <span className="text-[9px] px-1.5 py-0.5 rounded-full"
                style={{ background: `${AMBER}15`, color: AMBER, border: `1px solid ${AMBER}30` }}>
                {waiting} waiting
              </span>
            )}
            {running + waiting === 0 && (
              <span className="text-[9px]" style={{ color: 'rgba(255,255,255,0.3)' }}>{list.length} recent</span>
            )}
          </button>
          {list.some((c) => isFinal(c.status)) && (
            <button onClick={clearFinished} className="text-[9px] px-1.5 py-0.5 rounded text-white/30 hover:text-white/60 hover:bg-white/5">
              Clear done
            </button>
          )}
          <span style={{ color: 'rgba(255,255,255,0.35)' }} className="text-[11px] cursor-pointer" onClick={() => setCollapsed((v) => !v)}>
            {collapsed ? '▸' : '▾'}
          </span>
        </div>

        {!collapsed && (
          <div className="flex flex-col gap-1 p-1.5 max-h-72 overflow-y-auto">
            <AnimatePresence initial={false}>
              {list.slice(0, VISIBLE).map((cmd) => (
                <CommandRow key={cmd.id} cmd={cmd} glow={glow} now={now} onStop={onStop} />
              ))}
            </AnimatePresence>
            {list.length > VISIBLE && (
              <div className="text-[9px] px-2 py-0.5" style={{ color: 'rgba(255,255,255,0.25)' }}>
                +{list.length - VISIBLE} older
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default AgentCommandsPanel
