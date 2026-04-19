'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { useBrandColor } from '@/contexts/BrandColorContext'
import { useTerminal } from '@/contexts/TerminalContext'
import { TerminalHeaderBar } from './TerminalHeaderBar'
import { FileActivityPanel } from './FileActivityPanel'

// Portal target IDs — FloatingTerminalPanel provides the floating target
export const TERMINAL_DOCKED_ID = 'iris-terminal-docked'
export const TERMINAL_FLOATING_ID = 'iris-terminal-floating'

const ACCENT_FALLBACK = '#60a5fa'

export function TerminalWidget() {
  const { getThemeConfig } = useBrandColor()
  const glowColor = getThemeConfig().glow?.color || ACCENT_FALLBACK
  const { isFloating, setIsFloating, sendMessage } = useTerminal()

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const termRef = useRef<any>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fitAddonRef = useRef<any>(null)
  const lineBufferRef = useRef<string>('')
  const sendRef = useRef(sendMessage)
  const xtermContainerRef = useRef<HTMLDivElement | null>(null)
  const [portalTarget, setPortalTarget] = useState<HTMLElement | null>(null)
  const [workdir, setWorkdir] = useState<string>('')
  const [mounted, setMounted] = useState(false)

  useEffect(() => { sendRef.current = sendMessage }, [sendMessage])

  // Resolve portal target when floating state changes
  useEffect(() => {
    const targetId = isFloating ? TERMINAL_FLOATING_ID : TERMINAL_DOCKED_ID
    const timer = setTimeout(() => {
      const el = document.getElementById(targetId)
      setPortalTarget(el)
    }, 50)
    return () => clearTimeout(timer)
  }, [isFloating])

  // Re-fit xterm when portal target changes
  useEffect(() => {
    if (fitAddonRef.current && portalTarget) {
      const timer = setTimeout(() => {
        try { fitAddonRef.current.fit() } catch { /* ignore */ }
      }, 100)
      return () => clearTimeout(timer)
    }
  }, [portalTarget])

  // Initialize xterm once
  useEffect(() => {
    const container = document.createElement('div')
    container.className = 'flex-1 overflow-hidden'
    container.style.cssText = `padding: 12px 16px; min-height: 0; box-shadow: inset 0 0 40px ${glowColor}08;`
    xtermContainerRef.current = container

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let term: any
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let fitAddon: any
    let resizeObserver: ResizeObserver | null = null
    let disposed = false

    Promise.all([
      import('@xterm/xterm'),
      import('@xterm/addon-fit'),
    ]).then(([{ Terminal }, { FitAddon }]) => {
      if (disposed) return

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
      term.open(container)
      fitAddon.fit()

      termRef.current = term
      fitAddonRef.current = fitAddon

      term.writeln('\x1b[2m\u250C\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510\x1b[0m')
      term.writeln(`\x1b[2m\u2502\x1b[0m  \x1b[1m\x1b[38;2;96;165;250mIRIS Developer Terminal\x1b[0m                \x1b[2m\u2502\x1b[0m`)
      term.writeln('\x1b[2m\u2502  Direct shell access \u2022 Security filtered  \u2502\x1b[0m')
      term.writeln('\x1b[2m\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518\x1b[0m')
      term.writeln('')
      term.write('$ ')

      // Input handler — direct shell via terminal_input
      term.onData((data: string) => {
        if (data === '\r') {
          const line = lineBufferRef.current
          lineBufferRef.current = ''
          term.write('\r\n')
          if (line.trim()) {
            sendRef.current('terminal_input', { line })
          } else {
            term.write('$ ')
          }
        } else if (data === '\x7f' || data === '\b') {
          if (lineBufferRef.current.length > 0) {
            lineBufferRef.current = lineBufferRef.current.slice(0, -1)
            term.write('\b \b')
          }
        } else if (data === '\x03') {
          lineBufferRef.current = ''
          term.write('^C\r\n')
          sendRef.current('dev_abort', {})
          term.write('$ ')
        } else if (data >= ' ') {
          lineBufferRef.current += data
          term.write(data)
        }
      })

      resizeObserver = new ResizeObserver(() => {
        try { fitAddon.fit() } catch { /* ignore */ }
      })
      resizeObserver.observe(container)

      setMounted(true)
    }).catch((err) => {
      console.error('[TerminalWidget] failed to load xterm:', err)
    })

    // Backend output listeners
    const onOutput = (e: Event) => {
      const detail = (e as CustomEvent).detail as { line?: string }
      if (detail?.line !== undefined && termRef.current) {
        termRef.current.write(detail.line.replace(/\r?\n/g, '\r\n'))
      }
    }
    const onStarted = (e: Event) => {
      const detail = (e as CustomEvent).detail as { tool_name?: string }
      if (termRef.current && detail?.tool_name) {
        termRef.current.write(`\x1b[2m[${detail.tool_name} started]\x1b[0m\r\n`)
      }
    }
    const onActivity = (e: Event) => {
      const detail = (e as CustomEvent).detail as { tool_name?: string; workdir?: string }
      if (termRef.current && detail?.tool_name) {
        termRef.current.write(`\x1b[36m[tool: ${detail.tool_name}]\x1b[0m\r\n`)
      }
      if (detail?.workdir) setWorkdir(detail.workdir)
    }
    const onTextResponse = (e: Event) => {
      const detail = (e as CustomEvent).detail as { text?: string }
      if (termRef.current && detail?.text) {
        const text = detail.text.replace(/\r?\n/g, '\r\n')
        termRef.current.write(text + '\r\n$ ')
      }
    }

    window.addEventListener('iris:cli_output', onOutput)
    window.addEventListener('iris:cli_started', onStarted)
    window.addEventListener('iris:cli_activity', onActivity)
    window.addEventListener('iris:text_response', onTextResponse)

    return () => {
      disposed = true
      window.removeEventListener('iris:cli_output', onOutput)
      window.removeEventListener('iris:cli_started', onStarted)
      window.removeEventListener('iris:cli_activity', onActivity)
      window.removeEventListener('iris:text_response', onTextResponse)
      resizeObserver?.disconnect()
      term?.dispose()
      termRef.current = null
      fitAddonRef.current = null
      xtermContainerRef.current = null
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleClear = useCallback(() => {
    if (termRef.current) {
      termRef.current.clear()
      termRef.current.write('$ ')
    }
  }, [])

  // Portal: attach xterm container div to the active target
  const xtermPortal = mounted && portalTarget && xtermContainerRef.current
    ? createPortal(
        <div ref={(el) => {
          if (el && xtermContainerRef.current && !el.contains(xtermContainerRef.current)) {
            el.appendChild(xtermContainerRef.current)
          }
        }}
          className="flex-1 min-h-0 overflow-hidden"
        />,
        portalTarget
      )
    : null

  return (
    <>
      {/* Docked view */}
      {!isFloating && (
        <div className="w-full h-full flex flex-col" style={{ minHeight: 0 }}>
          <TerminalHeaderBar workdir={workdir} onClear={handleClear} />
          <div className="flex-1 flex min-h-0">
            <div id={TERMINAL_DOCKED_ID} className="flex-1 flex flex-col min-h-0 min-w-0" />
            <FileActivityPanel />
          </div>
        </div>
      )}

      {/* Floating placeholder in docked slot */}
      {isFloating && (
        <div className="w-full h-full flex items-center justify-center">
          <div className="text-center">
            <p className="text-xs text-white/40 mb-2">Terminal is floating</p>
            <button
              onClick={() => setIsFloating(false)}
              className="text-xs px-3 py-1 rounded border border-white/20 text-white/60 hover:bg-white/10 transition-colors"
            >
              Dock
            </button>
          </div>
        </div>
      )}

      {xtermPortal}
    </>
  )
}
