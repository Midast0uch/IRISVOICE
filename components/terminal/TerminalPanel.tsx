'use client'

/**
 * TerminalPanel — xterm.js display driver for the Developer Terminal tab.
 *
 * Architecture (Domain 13.4):
 *   User input → xterm.onData → buffer → on Enter:
 *     sendMessage('dev_cli', { query }) → iris_gateway → DevOrchestrator → agent_kernel DER loop
 *
 *   Backend output (dispatched by useIRISWebSocket):
 *     iris:cli_output    → term.write(line)        — streaming stdout from agent pipeline
 *     iris:cli_started   → term.write(banner)      — CLI tool is starting
 *     iris:cli_activity  → term.write(activity)    — DER loop tool call notification
 *     iris:text_response → term.write(text)        — agent summary / completion text
 *
 * The terminal is a pure display driver. All security, process management, DER loop
 * execution, and working-directory resolution happen in the existing IRIS pipeline:
 *   security_filter → iris_gateway → agent_kernel → tool_bridge → DevOrchestrator
 *
 * Quality-check gates:
 *   - Terminal instance created once (useRef), mounted/unmounted in useEffect
 *   - FitAddon + ResizeObserver for responsive sizing
 *   - All event listeners cleaned up on unmount
 *   - No persistent state — stateless display driver per spec
 *   - xterm is dynamically imported (lazy) to avoid bundling in non-dev builds
 */

import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import {
  subscribe as subscribeTerminal,
  getSnapshot as getTerminalSnapshot,
} from './terminalScrollback'

interface TerminalPanelProps {
  glowColor?: string
  sendMessage: (type: string, payload: Record<string, unknown>) => boolean | void
}

export function TerminalPanel({ glowColor = '#60a5fa', sendMessage }: TerminalPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const termRef = useRef<any>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fitAddonRef = useRef<any>(null)
  const lineBufferRef = useRef<string>('')
  // REQ-13 AC3 (T0d): surface sandbox-worktree isolation in the panel header.
  const [sandboxPath, setSandboxPath] = useState<string | null>(null)
  // Gate 3 T10/T14: effective workdir + session state badge (store-driven).
  const terminal = useSyncExternalStore(subscribeTerminal, getTerminalSnapshot, getTerminalSnapshot)
  const workdir = terminal.workdir
  const sessionState = terminal.sessionState

  useEffect(() => {
    let cancelled = false
    fetch('/api/git/worktree/status')
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => {
        if (!cancelled && s?.exists && s?.path) setSandboxPath(s.path as string)
      })
      .catch(() => { /* personal mode / offline — no badge */ })
    return () => { cancelled = true }
  }, [])

  // Stable ref so event listeners don't capture stale sendMessage
  const sendRef = useRef(sendMessage)
  useEffect(() => { sendRef.current = sendMessage }, [sendMessage])

  useEffect(() => {
    if (!containerRef.current) return

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let term: any
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let fitAddon: any
    let resizeObserver: ResizeObserver | null = null
    let disposed = false

    // Dynamic import — avoids bundling xterm in the initial chunk
    Promise.all([
      import('@xterm/xterm'),
      import('@xterm/addon-fit'),
    ]).then(([{ Terminal }, { FitAddon }]) => {
      if (disposed || !containerRef.current) return

      term = new Terminal({
        fontFamily: '"JetBrains Mono", "Fira Code", "Cascadia Code", monospace',
        fontSize: 13,
        lineHeight: 1.5,
        cursorBlink: true,
        cursorStyle: 'bar',
        theme: {
          background: 'transparent',
          foreground: '#e2e8f0',
          cursor: glowColor,
          selectionBackground: `${glowColor}40`,
          black: '#1a1a2e',
          brightBlack: '#4a5568',
          red: '#fc8181',
          brightRed: '#feb2b2',
          green: '#68d391',
          brightGreen: '#9ae6b4',
          yellow: '#f6e05e',
          brightYellow: '#faf089',
          blue: '#63b3ed',
          brightBlue: '#90cdf4',
          magenta: '#b794f4',
          brightMagenta: '#d6bcfa',
          cyan: '#76e4f7',
          brightCyan: '#b2f5ea',
          white: '#e2e8f0',
          brightWhite: '#ffffff',
        },
        allowTransparency: true,
        scrollback: 2000,
        convertEol: false,
      })

      fitAddon = new FitAddon()
      term.loadAddon(fitAddon)
      term.open(containerRef.current!)
      fitAddon.fit()

      termRef.current = term
      fitAddonRef.current = fitAddon

      // Welcome banner
      term.writeln('\x1b[2m┌─────────────────────────────────────────┐\x1b[0m')
      term.writeln(`\x1b[2m│\x1b[0m  \x1b[1m\x1b[38;2;96;165;250mIRIS Developer Terminal\x1b[0m                \x1b[2m│\x1b[0m`)
      term.writeln('\x1b[2m│  Delegate — IRIS picks the tool for you   │\x1b[0m')
      term.writeln('\x1b[2m└─────────────────────────────────────────┘\x1b[0m')
      term.writeln('')
      term.write('$ ')

      // Input handler — buffer keystrokes, submit on Enter via dev_cli pipeline
      term.onData((data: string) => {
        if (data === '\r') {
          const line = lineBufferRef.current
          lineBufferRef.current = ''
          term.write('\r\n')
          if (line.trim()) {
            // Route through: iris_gateway → DevOrchestrator → agent_kernel DER loop
            // workdir defaults to active worktree in DevOrchestrator._get_default_workdir()
            sendRef.current('dev_cli', { query: line })
          } else {
            term.write('$ ')
          }
        } else if (data === '\x7f' || data === '\b') {
          // Backspace
          if (lineBufferRef.current.length > 0) {
            lineBufferRef.current = lineBufferRef.current.slice(0, -1)
            term.write('\b \b')
          }
        } else if (data === '\x03') {
          // Ctrl-C — abort active dev process
          lineBufferRef.current = ''
          term.write('^C\r\n')
          sendRef.current('dev_abort', {})
          term.write('$ ')
        } else if (data >= ' ') {
          lineBufferRef.current += data
          term.write(data)
        }
      })

      // Responsive resize
      resizeObserver = new ResizeObserver(() => {
        try { fitAddon.fit() } catch { /* ignore */ }
      })
      resizeObserver.observe(containerRef.current!)
    }).catch((err) => {
      console.error('[TerminalPanel] failed to load xterm:', err)
    })

    // ── Backend output listeners (dispatched by useIRISWebSocket) ─────────────

    // cli_output: streaming stdout/stderr from DevOrchestrator subprocess
    const onOutput = (e: Event) => {
      const detail = (e as CustomEvent).detail as { line?: string }
      if (detail?.line !== undefined && termRef.current) {
        termRef.current.write(detail.line.replace(/\r?\n/g, '\r\n'))
      }
    }

    // Gate 3 T1: direct shell output — same display, own event.
    const onShellOutput = (e: Event) => {
      const detail = (e as CustomEvent).detail as { line?: string }
      if (detail?.line !== undefined && termRef.current) {
        termRef.current.write(detail.line.replace(/\r?\n/g, '\r\n') + '\r\n')
      }
    }

    // cli_started: CLI tool / subprocess started
    const onStarted = (e: Event) => {
      const detail = (e as CustomEvent).detail as { tool_name?: string; proc_id?: string }
      if (termRef.current && detail?.tool_name) {
        termRef.current.write(`\x1b[2m[${detail.tool_name} started]\x1b[0m\r\n`)
      }
    }

    // cli_activity: DER loop tool-call notification (agent is working)
    const onActivity = (e: Event) => {
      const detail = (e as CustomEvent).detail as { tool_name?: string; workdir?: string }
      if (termRef.current && detail?.tool_name) {
        termRef.current.write(`\x1b[36m[tool: ${detail.tool_name}]\x1b[0m\r\n`)
      }
    }

    // text_response: agent summary / task completion text
    const onTextResponse = (e: Event) => {
      const detail = (e as CustomEvent).detail as { text?: string }
      if (termRef.current && detail?.text) {
        const text = detail.text.replace(/\r?\n/g, '\r\n')
        termRef.current.write(text + '\r\n$ ')
      }
    }

    window.addEventListener('iris:cli_output', onOutput)
    window.addEventListener('iris:terminal_output', onShellOutput)
    window.addEventListener('iris:cli_started', onStarted)
    window.addEventListener('iris:cli_activity', onActivity)
    window.addEventListener('iris:text_response', onTextResponse)

    return () => {
      disposed = true
      window.removeEventListener('iris:cli_output', onOutput)
      window.removeEventListener('iris:terminal_output', onShellOutput)
      window.removeEventListener('iris:cli_started', onStarted)
      window.removeEventListener('iris:cli_activity', onActivity)
      window.removeEventListener('iris:text_response', onTextResponse)
      resizeObserver?.disconnect()
      term?.dispose()
      termRef.current = null
      fitAddonRef.current = null
    }
  }, [glowColor]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="w-full h-full flex flex-col" style={{ minHeight: 0 }}>
      {/* Gate 3 T10 (REQ-4 AC4) + T14 (REQ-5 AC3): effective workdir and
          session state badge, driven by the scrollback store's snapshot. */}
      {(workdir || sessionState !== 'idle') && (
        <div
          className="flex items-center gap-2 px-4 py-1 text-[10px] font-mono shrink-0"
          style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.45)' }}
          role="status"
          aria-label="Terminal workdir and session state"
        >
          {workdir && (
            <>
              <span style={{ color: glowColor }}>DIR</span>
              <span className="truncate" title={workdir}>{workdir}</span>
            </>
          )}
          <span className="ml-auto flex items-center gap-1">
            <span style={{
              color:
                sessionState === 'working' ? '#34d399'
                : sessionState === 'blocked' ? '#fbbf24'
                : sessionState === 'done' ? 'rgba(255,255,255,0.6)'
                : 'rgba(255,255,255,0.3)',
            }}>
              ● {sessionState.toUpperCase()}
            </span>
          </span>
        </div>
      )}
      {sandboxPath && (
        <div
          className="flex items-center gap-2 px-4 py-1 text-[10px] font-mono shrink-0"
          style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.45)' }}
          role="status"
          aria-label="Sandbox worktree active"
        >
          <span style={{ color: '#fbbf24' }}>SANDBOX</span>
          <span className="truncate" title={sandboxPath}>{sandboxPath}</span>
          <span className="ml-auto">agent edits land here — not the live tree</span>
        </div>
      )}
      <div
        ref={containerRef}
        className="flex-1 overflow-hidden"
        style={{
          padding: '12px 16px',
          minHeight: 0,
          boxShadow: `inset 0 0 40px ${glowColor}08`,
        }}
      />
    </div>
  )
}
